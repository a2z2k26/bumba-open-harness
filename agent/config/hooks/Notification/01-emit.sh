#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# Notification/01-emit.sh — emits Notification telemetry on system notifications.
# Fires when the Claude Code CLI emits a notification event (e.g. permission requests).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "Notification" "type=${CLAUDE_NOTIFICATION_TYPE:-unknown}"
