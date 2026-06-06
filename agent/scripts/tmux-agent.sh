#!/usr/bin/env bash
# tmux-agent.sh — CLI helper for spawning/managing Claude Code agents in tmux sessions.
# Used by the Claude subprocess (via Bash tool) to delegate parallel work.
#
# Usage:
#   tmux-agent.sh spawn "task description" [--max-turns N]
#   tmux-agent.sh list
#   tmux-agent.sh status <agent-id>
#   tmux-agent.sh output <agent-id> [--lines N]
#   tmux-agent.sh kill <agent-id>

set -euo pipefail

SOCKET="bumba-agents"
AGENTS_DIR="${AGENTS_DIR:-data/agents}"
SECRETS_FILE="${SECRETS_FILE:-/opt/bumba-harness/data/.secrets}"

# Resolve Claude binary
find_claude() {
    if command -v claude &>/dev/null; then
        command -v claude
    elif [ -f "$HOME/.local/bin/claude" ]; then
        echo "$HOME/.local/bin/claude"
    elif [ -f "/usr/local/bin/claude" ]; then
        echo "/usr/local/bin/claude"
    else
        echo ""
    fi
}

# Read OAuth token from .secrets file
get_token() {
    if [ -f "$SECRETS_FILE" ]; then
        grep "^claude_oauth_token=" "$SECRETS_FILE" | cut -d= -f2-
    else
        echo ""
    fi
}

cmd_spawn() {
    local task="$1"
    shift
    local max_turns=25

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --max-turns) max_turns="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [ -z "$task" ]; then
        echo "ERROR: Task description required"
        exit 1
    fi

    # Check tmux
    if ! command -v tmux &>/dev/null; then
        echo "ERROR: tmux not installed. Run: brew install tmux"
        exit 1
    fi

    # Check active session count
    local active_count
    active_count=$(tmux -L "$SOCKET" list-sessions 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    if [ "$active_count" -ge 3 ]; then
        echo "ERROR: Max 3 concurrent agents. Kill one first."
        exit 1
    fi

    local claude_bin
    claude_bin=$(find_claude)
    if [ -z "$claude_bin" ]; then
        echo "ERROR: Claude binary not found"
        exit 1
    fi

    local token
    token=$(get_token)
    if [ -z "$token" ]; then
        echo "ERROR: No OAuth token found in $SECRETS_FILE"
        exit 1
    fi

    # Generate agent ID
    local agent_id
    agent_id=$(python3 -c "import uuid; print(uuid.uuid4().hex[:8])")

    local session_name="bumba-${agent_id}"
    local agent_dir="${AGENTS_DIR}/${agent_id}"
    mkdir -p "$agent_dir"

    # Write task file
    echo "$task" > "${agent_dir}/task.txt"

    local output_file="${agent_dir}/output.jsonl"

    # Build and run tmux session
    tmux -L "$SOCKET" new-session -d -s "$session_name" \
        "bash -c 'export CLAUDE_CODE_OAUTH_TOKEN=\"${token}\" && cat ${agent_dir}/task.txt | ${claude_bin} -p --output-format stream-json --verbose --max-turns ${max_turns} --dangerously-skip-permissions > ${output_file} 2>&1; echo \"EXIT_CODE:\$?\" >> ${output_file}'"

    echo "$agent_id"
}

cmd_list() {
    if ! command -v tmux &>/dev/null; then
        echo "tmux not installed"
        exit 1
    fi

    local sessions
    sessions=$(tmux -L "$SOCKET" list-sessions -F "#{session_name} #{session_activity} #{session_created}" 2>/dev/null || true)

    if [ -z "$sessions" ]; then
        echo "No active agents."
        return
    fi

    echo "Active agents:"
    echo "---"
    echo "$sessions" | while read -r name _ _; do
        local agent_id="${name#bumba-}"
        local task_file="${AGENTS_DIR}/${agent_id}/task.txt"
        local task_preview=""
        if [ -f "$task_file" ]; then
            task_preview=$(head -c 80 "$task_file")
        fi
        echo "  ${agent_id}  ${task_preview}"
    done
}

cmd_status() {
    local agent_id="$1"
    if [ -z "$agent_id" ]; then
        echo "ERROR: Agent ID required"
        exit 1
    fi

    local session_name="bumba-${agent_id}"

    # Check if session is alive
    if tmux -L "$SOCKET" has-session -t "$session_name" 2>/dev/null; then
        echo "Status: running"
    else
        echo "Status: completed"
    fi

    # Show task
    local task_file="${AGENTS_DIR}/${agent_id}/task.txt"
    if [ -f "$task_file" ]; then
        echo "Task: $(cat "$task_file")"
    fi

    # Show last 20 lines of output
    local output_file="${AGENTS_DIR}/${agent_id}/output.jsonl"
    if [ -f "$output_file" ]; then
        echo "---"
        echo "Recent output (last 20 lines):"
        tail -20 "$output_file"
    fi
}

cmd_output() {
    local agent_id="$1"
    shift || true
    local lines=0

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --lines) lines="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [ -z "$agent_id" ]; then
        echo "ERROR: Agent ID required"
        exit 1
    fi

    local output_file="${AGENTS_DIR}/${agent_id}/output.jsonl"
    if [ ! -f "$output_file" ]; then
        echo "ERROR: No output file for agent $agent_id"
        exit 1
    fi

    # Extract final result from stream-json
    local result
    result=$(grep '"type":"result"' "$output_file" | tail -1)

    if [ -n "$result" ]; then
        echo "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('Cost: \$%.4f | Turns: %d' % (data.get('cost_usd', 0), data.get('num_turns', 0)))
result = data.get('result', '')
if result:
    print('---')
    print(result)
else:
    print('(no result text)')
"
    else
        # No result event yet — show tail of output
        if [ "$lines" -gt 0 ]; then
            tail -"$lines" "$output_file"
        else
            echo "Agent still running. No result event yet."
            echo "Live output (last 10 lines):"
            tail -10 "$output_file"
        fi
    fi
}

cmd_kill() {
    local agent_id="$1"
    if [ -z "$agent_id" ]; then
        echo "ERROR: Agent ID required"
        exit 1
    fi

    local session_name="bumba-${agent_id}"

    if tmux -L "$SOCKET" kill-session -t "$session_name" 2>/dev/null; then
        echo "Killed agent $agent_id"
    else
        echo "Agent $agent_id not found or already stopped"
    fi
}

# Main dispatch
case "${1:-}" in
    spawn)  shift; cmd_spawn "$@" ;;
    list)   cmd_list ;;
    status) shift; cmd_status "${1:-}" ;;
    output) shift; cmd_output "$@" ;;
    kill)   shift; cmd_kill "${1:-}" ;;
    *)
        echo "Usage: tmux-agent.sh {spawn|list|status|output|kill} [args]"
        echo ""
        echo "Commands:"
        echo "  spawn \"task\" [--max-turns N]  Spawn a new agent"
        echo "  list                          List active agents"
        echo "  status <id>                   Check agent status"
        echo "  output <id> [--lines N]       Get agent output/result"
        echo "  kill <id>                     Kill a running agent"
        exit 1
        ;;
esac
