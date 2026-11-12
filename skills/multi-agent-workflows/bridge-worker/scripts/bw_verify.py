#!/usr/bin/env python3
"""Verify bridge-delivery/1 evidence without trusting report prose."""

import argparse
import csv
import json
import re
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext
from pathlib import Path

from bw_common import atomic_json, bridge_root, file_sha256, resolve_path, valid_id


class Verification:
    def __init__(self):
        self.results = []
        self.delivery = None
        self.schema_valid = False

    def add(self, level, check, reason):
        self.results.append({"level": level, "check": check, "reason": str(reason)})

    @property
    def passed(self):
        return sum(row["level"] == "PASS" for row in self.results)

    @property
    def failed(self):
        return sum(row["level"] == "FAIL" for row in self.results)

    def as_dict(self):
        return {"passed": self.passed, "failed": self.failed,
                "schema_valid": self.schema_valid, "results": self.results}

    def display(self):
        for row in self.results:
            print("{level} {check}: {reason}".format(**row))
        print("PASS={} FAIL={} WARN={}".format(self.passed, self.failed,
              sum(row["level"] == "WARN" for row in self.results)))


def schema_errors(data):
    """Validate structure independently of evidence, including for failed deliveries."""
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    def string(value):
        return isinstance(value, str) and bool(value.strip())

    def source(value, label):
        if not isinstance(value, dict):
            errors.append(label + " must be an object")
            return
        require(string(value.get("path")), label + ".path is required")
        kind = value.get("kind")
        require(kind in ("json", "csv", "text"), label + ".kind must be json/csv/text")
        if kind == "json":
            require(isinstance(value.get("pointer"), str) and
                    (value["pointer"] == "" or value["pointer"].startswith("/")), label + ".pointer must be RFC 6901")
        elif kind == "csv":
            require(isinstance(value.get("where"), dict) and
                    all(string(k) and isinstance(v, (str, int, float, bool)) for k, v in value.get("where", {}).items()),
                    label + ".where must map column names to scalar values")
            require(string(value.get("column")), label + ".column is required")
        elif kind == "text":
            require(string(value.get("regex")), label + ".regex is required")
            group = value.get("group")
            require((type(group) is int and group >= 0) or string(group), label + ".group must be a group number/name")

    if not isinstance(data, dict):
        return ["delivery must be an object"]
    require(data.get("schema") == "bridge-delivery/1", "schema must be bridge-delivery/1")
    require(valid_id(data.get("task_id")), "task_id must be a safe nonempty id")
    require(type(data.get("channel")) is int and data["channel"] in (1, 2, 3), "channel must be 1, 2 or 3")
    require(data.get("status") in ("ok", "blocked", "failed"), "status must be ok/blocked/failed")
    list_fields = ("claims", "artifacts", "commands", "deviations", "pending_confirmation", "fallbacks", "resources", "unverified")
    for key in list_fields:
        require(isinstance(data.get(key), list), key + " must be an array")
    require(isinstance(data.get("labels"), dict) and type(data.get("labels", {}).get("human_reviewed")) is bool,
            "labels.human_reviewed must be boolean")
    for field in ("pending_confirmation", "unverified"):
        if isinstance(data.get(field), list):
            require(all(string(v) for v in data[field]), field + " entries must be nonempty strings")
    if "report" in data:
        require(string(data["report"]), "report must be a nonempty path")
    if "report_exempt_numbers" in data:
        require(isinstance(data["report_exempt_numbers"], list) and
                all(type(v) in (str, int, float) for v in data["report_exempt_numbers"]),
                "report_exempt_numbers must be an array of strings or numbers")
    seen = set()
    for field in ("claims", "artifacts", "commands", "deviations", "fallbacks", "resources"):
        if not isinstance(data.get(field), list):
            continue
        for index, item in enumerate(data[field]):
            label = "{}[{}]".format(field, index)
            if not isinstance(item, dict):
                errors.append(label + " must be an object")
                continue
            if field == "claims":
                identifier = item.get("id")
                require(string(identifier), label + ".id is required")
                if isinstance(identifier, str):
                    require(identifier not in seen, label + ".id is duplicated")
                    seen.add(identifier)
                require(isinstance(item.get("value"), str), label + ".value must be a string")
                source(item.get("source"), label + ".source")
            elif field == "artifacts":
                require(string(item.get("path")), label + ".path is required")
                require(isinstance(item.get("sha256"), str) and re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"]) is not None,
                        label + ".sha256 must be a SHA-256 digest")
            elif field == "commands":
                cmd = item.get("cmd")
                require(string(cmd) or (isinstance(cmd, list) and bool(cmd) and all(isinstance(v, str) for v in cmd)), label + ".cmd is required")
                require(type(item.get("exit_code")) is int, label + ".exit_code must be an integer")
                require(string(item.get("log_path")), label + ".log_path is required")
                require(item.get("killed_reason") is None or isinstance(item["killed_reason"], str), label + ".killed_reason must be null/string")
                if "name" in item:
                    require(string(item["name"]), label + ".name must be nonempty")
            elif field == "deviations":
                require(string(item.get("what")) and string(item.get("why")), label + ".what and .why are required")
                require("authorized_by" in item and (item["authorized_by"] is None or isinstance(item["authorized_by"], str)),
                        label + ".authorized_by must be null/string")
            elif field == "fallbacks":
                require(string(item.get("name")), label + ".name is required")
                require(type(item.get("count")) is int and item["count"] >= 0, label + ".count must be a nonnegative integer")
                source(item.get("source"), label + ".source")
            elif field == "resources":
                require(string(item.get("kind")) and string(item.get("name")), label + ".kind and .name are required")
                require(type(item.get("released")) is bool, label + ".released must be boolean")
                require(item.get("evidence_log") is None or string(item["evidence_log"]), label + ".evidence_log must be null/path")
    return errors


def json_pointer(document, pointer):
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError("invalid JSON pointer escape")
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(document, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise ValueError("invalid JSON array index: " + key)
            document = document[int(key)]
        elif isinstance(document, dict):
            document = document[key]
        else:
            raise ValueError("JSON pointer traverses a scalar")
    return document


def read_source(source, base):
    path = resolve_path(base, source["path"])
    kind = source["kind"]
    if kind == "json":
        with path.open(encoding="utf-8") as stream:
            document = json.load(stream, parse_float=Decimal)
        return json_pointer(document, source["pointer"])
    if kind == "csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = set(reader.fieldnames or [])
            if not set(source["where"]).union([source["column"]]).issubset(columns):
                raise ValueError("CSV column does not exist")
            rows = [row for row in reader if all(row[k] == str(v) for k, v in source["where"].items())]
        if len(rows) != 1:
            raise ValueError("CSV where matched {} rows, expected exactly one".format(len(rows)))
        return rows[0][source["column"]]
    if kind == "text":
        matches = list(re.finditer(source["regex"], path.read_text(encoding="utf-8"), re.MULTILINE))
        if len(matches) != 1:
            raise ValueError("text regex matched {} places, expected exactly one".format(len(matches)))
        value = matches[0].group(source["group"])
        if value is None:
            raise ValueError("text capture did not participate in the match")
        return value
    raise ValueError("unknown source kind: " + str(kind))


def compare_value(actual, expected):
    """Return an auditable explanation; do not convert evidence through float."""
    try:
        target = Decimal(expected)
    except InvalidOperation:
        target = None
    if target is None:
        if str(actual) != expected:
            raise ValueError("source {!r} != value {!r}".format(actual, expected))
        return "string equality"
    if not target.is_finite():
        raise ValueError("non-finite numeric value")
    try:
        number = Decimal(str(actual))
    except InvalidOperation:
        raise ValueError("source {!r} is not numeric".format(actual))
    if not number.is_finite():
        raise ValueError("non-finite numeric source")
    decimals = max(0, -target.as_tuple().exponent)
    with localcontext() as context:
        context.prec = max(28, len(number.as_tuple().digits) + abs(number.adjusted()) + decimals + 10)
        quantum = Decimal(1).scaleb(-decimals)
        rounded = []
        for mode in (ROUND_HALF_EVEN, ROUND_HALF_UP):
            value = format(number.quantize(quantum, rounding=mode), ".{}f".format(decimals))
            rounded.append(value)
            if value == expected:
                return "{} to {} decimal places ({!r} -> {!r})".format(mode, decimals, str(actual), expected)
    raise ValueError("source {!r} rounds to {}, not {!r}".format(str(actual), "/".join(rounded), expected))


def verify_claim(claim, base):
    """Shared by verification and rendering; raises on missing/ambiguous evidence."""
    return compare_value(read_source(claim["source"], base), claim["value"])


# Mask rather than delete, preserving line numbers and numeric token boundaries.
MASKS = [
    r"\b0[xX][0-9a-fA-F]+\b",
    r"\b(?=[0-9a-fA-F]{12,}\b)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]+\b",
    r"(?<!\d)\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?(?!\d)",
    r"(?<!\d)\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?(?!\d)",
]
NUMBER = re.compile(r"(?<![\d.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?%?|(?<![\d.])[+-]?\.\d+%?")


def report_numbers(text):
    fence = None
    inline_ticks = None
    for lineno, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence):
                fence = None
            continue
        if match and inline_ticks is None:
            fence = match[1]
            continue
        # Inline code spans may use multiple backticks and span lines.
        parts = re.split(r"(`+)", line)
        visible = []
        for part in parts:
            if part.startswith("`"):
                if inline_ticks is None:
                    inline_ticks = part
                elif part == inline_ticks:
                    inline_ticks = None
                visible.append(" " * len(part))
            else:
                visible.append(" " * len(part) if inline_ticks else part)
        line = "".join(visible)
        for pattern in MASKS:
            line = re.sub(pattern, lambda m: " " * len(m[0]), line)
        for number in NUMBER.finditer(line):
            yield lineno, number[0]


def verify_delivery(delivery_path, strict=False):
    result = Verification()
    path = Path(delivery_path).resolve()
    base = path.parent
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        result.add("FAIL", "schema", exc)
        return result
    result.delivery = data
    errors = schema_errors(data)
    if errors:
        for error in errors:
            result.add("FAIL", "schema", error)
        return result
    result.schema_valid = True
    result.add("PASS", "schema", "bridge-delivery/1 structure and status are valid")

    def check(label, operation):
        try:
            result.add("PASS", label, operation())
        except (OSError, ValueError, KeyError, IndexError, TypeError, UnicodeError, InvalidOperation, re.error) as exc:
            result.add("FAIL", label, exc)

    def artifact(item):
        actual = file_sha256(resolve_path(base, item["path"]))
        if actual.lower() != item["sha256"].lower():
            raise ValueError("SHA-256 mismatch: expected {}, got {}".format(item["sha256"], actual))
        return "file exists and SHA-256 matches"

    for item in data["artifacts"]:
        check("artifact " + item["path"], lambda item=item: artifact(item))
    for claim in data["claims"]:
        check("claim " + claim["id"], lambda claim=claim: verify_claim(claim, base))
    for item in data["fallbacks"]:
        check("fallback " + item["name"], lambda item=item: verify_claim({"source": item["source"], "value": str(item["count"])}, base))
    for index, command in enumerate(data["commands"]):
        def command_check(command=command, index=index):
            log_path = resolve_path(base, command["log_path"])
            if not log_path.is_file():
                raise ValueError("log_path does not exist")
            if data["status"] == "ok" and command.get("killed_reason"):
                related = [c for c in data["commands"][index:] if
                           (command.get("name") is not None and c.get("name") == command["name"]) or c["cmd"] == command["cmd"]]
                if related[-1]["exit_code"] != 0 or related[-1].get("killed_reason"):
                    raise ValueError("killed command has no subsequent successful rerun")
            return "log exists; integer exit_code={}".format(command["exit_code"])
        check("command {}".format(index), command_check)
    if data["status"] == "ok":
        for index, deviation in enumerate(data["deviations"]):
            authorized = deviation.get("authorized_by")
            result.add("PASS" if authorized and authorized.strip() else "FAIL", "deviation {}".format(index),
                       "authorized_by=" + str(authorized))
        result.add("FAIL" if data["pending_confirmation"] else "PASS", "pending_confirmation", "must be empty for status=ok")
        for item in data["resources"]:
            def resource_check(item=item):
                if item["released"] is not True:
                    raise ValueError("resource has not been released")
                if not item.get("evidence_log") or not resolve_path(base, item["evidence_log"]).is_file():
                    raise ValueError("release evidence_log is missing")
                return "released with evidence log"
            check("resource " + item["name"], resource_check)
    if "report" in data:
        report = resolve_path(base, data["report"]).resolve()
        artifacts = {resolve_path(base, item["path"]).resolve() for item in data["artifacts"]}
        result.add("PASS" if report in artifacts else "FAIL", "report artifact", "report must be listed in artifacts")
        def check_report():
            registered = {claim["value"] for claim in data["claims"]}
            registered.update(str(value) for value in data.get("report_exempt_numbers", []))
            if data.get("report_exempt_numbers"):
                # Exemptions bypass source checks, so surface them to the reviewer.
                result.add("WARN", "report exemptions", "numbers exempted without a source: " +
                           ", ".join(str(value) for value in data["report_exempt_numbers"]))
            unknown = []
            for lineno, token in report_numbers(report.read_text(encoding="utf-8")):
                bare = token.rstrip("%")
                digits = bare.lstrip("+-").replace(",", "")
                required = strict or "." in token or "%" in token or len(re.sub(r"\D", "", digits)) >= 3 or "e" in token.lower()
                if required and token not in registered and bare not in registered:
                    unknown.append("line {}: {}".format(lineno, token))
            if unknown:
                raise ValueError("unregistered numbers: " + "; ".join(unknown))
            return "all required report numbers are registered"
        check("report numbers", check_report)
    claim_path = bridge_root(data["channel"]) / "runs" / data["task_id"] / "claim.json"
    if claim_path.exists():
        def check_channel():
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            if not isinstance(claim, dict) or type(claim.get("channel")) is not int or claim["channel"] != data["channel"]:
                raise ValueError("channel differs from claim.json")
            return "channel matches claim.json"
        check("channel", check_channel)
    else:
        result.add("WARN", "channel", "claim.json is absent: " + str(claim_path))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delivery")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)
    result = verify_delivery(args.delivery, args.strict)
    result.display()
    if args.json_out:
        try:
            atomic_json(args.json_out, result.as_dict())
        except OSError as exc:
            print("FAIL json-out: {}".format(exc))
            return 1
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
