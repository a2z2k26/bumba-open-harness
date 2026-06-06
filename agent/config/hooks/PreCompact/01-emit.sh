#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# PreCompact/01-emit.sh — emits PreCompact telemetry before transcript compaction.
# Fires before the Claude Code CLI initiates context window compaction.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "PreCompact" "context_tokens=${CLAUDE_CONTEXT_TOKENS:-unknown}"
