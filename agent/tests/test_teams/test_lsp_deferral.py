"""LSP runtime un-defer guard (Z4-20 #2446, Z4-21 #2447).

This file replaces the PR #2557 *deferral* guard. Originally it asserted that
``lsp_*`` tools must NOT be registered while no LSP runtime existed. The
2026-06-01 operator directive flipped that decision: Serena was added to the
agent MCP config as the LSP runtime, so the deferral guard is retired and
inverted. These tests now assert the un-defer is real and complete:

- the LSP tools ARE registered as in-process callables;
- the Serena MCP entry is present and well-formed in the canonical config;
- the probe recommendation has flipped off ``defer-*`` to ``mcp-serena-baseline``.

If any of these regress, the LSP track has silently fallen back to "looks
LSP-backed but isn't" — the exact failure mode the original guard prevented.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from teams._tool_registry import TOOL_CALLABLES

AGENT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AGENT_ROOT.parent
CANONICAL_MCP = AGENT_ROOT / "config" / "mcp-servers.canonical.json"

LSP_TOOLS = frozenset(
    {
        "lsp_find_definition",
        "lsp_find_references",
        "lsp_diagnostics",
    }
)


def test_lsp_agent_tools_are_registered_now_runtime_exists() -> None:
    """Serena is the LSP runtime, so the lsp_* tools must be registered."""
    assert LSP_TOOLS.issubset(TOOL_CALLABLES)
    for name in LSP_TOOLS:
        assert callable(TOOL_CALLABLES[name]), name


def test_serena_mcp_entry_present_and_wellformed() -> None:
    """The canonical MCP config must expose Serena as a stdio server."""
    data = json.loads(CANONICAL_MCP.read_text(encoding="utf-8"))
    servers = data["mcpServers"]
    assert "serena" in servers, "serena MCP entry missing — LSP runtime absent"

    entry = servers["serena"]
    assert entry.get("type") == "stdio"
    assert entry.get("command") == "uvx"
    args = entry.get("args", [])
    assert "start-mcp-server" in args
    assert "--project" in args
    # The --from package spec must pin Serena to a tag, not HEAD.
    joined = " ".join(str(a) for a in args)
    assert "github.com/oraios/serena@" in joined


def test_probe_recommendation_flips_to_serena_baseline() -> None:
    """The Z4-19 probe must now recommend the Serena MCP path."""
    probe = importlib.import_module("scripts.probe_lsp_capabilities")
    inventory = probe.inventory_mcp_servers(CANONICAL_MCP)
    assert inventory.serena_style_server is True
    assert "serena" in inventory.lsp_related_servers

    recommendation = probe.choose_lsp_recommendation(
        serena_style_server=inventory.serena_style_server,
        python_lsp_available=False,
        typescript_lsp_available=False,
    )
    assert recommendation == "mcp-serena-baseline"
