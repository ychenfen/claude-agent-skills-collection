#!/usr/bin/env python3
"""Render claim placeholders only after checking their source evidence."""

import argparse
import json
import re
import sys
from pathlib import Path

from bw_common import atomic_write
from bw_verify import schema_errors, verify_claim


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delivery")
    parser.add_argument("template")
    parser.add_argument("-o", required=True, dest="report")
    args = parser.parse_args(argv)
    try:
        path = Path(args.delivery).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        errors = schema_errors(data)
        if errors:
            raise ValueError("invalid schema: " + "; ".join(errors))
        template = Path(args.template).read_text(encoding="utf-8")
        pattern = re.compile(r"\{\{c:([^{}]*)\}\}")
        identifiers = set(pattern.findall(template))
        claims = {claim["id"]: claim for claim in data["claims"]}
        for identifier in sorted(identifiers):
            if identifier not in claims:
                raise ValueError("unknown claim id: " + identifier)
            explanation = verify_claim(claims[identifier], path.parent)
            print("PASS claim {}: {}".format(identifier, explanation))
        rendered = pattern.sub(lambda match: claims[match[1]]["value"], template)
        atomic_write(args.report, rendered)
        return 0
    except (OSError, ValueError, KeyError, IndexError, TypeError, UnicodeError, ArithmeticError, re.error) as exc:
        print("FAIL render: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
