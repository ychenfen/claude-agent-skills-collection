#!/usr/bin/env python3
"""Generate or validate a .ai/next_task.md task specification for offline self-hosted runner execution."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def render_task_md(
    task_id: str,
    title: str,
    command: str,
    expected_outputs: list[str],
    timeout_minutes: int,
    notes: str,
) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    outputs_yaml = "\n".join(f'  - "{item}"' for item in expected_outputs) or '  - "results/summary.json"'
    outputs_checklist = "\n".join(f"- [ ] `{item}`" for item in expected_outputs) or "- [ ] `results/summary.json`"
    return f"""---
task_id: "{task_id}"
title: "{title}"
status: "queued"
created_at_utc: "{now}"
timeout_minutes: {timeout_minutes}
max_artifact_mb: 5
expected_outputs:
{outputs_yaml}
---

# Next Local Runner Task: {title} (`{task_id}`)

## 1. Execution Command

```bash
{command}
```

## 2. Expected Outputs & Guardrails

{outputs_checklist}

- Before committing results back to the repository, run:
  ```bash
  python3 skills/multi-agent-workflows/cloud-local-github-loop/scripts/check_guardrails.py .
  ```
- Write execution metadata (`exit_code`, `duration_sec`, `commit_sha`, `output_sha256`) to `.ai/last_result.json`.

## 3. Context & Notes

{notes or "Dispatched asynchronously because the local self-hosted runner was offline/asleep."}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True, help="Unique task identifier (e.g. exp-042)")
    parser.add_argument("--title", required=True, help="Concise human-readable task title")
    parser.add_argument("--command", required=True, help="Shell command for the local runner/agent to execute")
    parser.add_argument(
        "--expected-output",
        action="append",
        default=[],
        help="Expected relative output path (repeatable)",
    )
    parser.add_argument("--timeout-minutes", type=int, default=30, help="Task timeout in minutes")
    parser.add_argument("--notes", default="", help="Additional context or acceptance criteria")
    parser.add_argument("--out", default=".ai/next_task.md", help="Output path (default: .ai/next_task.md)")
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_task_md(
        task_id=args.task_id,
        title=args.title,
        command=args.command,
        expected_outputs=args.expected_output,
        timeout_minutes=args.timeout_minutes,
        notes=args.notes,
    )
    out_path.write_text(content, encoding="utf-8")
    print(json.dumps({"status": "queued", "task_id": args.task_id, "path": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
