# Bumba Open Harness

Bumba Open Harness is a local, single-operator agent harness that connects a
Discord control surface, durable SQLite memory, scheduled automation services,
and a pluggable model backend layer. This variant is the OpenRouter-ready
edition: it keeps Claude Code support, but the backend registry can route work
to OpenRouter-compatible HTTP models for lower cost and broader model choice.

The repository is prepared for public adoption. It does not include private
deployment history, local machine paths, personal job-search data, resumes,
portfolio links, API keys, OAuth tokens, browser profiles, or runtime databases.
The job-search workflow ships as a configurable scaffold and fails closed until
an adopter supplies their own profile, criteria, secrets, and approval database.

## What It Does

- Runs a Discord bot that accepts operator messages and routes them through the
  bridge.
- Persists conversation state, service state, events, and operational memory in
  SQLite.
- Supports scheduled services for briefings, calendar/email workflows, job
  search, knowledge review, health checks, and maintenance.
- Provides a Zone 4 department system where chiefs route work to typed
  specialists with explicit tool boundaries.
- Vendors two MCP servers, `bumba-memory` and `bumba-sandbox`, so deployments do
  not depend on local absolute paths.
- Includes an OpenRouter backend implementation plus fallback/cross-model
  adapter code.

## Repository Layout

```text
.
├── agent/                  Python bridge, services, teams, configs, tests
├── mcp-servers/            Vendored MCP servers used by the harness
├── docs/                   Public adoption and architecture notes
├── .github/                Public CI and issue/PR templates
├── Makefile                Common local developer commands
└── README.md
```

The canonical Python package root is `agent/`. Source, tests, runtime config,
and Python scripts should stay under that directory.

## Requirements

- Python 3.13
- `uv`
- Git
- Optional for MCP server development: Node.js 20.x or 22.x
- Optional for live operation: Discord bot credentials, Claude Code or
  OpenRouter credentials, and any service credentials you enable

## Quickstart

The smoke path does not require secrets or networked model calls.

```bash
git clone https://github.com/your-org/bumba-open-harness.git
cd bumba-open-harness
make setup
make test
```

For a narrower first check:

```bash
cd agent
uv sync --extra dev
.venv/bin/python -m pytest tests/test_app.py::TestAppInitialize -q
```

## OpenRouter Setup

Secrets are loaded from the flat `.secrets` file described in
`agent/data/.secrets-template`. For an OpenRouter-backed run, provide:

```text
discord_token=
operator_discord_id=
openrouter_api_key=
```

Then enable backend routing in `agent/config/bridge.toml`:

```toml
[backends]
enabled = true
main = "openrouter"
chiefs_default = "openrouter"
specialists_default = "openrouter"

[openrouter]
default_model = "deepseek/deepseek-chat"
```

If any role still resolves to `claude`, the bridge also requires Claude Code
OAuth credentials. See [docs/configuration.md](docs/configuration.md).

## Running Locally

Development checks:

```bash
make test
make lint
make validate-services
make secrets-scan
```

Live bridge operation is intentionally not one-command. Before enabling it,
create a local secrets file, review `agent/config/bridge.toml`, choose your
backend policy, and disable any services you do not intend to operate. The
public defaults keep voice off and leave job-search automation incomplete until
you add adopter-owned data.

## Job Search Scaffold

The job-search package is included because it is part of the harness shape, but
it has been scrubbed of personal materials. To use it, create local copies of:

- `agent/job_search/candidate.json.example`
- `agent/job_search/criteria.json.example`

Then provide your own resume URL, profile links, board credentials, and Notion
database ID. Without `BUMBA_NOTION_JOB_DB_ID` or `notion_job_db_id` in
`.secrets`, the approval pipeline refuses to run. See
[docs/job-search.md](docs/job-search.md).

## Security Posture

This public tree is intended to be safe to inspect and fork. It still operates
automation surfaces that can touch external systems when configured, so adopters
must keep runtime state out of Git:

- Do not commit `.secrets`, `.mcp.json`, browser profiles, SQLite databases,
  logs, OAuth caches, or generated worktrees.
- Run `make secrets-scan` before publishing changes.
- Treat every service credential as adopter-owned and rotate it if it is ever
  printed or committed.

Security reporting details are in [SECURITY.md](SECURITY.md).

## Documentation

- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [Development](docs/development.md)
- [Job search](docs/job-search.md)
- [Publication cleanup notes](docs/publication-cleanup.md)

## License

MIT. See [LICENSE](LICENSE).
