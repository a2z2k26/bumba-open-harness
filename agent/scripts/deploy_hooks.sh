#!/bin/bash
# deploy_hooks.sh -- Single-source-of-truth hook tree deployment
# Purpose: Rsync the canonical 13-point hook taxonomy at agent/config/hooks/
#          to the runtime location at ~/.claude/hooks/.
# Run as: any user (deploys to the invoking user's $HOME/.claude/hooks)
#
# Replaces the inlined per-hook copy loop that previously lived in
# install.sh:134-143. The canonical tree is agent/config/hooks/ — anything
# under ~/.claude/hooks/ that is not in the source tree gets deleted by
# --delete so the runtime never drifts from source.
#
# Sprint E1.2 / issue #1712 — hook tree consolidation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_DIR="$REPO_ROOT/agent/config/hooks/"
TARGET_DIR="${HOME}/.claude/hooks/"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "ERROR: source tree $SOURCE_DIR not found"
    exit 1
fi

mkdir -p "$TARGET_DIR"

echo "Deploying hooks: $SOURCE_DIR -> $TARGET_DIR"
rsync -av --delete "$SOURCE_DIR" "$TARGET_DIR"
echo "Hook tree deployed."
