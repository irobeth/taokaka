#!/usr/bin/env bash
# ship.sh — commit and push all changes with a version tag
# Usage: ./ship.sh "commit message"
#   or:  ./ship.sh   (uses a default message)

set -e
cd "$(dirname "$0")"

MSG="${1:-Ship it}"

git add -A
git commit -m "$MSG

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
git push

echo ""
echo "Shipped."
