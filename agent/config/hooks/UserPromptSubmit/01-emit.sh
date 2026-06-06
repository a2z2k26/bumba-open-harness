#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# UserPromptSubmit/01-emit.sh — emits UserPromptSubmit telemetry on each user message.
# Fires when the user submits a prompt to the Claude Code CLI session.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "UserPromptSubmit"
