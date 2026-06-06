#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# _lib/emit.sh — shared JSONL emitter helper for all Bumba lifecycle hook scripts.
#
# Usage: . "$(dirname "$0")/../_lib/emit.sh"
#        emit "PreToolUse" "tool=${CLAUDE_TOOL_NAME:-unknown}"
#
# Writes one JSONL line to ${BUMBA_HOOKS_TELEMETRY:-~/data/hooks-telemetry.jsonl}
# with fields: ts, event, session_id, payload (JSON object from key=value args).
# Falls back silently if the sink is not writable — hooks must never block the CLI.
#
# Concurrency: uses flock on a sidecar .lock file for safe concurrent-process appends.
# If flock is unavailable the append proceeds without locking (rare race accepted).

set -u

emit() {
    local event="$1"
    shift

    local sink="${BUMBA_HOOKS_TELEMETRY:-$HOME/data/hooks-telemetry.jsonl}"
    mkdir -p "$(dirname "$sink")" 2>/dev/null || return 0

    local sid="${CLAUDE_SESSION_ID:-unknown}"
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%S.000Z 2>/dev/null || echo "1970-01-01T00:00:00.000Z")"

    # Build payload JSON object from key=value arguments.
    local payload="{}"
    if [ "$#" -gt 0 ]; then
        # awk: iterate over key=value pairs, produce {"k":"v",...}
        payload=$(printf '%s\n' "$@" | awk -F= 'BEGIN{ORS=""; print "{"} NR>1{print ","} {printf "\"%s\":\"%s\"", $1, $2} END{print "}"}')
    fi

    local line="{\"ts\":\"$ts\",\"event\":\"$event\",\"session_id\":\"$sid\",\"payload\":$payload}"

    # Attempt flock-safe append; fall back to direct append if flock not available.
    if command -v flock >/dev/null 2>&1; then
        ( flock -n 9 || exit 0; printf '%s\n' "$line" >> "$sink" ) 9>>"${sink}.lock" 2>/dev/null || true
    else
        printf '%s\n' "$line" >> "$sink" 2>/dev/null || true
    fi
}
