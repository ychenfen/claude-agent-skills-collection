#!/usr/bin/env python3
"""Run a process group with atomic logs, progress heartbeats and two deadlines."""

import argparse
import fcntl
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bw_common import atomic_copy, atomic_json, atomic_write, file_sha256, utc_now, valid_id


def positive_number(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def size(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def terminate_group(process):
    """Give the entire process group ten seconds, including surviving descendants."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        process.poll()  # Reap the leader, so it does not keep an empty group alive.
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def append_command(run_dir, record):
    # Lock the stable directory inode: replacing commands.jsonl must not replace
    # the inode being locked. No persistent lockfile is needed.
    fd = os.open(str(run_dir), os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        path = run_dir / "commands.jsonl"
        previous = path.read_bytes() if path.exists() else b""
        line = json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
        atomic_write(path, previous + line)
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--hard-timeout", type=positive_number, required=True)
    parser.add_argument("--stall-timeout", type=positive_number, required=True)
    parser.add_argument("--progress-file", action="append", default=[])
    parser.add_argument("--heartbeat-interval", type=positive_number, default=60)
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not valid_id(args.name):
        parser.error("--name must be a safe filename")
    if not args.cmd or args.cmd[0] != "--" or len(args.cmd) == 1:
        parser.error("a command after -- is required")
    cmd = args.cmd[1:]
    run_dir = Path(args.run_dir).resolve()
    staging = None
    process = None
    old_handlers = {}
    stop_signal = [None]

    def request_stop(signum, frame):
        stop_signal[0] = signum

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / (args.name + ".log")
        fd, staging = tempfile.mkstemp(prefix="." + args.name + ".log.running.", dir=str(run_dir))
        started_at = utc_now()
        started = time.monotonic()
        last_progress = started
        last_progress_at = started_at
        progress_paths = [Path(p) for p in args.progress_file]
        sizes = [0] + [size(p) for p in progress_paths]
        atomic_copy(staging, log_path)
        launch_error = None
        for signum in (signal.SIGINT, signal.SIGTERM):
            old_handlers[signum] = signal.signal(signum, request_stop)
        with os.fdopen(fd, "wb") as log_stream:
            try:
                process = subprocess.Popen(cmd, stdout=log_stream, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as exc:
                launch_error = str(exc)
                log_stream.write(("Launch failed: " + launch_error + "\n").encode("utf-8"))
        state = "running" if process is not None else "exited"
        killed_reason = None
        forced_exit = None
        next_heartbeat = started
        published_size = -1

        def heartbeat(now):
            atomic_json(run_dir / "heartbeat.json", {
                "name": args.name, "pid": process.pid if process else None, "state": state,
                "started_at": started_at, "updated_at": utc_now(),
                "elapsed_s": round(now - started, 3), "last_progress_at": last_progress_at,
                "progress_bytes": sum(sizes),
            })

        while process is not None:
            now = time.monotonic()
            current_sizes = [size(Path(staging))] + [size(p) for p in progress_paths]
            if any(new > old for new, old in zip(current_sizes, sizes)):
                last_progress = now
                last_progress_at = utc_now()
            sizes = current_sizes
            if sizes[0] != published_size:
                atomic_copy(staging, log_path)
                published_size = sizes[0]
            if process.poll() is not None:
                state = "exited"
                break
            if stop_signal[0] is not None:
                state, killed_reason = "exited", "signal_{}".format(stop_signal[0])
                forced_exit = 128 + stop_signal[0]
            elif now - started >= args.hard_timeout:
                state, killed_reason = "killed_timeout", "hard_timeout"
                forced_exit = 124
            elif now - last_progress >= args.stall_timeout:
                state, killed_reason = "killed_stall", "stall_timeout"
                forced_exit = 75
            if killed_reason:
                heartbeat(now)
                terminate_group(process)
                break
            if now >= next_heartbeat:
                heartbeat(now)
                next_heartbeat = now + args.heartbeat_interval
            time.sleep(min(0.1, args.heartbeat_interval, args.hard_timeout, args.stall_timeout))
        exit_code = 1 if launch_error else process.returncode
        if forced_exit is not None:
            exit_code = forced_exit
        atomic_copy(staging, log_path)
        sizes = [size(log_path)] + [size(p) for p in progress_paths]
        heartbeat(time.monotonic())
        append_command(run_dir, {
            "name": args.name, "cmd": cmd, "started_at": started_at, "ended_at": utc_now(),
            "exit_code": exit_code, "log_path": str(log_path),
            "log_sha256": file_sha256(log_path), "killed_reason": killed_reason,
        })
        return exit_code if exit_code >= 0 else 128 - exit_code
    except (OSError, ValueError) as exc:
        if process is not None and process.poll() is None:
            terminate_group(process)
        print("FAIL: {}".format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if process is not None:
            terminate_group(process)
        return 130
    finally:
        for signum, old_handler in old_handlers.items():
            signal.signal(signum, old_handler)
        if staging and os.path.exists(staging):
            os.unlink(staging)


if __name__ == "__main__":
    sys.exit(main())
