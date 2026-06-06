# Bumba Lifecycle Hooks — 13-Point Taxonomy

Concept-only port of `disler/claude-code-hooks-mastery` (MIT, paraphrased).
13-lifecycle taxonomy for Claude Code CLI hook scripts.

## Overview

Each Claude Code CLI subprocess invocation fires hooks at 13 lifecycle points.
Hook scripts in this directory emit a single structured JSONL line to
`~/data/hooks-telemetry.jsonl` for each event. Downstream sprints (E2.2 spans,
E2.3 event-bus reconciliation) build against this telemetry stream.

Source-of-truth: `agent/config/hooks/` (this directory).
Runtime deployment: `~/.claude/hooks/` (one subdirectory per lifecycle point).

## The 13 Lifecycle Points

| Subdirectory | CLI Event | Fires When |
|---|---|---|
| `SessionStart/` | `SessionStart` | Claude Code CLI session begins |
| `SessionEnd/` | `SessionEnd` | Claude Code CLI session ends (clean exit) |
| `UserPromptSubmit/` | `UserPromptSubmit` | User message submitted to the session |
| `PreToolUse/` | `PreToolUse` | Before each tool invocation |
| `PostToolUse/` | `PostToolUse` | After each tool invocation (success or failure) |
| `Stop/` | `Stop` | Session stop signal received |
| `SubagentStop/` | `SubagentStop` | Subagent subprocess exits |
| `Notification/` | `Notification` | Permission request or system notification |
| `PreCompact/` | `PreCompact` | Before context window compaction |
| `PostCompact/` | `PostCompact` | After context window compaction |
| `PreModelInvoke/` | `PreModelInvoke` | Before each Anthropic API call |
| `PostModelInvoke/` | `PostModelInvoke` | After each Anthropic API call |
| `Error/` | `Error` | CLI-level error condition |

## JSONL Schema

Each hook emits one line to `~/data/hooks-telemetry.jsonl`:

```json
{
  "ts": "2026-05-03T14:22:01.000Z",
  "event": "PreToolUse",
  "session_id": "claude-session-abc123",
  "payload": {"tool": "Bash"}
}
```

| Field | Type | Description |
|---|---|---|
| `ts` | ISO-8601 UTC string | Timestamp of the event |
| `event` | string | One of the 13 lifecycle point names above |
| `session_id` | string | `$CLAUDE_SESSION_ID` env var, or `"unknown"` |
| `payload` | JSON object | Event-specific key-value pairs (may be `{}`) |

## Shared Emit Helper

`_lib/emit.sh` provides the `emit()` function used by all 13 scripts:

```bash
# Source and use:
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "EventName" "key=value" "key2=value2"
```

Sink path is configurable via `BUMBA_HOOKS_TELEMETRY` env var (default:
`~/data/hooks-telemetry.jsonl`). The helper:
- Uses `flock` on a `.lock` sidecar for concurrent-safe appends
- Falls back silently if the sink is not writable (hooks never block CLI)
- Handles `flock` unavailability gracefully (appends without locking)

## Memory Hooks (Pre-existing, Relocated)

Three existing Bumba memory hooks are registered as the `00-` scripts in
their respective subdirectories, preserving invocation order before the
new `01-emit.sh` telemetry scripts:

| Old path | New path | Lifecycle point |
|---|---|---|
| `memory-session-start.sh` | `SessionStart/00-memory-session-start.sh` | SessionStart |
| `memory-session-stop.sh` | `Stop/00-memory-session-stop.sh` | Stop |
| `memory-subagent-stop.sh` | `SubagentStop/00-memory-subagent-stop.sh` | SubagentStop |

These scripts retain their existing logic (kernel integrity verification,
knowledge persistence prompts) and add a single `emit` call at the end.

## Deploy Convention

Single source of truth: `agent/config/hooks/` is the canonical tree.
`agent/scripts/deploy_hooks.sh` rsyncs it to `~/.claude/hooks/`
(`rsync -av --delete`), so anything in the runtime that is not in the
source tree gets removed. Sprint E1.2 / issue #1712 retired the
pre-D6-bis #851 dual-location convention and the phantom
`copy_hooks` helper that referenced it.

## Smoke Test

After deploy, verify telemetry is flowing:

```bash
BUMBA_HOOKS_TELEMETRY=/tmp/test-hooks.jsonl claude -p "echo hello"
cat /tmp/test-hooks.jsonl | python3 -c "import sys,json; [json.loads(l) for l in sys.stdin]" && echo "All lines parse OK"
```

Expected: at least 5 parseable JSONL lines covering SessionStart,
UserPromptSubmit, PreToolUse, PostToolUse, and Stop.

## Attribution

Lifecycle taxonomy concept-only-no-license-lineage port from
`disler/claude-code-hooks-mastery` (MIT). The 13-point vocabulary is
the hard-won artifact; implementations are Bumba-original.
Per the karpathy-skills convention in `agent/CLAUDE.md` "Behavioral Doctrine".
