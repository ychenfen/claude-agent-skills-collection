#!/usr/bin/env python3
"""File-based IPC bridge from Claude Code to the live Antigravity IDE agent."""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a batch/task to the live Antigravity IDE session (uses Antigravity membership quota)."
    )
    parser.add_argument("prompt", nargs="*", help="Task instructions or prompt for Antigravity")
    parser.add_argument("--input-file", "-i", help="Optional path to input data file (e.g. JSONL/CSV/MD)")
    parser.add_argument("--output-file", "-o", help="Optional path where Antigravity should write output data")
    parser.add_argument("--timeout", "-t", type=int, default=1800, help="Timeout in seconds (default: 1800)")
    parser.add_argument("--channel", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.input_file and not Path(args.input_file).is_file():
        parser.error("--input-file does not exist or is not a file")
    default_root = "/tmp/claude_agy_bridge" + (str(args.channel) if args.channel != 1 else "")
    bridge_dir = os.environ.get("BW_BRIDGE_ROOT_{}".format(args.channel), default_root)
    inbox_dir = os.path.join(bridge_dir, "inbox")
    outbox_dir = os.path.join(bridge_dir, "outbox")

    prompt_text = " ".join(args.prompt).strip()
    if not prompt_text and not sys.stdin.isatty():
        prompt_text = sys.stdin.read().strip()

    if not prompt_text and not args.input_file:
        parser.print_help(sys.stderr)
        sys.exit(1)

    os.makedirs(inbox_dir, exist_ok=True)
    os.makedirs(outbox_dir, exist_ok=True)

    req_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    req_path = os.path.join(inbox_dir, f"req_{req_id}.json")
    tmp_path = os.path.join(inbox_dir, f".tmp_{req_id}.json")
    res_path = os.path.join(outbox_dir, f"res_{req_id}.json")

    payload = {
        "id": req_id,
        "channel": args.channel,
        "created_at": time.time(),
        "prompt": prompt_text,
        "input_file": os.path.abspath(args.input_file) if args.input_file else None,
        "output_file": os.path.abspath(args.output_file) if args.output_file else None,
    }

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, req_path)

    start = time.monotonic()
    while time.monotonic() - start < args.timeout:
        if os.path.exists(res_path):
            time.sleep(0.1)
            with open(res_path, "r", encoding="utf-8") as f:
                res = json.load(f)
            if res.get("id") != req_id:
                print("Response ID does not match request", file=sys.stderr)
                sys.exit(1)
            if res.get("error") or res.get("status") not in (None, "ok"):
                print(res.get("error") or f"status={res.get('status')}", file=sys.stderr)
                sys.exit(1)
            # Watcher versions differ: older ones write "response", newer ones "output".
            text = res.get("response")
            if text is None:
                text = res.get("output")
            if text is None:
                print(f"Unrecognized response format: {sorted(res)}", file=sys.stderr)
                sys.exit(1)
            print(text)
            sys.exit(0)
        time.sleep(1.0)

    print(f"Timeout waiting for Antigravity response ({args.timeout}s). Request ID: {req_id}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
