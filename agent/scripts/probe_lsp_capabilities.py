"""Probe local LSP and MCP code-intelligence capability for Z4-19."""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class McpInventory:
    server_names: tuple[str, ...]
    serena_style_server: bool
    lsp_related_servers: tuple[str, ...]


@dataclass(frozen=True)
class ProbeResult:
    language: str
    server: str
    file: str
    symbol: str
    definition_found: bool
    references_found: int
    diagnostics_count: int
    latency_ms: float
    failure_mode: str | None = None


_PYTHON_LSP_BINARIES = (
    "pyright",
    "basedpyright",
    "pylsp",
    "jedi-language-server",
)
_TYPESCRIPT_LSP_BINARIES = (
    "typescript-language-server",
    "tsserver",
)


def inventory_mcp_servers(config_path: Path) -> McpInventory:
    """Read a repo MCP config and identify LSP/Serena-style surfaces."""
    if not config_path.exists():
        return McpInventory((), False, ())

    data = json.loads(config_path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    if not isinstance(servers, dict):
        return McpInventory((), False, ())

    server_names = tuple(sorted(str(name) for name in servers))
    lsp_related = tuple(
        name
        for name in server_names
        if _server_name_is_lsp_related(name)
        or _server_command_is_lsp_related(servers.get(name))
    )
    serena_style = any("serena" in name.lower() for name in lsp_related)
    return McpInventory(
        server_names=server_names,
        serena_style_server=serena_style,
        lsp_related_servers=lsp_related,
    )


def probe_python_symbol(
    *,
    repo_root: Path,
    file_path: Path,
    symbol: str,
    server: str,
) -> ProbeResult:
    """Probe a Python symbol with AST fallback semantics."""
    started = time.perf_counter()
    path = repo_root / file_path
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return _probe_result(
            language="python",
            server=server,
            file=file_path,
            symbol=symbol,
            definition_found=False,
            references_found=0,
            diagnostics_count=1,
            started=started,
            failure_mode="syntax_error",
        )

    definition_found = any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.name == symbol
        for node in ast.walk(tree)
    )
    references = sum(
        1
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == symbol)
        or (isinstance(node, ast.Attribute) and node.attr == symbol)
        or (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == symbol
        )
    )
    return _probe_result(
        language="python",
        server=server,
        file=file_path,
        symbol=symbol,
        definition_found=definition_found,
        references_found=references,
        diagnostics_count=0,
        started=started,
    )


def probe_typescript_symbol(
    *,
    repo_root: Path,
    file_path: Path,
    symbol: str,
    server: str,
) -> ProbeResult:
    """Probe a TypeScript symbol with deterministic text fallback semantics."""
    started = time.perf_counter()
    source = (repo_root / file_path).read_text(encoding="utf-8")
    escaped = re.escape(symbol)
    definition_pattern = re.compile(
        rf"\b(export\s+)?(async\s+)?(function|class|interface|const|let|var)\s+{escaped}\b"
    )
    definition_found = bool(definition_pattern.search(source))
    references = len(re.findall(rf"\b{escaped}\b", source))
    return _probe_result(
        language="typescript",
        server=server,
        file=file_path,
        symbol=symbol,
        definition_found=definition_found,
        references_found=references,
        diagnostics_count=0,
        started=started,
    )


def choose_lsp_recommendation(
    *,
    serena_style_server: bool,
    python_lsp_available: bool,
    typescript_lsp_available: bool,
) -> str:
    """Select the Z4-19 recommendation from observed capability."""
    if serena_style_server:
        return "mcp-serena-baseline"
    if python_lsp_available and typescript_lsp_available:
        return "local-lsp-processes"
    return "defer-runtime-add-serena-or-local-lsp"


def run_probe(repo_root: Path) -> dict[str, object]:
    """Run the deterministic Z4-19 probe and return JSON-serializable data."""
    repo_root = _normalize_repo_root(repo_root)
    mcp_inventory = inventory_mcp_servers(
        repo_root / "agent" / "config" / "mcp-servers.canonical.json"
    )
    python_binaries = _available_binaries(_PYTHON_LSP_BINARIES)
    typescript_binaries = _available_binaries(_TYPESCRIPT_LSP_BINARIES)
    node_tsserver = repo_root / "mcp-servers/bumba-sandbox/node_modules/.bin/tsserver"
    typescript_lsp_available = bool(typescript_binaries) or node_tsserver.exists()

    python_server = python_binaries[0] if python_binaries else "python-ast-fallback"
    typescript_server = (
        typescript_binaries[0]
        if typescript_binaries
        else "typescript-text-fallback"
    )

    python_probe = probe_python_symbol(
        repo_root=repo_root,
        file_path=Path("agent/teams/_factory.py"),
        symbol="_resolve_model",
        server=python_server,
    )
    typescript_probe = probe_typescript_symbol(
        repo_root=repo_root,
        file_path=Path("mcp-servers/bumba-sandbox/src/tools/file-operations.ts"),
        symbol="filesList",
        server=typescript_server,
    )
    recommendation = choose_lsp_recommendation(
        serena_style_server=mcp_inventory.serena_style_server,
        python_lsp_available=bool(python_binaries),
        typescript_lsp_available=typescript_lsp_available,
    )

    return {
        "mcp_inventory": asdict(mcp_inventory),
        "local_binaries": {
            "python_lsp": python_binaries,
            "typescript_lsp": typescript_binaries,
            "npm": shutil.which("npm") or "",
            "node_tsserver": str(node_tsserver) if node_tsserver.exists() else "",
        },
        "probes": {
            "python": asdict(python_probe),
            "typescript": asdict(typescript_probe),
        },
        "recommendation": recommendation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to probe.",
    )
    args = parser.parse_args()
    print(json.dumps(run_probe(args.repo_root), indent=2, sort_keys=True))
    return 0


def _available_binaries(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if shutil.which(name))


def _normalize_repo_root(path: Path) -> Path:
    resolved = path.resolve()
    if (resolved / "agent" / "teams").exists():
        return resolved
    if resolved.name == "agent" and (resolved / "teams").exists():
        return resolved.parent
    return resolved


def _server_name_is_lsp_related(name: str) -> bool:
    lowered = name.lower()
    return "lsp" in lowered or "language" in lowered or "serena" in lowered


def _server_command_is_lsp_related(server_config: object) -> bool:
    if not isinstance(server_config, dict):
        return False
    values: list[str] = []
    command = server_config.get("command")
    if isinstance(command, str):
        values.append(command)
    args = server_config.get("args")
    if isinstance(args, list):
        values.extend(str(arg) for arg in args)
    joined = " ".join(values).lower()
    return "lsp" in joined or "language" in joined or "serena" in joined


def _probe_result(
    *,
    language: str,
    server: str,
    file: Path,
    symbol: str,
    definition_found: bool,
    references_found: int,
    diagnostics_count: int,
    started: float,
    failure_mode: str | None = None,
) -> ProbeResult:
    return ProbeResult(
        language=language,
        server=server,
        file=file.as_posix(),
        symbol=symbol,
        definition_found=definition_found,
        references_found=references_found,
        diagnostics_count=diagnostics_count,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        failure_mode=failure_mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
