#!/usr/bin/env bash
set -euo pipefail

# One-Command Skill Installer for ychenfen/claude-agent-skills-collection
# Supports: Claude Code (~/.claude/skills), OpenAI Codex (~/.codex/skills), or custom directory.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$ROOT_DIR/skills"

MODE=""
SUITE_NAME=""
SKILL_NAME=""
TARGET="both"
CUSTOM_DEST=""
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  ./install.sh --list
  ./install.sh --all [--target claude|codex|both] [--dest DIR] [--dry-run]
  ./install.sh --suite <suite-name> [--target claude|codex|both] [--dest DIR]
  ./install.sh --skill <skill-name> [--target claude|codex|both] [--dest DIR]

Suites:
  academic-modeling       (5 skills: gmcm-paper, cumcm-delivery-compliance, mcm-humanizer, competition-model-quality-freeze, guosai-docx-format)
  career-automation       (3 skills: resume-writer, boss-zhipin, browser-form-registration)
  knowledge-engineering   (3 skills: marginnote-cards, wechat-paid-album-archive, short-video-to-notes)
  multi-agent-workflows   (4 skills: agent-commander, antigravity, bridge-worker, cloud-local-github-loop)

Targets:
  claude   Install into ~/.claude/skills/<skill-name>
  codex    Install into ~/.codex/skills/<skill-name>
  both     Install into both ~/.claude/skills and ~/.codex/skills (default)
EOF
}

list_skills() {
  echo "Available Suites & Skills in claude-agent-skills-collection:"
  echo "============================================================"
  local total=0
  for suite_dir in "$SKILLS_ROOT"/*/; do
    [ -d "$suite_dir" ] || continue
    local suite
    suite="$(basename "$suite_dir")"
    echo ""
    echo "[$suite]"
    for skill_dir in "$suite_dir"*/; do
      [ -d "$skill_dir" ] || continue
      local skill
      skill="$(basename "$skill_dir")"
      local scripts_count=0
      if [ -d "$skill_dir/scripts" ]; then
        scripts_count="$(find "$skill_dir/scripts" -maxdepth 1 -name '*.py' | wc -l | tr -d ' ')"
      fi
      printf "  - %-34s (scripts: %s, codex-ready: yes)\n" "$skill" "$scripts_count"
      total=$((total + 1))
    done
  done
  echo ""
  echo "Total: $total skills across 4 suites."
}

while [ $# -gt 0 ]; do
  case "$1" in
    --list|-l)
      MODE="list"
      shift
      ;;
    --all|-a)
      MODE="all"
      shift
      ;;
    --suite)
      MODE="suite"
      SUITE_NAME="${2:-}"
      shift 2
      ;;
    --skill)
      MODE="skill"
      SKILL_NAME="${2:-}"
      shift 2
      ;;
    --target|-t)
      TARGET="${2:-both}"
      shift 2
      ;;
    --dest)
      CUSTOM_DEST="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -z "$MODE" ]; then
  usage
  exit 0
fi

if [ "$MODE" = "list" ]; then
  list_skills
  exit 0
fi

declare -a DEST_DIRS=()
if [ -n "$CUSTOM_DEST" ]; then
  case "$TARGET" in
    claude) DEST_DIRS=("$CUSTOM_DEST/claude/skills") ;;
    codex)  DEST_DIRS=("$CUSTOM_DEST/codex/skills") ;;
    both)   DEST_DIRS=("$CUSTOM_DEST/claude/skills" "$CUSTOM_DEST/codex/skills") ;;
    *) echo "Invalid --target: $TARGET (expected claude, codex, or both)" >&2; exit 2 ;;
  esac
else
  case "$TARGET" in
    claude) DEST_DIRS=("$HOME/.claude/skills") ;;
    codex)  DEST_DIRS=("$HOME/.codex/skills") ;;
    both)   DEST_DIRS=("$HOME/.claude/skills" "$HOME/.codex/skills") ;;
    *) echo "Invalid --target: $TARGET (expected claude, codex, or both)" >&2; exit 2 ;;
  esac
fi

install_one_skill() {
  local src_dir="$1"
  local name
  name="$(basename "$src_dir")"
  for dest_base in "${DEST_DIRS[@]}"; do
    local target_dir="$dest_base/$name"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "[dry-run] Would copy $src_dir -> $target_dir"
    else
      mkdir -p "$dest_base"
      if [ -e "$target_dir" ] || [ -L "$target_dir" ]; then
        local backup_base="$dest_base/../skill-backups"
        mkdir -p "$backup_base"
        local backup_dir
        backup_dir="$(mktemp -d "$backup_base/$name.$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"
        mv "$target_dir" "$backup_dir/$name"
        echo "Backup: $backup_dir/$name"
      fi
      cp -R "$src_dir" "$target_dir"
      echo "Installed: $name -> $target_dir"
    fi
  done
}

case "$MODE" in
  all)
    count=0
    for suite_dir in "$SKILLS_ROOT"/*/; do
      for skill_dir in "$suite_dir"*/; do
        [ -f "$skill_dir/SKILL.md" ] || continue
        install_one_skill "${skill_dir%/}"
        count=$((count + 1))
      done
    done
    echo "Done! Installed $count skills (target=$TARGET)."
    ;;
  suite)
    suite_path="$SKILLS_ROOT/$SUITE_NAME"
    if [ ! -d "$suite_path" ]; then
      echo "Error: suite '$SUITE_NAME' not found under $SKILLS_ROOT" >&2
      exit 1
    fi
    count=0
    for skill_dir in "$suite_path"/*/; do
      [ -f "$skill_dir/SKILL.md" ] || continue
      install_one_skill "${skill_dir%/}"
      count=$((count + 1))
    done
    echo "Done! Installed $count skills from suite '$SUITE_NAME' (target=$TARGET)."
    ;;
  skill)
    found=""
    for suite_dir in "$SKILLS_ROOT"/*/; do
      if [ -f "$suite_dir/$SKILL_NAME/SKILL.md" ]; then
        found="$suite_dir/$SKILL_NAME"
        break
      fi
    done
    if [ -z "$found" ]; then
      echo "Error: skill '$SKILL_NAME' not found in any suite." >&2
      exit 1
    fi
    install_one_skill "$found"
    echo "Done! Installed skill '$SKILL_NAME' (target=$TARGET)."
    ;;
esac
