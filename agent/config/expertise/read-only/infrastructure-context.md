---
type: read-only
domain: infrastructure
access: ops-department
---

# Infrastructure Context

## Platform

- **OS:** macOS (Darwin 25.3.0)
- **Process model:** LaunchDaemons (system-level, /Library/LaunchDaemons/)
- **Runtime user:** bumba-agent (standard, not admin)
- **Source user:** bumba (admin)

## Deployment Pattern

1. Code changes staged by agent in source repo
2. Operator creates deploy script at /tmp/deploy-*.sh
3. Operator runs: sudo bash /tmp/deploy-*.sh
4. Script copies from source to runtime, sets ownership, restarts services

**Never modify runtime files directly.** All changes go through the source repo.

## Active Services (14 LaunchDaemons)

- com.bumba.agent-bridge — Main bridge (always running)
- com.bumba.agent-briefing, checkin, calendar, email — Daily services
- com.bumba.agent-knowledge-review, retro, weekly-review — Review services
- com.bumba.agent-job-search, job-execute — Job search pipeline
- com.bumba.agent-monitor, deploy-helper — Operations
- com.bumba.experiment-loop — Autonomous self-improvement
- com.bumba.oauth-refresh — Token management

## Key Paths

- Config: /opt/bumba-harness/agent-flat/agent/config/bridge.toml (post-D6-bis canonical)
- Secrets: /opt/bumba-harness/data/.secrets (mode 0600)
- Logs: /opt/bumba-harness/logs/
- Data: /opt/bumba-harness/data/

## Service Management

```bash
sudo launchctl bootstrap system /Library/LaunchDaemons/<name>.plist
sudo launchctl bootout system/<label>
```

**Never** use launchctl load/unload. Always bootstrap/bootout.
