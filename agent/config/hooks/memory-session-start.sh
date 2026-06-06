#!/bin/bash
# Memory Session Start Hook
# Event: SessionStart
# Purpose: Inject prior context into Claude session + verify kernel integrity
#
# Per CLAUDE.md Section 5.4:
#   1. Read recent knowledge from SQLite via sqlite3 CLI
#   2. Output JSON to stdout (injected into Claude's context)
#   3. Compute SHA-256 hashes of protected kernel files
#   4. Compare against stored baselines
#   5. Alert on any mismatch (write to stderr, bridge captures)

MEMORY_DB="/opt/bumba-harness/data/memory.db"
BASELINE_FILE="/opt/bumba-harness/data/kernel-baseline.json"
PRIMER_PATH="/opt/bumba-harness/.claude/projects/-opt-bumba-harness-agent/memory/primer.json"

context_parts=()

# --- 0. Load T1 session primer (if present) ---
primer_block=""
if [ -f "$PRIMER_PATH" ] && command -v python3 &>/dev/null; then
    primer_json=$(cat "$PRIMER_PATH" 2>/dev/null)
    if [ -n "$primer_json" ]; then
        # Validate JSON and check expiry
        primer_data=$(python3 -c "
import json, sys
from datetime import datetime, timezone

try:
    data = json.loads(sys.stdin.read())
    expires_at = data.get('expires_at', '')
    stale = False
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            stale = now > exp
        except Exception:
            stale = True  # Can't parse expiry → treat as stale

    # Format primer block
    track = data.get('current_track', {})
    track_name = track.get('name', 'unknown')
    track_type = track.get('type', 'unknown')
    generated_at = data.get('generated_at', 'unknown')
    summary = data.get('session_summary', '')

    lines = []
    stale_prefix = '[STALE PRIMER — generated >24h ago] ' if stale else ''
    lines.append(f'SESSION PRIMER (T1): {stale_prefix}')
    lines.append(f'Track: {track_name} ({track_type})')
    lines.append(f'Generated: {generated_at}')

    projects = data.get('active_projects', [])
    if projects:
        lines.append('Active Projects:')
        for p in projects:
            lines.append(f'  - {p.get(\"name\", \"?\")} [{p.get(\"status\", \"?\")}] — {p.get(\"next_action\", \"\")}')

    decisions = data.get('recent_decisions', [])
    if decisions:
        lines.append('Recent Decisions:')
        for d in decisions[:5]:
            lines.append(f'  - {d.get(\"topic\", \"?\")} : {d.get(\"decision\", \"\")}')

    blockers = data.get('open_blockers', [])
    if blockers:
        lines.append('Open Blockers:')
        for b in blockers:
            lines.append(f'  - [{b.get(\"id\", \"?\")}] {b.get(\"description\", \"\")} [waiting on: {b.get(\"waiting_on\", \"?\")}]')

    tasks = data.get('pending_tasks', [])
    if tasks:
        lines.append('Pending Tasks:')
        for t in tasks[:10]:
            lines.append(f'  - [{t.get(\"priority\", \"?\")}] {t.get(\"description\", \"\")}')

    if summary:
        lines.append(f'Last Session: {summary}')

    print('\n'.join(lines))
except Exception as e:
    sys.exit(1)
" <<< "$primer_json" 2>/dev/null)

        if [ -n "$primer_data" ]; then
            primer_block="$primer_data"
        fi
    fi
fi

# --- 1. Load recent knowledge context ---
if [ -f "$MEMORY_DB" ] && command -v sqlite3 &>/dev/null; then
    # Recent decisions (last 48 hours)
    recent_decisions=$(sqlite3 "$MEMORY_DB" \
        "SELECT key || ': ' || substr(value, 1, 200) FROM knowledge WHERE key LIKE 'decision:%' AND updated_at > datetime('now', '-48 hours') ORDER BY updated_at DESC LIMIT 10;" 2>/dev/null)
    if [ -n "$recent_decisions" ]; then
        context_parts+=("Recent decisions:")
        while IFS= read -r line; do
            context_parts+=("  - $line")
        done <<< "$recent_decisions"
    fi

    # User facts (preferences, names, etc.)
    user_facts=$(sqlite3 "$MEMORY_DB" \
        "SELECT key || ': ' || substr(value, 1, 200) FROM knowledge WHERE key LIKE 'user:%' ORDER BY updated_at DESC LIMIT 10;" 2>/dev/null)
    if [ -n "$user_facts" ]; then
        context_parts+=("User context:")
        while IFS= read -r line; do
            context_parts+=("  - $line")
        done <<< "$user_facts"
    fi

    # Last session summary
    last_summary=$(sqlite3 "$MEMORY_DB" \
        "SELECT substr(value, 1, 500) FROM knowledge WHERE key LIKE 'session:summary:%' ORDER BY updated_at DESC LIMIT 1;" 2>/dev/null)
    if [ -n "$last_summary" ]; then
        context_parts+=("Last session summary: $last_summary")
    fi

    # Active goals
    goals=$(sqlite3 "$MEMORY_DB" \
        "SELECT substr(value, 1, 300) FROM knowledge WHERE key LIKE 'goal:%' AND (archived IS NULL OR archived = 0) ORDER BY updated_at DESC LIMIT 10;" 2>/dev/null)
    if [ -n "$goals" ]; then
        context_parts+=("Active Goals:")
        while IFS= read -r line; do
            context_parts+=("  - $line")
        done <<< "$goals"
    fi

    # Pending self-improvement tickets
    improvement_count=$(sqlite3 "$MEMORY_DB" \
        "SELECT COUNT(*) FROM knowledge WHERE key LIKE 'decision:self-improvement:%';" 2>/dev/null)
    if [ "$improvement_count" -gt 0 ] 2>/dev/null; then
        context_parts+=("$improvement_count pending self-improvement ticket(s)")
    fi
fi

# --- 2. Kernel integrity verification ---
if [ -f "$BASELINE_FILE" ]; then
    mismatch_found=false
    mismatched_files=""

    # Read baseline and check each file
    while IFS='=' read -r file expected_hash; do
        # Skip empty lines and comments
        [ -z "$file" ] && continue
        [[ "$file" == \#* ]] && continue

        if [ -f "$file" ]; then
            current_hash=$(shasum -a 256 "$file" 2>/dev/null | cut -d' ' -f1)
            if [ "$current_hash" != "$expected_hash" ]; then
                mismatch_found=true
                mismatched_files="$mismatched_files\n  MISMATCH: $file"
            fi
        else
            mismatch_found=true
            mismatched_files="$mismatched_files\n  MISSING: $file"
        fi
    done < <(python3 -c "
import json, sys
try:
    with open('$BASELINE_FILE') as f:
        data = json.load(f)
    files = data.get('files', data) if isinstance(data, dict) else {}
    for path, h in files.items():
        print(f'{path}={h}')
except Exception:
    sys.exit(0)
" 2>/dev/null)

    if [ "$mismatch_found" = true ]; then
        echo "SECURITY ALERT: Protected kernel file hash mismatch" >&2
        echo -e "Affected files:$mismatched_files" >&2

        # Write halt flag
        echo "Kernel integrity violation detected at $(date -Iseconds)" > /opt/bumba-harness/data/halt.flag

        # Add alert to context
        context_parts+=("SECURITY ALERT: Kernel file integrity violation detected. Agent entering halted state.")
    fi
fi

# --- 3. Output systemMessage JSON ---
if [ ${#context_parts[@]} -gt 0 ] || [ -n "$primer_block" ]; then
    # Build message: primer first (T1), then T3 knowledge
    if [ -n "$primer_block" ]; then
        primer_section="$primer_block

---
"
    else
        primer_section=""
    fi

    if [ ${#context_parts[@]} -gt 0 ]; then
        t3_section="MEMORY CONTEXT (T3):
$(printf '%s\n' "${context_parts[@]}")
"
    else
        t3_section=""
    fi

    msg="${primer_section}${t3_section}

KNOWLEDGE STORAGE INSTRUCTIONS:
You run in one-shot mode — each message is a separate process. You MUST store important information DURING your response, not after. The session-stop hook cannot reach you.

When to store (use Bash tool to run sqlite3):
- Operator says \"remember\", \"note that\", \"always\", \"never\", \"I prefer\" → Store as user fact
- A decision is made → Store as decision
- You create something (skill, file) → Store as self-improvement record
- Session had meaningful content → Store a brief summary

How to store:
  sqlite3 ~/data/memory.db \"INSERT OR REPLACE INTO knowledge (key, value, tags, source, updated_at) VALUES ('user:<topic>', '<info>', 'memory', 'agent', datetime('now'))\"
  sqlite3 ~/data/memory.db \"INSERT OR REPLACE INTO knowledge (key, value, tags, source, updated_at) VALUES ('decision:<topic>', '<rationale>', 'decision', 'agent', datetime('now'))\"

How to search:
  sqlite3 ~/data/memory.db \"SELECT key, value FROM knowledge WHERE key IN (SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH '<query>') LIMIT 5\"

You have access to prior context from your memory system. Use sqlite3 /opt/bumba-harness/data/memory.db to query the knowledge table for more details if needed."

    jq -n --arg msg "$msg" '{"systemMessage": $msg}'
else
    echo '{}'
fi
