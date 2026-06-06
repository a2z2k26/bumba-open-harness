# Development

## Setup

```bash
make setup
```

This runs `uv sync --extra dev` inside `agent/`.

## Common Checks

```bash
make test
make lint
make validate-services
make secrets-scan
```

`make test` runs the offline, no-socket test lane. Live tests are opt-in and
must not be run without intentional local credentials and cost awareness.

## Python Layout

The Python package root is `agent/`. Keep new source under:

- `agent/bridge/` for bridge runtime modules
- `agent/teams/` for department/team logic
- `agent/job_search/` for job-search pipeline logic
- `agent/tests/` and `agent/job_search/tests/` for tests
- `agent/scripts/` for local operator/developer scripts

Avoid creating root-level `bridge/`, `teams/`, `tests/`, `job_search/`,
`pyproject.toml`, or `uv.lock` shadows.

## Commit Style

Use conventional commits:

```text
fix: handle missing notion job database id
docs: clarify OpenRouter setup
test: cover backend policy validation
```

## Before Publishing Changes

Run the relevant tests, then scan for secrets:

```bash
make test
make secrets-scan
```

If a real credential is ever committed, remove it from Git history before
publishing and rotate the credential at the provider.
