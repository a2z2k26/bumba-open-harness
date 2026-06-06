#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# PostModelInvoke/01-emit.sh — emits PostModelInvoke telemetry after model API responses.
# Fires after the model API call completes and response is available.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "PostModelInvoke" "model=${CLAUDE_MODEL:-unknown}" "input_tokens=${CLAUDE_INPUT_TOKENS:-0}" "output_tokens=${CLAUDE_OUTPUT_TOKENS:-0}"
