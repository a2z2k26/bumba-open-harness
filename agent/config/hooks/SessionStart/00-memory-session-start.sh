#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# SessionStart/00-memory-session-start.sh — Bumba memory context injection + kernel integrity check.
# Relocated from ~/.claude/hooks/memory-session-start.sh; emit call appended.
#
# Sources the shared emit helper and emits a SessionStart telemetry event to
# ~/data/hooks-telemetry.jsonl in addition to existing memory + integrity logic.
# The 00- prefix ensures this fires before any other SessionStart hooks.

# Source the shared emit helper (path relative to this script's location).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"

MEMORY_DB="/opt/bumba-harness/data/memory.db"
BASELINE_FILE="/opt/bumba-harness/data/kernel-baseline.json"
PRIMER_PATH="/opt/bumba-harness/.claude/projects/-opt-bumba-harness-agent/memory/primer.json"

context_parts=()

# --- Load T1 session primer ---
primer_block=""
if [ -f "$PRIMER_PATH" ] && command -v python3 &>/dev/null; then
    primer_json=$(cat "$PRIMER_PATH" 2>/dev/null)
    if [ -n "$primer_json" ]; then
        primer_data=$(python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    data = json.loads(sys.stdin.read())
    exp = data.get('expires_at')
    if exp:
        now = datetime.now(timezone.utc).isoformat()
        if now > exp:
            sys.exit(1)
    print(json.dumps(data))
except Exception:
    sys.exit(1)
" <<< "$primer_json" 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "$primer_data" ]; then
            primer_block=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
tasks = data.get('tasks', [])
lines = ['=== SESSION PRIMER ===']
if tasks:
    lines.append('Active tasks:')
    for t in tasks[:5]:
        lines.append(f'  - [{t.get(\"priority\",\"?\")}] {t.get(\"title\",\"?\")} ({t.get(\"status\",\"?\")})')
print('\n'.join(lines))
" <<< "$primer_data" 2>/dev/null)
        fi
    fi
fi

# --- Load recent knowledge from SQLite ---
if [ -f "$MEMORY_DB" ] && command -v sqlite3 &>/dev/null; then
    recent_knowledge=$(sqlite3 "$MEMORY_DB" "
        SELECT content FROM knowledge
        WHERE expires_at IS NULL OR expires_at > datetime('now')
        ORDER BY created_at DESC
        LIMIT 10
    " 2>/dev/null)

    if [ -n "$recent_knowledge" ]; then
        context_parts+=("=== RECENT KNOWLEDGE ===
$recent_knowledge")
    fi
fi

# --- Kernel integrity verification ---
integrity_status="ok"
integrity_issues=""
if [ -f "$BASELINE_FILE" ] && command -v python3 &>/dev/null; then
    integrity_result=$(python3 -c "
import json, hashlib, os, sys

baseline_path = '$BASELINE_FILE'
issues = []

try:
    with open(baseline_path) as f:
        baseline = json.load(f)
    for path, expected_hash in baseline.items():
        if not os.path.isabs(path):
            continue
        if not os.path.exists(path):
            issues.append(f'MISSING: {path}')
            continue
        with open(path, 'rb') as fh:
            actual = hashlib.sha256(fh.read()).hexdigest()
        if actual != expected_hash:
            issues.append(f'MODIFIED: {path}')
    if issues:
        print('FAIL:' + '|'.join(issues))
    else:
        print('OK')
except Exception as e:
    print(f'ERROR:{e}')
" 2>/dev/null)

    if [[ "$integrity_result" == FAIL:* ]]; then
        integrity_status="fail"
        integrity_issues="${integrity_result#FAIL:}"
        context_parts+=("=== KERNEL INTEGRITY ALERT ===
MODIFIED FILES DETECTED: $integrity_issues
Notify operator immediately via /halt if unauthorized changes found.")
        echo "[KERNEL INTEGRITY ALERT] Modified files: $integrity_issues" >&2
    elif [[ "$integrity_result" == ERROR:* ]]; then
        integrity_status="error"
        echo "[KERNEL INTEGRITY WARNING] Could not verify: ${integrity_result#ERROR:}" >&2
    fi
fi

# --- Emit structured output if we have context ---
if [ "${#context_parts[@]}" -gt 0 ] || [ -n "$primer_block" ]; then
    output=""
    [ -n "$primer_block" ] && output="$primer_block"$'\n\n'
    for part in "${context_parts[@]}"; do
        output+="$part"$'\n\n'
    done
    printf '%s' "$output"
fi

# --- Emit lifecycle telemetry (always last) ---
emit "SessionStart" "integrity=${integrity_status}" "has_primer=$([ -n "$primer_block" ] && echo 1 || echo 0)"
