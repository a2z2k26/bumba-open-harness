# Running the test suite

This file documents how to run the bridge test suite reliably across
environments — specifically how to dodge the trap that the 2026-05-15
comprehensive audit (§M-3, sprint `audit-2026-05-15.D.03`) caught when a
clean worktree's pytest run failed before collection.

## TL;DR

```bash
# Preferred: run inside the repo's .venv
agent/.venv/bin/python -m pytest agent/tests -q

# Or, from inside agent/:
make -C agent test-clean-worktree   # quick lint-grade smoke (sync tests)
make -C agent test-async            # async tests with pytest-asyncio
make -C agent test-all              # both, sequentially
```

## Why this matters

The 2026-05-15 audit (§M-3) tried to run

```bash
python3 -m pytest agent/tests/test_experiment_loop.py agent/tests/test_token_refresher.py -q
```

against a clean worktree without entering the project venv. Pytest failed
**before collection** because globally installed pytest plugins on the host
loaded incompatible `logfire` / `opentelemetry` versions — a pure environment
clash, no product-code defect.

Setting `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` lets the synchronous tests reach
collection, but it also disables `pytest-asyncio`, so any test marked
`@pytest.mark.asyncio` (e.g. the async cases in `test_token_refresher.py`)
silently no-ops. The fix is to disable autoload **and** re-enable the one
async plugin the suite actually wants.

That two-step pattern is what the Makefile targets and the rules below
encode.

## Rule 1 — Prefer the project `.venv` whenever possible

Run inside `.venv` whenever possible:

```bash
agent/.venv/bin/python -m pytest agent/tests/...
```

The `.venv` is provisioned with the exact `pytest` / `pytest-asyncio` /
`logfire` versions pinned in `pyproject.toml`, so there is no autoload
collision. This is the path PR-evidence runs and CI use.

If `agent/.venv` is missing, recreate it from the project root:

```bash
cd agent && uv sync --dev
```

## Rule 2 — Outside `.venv`, disable autoload AND re-enable specific plugins

When you need to run pytest with a system `python3` (audit harness, debug
shell on a host without the venv, etc.):

```bash
# Synchronous tests only — strictest, fastest.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest agent/tests -q

# Async tests — disable autoload AND re-enable pytest-asyncio explicitly.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTEST_PLUGINS=pytest_asyncio \
  python3 -m pytest agent/tests -q
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` blocks every entry-point-discovered plugin
on the host (including the conflicting `logfire` / `opentelemetry` shims).
`PYTEST_PLUGINS=pytest_asyncio` then re-injects only the plugins the suite
needs. Comma-separate the list if you need more than one.

## Rule 3 — Async tests in `test_token_refresher.py` need `pytest-asyncio`

The async cases in `agent/tests/test_token_refresher.py` depend on
`pytest-asyncio`. If it is not installed, the async tests will fail with
collection-time errors about coroutines not being awaited.

Install it into the project venv (preferred):

```bash
agent/.venv/bin/pip install pytest-asyncio
```

Or into the current interpreter:

```bash
python3 -m pip install pytest-asyncio
```

Inside the venv, `pyproject.toml` already pins `pytest-asyncio` under
`[project.optional-dependencies].dev`, so `uv sync --dev` is the canonical
way to get it.

## Makefile targets

The `agent/Makefile` exposes three convenience targets that encode the rules
above:

### `make -C agent test-clean-worktree`

Runs the entire `agent/tests/` suite with plugin autoload disabled. Async
tests that require `pytest-asyncio` will be skipped or no-op — this target
is for the "fast smoke" pass where you only care about synchronous coverage.

Expected output (clean tree, abbreviated):

```
================================ test session starts ================================
collected NNN items / M skipped

agent/tests/test_app_startup_smoke.py ............                              [  3%]
agent/tests/test_experiment_loop.py ..............................              [ 18%]
...
=================== NNN passed, M skipped, K warnings in <secs>s ===================
```

### `make -C agent test-async`

Same suite, but with `pytest-asyncio` explicitly re-enabled. Use this when
you want the async test cases to actually run.

Expected output (clean tree, abbreviated):

```
================================ test session starts ================================
plugins: asyncio-X.Y.Z
collected NNN items

agent/tests/test_token_refresher.py ............                                [ 12%]
agent/tests/test_experiment_loop.py ..............................              [ 28%]
...
============================ NNN passed in <secs>s ============================
```

### `make -C agent test-all`

Runs `test-clean-worktree` first, then `test-async`. Final line on success:

```
All test suites green.
```

If either target fails, `make` exits non-zero and the final line is not
printed — that is your signal that something failed before the summary.

## When to use which path

| Situation | Use |
|---|---|
| Local development with `agent/.venv` provisioned | `agent/.venv/bin/python -m pytest ...` |
| PR evidence collection | `agent/.venv/bin/python -m pytest ...` |
| CI | `agent/.venv/bin/python -m pytest ...` (already configured) |
| Clean-worktree audit on a host without the venv | `make -C agent test-clean-worktree` (sync) or `make -C agent test-async` (async) |
| Single test file, no venv | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTEST_PLUGINS=pytest_asyncio python3 -m pytest agent/tests/<file> -q` |

## References

- Audit: [`docs/audits/2026-05-15-comprehensive-codebase-audit.md`](../docs/audits/2026-05-15-comprehensive-codebase-audit.md) §M-3 ("Toolchain reproducibility is fragile outside the project venv").
- Sprint: `audit-2026-05-15.D.03` — "docs(test): document pytest plugin environment for clean worktrees" (this file).
- Pytest plugin discovery: <https://docs.pytest.org/en/stable/how-to/plugins.html#autoload-explicit-loading>.
