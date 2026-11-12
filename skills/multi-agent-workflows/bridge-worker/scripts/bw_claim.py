#!/usr/bin/env python3
"""Atomically claim the oldest request in one channel."""

import argparse
import json
import os
import sys
from pathlib import Path

from bw_common import atomic_json, bridge_root, file_sha256, resolve_path, utc_now, valid_id


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--req-id")
    parser.add_argument("--adopt", action="store_true",
                        help="with --req-id: record a request this channel's listener already renamed to .claimed")
    args = parser.parse_args(argv)
    if args.req_id is not None and not valid_id(args.req_id):
        parser.error("invalid --req-id")
    root = bridge_root(args.channel).resolve()
    inbox = root / "inbox"
    try:
        if args.adopt:
            # Listener sessions started before this skill rename the request themselves.
            if not args.req_id:
                parser.error("--adopt requires --req-id")
            claimed = inbox / "req_{}.json.claimed".format(args.req_id)
            run_dir = root / "runs" / args.req_id
            if not claimed.is_file():
                raise ValueError("no claimed request to adopt in this channel: " + args.req_id)
            if run_dir.exists():
                raise ValueError("request already has a run directory: " + args.req_id)
            request = json.loads(claimed.read_text(encoding="utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            if "channel" in request and request["channel"] != args.channel:
                raise ValueError("request channel does not match --channel")
            input_path = resolve_path(inbox, request.get("input_file") or str(claimed))
            output_path = resolve_path(root, request.get("output_file") or "outbox/res_{}.json".format(args.req_id))
            input_hash = file_sha256(input_path)
            run_dir.mkdir(parents=True, exist_ok=False)
            atomic_json(run_dir / "claim.json", {
                "id": args.req_id, "channel": args.channel, "claimed_at_utc": utc_now(), "adopted": True,
                "pid": os.getpid(), "input_file": str(input_path),
                "input_sha256": input_hash, "output_file": str(output_path),
            })
            print(run_dir)
            return 0
        candidates = list(inbox.glob("req_*.json"))
        if args.req_id:
            candidates = [p for p in candidates if p.name == "req_{}.json".format(args.req_id)]
        # Files may disappear between enumeration and stat because another worker won.
        dated = []
        for path in candidates:
            try:
                dated.append((path.stat().st_mtime_ns, path.name, path))
            except FileNotFoundError:
                continue
        for _, _, path in sorted(dated):
            task_id = path.name[4:-5]
            if not valid_id(task_id):
                raise ValueError("invalid request filename: " + path.name)
            try:
                request = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            if "channel" in request and (type(request["channel"]) is not int or request["channel"] != args.channel):
                raise ValueError("request channel does not match --channel")
            if "id" in request and request["id"] != task_id:
                raise ValueError("request id does not match filename")
            claimed = path.with_name(path.name + ".claimed")
            run_dir = root / "runs" / task_id
            if claimed.exists() or run_dir.exists():
                raise ValueError("request already claimed: " + task_id)
            # If no separate task file was supplied, the request itself is the input.
            # ask-agy writes explicit nulls for prompt-only requests.
            input_path = resolve_path(inbox, request.get("input_file") or str(path))
            output_path = resolve_path(root, request.get("output_file") or "outbox/res_{}.json".format(task_id))
            input_hash = file_sha256(input_path)
            try:
                os.rename(path, claimed)
            except OSError:
                continue
            run_dir.mkdir(parents=True, exist_ok=False)
            atomic_json(run_dir / "claim.json", {
                "id": task_id, "channel": args.channel, "claimed_at_utc": utc_now(),
                "pid": os.getpid(), "input_file": str(claimed if input_path == path else input_path),
                "input_sha256": input_hash, "output_file": str(output_path),
            })
            print(run_dir)
            return 0
        print("FAIL: no claimable requests", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError) as exc:
        print("FAIL: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
