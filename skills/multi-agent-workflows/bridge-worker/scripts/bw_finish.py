#!/usr/bin/env python3
"""Verify a delivery and atomically publish a bridge-compatible receipt."""

import argparse
import sys
from pathlib import Path

from bw_common import atomic_json, bridge_root, file_sha256, resolve_path
from bw_verify import verify_delivery


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delivery")
    args = parser.parse_args(argv)
    path = Path(args.delivery).resolve()
    result = verify_delivery(path)
    result.display()
    if not result.schema_valid:
        return 1
    data = result.delivery
    status = data["status"]
    if status == "ok" and result.failed:
        return 1
    reasons = data["unverified"] or data["pending_confirmation"]
    if status != "ok" and not reasons:
        print("FAIL finish: blocked/failed requires unverified or pending_confirmation")
        return 1
    try:
        receipt = {"id": data["task_id"], "status": "ok" if status == "ok" else "error",
                   "delivery_path": str(path), "delivery_sha256": file_sha256(path),
                   "verify": {"passed": result.passed, "failed": result.failed}}
        if status == "ok":
            receipt["response"] = (resolve_path(path.parent, data["report"]).read_text(encoding="utf-8")
                                   if data.get("report") else "Verified delivery: " + str(path))
        else:
            receipt["error"] = status + ": " + reasons[0]
        output = bridge_root(data["channel"]) / "outbox" / ("res_" + data["task_id"] + ".json")
        atomic_json(output, receipt)
        print("Receipt: " + str(output))
        return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print("FAIL finish: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
