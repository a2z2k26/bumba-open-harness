---
name: sandbox-execution
description: Cloud sandbox execution via E2B for isolated code running, file operations, and multi-agent orchestration. Provides 23 MCP tools for full sandbox lifecycle management.
---

# Sandbox Execution (Bumba-SandboxMCP)

Isolated cloud sandboxes via E2B for running untrusted code, experiments, CI-like tasks, and multi-issue parallel execution. All tools use the `bumba-sandbox:` prefix.

## When to Use Sandboxes

- Running untrusted or experimental code safely
- Testing code changes in an isolated environment
- CI-like build/test workflows
- Multi-language execution (Node, Python, Go, Rust, Java)
- File manipulation in isolation before committing

## Quick Start

```
1. bumba-sandbox:sandbox_init  →  get sandboxId
2. bumba-sandbox:execute_command  →  run code/commands
3. bumba-sandbox:files_read  →  read results
4. bumba-sandbox:sandbox_kill  →  cleanup when done
```

Always kill sandboxes when finished to avoid unnecessary costs.

## Tool Reference

### Lifecycle Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `sandbox_init` | Initialize sandbox with template | `template` (string: base/node/python/go/rust/java), `timeout` (number, default 3600s) |
| `sandbox_create` | Create with advanced config | `template`, `timeout`, `envVars` (object), `metadata` (object) |
| `sandbox_connect` | Connect to existing sandbox | `sandboxId` (required) |
| `sandbox_kill` | Terminate and cleanup | `sandboxId` (required) |
| `sandbox_status` | Get health/status info | `sandboxId` (required) |

### File Operations

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `files_list` | List files/directories | `sandboxId`, `path` (default "/") |
| `files_read` | Read text file | `sandboxId`, `path` |
| `files_write` | Write text file | `sandboxId`, `path`, `content` |
| `files_upload` | Upload binary file | `sandboxId`, `path`, `content` (base64) |
| `files_download` | Download binary file | `sandboxId`, `path` |
| `file_exists` | Check existence | `sandboxId`, `path` |
| `file_info` | Get file metadata | `sandboxId`, `path` |
| `file_remove` | Remove file/directory | `sandboxId`, `path` |
| `file_rename` | Rename/move file | `sandboxId`, `oldPath`, `newPath` |
| `make_directory` | Create directory (recursive) | `sandboxId`, `path` |

### Command Execution

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `execute_command` | Run shell command | `sandboxId`, `command`, `cwd` (optional), `envVars` (optional object), `timeout` (optional number), `background` (optional boolean) |

Returns: `stdout`, `stderr`, `exitCode`

### Orchestration (Experimental — some are placeholders)

| Tool | Description | Status |
|------|-------------|--------|
| `analyze_dependencies` | Build dependency graph from GitHub issues | Working |
| `plan_sandbox_allocation` | Plan allocation strategy | Working |
| `spawn_sandbox_agent` | Spawn agent for an issue | Placeholder |
| `monitor_agents` | Monitor active agents | Working |
| `handle_agent_event` | Handle agent events | Placeholder |
| `optimize_resources` | Resource optimization recommendations | Working |
| `get_cost_tracking` | Cost tracking from hook logs | Working |

### Orchestration Tool Details

**analyze_dependencies:**
- `owner` (string), `repo` (string), `issueNumbers` (number array)
- Returns dependency graph with edges and parallel execution groups

**plan_sandbox_allocation:**
- `dependencyGraph` (from analyze_dependencies), `strategy` (string: balanced/max-speed/cost-optimized), `maxConcurrent` (number), `templateOverrides` (object)
- Returns allocation plan with phases, estimated cost, and timing

**monitor_agents:**
- `sandboxIds` (string array, optional)
- Returns status summary for all active agents

## Sandbox Templates

| Template | Pre-installed | Use Case |
|----------|--------------|----------|
| `base` | Ubuntu, basic tools | General-purpose |
| `node` | Node.js, npm | JavaScript/TypeScript |
| `python` | Python 3, pip | Python scripts/ML |
| `go` | Go compiler | Go projects |
| `rust` | Rust, cargo | Rust projects |
| `java` | JDK, Maven | Java projects |

## Lifecycle Workflow

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│ init/    │────▶│ execute_     │────▶│ files_read/  │────▶│ sandbox_ │
│ create   │     │ command      │     │ download     │     │ kill     │
└──────────┘     └──────────────┘     └──────────────┘     └──────────┘
     │                  │                     │
     │           ┌──────┴──────┐              │
     │           │ files_write/│              │
     │           │ upload      │              │
     │           └─────────────┘              │
     │                                        │
     └──── sandbox_status (check anytime) ────┘
```

## Best Practices

1. **Always kill sandboxes** when done — they cost money while running
2. **Use timeouts** on commands to prevent hanging processes
3. **Choose the right template** — `base` works for everything but language-specific templates are faster
4. **Check sandbox_status** before long operations to verify the sandbox is still alive
5. **Use background mode** for long-running processes (set `background: true` in execute_command)
6. **Handle errors** — check `exitCode` from execute_command; non-zero means failure
7. **Orchestration placeholders** — `spawn_sandbox_agent` and `handle_agent_event` return stub data; use `analyze_dependencies` and `plan_sandbox_allocation` for planning only

## Error Handling

- If sandbox_init fails: check E2B API key, template name, or quota
- If execute_command times out: increase timeout or use background mode
- If files_read returns empty: verify path with files_list first
- If sandbox_status shows unhealthy: kill and create a new one
