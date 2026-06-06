#!/bin/bash
# Repo Awareness Hook Helper
# Called by memory-session-start.sh to produce a short orientation block.
#
# Purpose: prevent stale-context bugs — the class of failure where an agent
# operates from a frozen snapshot of the repo and misses recent merges,
# hotfixes, or concurrent work by another operator.
#
# Output: a short markdown block on stdout. Always exits 0 — this script
# must never fail the parent session-start hook. All git/gh calls are
# timed out and errors are swallowed gracefully.
#
# Feature flag: set BUMBA_REPO_AWARENESS=0 in the environment (or in
# /opt/bumba-harness/data/.secrets as BUMBA_REPO_AWARENESS=0) to disable.

set +e  # never propagate errors

# --- Feature flag: short-circuit if disabled ---
flag="${BUMBA_REPO_AWARENESS:-1}"
if [[ -z "$flag" ]] && [[ -f /opt/bumba-harness/data/.secrets ]]; then
    flag=$(grep -E '^BUMBA_REPO_AWARENESS=' /opt/bumba-harness/data/.secrets 2>/dev/null | cut -d= -f2)
fi
if [[ "$flag" == "0" ]] || [[ "$flag" == "false" ]]; then
    exit 0
fi

# --- Host detection: find a git repo we can read ---
# Candidates cover runtime, source checkout, and local development scenarios.
SOURCE_REPO=""
# BUMBA_SOURCE_REPO env var lets tests and CI inject the correct path
if [[ -n "$BUMBA_SOURCE_REPO" ]] && [[ -d "$BUMBA_SOURCE_REPO/.git" ]]; then
    SOURCE_REPO="$BUMBA_SOURCE_REPO"
fi
if [[ -z "$SOURCE_REPO" ]]; then
    for candidate in \
        /opt/bumba-harness/agent-flat \
        /opt/bumba-harness/source \
        /home/operator/bumba-open-harness \
        /opt/bumba-harness/agent
    do
        if [[ -d "$candidate/.git" ]] && [[ -r "$candidate/.git" ]]; then
            SOURCE_REPO="$candidate"
            break
        fi
    done
fi
# Last resort: if CWD is a git repo root, use it (handles CI and arbitrary paths)
if [[ -z "$SOURCE_REPO" ]] && [[ -d "$PWD/.git" ]]; then
    SOURCE_REPO="$PWD"
fi

if [[ -z "$SOURCE_REPO" ]]; then
    # Can't do anything without a source repo; bail silently
    exit 0
fi

# --- Runtime detection (Mac mini only) ---
RUNTIME_DIR=""
# Post-D6-bis canonical first; fall back to legacy path for back-compat
# (the operator may re-symlink during recovery / D6-bis rollback).
if [[ -d /opt/bumba-harness/agent-flat/agent/bridge ]]; then
    RUNTIME_DIR=/opt/bumba-harness/agent-flat/agent
elif [[ -d /opt/bumba-harness/agent/bridge ]]; then
    RUNTIME_DIR=/opt/bumba-harness/agent
fi

# --- Last-session timestamp tracking ---
# Use the actual user's home dir (not $HOME, which may still be set to the
# invoking user's home when called via `sudo -u <user>`). Fall back to /tmp
# if lookup fails.
real_home=$(eval echo "~$(whoami 2>/dev/null)" 2>/dev/null)
if [[ -z "$real_home" ]] || [[ ! -d "$real_home" ]] || [[ ! -w "$real_home" ]]; then
    real_home="/tmp"
fi
LAST_SESSION_FILE="${real_home}/.bumba-last-session"
now_epoch=$(date +%s)
last_epoch=""
if [[ -f "$LAST_SESSION_FILE" ]]; then
    last_epoch=$(cat "$LAST_SESSION_FILE" 2>/dev/null | tr -cd '0-9')
fi

# Compute "ago" string
ago_str="unknown"
if [[ -n "$last_epoch" ]] && [[ "$last_epoch" -gt 0 ]]; then
    delta=$(( now_epoch - last_epoch ))
    if [[ $delta -lt 300 ]]; then
        ago_str="${delta}s ago"
    elif [[ $delta -lt 3600 ]]; then
        ago_str="$(( delta / 60 ))m ago"
    elif [[ $delta -lt 86400 ]]; then
        ago_str="$(( delta / 3600 ))h ago"
    else
        ago_str="$(( delta / 86400 ))d ago"
    fi
fi

# Update timestamp for next session (best-effort)
echo "$now_epoch" > "$LAST_SESSION_FILE" 2>/dev/null || true

# --- Git fetch with timeout (best-effort, 3s cap) ---
pushd "$SOURCE_REPO" >/dev/null 2>&1 || exit 0

# Stash any local state considerations aside — we only read
# Use timeout so a slow/dead network can't stall the hook
fetch_status="ok"
if command -v timeout >/dev/null 2>&1; then
    timeout 3 git fetch --quiet origin main 2>/dev/null || fetch_status="unreachable"
else
    # macOS without coreutils: use gtimeout if available, else run bare with background-kill
    if command -v gtimeout >/dev/null 2>&1; then
        gtimeout 3 git fetch --quiet origin main 2>/dev/null || fetch_status="unreachable"
    else
        # Fallback: run fetch in background, kill after 3s. Swallow all output
        # and wait-result messages so nothing reaches the parent hook's stdout.
        (git fetch --quiet origin main 2>/dev/null) &
        fetch_pid=$!
        ( sleep 3 && kill -9 $fetch_pid >/dev/null 2>&1 ) >/dev/null 2>&1 &
        killer_pid=$!
        wait $fetch_pid >/dev/null 2>&1
        kill -9 $killer_pid >/dev/null 2>&1
        wait $killer_pid >/dev/null 2>&1
    fi
fi

# --- Commits behind / recent commits ---
local_sha=$(git rev-parse HEAD 2>/dev/null)
origin_sha=$(git rev-parse origin/main 2>/dev/null)
current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

behind_count=0
if [[ -n "$local_sha" ]] && [[ -n "$origin_sha" ]]; then
    behind_count=$(git rev-list --count HEAD..origin/main 2>/dev/null)
    behind_count=${behind_count:-0}
fi

recent_commits=""
if [[ "$behind_count" -gt 0 ]]; then
    recent_commits=$(git log --oneline --no-decorate HEAD..origin/main 2>/dev/null | head -3)
fi

# --- Branches updated on remote in last 4 hours by anyone else ---
# Only meaningful on the Mac mini where the agent and the operator both push
other_branches=""
other_branch_count=0
if [[ "$fetch_status" == "ok" ]]; then
    # Look at origin refs, skip main and current branch, filter to last 4h
    # git for-each-ref with --sort=-committerdate puts newest first
    other_branches=$(git for-each-ref \
        --format='%(committerdate:unix) %(refname:short) %(authorname)' \
        --sort=-committerdate \
        refs/remotes/origin/ 2>/dev/null \
        | awk -v now="$now_epoch" -v cb="origin/$current_branch" '
            $1 > (now - 14400) && $2 != "origin/main" && $2 != "origin/HEAD" && $2 != "origin" && $2 != cb {
                # Print "  - branch-name (author, Nm ago)"
                delta = now - $1
                if (delta < 3600) ago = int(delta/60) "m"
                else ago = int(delta/3600) "h"
                # Strip "origin/" prefix for display
                bn = $2; sub(/^origin\//, "", bn)
                # Author is fields 3..NF
                author = ""
                for (i = 3; i <= NF; i++) author = author (i>3?" ":"") $i
                print "      - " bn "  (" author ", " ago " ago)"
                c++
                if (c >= 5) exit
            }
        ')
    if [[ -n "$other_branches" ]]; then
        other_branch_count=$(echo "$other_branches" | grep -c '^')
    fi
fi

# --- Open PRs targeting main (requires gh auth — best-effort) ---
open_prs=""
open_pr_count=0
if command -v gh >/dev/null 2>&1; then
    # 2s timeout on gh, don't wait forever
    if command -v timeout >/dev/null 2>&1; then
        pr_json=$(timeout 2 gh pr list --state open --base main --json number,title --limit 10 2>/dev/null)
    else
        pr_json=$(gh pr list --state open --base main --json number,title --limit 10 2>/dev/null)
    fi
    if [[ -n "$pr_json" ]] && [[ "$pr_json" != "[]" ]]; then
        open_pr_count=$(echo "$pr_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))" 2>/dev/null)
        open_prs=$(echo "$pr_json" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for pr in d[:5]:
        title = pr.get('title','')[:70]
        print(f\"      - #{pr['number']}: {title}\")
except Exception:
    pass
" 2>/dev/null)
    fi
fi

popd >/dev/null 2>&1

# --- Runtime drift: is the runtime tree behind source? ---
runtime_status=""
if [[ -n "$RUNTIME_DIR" ]] && [[ -f "$RUNTIME_DIR/bridge/claude_runner.py" ]]; then
    src_hash=$(shasum -a 256 "$SOURCE_REPO/agent/bridge/claude_runner.py" 2>/dev/null | awk '{print $1}')
    rt_hash=$(shasum -a 256 "$RUNTIME_DIR/bridge/claude_runner.py" 2>/dev/null | awk '{print $1}')
    if [[ -n "$src_hash" ]] && [[ -n "$rt_hash" ]]; then
        if [[ "$src_hash" == "$rt_hash" ]]; then
            runtime_status="runtime matches source (bridge/claude_runner.py)"
        else
            runtime_status="runtime DRIFT detected — bridge/claude_runner.py differs from source"
        fi
    fi
fi

# --- Halt flag state (Mac mini only) ---
halt_status=""
if [[ -f /opt/bumba-harness/data/halt.flag ]]; then
    halt_mtime=$(stat -f%Sm -t '%Y-%m-%dT%H:%M:%S' /opt/bumba-harness/data/halt.flag 2>/dev/null)
    halt_status="HALT FLAG PRESENT since ${halt_mtime:-unknown}"
fi

# --- Emit the orientation block ---
hostname_short=$(hostname -s 2>/dev/null || echo "?")
who_am_i=$(whoami 2>/dev/null || echo "?")
utc_now=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

{
    echo "REPO AWARENESS (auto-generated, read-only orientation)"
    echo ""
    echo "Host: ${hostname_short}  ·  User: ${who_am_i}  ·  UTC: ${utc_now}"
    echo "Source: ${SOURCE_REPO}  ·  Branch: ${current_branch}"
    if [[ "$ago_str" != "unknown" ]]; then
        echo "Last session: ${ago_str}"
    fi

    if [[ "$fetch_status" != "ok" ]]; then
        echo ""
        echo "⚠ Unable to fetch origin (network or auth) — data below is cached and may be stale"
    fi

    echo ""
    if [[ "$behind_count" -eq 0 ]]; then
        echo "• Up-to-date with origin/main"
    else
        echo "• ${behind_count} commit(s) on origin/main not in local HEAD — most recent:"
        echo "$recent_commits" | sed 's/^/      /'
    fi

    if [[ -n "$runtime_status" ]]; then
        echo "• $runtime_status"
    fi

    if [[ "$open_pr_count" -gt 0 ]]; then
        echo "• Open PRs targeting main: ${open_pr_count}"
        echo "$open_prs"
    fi

    if [[ "$other_branch_count" -gt 0 ]]; then
        echo "• Other branches updated in last 4h: ${other_branch_count}"
        echo "$other_branches"
    fi

    if [[ -n "$halt_status" ]]; then
        echo "• ⚠ ${halt_status}"
    fi

    echo ""
    echo "If any of the above looks unexpected, stop and verify before acting."
} 2>/dev/null

exit 0
