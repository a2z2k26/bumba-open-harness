# Bumba Open Harness Repo Guide

This file gives agent contributors the repo-level rules for working from the
repository root. Runtime architecture details live in `agent/CLAUDE.md`; public
adoption docs live in `docs/`.

## Canonical Layout

All Python source, tests, configs, and Python scripts live under `agent/`.
Do not create root-level shadow trees:

- `bridge/` -> use `agent/bridge/`
- `teams/` -> use `agent/teams/`
- `tests/` -> use `agent/tests/`
- `job_search/` -> use `agent/job_search/`
- `pyproject.toml` -> use `agent/pyproject.toml`
- `uv.lock` -> use `agent/uv.lock`

## Public Data Boundary

Do not commit private operator data, personal profile material, local
home-directory paths, browser profiles, runtime databases, logs, OAuth caches,
`.mcp.json`, or `.secrets` files. Examples must use placeholders and generic
domains.

## Development Rules

- Read files before modifying them.
- Prefer the existing project patterns over new abstractions.
- Keep changes scoped to the requested behavior.
- Add tests for behavior changes and run the narrowest meaningful test lane.
- Use conventional commits.
- Run `make secrets-scan` before publishing changes.

## Useful Commands

```bash
make setup
make test
make lint
make validate-services
make secrets-scan
```
