# Architecture

Bumba Open Harness is organized around one durable bridge process and a set of
optional service surfaces. The repo is intentionally shaped as a local harness,
not a hosted SaaS product.

## Main Flow

```text
Discord operator
    |
    v
bridge.discord_bot
    |
    v
bridge.app / invocation_pipeline
    |
    v
backend registry
    |
    +-- OpenRouterBackend -> OpenRouter chat completions API
    +-- ClaudeBackend     -> Claude Code CLI subprocess
    +-- CodexBackend      -> Codex CLI subprocess, when configured
    |
    v
SQLite memory, event, service, and routing stores
```

The OpenRouter edition keeps Claude Code as a compatible backend, but the
public adoption path is to enable `[backends]` and route one or more roles to
`openrouter`.

## Zones

- Zone 1: bridge core, Discord IO, invocation pipeline, memory, security,
  config loading, and API routes.
- Zone 2: scheduled services such as briefing, calendar/email workflows,
  knowledge review, project pulse, and maintenance.
- Zone 3: work-order orchestration, worktree execution, quality gates, and
  factory-style automation loops.
- Zone 4: department chiefs and specialists. Chiefs route work; specialists
  execute typed tasks behind tool boundaries.

## State

Runtime state belongs outside Git. SQLite databases, WAL files, logs, browser
profiles, OAuth caches, `.mcp.json`, and `.secrets` are ignored and should stay
on the deployment host.

## MCP Servers

`mcp-servers/` vendors the memory and sandbox MCP servers used by the harness.
This keeps public deployments from depending on workstation-specific paths. If
you edit `bumba-sandbox`, rebuild its TypeScript output before committing.

## Public-Release Boundaries

The private planning archive, original deployment handoffs, private local
machine paths, and personal job-search content are intentionally absent. The
public tree keeps runnable source, tests, public config templates, and adoption
documentation.
