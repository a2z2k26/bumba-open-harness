#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# SessionEnd/01-emit.sh — emits SessionEnd telemetry to ~/data/hooks-telemetry.jsonl.
# Fires when a Claude Code CLI session ends (distinct from Stop which fires mid-stop).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "SessionEnd"
