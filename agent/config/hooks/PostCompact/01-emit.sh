#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# PostCompact/01-emit.sh — emits PostCompact telemetry after transcript compaction.
# Fires after the Claude Code CLI completes context window compaction.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "PostCompact" "compact_ratio=${CLAUDE_COMPACT_RATIO:-unknown}"
