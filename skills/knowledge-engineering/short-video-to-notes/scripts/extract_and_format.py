#!/usr/bin/env python3
"""Extract 16kHz WAV audio, compute SHA-256 fingerprint, and format ASR JSON into .srt + YAML-frontmatter Markdown notes."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def sha256_prefix(path: Path, length: int = 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.is_file():
        return 0.0
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        return round(float(res.stdout.strip()), 2)
    except ValueError:
        return 0.0


def extract_wav(media_path: Path, wav_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH; install ffmpeg to extract audio.")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(wav_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr.strip()}")


def format_srt_time(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for idx, seg in enumerate(segments, start=1):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 3.0))
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        blocks.append(f"{idx}\n{format_srt_time(start)} --> {format_srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


def render_markdown(
    title: str,
    source_url: str,
    digest: str,
    duration: float,
    asr_engine: str,
    transcript_text: str,
    segments: list[dict[str, Any]],
) -> str:
    today = dt.date.today().isoformat()
    timeline_lines: list[str] = []
    for seg in segments:
        start = int(float(seg.get("start", 0.0)))
        mm, ss = divmod(start, 60)
        txt = str(seg.get("text", "")).strip()
        if txt:
            timeline_lines.append(f"- `[{mm:02d}:{ss:02d}]` {txt}")
    timeline_block = "\n".join(timeline_lines) if timeline_lines else transcript_text.strip()

    return f"""---
title: "{title}"
source_type: "video"
source_url: "{source_url}"
media_sha256_prefix: "{digest}"
duration_sec: {duration}
asr_engine: "{asr_engine}"
created_at: "{today}"
rights_status: "personal-study-only"
tags:
  - 视频笔记
---

# {title}

## 一、核心结论（TL;DR）

- 待根据转写稿提炼核心结论 1
- 待根据转写稿提炼核心结论 2
- 待根据转写稿提炼核心结论 3

## 二、结构化要点

### 1. 关键方法与步骤

- 结合下方逐字稿与同音词规范整理。

## 三、原始转写稿（待术语校对）

<details>
<summary>展开完整时间轴转写稿</summary>

{timeline_block}

</details>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", nargs="?", help="Local video/audio file path (optional if --transcript-json given)")
    parser.add_argument("--title", default="未命名视频笔记", help="Note title")
    parser.add_argument("--source-url", default="", help="Original share URL")
    parser.add_argument("--transcript-json", help="Path to ASR JSON output")
    parser.add_argument("--asr-engine", default="SenseVoice", help="ASR engine name")
    parser.add_argument("--extract-audio", action="store_true", help="Extract 16kHz mono WAV via ffmpeg")
    parser.add_argument("--out-dir", default=".", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    media_path = Path(args.media).resolve() if args.media else None
    digest = sha256_prefix(media_path) if (media_path and media_path.is_file()) else "no-local-media"
    duration = probe_duration(media_path) if (media_path and media_path.is_file()) else 0.0
    stem = f"file-{digest}" if digest != "no-local-media" else "video-note"

    if args.extract_audio:
        if not media_path or not media_path.is_file():
            print("error: --extract-audio requires an existing media file", file=sys.stderr)
            return 2
        wav_path = out_dir / f"{stem}.wav"
        extract_wav(media_path, wav_path)

    transcript_text = ""
    segments: list[dict[str, Any]] = []
    if args.transcript_json:
        raw = json.loads(Path(args.transcript_json).read_text(encoding="utf-8"))
        transcript_text = str(raw.get("text") or raw.get("transcript") or "")
        segments = list(raw.get("segments") or [])
        if not duration and raw.get("duration"):
            duration = float(raw["duration"])

    source_url = args.source_url or (f"local://{media_path.name}" if media_path else "unknown")
    md_path = out_dir / f"{stem}.md"
    md_path.write_text(
        render_markdown(
            title=args.title,
            source_url=source_url,
            digest=digest,
            duration=duration,
            asr_engine=args.asr_engine,
            transcript_text=transcript_text,
            segments=segments,
        ),
        encoding="utf-8",
    )

    if segments:
        srt_path = out_dir / f"{stem}.srt"
        srt_path.write_text(build_srt(segments), encoding="utf-8")

    summary = {
        "status": "ok",
        "media_sha256_prefix": digest,
        "duration_sec": duration,
        "markdown_note": str(md_path),
        "srt_file": str(out_dir / f"{stem}.srt") if segments else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
