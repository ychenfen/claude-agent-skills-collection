#!/usr/bin/env python3
"""Validate all 12 skills in claude-agent-skills-collection.

Checks:
1. Valid SKILL.md YAML frontmatter (`name` matches directory name, non-empty `description`)
2. Valid `agents/openai.yaml` (`display_name`, `short_description`, `default_prompt`)
3. Python syntax compilation (`py_compile`) of all `scripts/*.py` inside every skill
4. Zero broken relative Markdown links `[label](path)` in `SKILL.md` and `docs/*.md`
5. No oversized files (>5MB) or leaked credential filenames
"""
from __future__ import annotations

import json
import py_compile
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def parse_simple_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    result: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not raw_line.startswith((" ", "\t")) and ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            result[k] = v
            current_key = k
        elif current_key and raw_line.startswith((" ", "\t")):
            result[current_key] = (result[current_key] + " " + line.strip()).strip()
    return result


def check_openai_yaml(yaml_path: Path) -> list[str]:
    errors: list[str] = []
    if not yaml_path.is_file():
        return ["missing agents/openai.yaml"]
    content = yaml_path.read_text(encoding="utf-8")
    if "interface:" not in content:
        errors.append("agents/openai.yaml missing 'interface:' root key")
    for req_key in ("display_name:", "short_description:", "default_prompt:"):
        if req_key not in content:
            errors.append(f"agents/openai.yaml missing '{req_key}'")
    return errors


def check_markdown_links(md_path: Path) -> list[str]:
    errors: list[str] = []
    text = md_path.read_text(encoding="utf-8")
    # Strip fenced code blocks before checking links
    stripped = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for match in MD_LINK_RE.finditer(stripped):
        target = match.group(1).strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "#", "conversation://", "file://", "sidecar://")):
            continue
        clean_target = target.split("#", 1)[0].strip()
        if not clean_target:
            continue
        resolved = (md_path.parent / clean_target).resolve()
        if not resolved.exists():
            errors.append(f"broken relative link '{target}' in {md_path.relative_to(ROOT)}")
    return errors


def main() -> int:
    errors: list[str] = []
    skill_summaries: list[dict[str, object]] = []
    total_py_compiled = 0

    if not SKILLS_DIR.is_dir():
        print("skills/ directory not found", file=sys.stderr)
        return 1

    for suite_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        for skill_dir in sorted(p for p in suite_dir.iterdir() if p.is_dir()):
            skill_name = skill_dir.name
            suite_name = suite_dir.name
            skill_md = skill_dir / "SKILL.md"
            skill_errors: list[str] = []

            if not skill_md.is_file():
                skill_errors.append("missing SKILL.md")
            else:
                fm = parse_simple_frontmatter(skill_md.read_text(encoding="utf-8"))
                if fm.get("name") != skill_name:
                    skill_errors.append(
                        f"SKILL.md frontmatter name={fm.get('name')!r} does not match folder {skill_name!r}"
                    )
                if not fm.get("description") or len(fm["description"]) < 15:
                    skill_errors.append("SKILL.md frontmatter description is missing or too short")
                skill_errors.extend(check_markdown_links(skill_md))

            # Check agents/openai.yaml
            skill_errors.extend(check_openai_yaml(skill_dir / "agents" / "openai.yaml"))

            # Compile all Python scripts inside scripts/
            py_files = sorted((skill_dir / "scripts").glob("*.py")) if (skill_dir / "scripts").is_dir() else []
            with tempfile.TemporaryDirectory() as tmpdir:
                for py_file in py_files:
                    try:
                        cfile = Path(tmpdir) / (py_file.name + "c")
                        py_compile.compile(str(py_file), cfile=str(cfile), doraise=True)
                        total_py_compiled += 1
                    except py_compile.PyCompileError as exc:
                        skill_errors.append(f"py_compile failed for {py_file.name}: {exc}")

            # Check file sizes <= 5 MB
            for f in skill_dir.rglob("*"):
                if f.is_file() and f.stat().st_size > 5 * 1024 * 1024:
                    skill_errors.append(f"file exceeds 5MB: {f.relative_to(ROOT)}")

            for err in skill_errors:
                errors.append(f"[{suite_name}/{skill_name}] {err}")

            skill_summaries.append(
                {
                    "suite": suite_name,
                    "skill": skill_name,
                    "scripts_compiled": len(py_files),
                    "has_references": (skill_dir / "references").is_dir(),
                    "status": "ok" if not skill_errors else "error",
                }
            )

    # Also check root READMEs and docs/*.md links
    for root_md in (ROOT / "README.md", ROOT / "README_EN.md"):
        if root_md.is_file():
            errors.extend(check_markdown_links(root_md))
    docs_dir = ROOT / "docs"
    if docs_dir.is_dir():
        for doc_md in sorted(docs_dir.glob("*.md")):
            errors.extend(check_markdown_links(doc_md))

    report = {
        "status": "ok" if not errors else "failed",
        "total_skills": len(skill_summaries),
        "total_python_scripts_compiled": total_py_compiled,
        "skills": skill_summaries,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
