"""LSP-backed code-intelligence tools for Zone 4 specialists (Z4-20, #2446).

These tools give code-oriented QA/Ops specialists bounded code-navigation
questions — definition lookup, reference search, and per-file diagnostics —
without loading whole files or directories into the model context.

## Runtime

The tools drive **Serena** (https://github.com/oraios/serena) as a stdio MCP
server spawned per call via ``uvx``. Serena wraps a real language server
(``pyright`` for Python, bundled at install time), so results are LSP-backed:
cross-file references and rename-safe symbol resolution, not the AST/text
fallback that ``scripts/probe_lsp_capabilities.py`` warns against.

Mapping from the #2446 tool spec to Serena's LSP-backed tools:

| #2446 tool             | Serena tool                | Intent                       |
| ---------------------- | -------------------------- | ---------------------------- |
| ``lsp_find_definition``  | ``find_symbol``            | locate where a symbol is defined |
| ``lsp_find_references``  | ``find_referencing_symbols`` | who references a symbol        |
| ``lsp_diagnostics``      | ``get_symbols_overview``   | per-file symbol/structure read |

We deliberately wrap rather than expose Serena's MCP tools directly: Zone 4
specialists are pydantic-ai agents whose toolset is in-process Python callables
(``teams._tool_registry.TOOL_CALLABLES``). MCP servers in
``mcp-servers.canonical.json`` reach only the main ``claude -p`` subprocess, not
the Zone 4 agents — so a thin in-process wrapper is the only surface that can
deliver the ``lsp_*`` tools the spec requires.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

from teams._types import BridgeDeps

log = logging.getLogger(__name__)

# Pinned Serena ref — a tag, not HEAD, so the runtime build is reproducible
# (HEAD-tracking produced a corrupt git-cache checkout on the workstation).
# Override via BUMBA_SERENA_REF for an upgrade without a code change.
SERENA_REF = os.environ.get("BUMBA_SERENA_REF", "v0.1.4")
SERENA_PACKAGE = f"git+https://github.com/oraios/serena@{SERENA_REF}"

# uvx resolves differently per host: /opt/homebrew/bin/uvx on the mini,
# ~/.local/bin/uvx on the workstation. Resolve from PATH, allow override.
_UVX_OVERRIDE = os.environ.get("BUMBA_UVX_PATH", "")

# Bounded previews keep tool output model-safe.
PREVIEW_MAX_CHARS = 200
DEFAULT_REFERENCE_LIMIT = 20
MAX_REFERENCE_LIMIT = 100
# Serena's first cold start builds the language server index; give it room.
SERENA_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class LspLocation:
    """A single resolved code location with a bounded source preview."""

    file_path: str
    line: int
    character: int
    preview: str


@dataclass(frozen=True)
class LspToolResult:
    """Structured result for every ``lsp_*`` tool.

    ``error`` carries a human-readable, non-stack-trace message when the
    underlying runtime fails — callers (and the model) never see a Python
    traceback.
    """

    query: str
    tool: str
    locations: tuple[LspLocation, ...] = ()
    diagnostics: tuple[str, ...] = ()
    truncated: bool = False
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        """Render a compact, model-friendly text payload."""
        return json.dumps(self._as_jsonable(), indent=2, sort_keys=True)

    def _as_jsonable(self) -> dict[str, Any]:
        data = asdict(self)
        data["locations"] = [asdict(loc) for loc in self.locations]
        data["diagnostics"] = list(self.diagnostics)
        return data


def _uvx_path() -> str | None:
    if _UVX_OVERRIDE:
        return _UVX_OVERRIDE if Path(_UVX_OVERRIDE).exists() else None
    return shutil.which("uvx")


def _repo_root() -> Path:
    """Resolve the repo root that Serena should index (the ``agent/`` parent)."""
    # _lsp.py lives at agent/teams/tools/_lsp.py → parents[3] is the repo root.
    return Path(__file__).resolve().parents[3]


def _confine_to_repo(file_path: str) -> tuple[Path | None, str | None]:
    """Resolve ``file_path`` and confirm it stays inside the repo tree.

    Defense in depth beyond the read-domain glob enforcement applied by
    ``make_tracked`` — a Serena query must never escape the indexed project.
    """
    root = _repo_root()
    candidate = Path(file_path)
    resolved = candidate if candidate.is_absolute() else (root / candidate)
    try:
        resolved = resolved.resolve()
    except OSError as exc:  # pragma: no cover - exotic FS error
        return None, f"path could not be resolved: {exc}"
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, f"path escapes the repo tree: {file_path!r}"
    if not resolved.exists():
        return None, f"file not found: {file_path}"
    return resolved, None


def _preview_for(path: Path, line: int) -> str:
    """Read a single source line for the preview, bounded and newline-free."""
    if line < 1:
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for current, text in enumerate(handle, start=1):
                if current == line:
                    return text.strip()[:PREVIEW_MAX_CHARS]
    except OSError:
        return ""
    return ""


def _serena_command(project_root: Path, context: str = "agent") -> list[str] | None:
    uvx = _uvx_path()
    if uvx is None:
        return None
    return [
        uvx,
        "--from",
        SERENA_PACKAGE,
        "serena",
        "start-mcp-server",
        "--transport",
        "stdio",
        "--context",
        context,
        "--project",
        str(project_root),
    ]


async def _call_serena_tool(
    tool_name: str, arguments: dict[str, Any]
) -> tuple[Any, str | None]:
    """Spawn Serena as a stdio MCP server, call one tool, tear down.

    Returns ``(result, None)`` on success or ``(None, error_message)`` on any
    failure — never raises into the agent loop, never leaks a stack trace.
    """
    project_root = _repo_root()
    command = _serena_command(project_root)
    if command is None:
        return None, (
            "LSP runtime unavailable: 'uvx' not found on PATH "
            "(set BUMBA_UVX_PATH or install uv)."
        )

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:  # pragma: no cover - SDK pinned in deps
        return None, f"LSP runtime unavailable: mcp SDK import failed: {exc}"

    params = StdioServerParameters(
        command=command[0],
        args=command[1:],
        env={**os.environ},
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool(tool_name, arguments)
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        log.warning("serena tool %s failed: %s", tool_name, exc)
        return None, f"LSP runtime error invoking {tool_name}: {exc}"

    return _extract_tool_payload(response), None


def _extract_tool_payload(response: Any) -> Any:
    """Pull the text/JSON payload out of an MCP CallToolResult."""
    content = getattr(response, "content", None)
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    joined = "\n".join(parts)
    try:
        return json.loads(joined)
    except (json.JSONDecodeError, TypeError):
        return joined


def _locations_from_serena(payload: Any, *, limit: int) -> tuple[
    tuple[LspLocation, ...], bool
]:
    """Normalise Serena symbol/reference payloads into bounded LspLocations."""
    items = _as_item_list(payload)
    truncated = len(items) > limit
    locations: list[LspLocation] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        rel = _symbol_relative_path(item)
        line, character = _symbol_line_char(item)
        preview = _symbol_preview(item)
        if not preview and rel and line:
            resolved, err = _confine_to_repo(rel)
            if resolved is not None and err is None:
                preview = _preview_for(resolved, line)
        locations.append(
            LspLocation(
                file_path=rel,
                line=line,
                character=character,
                preview=preview,
            )
        )
    return tuple(locations), truncated


def _as_item_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("symbols", "references", "results", "matches"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    return []


def _symbol_relative_path(item: dict[str, Any]) -> str:
    for key in ("relative_path", "file_path", "file", "path"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    location = item.get("location")
    if isinstance(location, dict):
        return _symbol_relative_path(location)
    return ""


def _symbol_line_char(item: dict[str, Any]) -> tuple[int, int]:
    """Best-effort line/character extraction across Serena payload shapes.

    Serena returns either a flat ``body_location`` / ``line`` or an LSP-style
    ``range``/``start`` block. We read whichever is present; absent data
    yields ``(0, 0)`` rather than guessing.
    """
    for key in ("body_location", "location", "range", "start"):
        loc = item.get(key)
        if not isinstance(loc, dict):
            continue
        start = loc.get("start") if isinstance(loc.get("start"), dict) else loc
        line = start.get("line") or start.get("start_line")
        char = start.get("character") or start.get("column") or 0
        if isinstance(line, int):
            return line, int(char or 0)
    line = item.get("line")
    if isinstance(line, int):
        return line, int(item.get("character") or 0)
    return 0, 0


def _symbol_preview(item: dict[str, Any]) -> str:
    for key in ("name_path", "name", "body", "preview"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value.strip()[:PREVIEW_MAX_CHARS]
    return ""


# --------------------------------------------------------------------------
# Agent-facing tools
# --------------------------------------------------------------------------


async def lsp_find_definition(
    ctx: RunContext[BridgeDeps], symbol: str, file_path: str
) -> str:
    """Find where ``symbol`` is defined, using the LSP-backed symbol index.

    Returns a structured ``LspToolResult`` (rendered as JSON) with the
    definition location(s) and a bounded source preview, or an ``error``
    field when the runtime is unavailable. Prefer this over reading whole
    files when you only need to locate a named function/class.
    """
    resolved, err = _confine_to_repo(file_path)
    if err is not None:
        return LspToolResult(
            query=symbol, tool="lsp_find_definition", error=err
        ).render()

    payload, err = await _call_serena_tool(
        "find_symbol",
        {
            "name_path": symbol,
            "relative_path": _to_relative(resolved),
            "include_body": False,
        },
    )
    if err is not None:
        return LspToolResult(
            query=symbol, tool="lsp_find_definition", error=err
        ).render()

    locations, truncated = _locations_from_serena(payload, limit=MAX_REFERENCE_LIMIT)
    return LspToolResult(
        query=symbol,
        tool="lsp_find_definition",
        locations=locations,
        truncated=truncated,
    ).render()


async def lsp_find_references(
    ctx: RunContext[BridgeDeps],
    symbol: str,
    file_path: str,
    limit: int = DEFAULT_REFERENCE_LIMIT,
) -> str:
    """Find symbols that reference ``symbol`` defined in ``file_path``.

    Results are bounded by ``limit`` (default 20, max 100); ``truncated``
    is true when more references exist than were returned. Use this before
    editing shared code so you know who depends on it.
    """
    bounded_limit = max(1, min(MAX_REFERENCE_LIMIT, limit))
    resolved, err = _confine_to_repo(file_path)
    if err is not None:
        return LspToolResult(
            query=symbol, tool="lsp_find_references", error=err
        ).render()

    payload, err = await _call_serena_tool(
        "find_referencing_symbols",
        {
            "name_path": symbol,
            "relative_path": _to_relative(resolved),
        },
    )
    if err is not None:
        return LspToolResult(
            query=symbol, tool="lsp_find_references", error=err
        ).render()

    locations, truncated = _locations_from_serena(payload, limit=bounded_limit)
    return LspToolResult(
        query=symbol,
        tool="lsp_find_references",
        locations=locations,
        truncated=truncated,
    ).render()


async def lsp_diagnostics(ctx: RunContext[BridgeDeps], file_path: str) -> str:
    """Report the symbol/structure overview for ``file_path``.

    Backed by Serena's ``get_symbols_overview`` (LSP-derived), this surfaces
    the top-level symbols defined in a file so a specialist can orient on a
    code path without reading the whole file. Use after a code path is
    identified.
    """
    resolved, err = _confine_to_repo(file_path)
    if err is not None:
        return LspToolResult(
            query=file_path, tool="lsp_diagnostics", error=err
        ).render()

    payload, err = await _call_serena_tool(
        "get_symbols_overview",
        {"relative_path": _to_relative(resolved)},
    )
    if err is not None:
        return LspToolResult(
            query=file_path, tool="lsp_diagnostics", error=err
        ).render()

    diagnostics = _diagnostics_from_overview(payload)
    return LspToolResult(
        query=file_path,
        tool="lsp_diagnostics",
        diagnostics=diagnostics,
        truncated=False,
    ).render()


def _diagnostics_from_overview(payload: Any) -> tuple[str, ...]:
    items = _as_item_list(payload)
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name_path") or item.get("name") or "<symbol>"
        kind = item.get("kind") or item.get("symbol_kind") or ""
        lines.append(f"{name} ({kind})".strip())
    return tuple(lines)


def _to_relative(resolved: Path) -> str:
    try:
        return resolved.relative_to(_repo_root()).as_posix()
    except ValueError:
        return resolved.as_posix()
