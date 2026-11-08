#!/usr/bin/env python3
"""Scan a workspace or artifact directory to enforce the 5MB per-file limit and zero-secret guardrails."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
SECRET_NAME_HINTS = ("credential", "secret", "password", "token", "cookie", "id_rsa", "id_ed25519")
SECRET_EXTS = (".pem", ".key", ".p12", ".pfx", ".kdbx")
TOKEN_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PRIVATE )?KEY-----"),
]


def is_secret_filename(path: Path) -> str:
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        if not name.endswith((".example", ".sample", ".template")):
            return "dotenv file"
    if name.endswith(SECRET_EXTS):
        return f"private key/certificate extension ({path.suffix})"
    for hint in SECRET_NAME_HINTS:
        if hint in name and path.suffix.lower() in {".json", ".txt", ".yaml", ".yml", ".ini", ".conf", ""}:
            return f"filename contains sensitive keyword '{hint}'"
    return ""


def scan_text_for_tokens(path: Path) -> str:
    if path.stat().st_size > 1024 * 1024:
        return ""
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""
    for pat in TOKEN_PATTERNS:
        if pat.search(content):
            return f"matched secret pattern: {pat.pattern}"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Directory or file to scan")
    parser.add_argument("--max-file-mb", type=float, default=5.0, help="Max single file size in MB (default: 5.0)")
    parser.add_argument("--max-total-mb", type=float, default=50.0, help="Max total size in MB (default: 50.0)")
    args = parser.parse_args()

    root = Path(args.target).resolve()
    max_file_bytes = int(args.max_file_mb * 1024 * 1024)
    max_total_bytes = int(args.max_total_mb * 1024 * 1024)

    violations: list[dict[str, str]] = []
    total_bytes = 0
    scanned_files = 0

    files_to_check: list[Path] = []
    if root.is_file():
        files_to_check.append(root)
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for fname in sorted(filenames):
                files_to_check.append(Path(dirpath) / fname)

    for fpath in files_to_check:
        try:
            size = fpath.stat().st_size
        except OSError:
            continue
        scanned_files += 1
        total_bytes += size
        rel = str(fpath.relative_to(root)) if fpath != root else fpath.name

        if size > max_file_bytes:
            violations.append(
                {
                    "file": rel,
                    "type": "oversize_file",
                    "detail": f"{size / (1024 * 1024):.2f} MB exceeds {args.max_file_mb:.1f} MB limit",
                }
            )
        reason = is_secret_filename(fpath)
        if reason:
            violations.append({"file": rel, "type": "secret_filename", "detail": reason})
        else:
            token_hit = scan_text_for_tokens(fpath)
            if token_hit:
                violations.append({"file": rel, "type": "secret_content", "detail": token_hit})

    if total_bytes > max_total_bytes:
        violations.append(
            {
                "file": ".",
                "type": "oversize_bundle",
                "detail": f"total {total_bytes / (1024 * 1024):.2f} MB exceeds {args.max_total_mb:.1f} MB limit",
            }
        )

    report = {
        "status": "ok" if not violations else "violation",
        "scanned_files": scanned_files,
        "total_kb": round(total_bytes / 1024, 2),
        "violations": violations,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
