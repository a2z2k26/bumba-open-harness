"""Tests for the Z4-19 LSP capability probe."""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def _probe_module():
    return importlib.import_module("scripts.probe_lsp_capabilities")


def test_inventory_mcp_servers_detects_serena_style_server(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {"command": "npx"},
                    "serena": {"command": "serena-mcp-server"},
                }
            }
        ),
        encoding="utf-8",
    )

    inventory = _probe_module().inventory_mcp_servers(config)

    assert inventory.server_names == ("github", "serena")
    assert inventory.serena_style_server is True


def test_python_symbol_probe_finds_definition_and_references(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "def target() -> int:\n"
        "    return 1\n\n"
        "def caller() -> int:\n"
        "    return target()\n",
        encoding="utf-8",
    )

    result = _probe_module().probe_python_symbol(
        repo_root=tmp_path,
        file_path=source.relative_to(tmp_path),
        symbol="target",
        server="python-ast-fallback",
    )

    assert result.language == "python"
    assert result.definition_found is True
    assert result.references_found >= 2
    assert result.diagnostics_count == 0


def test_typescript_symbol_probe_finds_exported_function(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.ts"
    source.write_text(
        "export function filesList(): string {\n"
        "  return 'ok';\n"
        "}\n\n"
        "filesList();\n",
        encoding="utf-8",
    )

    result = _probe_module().probe_typescript_symbol(
        repo_root=tmp_path,
        file_path=source.relative_to(tmp_path),
        symbol="filesList",
        server="typescript-text-fallback",
    )

    assert result.language == "typescript"
    assert result.definition_found is True
    assert result.references_found >= 2
    assert result.diagnostics_count == 0


def test_recommendation_prefers_existing_serena_server() -> None:
    assert _probe_module().choose_lsp_recommendation(
        serena_style_server=True,
        python_lsp_available=False,
        typescript_lsp_available=False,
    ) == "mcp-serena-baseline"


def test_recommendation_defers_runtime_when_no_lsp_surface() -> None:
    assert _probe_module().choose_lsp_recommendation(
        serena_style_server=False,
        python_lsp_available=False,
        typescript_lsp_available=False,
    ) == "defer-runtime-add-serena-or-local-lsp"


def test_run_probe_returns_required_repo_symbols() -> None:
    payload = _probe_module().run_probe(Path.cwd())

    assert payload["recommendation"]
    python_probe = payload["probes"]["python"]
    assert python_probe["file"] == "agent/teams/_factory.py"
    assert python_probe["symbol"] == "_resolve_model"
    assert python_probe["definition_found"] is True

    typescript_probe = payload["probes"]["typescript"]
    assert typescript_probe["file"].endswith("file-operations.ts")
    assert typescript_probe["symbol"] == "filesList"
    assert typescript_probe["definition_found"] is True
