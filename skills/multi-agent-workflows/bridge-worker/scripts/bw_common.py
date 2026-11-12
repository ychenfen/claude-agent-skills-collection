"""Shared filesystem helpers. Python 3.9+, standard library only."""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def bridge_root(channel):
    if type(channel) is not int or channel not in (1, 2, 3):
        raise ValueError("channel must be 1, 2 or 3")
    default = "/tmp/claude_agy_bridge" + (str(channel) if channel != 1 else "")
    return Path(os.environ.get("BW_BRIDGE_ROOT_{}".format(channel), default))


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is not None


def resolve_path(base, value):
    path = Path(value)
    return path if path.is_absolute() else base / path


def file_sha256(path):
    digest = sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data.encode("utf-8") if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def atomic_copy(source, target):
    """Publish a bounded snapshot, even while a subprocess is writing source."""
    target = Path(target)
    size = os.stat(source).st_size
    fd, temporary = tempfile.mkstemp(prefix="." + target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as output, open(source, "rb") as input_stream:
            remaining = size
            while remaining:
                chunk = input_stream.read(min(remaining, 1024 * 1024))
                if not chunk:
                    break
                output.write(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
