#!/bin/bash
# SessionStart hook: make the obra/superpowers skills available to Claude Code
# for THIS session only. The skills are fetched into .claude/skills/, which is
# git-ignored, so they enhance the development workflow without ever becoming
# part of the ZebOS codebase.
#
# Idempotent: clones on first run, fast-forwards on later runs, and rebuilds the
# skills directory from the pinned source each time.
set -euo pipefail

REPO_URL="https://github.com/obra/superpowers.git"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SRC_DIR="$PROJECT_DIR/.claude/.superpowers"
SKILLS_DIR="$PROJECT_DIR/.claude/skills"

# Skip cleanly if we can't reach the network — a missing skill set should never
# block a session from starting.
if [ -d "$SRC_DIR/.git" ]; then
  git -C "$SRC_DIR" fetch --quiet --depth 1 origin HEAD 2>/dev/null \
    && git -C "$SRC_DIR" reset --quiet --hard FETCH_HEAD 2>/dev/null \
    || echo "superpowers: fetch failed, using cached copy" >&2
else
  rm -rf "$SRC_DIR"
  if ! git clone --quiet --depth 1 "$REPO_URL" "$SRC_DIR" 2>/dev/null; then
    echo "superpowers: clone failed (offline?), skipping skill setup" >&2
    exit 0
  fi
fi

# Rebuild .claude/skills from the fetched source.
mkdir -p "$SKILLS_DIR"
if [ -d "$SRC_DIR/skills" ]; then
  # Remove previously synced skills, then copy the current set.
  find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -R "$SRC_DIR"/skills/. "$SKILLS_DIR"/
  cp -f "$SRC_DIR/LICENSE" "$SKILLS_DIR/LICENSE-superpowers" 2>/dev/null || true
  echo "superpowers: synced $(find "$SKILLS_DIR" -name SKILL.md | wc -l | tr -d ' ') skills into .claude/skills/"
fi
