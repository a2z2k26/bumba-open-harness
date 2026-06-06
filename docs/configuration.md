# Configuration

The checked-in config is a public starter configuration. It is safe to inspect,
but it is not enough to operate a live assistant until you add local secrets and
choose which surfaces to enable.

## Files

- `agent/config/bridge.toml`: primary bridge configuration.
- `agent/data/.secrets-template`: copy this to a local, untracked `.secrets`
  file on the runtime host.
- `agent/config/mcp-servers.canonical.json`: reference MCP server paths.
- `agent/config/feature_flags.yaml`: feature registry and default posture.

## Secrets

Do not commit secrets. The bridge loads credentials from a flat `key=value`
file. The template assumes `/opt/bumba-harness/data/.secrets`, but you can use
deployment-specific path handling as long as the bridge config and launch
environment agree.

Minimum live Discord run:

```text
discord_token=
operator_discord_id=
```

OpenRouter backend:

```text
openrouter_api_key=
```

Claude Code backend:

```text
claude_oauth_token=
claude_oauth_refresh_token=
claude_oauth_expires_at=0
```

Optional integrations have their own keys, including Notion, VAPI, GitHub
webhooks, Codex OAuth, E2B, and healthcheck URLs.

## Backend Policy

For OpenRouter-first operation:

```toml
[backends]
enabled = true
main = "openrouter"
chiefs_default = "openrouter"
specialists_default = "openrouter"

[openrouter]
default_model = "deepseek/deepseek-chat"
```

If any role resolves to `claude`, seed Claude Code OAuth. If any role resolves
to `codex`, seed Codex OAuth. The bridge validates required credentials and
fails closed when a configured backend is missing its auth material.

## Runtime Paths

The public defaults use `/opt/bumba-harness` for data, logs, and runtime layout
examples. Replace those values for your deployment. Do not replace them with a
personal home-directory path in committed config.

## Services

Many services are optional. Start with offline tests, then enable live services
one at a time. Voice is off by default. Job-search automation requires local
candidate data, criteria, Notion configuration, and approval workflow setup.
