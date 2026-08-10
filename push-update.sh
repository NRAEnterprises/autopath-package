#!/bin/sh
set -eu

GITHUB_USER="NRAEnterprises"
REPO_NAME="autopath-package"

BRANCH="${BRANCH:-main}"
LOCAL_DIR="${LOCAL_DIR:-$HOME/autopath-package}"

LICENSE_FILE="LICENSE"

GIT_AUTHOR_NAME="Nabbey88"
GIT_AUTHOR_EMAIL="Nabbey88@users.noreply.github.com"

MIT_HOLDER_1="Nicholas Abbey"
MIT_HOLDER_2="NRAEnterprises"

have_cmd() { command -v "$1" >/dev/null 2>&1; }

if ! have_cmd git; then
  echo "git is required but was not found on PATH." >&2
  exit 1
fi

cd "$LOCAL_DIR"
LOCAL_DIR="$(pwd)"
REMOTE_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}.git"

echo "Repo:   $REMOTE_URL"
echo "Branch: $BRANCH"
echo "Local:  $LOCAL_DIR"
echo

if [ ! -d ".git" ]; then
  echo "No git repo here yet — initializing."
  git init -b "$BRANCH"
  git remote add origin "$REMOTE_URL"
fi

if git remote get-url origin >/dev/null 2>&1; then
  current_remote="$(git remote get-url origin)"
  if [ "$current_remote" != "$REMOTE_URL" ]; then
    echo "WARNING: origin remote mismatch:" >&2
    echo "  current:   $current_remote" >&2
    echo "  expected:  $REMOTE_URL" >&2
    exit 1
  fi
else
  git remote add origin "$REMOTE_URL"
fi

git config user.name "$GIT_AUTHOR_NAME"
git config user.email "$GIT_AUTHOR_EMAIL"

if [ ! -f "$LICENSE_FILE" ]; then
  YEAR_NOW="$(date +%Y)"
  echo "LICENSE missing — creating default MIT LICENSE ($YEAR_NOW)..."
  cat > "$LICENSE_FILE" <<EOF_LIC
MIT License

Copyright (c) $YEAR_NOW $MIT_HOLDER_1
Copyright (c) $YEAR_NOW $MIT_HOLDER_2

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF_LIC
else
  echo "LICENSE already exists — leaving it untouched."
fi

echo "Checking remote state..."
if git ls-remote --exit-code origin "$BRANCH" >/dev/null 2>&1; then
  echo "Fetching and rebasing onto origin/$BRANCH..."
  git fetch origin "$BRANCH"

  if ! git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git branch "$BRANCH" "origin/$BRANCH"
  fi

  git checkout "$BRANCH" >/dev/null 2>&1 || true
  git pull --rebase --autostash origin "$BRANCH" || {
    echo "ERROR: pull --rebase failed (conflict). Resolve manually and rerun." >&2
    exit 1
  }
else
  echo "Remote branch '$BRANCH' doesn't exist yet — first push will create it."
fi

echo
git add -A

if git diff --cached --quiet; then
  echo
  echo "Nothing to commit — working tree already matches last commit."
  exit 0
fi

echo
echo "Committing: Update to latest"
git commit -m "Update to latest"

echo "Pushing to origin/$BRANCH..."
git push -u origin "$BRANCH"

echo
echo "Done. $REMOTE_URL is now up to date."
echo
echo "Changes pushed:"
git show --stat --format="" HEAD
