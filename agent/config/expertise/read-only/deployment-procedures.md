---
agent: deployment-procedures
zone: 4
department: operations
type: read-only
max_lines: 500
created: 2026-04-03
last_updated: 2026-04-03
schema_version: 1
---

## Domain Patterns

- Post-D6-bis (2026-05-09): source clone at `/opt/bumba-harness/agent-flat/` IS the runtime; the legacy split between `/home/bumba/Documents/bumba-open-harness/agent/` (admin) and `/opt/bumba-harness/agent/` (runtime) is retired. Workstation operator authoring (`/home/operator/bumba-open-harness/`) still goes through PR review.
- Deploy flow (post-D6-bis): `git pull --ff-only origin main` on the runtime → regen kernel baseline → bounce daemon → smoke. The legacy `sudo bash /tmp/deploy-*.sh` pattern is superseded.
- LaunchDaemons only: all services run as system-level daemons under `/Library/LaunchDaemons/` — never LaunchAgents
- Bootstrap: `sudo launchctl bootstrap system /Library/LaunchDaemons/<label>.plist`
- Restart: bootout then bootstrap (not reload)
- Kernel baseline: after any bridge file change, regenerate `data/kernel-baseline.json`

## Known Risks

- Direct runtime edits without PR: writing files into `/opt/bumba-harness/agent-flat/` outside the git history breaks the deployment model and skips kernel hash verification
- Inventing plist names: only 14 valid plists exist — do not create new ones without operator approval
- Skipping kernel baseline regen: causes hash mismatch alerts on next startup and possible halt mode
- Force-pushing main: destroys commit history; never do it

## Decision Log

- 2026-03-29: After crash caused by stale `set_voice_manager` ref — rule codified: NEVER modify runtime files directly
- 2026-04-03: Deploy pattern documented in CLAUDE.md: patch → operator deploy script → restart

## Cross-Agent Notes

- Any engineering agent proposing a code change must stage it as a patch, not apply it directly
- PRs go to `your-org/bumba-open-harness` on GitHub (private repo)
- Use `gh pr create` after committing to a feature branch
- Never commit to `main` directly — always PR
