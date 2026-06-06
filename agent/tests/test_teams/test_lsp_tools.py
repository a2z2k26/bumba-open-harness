"""Tests for the LSP-backed Zone 4 tools (Z4-20, #2446).

Serena is mocked at the ``_call_serena_tool`` boundary so these tests are
offline and deterministic — the live Serena resolution is proven separately
via the operator mini command in the PR description.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from teams.tools import _lsp
from teams.tools._lsp import (
    LspLocation,
    LspToolResult,
    lsp_diagnostics,
    lsp_find_definition,
    lsp_find_references,
)

# A real file inside the repo so _confine_to_repo passes.
REAL_REL_PATH = "agent/teams/_tool_registry.py"


def _ctx() -> MagicMock:
    return MagicMock()


def _parse(result: str) -> dict:
    return json.loads(result)


# --------------------------------------------------------------------------
# dataclass shape
# --------------------------------------------------------------------------


def test_lsp_tool_result_renders_jsonable() -> None:
    result = LspToolResult(
        query="Foo",
        tool="lsp_find_definition",
        locations=(LspLocation("a.py", 3, 0, "class Foo:"),),
        truncated=True,
    )
    data = json.loads(result.render())
    assert data["query"] == "Foo"
    assert data["truncated"] is True
    assert data["locations"][0]["file_path"] == "a.py"
    assert data["locations"][0]["line"] == 3


# --------------------------------------------------------------------------
# definition lookup
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_definition_returns_location(monkeypatch) -> None:
    payload = [
        {
            "name_path": "resolve_tools",
            "relative_path": REAL_REL_PATH,
            "body_location": {"line": 524, "character": 0},
        }
    ]
    monkeypatch.setattr(
        _lsp, "_call_serena_tool", AsyncMock(return_value=(payload, None))
    )

    out = _parse(
        await lsp_find_definition(_ctx(), "resolve_tools", REAL_REL_PATH)
    )
    assert out["tool"] == "lsp_find_definition"
    assert out["error"] is None
    assert out["locations"][0]["file_path"] == REAL_REL_PATH
    assert out["locations"][0]["line"] == 524
    assert out["truncated"] is False


# --------------------------------------------------------------------------
# reference truncation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_references_truncates_to_limit(monkeypatch) -> None:
    refs = [
        {"name_path": f"caller_{i}", "relative_path": REAL_REL_PATH, "line": i + 1}
        for i in range(30)
    ]
    monkeypatch.setattr(
        _lsp, "_call_serena_tool", AsyncMock(return_value=(refs, None))
    )

    out = _parse(
        await lsp_find_references(_ctx(), "resolve_tools", REAL_REL_PATH, limit=5)
    )
    assert len(out["locations"]) == 5
    assert out["truncated"] is True


@pytest.mark.asyncio
async def test_find_references_limit_is_bounded(monkeypatch) -> None:
    refs = [
        {"name_path": f"c_{i}", "relative_path": REAL_REL_PATH, "line": i + 1}
        for i in range(10)
    ]
    captured = AsyncMock(return_value=(refs, None))
    monkeypatch.setattr(_lsp, "_call_serena_tool", captured)

    # limit far above MAX_REFERENCE_LIMIT clamps; not below 1.
    out = _parse(
        await lsp_find_references(_ctx(), "x", REAL_REL_PATH, limit=99999)
    )
    assert len(out["locations"]) == 10
    assert out["truncated"] is False


# --------------------------------------------------------------------------
# diagnostics / overview
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostics_returns_symbol_overview(monkeypatch) -> None:
    overview = [
        {"name_path": "TOOL_CALLABLES", "kind": "variable"},
        {"name_path": "resolve_tools", "kind": "function"},
    ]
    monkeypatch.setattr(
        _lsp, "_call_serena_tool", AsyncMock(return_value=(overview, None))
    )

    out = _parse(await lsp_diagnostics(_ctx(), REAL_REL_PATH))
    assert out["tool"] == "lsp_diagnostics"
    assert any("resolve_tools" in d for d in out["diagnostics"])


# --------------------------------------------------------------------------
# path denial — escape + missing
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_outside_repo_is_denied(monkeypatch) -> None:
    # Should never reach Serena.
    sentinel = AsyncMock(return_value=([], None))
    monkeypatch.setattr(_lsp, "_call_serena_tool", sentinel)

    out = _parse(await lsp_find_definition(_ctx(), "Foo", "/etc/passwd"))
    assert out["error"] is not None
    assert "escapes the repo tree" in out["error"]
    sentinel.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_file_is_denied(monkeypatch) -> None:
    sentinel = AsyncMock(return_value=([], None))
    monkeypatch.setattr(_lsp, "_call_serena_tool", sentinel)

    out = _parse(
        await lsp_find_references(_ctx(), "Foo", "agent/teams/does_not_exist_xyz.py")
    )
    assert out["error"] is not None
    assert "file not found" in out["error"]
    sentinel.assert_not_awaited()


# --------------------------------------------------------------------------
# server failure → structured error, not a stack trace
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_failure_returns_structured_error(monkeypatch) -> None:
    monkeypatch.setattr(
        _lsp,
        "_call_serena_tool",
        AsyncMock(return_value=(None, "LSP runtime error invoking find_symbol: boom")),
    )

    out = _parse(
        await lsp_find_definition(_ctx(), "Foo", REAL_REL_PATH)
    )
    assert out["locations"] == []
    assert "LSP runtime error" in out["error"]


def test_serena_command_none_when_uvx_absent(monkeypatch) -> None:
    monkeypatch.setattr(_lsp, "_uvx_path", lambda: None)
    assert _lsp._serena_command(Path(".")) is None


@pytest.mark.asyncio
async def test_call_serena_tool_missing_uvx_returns_error(monkeypatch) -> None:
    monkeypatch.setattr(_lsp, "_uvx_path", lambda: None)
    payload, err = await _lsp._call_serena_tool("find_symbol", {})
    assert payload is None
    assert "uvx" in err


# --------------------------------------------------------------------------
# registry wiring
# --------------------------------------------------------------------------


def test_lsp_tools_registered_in_tool_callables() -> None:
    from teams._tool_registry import TOOL_CALLABLES

    for name in ("lsp_find_definition", "lsp_find_references", "lsp_diagnostics"):
        assert name in TOOL_CALLABLES
        assert callable(TOOL_CALLABLES[name])
