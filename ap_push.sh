#!/usr/bin/env bash
set -euo pipefail

# Ensure we're in a git repo
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$repo_root" ]; then
  echo "[ERR] Not inside a git repository."; exit 1
fi
cd "$repo_root"

# Safety: never push secrets
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "[ABORT] '.env' is tracked! Run: git rm --cached .env && git commit -m 'untrack .env'"; exit 2
fi

# Show what changed
git status --porcelain

# Stage, commit, rebase-pull, push
msg="${1:-chore: autopush $(date -Iseconds)}"
git add -A
git commit -m "$msg" || echo "[INFO] Nothing to commit."
git pull --rebase origin main || true
git push -u origin main
