#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository yet. Run: git init && git branch -M main"
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "No GitHub remote configured yet."
  echo "Run: git remote add origin git@github.com:YOUR_USER/YOUR_REPO.git"
  exit 1
fi

git add index.html data/status.json README.md .nojekyll .github/workflows/pages.yml
git commit -m "Update dashboard status" || true
git push origin main

