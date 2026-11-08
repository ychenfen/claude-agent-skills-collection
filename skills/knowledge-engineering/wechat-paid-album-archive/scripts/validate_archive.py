#!/usr/bin/env python3
"""Validate a generated offline WeChat album without exposing session data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


SECRET_VALUE_RE = re.compile(
    r"(?:pass_ticket|exportkey|[?&]key)=([A-Za-z0-9%_-]{8,})",
    re.I,
)
PAYWALL_MARKERS = ("mp-pay-preview-filter", "js_pay_preview_filter")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an offline WeChat album archive.")
    parser.add_argument("archive", type=Path, help="Archive directory containing manifest.json")
    args = parser.parse_args()
    root = args.archive.expanduser().resolve()

    required = ["manifest.json", "index.html", "README.md", "SHA256SUMS"]
    for name in required:
        if not (root / name).is_file():
            fail(f"missing required file: {name}")

    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    records = manifest.get("articles") or []
    expected = int((manifest.get("album") or {}).get("article_count") or len(records))
    if len(records) != expected:
        fail(f"article count mismatch: manifest has {len(records)}, album expects {expected}")
    if manifest.get("failed_assets"):
        fail(f"manifest contains {len(manifest['failed_assets'])} failed assets")

    missing_refs: list[str] = []
    for record in records:
        index = int(record["index"])
        article = root / record["file"]
        if not article.is_file():
            fail(f"missing article file: {record['file']}")
        if sha256(article) != record.get("sha256"):
            fail(f"article checksum mismatch: {record['file']}")
        text = article.read_text("utf-8")
        if any(marker in text for marker in PAYWALL_MARKERS):
            fail(f"paywall marker remains: {record['file']}")
        if "visibility:visible!important;opacity:1!important" not in text:
            fail(f"offline visibility override missing: {record['file']}")
        if SECRET_VALUE_RE.search(text):
            fail(f"session value pattern found: {record['file']}")

        state_path = root / ".state" / f"{index:02d}.json"
        if not state_path.is_file():
            fail(f"missing resume state: {state_path.relative_to(root)}")
        state = json.loads(state_path.read_text("utf-8"))
        if state.get("sha256") != record.get("sha256"):
            fail(f"state checksum mismatch: {state_path.relative_to(root)}")

        soup = BeautifulSoup(text, "html.parser")
        for node in soup.find_all(src=True):
            source = str(node.get("src", ""))
            if source.startswith("../assets/") and not (article.parent / source).resolve().is_file():
                missing_refs.append(f"{record['file']} -> {source}")
        for source in re.findall(r"\.\./assets/[A-Za-z0-9_.-]+", text):
            if not (article.parent / source).resolve().is_file():
                missing_refs.append(f"{record['file']} -> {source}")
    if missing_refs:
        fail(f"missing local asset references: {len(set(missing_refs))}")

    scan_paths = [root / "index.html", root / "manifest.json", root / "README.md"]
    scan_paths.extend(path for path in (root / ".state").rglob("*") if path.is_file())
    for path in scan_paths:
        if SECRET_VALUE_RE.search(path.read_text("utf-8", errors="ignore")):
            fail(f"session value pattern found: {path.relative_to(root)}")

    checksum_entries = 0
    covered: set[Path] = set()
    for line in (root / "SHA256SUMS").read_text("utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail("invalid SHA256SUMS line")
        target = (root / relative).resolve()
        if root not in target.parents or not target.is_file():
            fail(f"invalid checksum target: {relative}")
        if sha256(target) != digest:
            fail(f"checksum mismatch: {relative}")
        covered.add(target)
        checksum_entries += 1

    deliverables = {root / "README.md", root / "index.html", root / "manifest.json"}
    deliverables.update((root / "articles").glob("*.html"))
    deliverables.update(path for path in (root / "assets").iterdir() if path.is_file())
    uncovered = {path.resolve() for path in deliverables} - covered
    if uncovered:
        fail(f"deliverables missing from SHA256SUMS: {len(uncovered)}")

    result = {
        "status": "ok",
        "articles": len(records),
        "assets": len(list((root / "assets").iterdir())),
        "checksum_entries": checksum_entries,
        "missing_local_refs": 0,
        "failed_assets": 0,
        "paywall_markers": 0,
        "session_value_patterns": 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
