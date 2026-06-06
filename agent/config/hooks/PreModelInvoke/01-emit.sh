#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# PreModelInvoke/01-emit.sh — emits PreModelInvoke telemetry before model API calls.
# Fires before each call to the Anthropic model API within a session.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "PreModelInvoke" "model=${CLAUDE_MODEL:-unknown}"
