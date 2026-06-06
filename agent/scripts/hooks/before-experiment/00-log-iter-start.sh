#!/usr/bin/env bash
#
# 00-log-iter-start.sh — example before-experiment hook.
#
# The runner pipes one-line JSON metadata to stdin (iteration id,
# phase, etc). This hook just emits a marker line so operators can
# see hooks fire end-to-end. Replace with anything from a pre-flight
# disk check to a Slack ping.
#
# Contract reminders:
#   - 30s wall-clock timeout
#   - 8 KB stdout cap
#   - non-zero exit is logged but does NOT crash the loop
#   - JSON object on stdout is parsed as steering directives
#
set -euo pipefail

# Read stdin (best-effort; metadata may be empty in dry-run tests).
metadata="$(cat 2>/dev/null || true)"

iter_id="$(printf '%s' "$metadata" | python3 -c \
  'import json,sys
try:
    d=json.loads(sys.stdin.read() or "{}")
    print(d.get("iter_id") or d.get("id") or "unknown")
except Exception:
    print("unknown")
' 2>/dev/null || echo unknown)"

echo "iter-${iter_id} started"
