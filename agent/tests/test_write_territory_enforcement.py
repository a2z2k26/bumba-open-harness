"""R5.2 (#1904) — Prove write-territory enforcement against a real team YAML.

The existing ``test_teams/test_domain_lock_enforcement.py`` exercises
``make_tracked`` with synthetic deny lists. This module closes the loop
by loading a **real** team YAML (`agent/config/teams/ops.yaml`) and
asserting the declared ``deny_write`` rules actually block writes via
the same enforcement seam.

`ops-database-admin` carries `deny_write: ["bridge/database.py"]` —
exactly the kind of "one specialist must never touch one file" rule the
canonical-write-territory doctrine exists to enforce. If this test
fails, it means a YAML-declared write boundary stopped being honoured
at runtime, which is the regression class R5.2 is built to catch.

Referenced from `docs/security/write-jail-verification.md`.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from teams._tool_registry import make_tracked


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the repo root from this test file's path."""
    # agent/tests/test_write_territory_enforcement.py → agent/.. → repo root
    return Path(__file__).resolve().parent.parent.parent


def _load_ops_yaml() -> dict:
    """Load `agent/config/teams/ops.yaml` exactly as the runtime loader sees it."""
    path = _repo_root() / "agent" / "config" / "teams" / "ops.yaml"
    assert path.exists(), f"ops.yaml fixture missing at {path}"
    return yaml.safe_load(path.read_text())


def _ctx_with_event_bus():
    """Build a minimal RunContext-shaped mock for make_tracked invocations."""
    ctx = MagicMock()
    ctx.deps = MagicMock()
    ctx.deps.event_bus = MagicMock()
    ctx.deps.department = "ops"
    ctx.deps.session_id = "test-session"
    return ctx


# ---------------------------------------------------------------------------
# YAML structure assertion — guards against silent edits.
# ---------------------------------------------------------------------------


def test_ops_database_admin_declares_deny_write_for_database_py() -> None:
    """If this test fails, `ops.yaml` was edited to remove the canonical
    deny_write rule for `bridge/database.py`. That rule is load-bearing
    for the runtime enforcement test below.
    """
    data = _load_ops_yaml()
    workers = data["team"]["workers"]
    dba = next(
        (w for w in workers if w["name"] == "ops-database-admin"),
        None,
    )
    assert dba is not None, "ops-database-admin worker missing from ops.yaml"
    deny_write = dba.get("domain", {}).get("deny_write", [])
    assert "bridge/database.py" in deny_write, (
        f"ops-database-admin must declare deny_write: ['bridge/database.py']; "
        f"got {deny_write!r}. R5.2's regression catch hinges on this rule "
        f"being present in ops.yaml."
    )


# ---------------------------------------------------------------------------
# Runtime enforcement against the YAML rule.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yaml_deny_write_blocks_write_to_database_py() -> None:
    """R5.2 denied-path proof against a real team YAML rule.

    Loads the deny_write list from `ops.yaml` and asserts that writing
    to a path matching the declared rule (`bridge/database.py`) is
    rejected by `make_tracked` with a DOMAIN_VIOLATION error that names
    both the agent and the denied path.
    """
    data = _load_ops_yaml()
    workers = data["team"]["workers"]
    dba = next(w for w in workers if w["name"] == "ops-database-admin")
    deny_paths = tuple(dba["domain"]["deny_write"])

    async def write_file(ctx, path: str, contents: str) -> str:
        return f"wrote {path}"

    wrapped = make_tracked(
        write_file,
        department="ops",
        tool_name="write_file",
        deny_write_paths=deny_paths,
        agent_name="ops-database-admin",
    )
    ctx = _ctx_with_event_bus()
    result = await wrapped(
        ctx, path="bridge/database.py", contents="DROP TABLE knowledge;"
    )

    # Acceptance: failure message identifies the team/agent AND the denied path.
    assert result.startswith("DOMAIN_VIOLATION:"), result
    assert "ops-database-admin" in result, result
    assert "bridge/database.py" in result, result

    # Defense in depth: the violation was published to the EventBus, so
    # Mission Control sees it.
    ctx.deps.event_bus.publish.assert_called_once()
    evt = ctx.deps.event_bus.publish.call_args
    assert evt[0][0] == "z4.domain.violation"
    assert evt[0][1]["agent_name"] == "ops-database-admin"
    assert evt[0][1]["target"] == "bridge/database.py"


@pytest.mark.asyncio
async def test_yaml_deny_write_allows_write_to_permitted_path() -> None:
    """R5.2 allowed-path proof against the same real YAML rule.

    The same agent writing to a path NOT on its deny list must pass
    through cleanly. This is the symmetric assertion to the denied-path
    test above — together they prove enforcement is targeted, not
    catastrophic.
    """
    data = _load_ops_yaml()
    workers = data["team"]["workers"]
    dba = next(w for w in workers if w["name"] == "ops-database-admin")
    deny_paths = tuple(dba["domain"]["deny_write"])

    async def write_file(ctx, path: str, contents: str) -> str:
        return f"wrote {path}"

    wrapped = make_tracked(
        write_file,
        department="ops",
        tool_name="write_file",
        deny_write_paths=deny_paths,
        agent_name="ops-database-admin",
    )
    ctx = _ctx_with_event_bus()
    # ops-database-admin's declared write territory is `docs/ops/database/`
    # and `sessions/` — those should pass.
    result = await wrapped(
        ctx, path="docs/ops/database/migrations.md", contents="schema notes"
    )

    assert "wrote docs/ops/database/migrations.md" in result
    ctx.deps.event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_yaml_deny_write_blocks_bash_redirect_to_denied_path() -> None:
    """R5.2: the bash-command scanner honours the YAML-declared deny list
    the same way the direct write tool does.

    Equivalent to the bash-redirect scenario in test_domain_lock_enforcement
    but driven by the real ops.yaml rule, so a future YAML edit can't
    silently slip enforcement.
    """
    data = _load_ops_yaml()
    workers = data["team"]["workers"]
    dba = next(w for w in workers if w["name"] == "ops-database-admin")
    deny_paths = tuple(dba["domain"]["deny_write"])

    async def bash(ctx, command: str) -> str:
        return "ran"

    wrapped = make_tracked(
        bash,
        department="ops",
        tool_name="bash",
        deny_write_paths=deny_paths,
        agent_name="ops-database-admin",
    )
    ctx = _ctx_with_event_bus()
    result = await wrapped(
        ctx, command="echo 'malicious' > bridge/database.py"
    )

    assert result.startswith("DOMAIN_VIOLATION:"), result
    assert "ops-database-admin" in result
    assert "bridge/database.py" in result
    ctx.deps.event_bus.publish.assert_called_once()
