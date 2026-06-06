"""runtime_drift.py — Source vs. runtime file comparison.

Compares a configurable source checkout with the runtime agent directory
across key paths. Reports drift.
"""
from __future__ import annotations

import glob
import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)

# SOURCE_ROOT is the source checkout path (not the runtime). Override it with
# BUMBA_SOURCE_ROOT when comparing a separate source clone to the runtime tree.
# RUNTIME_ROOT resolves via bridge.paths.agent_root(). The lazy import avoids a
# circular dependency with bridge.app.
SOURCE_ROOT = Path(os.environ.get("BUMBA_SOURCE_ROOT", "/opt/bumba-harness/agent"))


def _resolve_runtime_root() -> Path:
    """Resolve the runtime tree root via the canonical helper.

    Wrapped in a function to defer the import until runtime use. This is the
    preferred call-site for in-tree code — it always re-resolves so a test
    or script that mutates ``cwd`` / ``BUMBA_AGENT_ROOT`` between imports
    observes the current value.
    """
    from bridge.paths import agent_root
    return agent_root()


# Module-level attribute ``RUNTIME_ROOT`` is preserved for back-compat with
# callers that import it directly (``background_loops.py``, ``commands.py``).
# Pre-#1501: bound at import time, freezing the value for the lifetime of
# the process. Post-#1501 (F3): resolved via PEP 562 ``__getattr__`` below
# so each attribute read re-resolves through ``_resolve_runtime_root()``.
# In-tree code should prefer ``_resolve_runtime_root()`` directly; the
# module attribute exists only as the deprecation shim.


def __getattr__(name: str) -> Path:
    """PEP 562 — lazy resolution for ``RUNTIME_ROOT`` (F3 of #1501).

    Pre-fix: ``RUNTIME_ROOT = _resolve_runtime_root()`` ran at import time
    and froze the result; tests/scripts mutating ``cwd`` between imports
    saw a stale value. Post-fix: the module-level binding is removed and
    every ``bridge.runtime_drift.RUNTIME_ROOT`` access (including the
    ``from bridge.runtime_drift import RUNTIME_ROOT`` form, which performs
    the attribute lookup at the moment of the import statement) re-routes
    here and re-resolves.

    Note: callers that did ``from bridge.runtime_drift import RUNTIME_ROOT``
    at module import time still bind a local name to the resolved value at
    *their* import time. The fix benefits two paths: (a) attribute access
    via the module object (``bridge.runtime_drift.RUNTIME_ROOT``) and (b)
    deferred imports done inside functions (the pattern used by
    ``background_loops.drift_loop`` and ``commands._cmd_drift``).
    """
    if name == "RUNTIME_ROOT":
        return _resolve_runtime_root()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Patterns relative to the repo root (not including the root itself).
# Globs are expanded relative to each root.
DRIFT_PATTERNS: tuple[str, ...] = (
    "bridge/**/*.py",
    "teams/**/*.py",
    "config/hooks/*.sh",
    "config/teams/*.yaml",
    "config/system-prompt.md",
    "config/bridge.toml",
    "config/disallowed-tools.txt",
    ".mcp.json",
    # Sprint 24 (Phase 5D): per-tier doctrine. Drift here means an agent
    # is running with different doctrine than the source — silent
    # behavioral divergence, exactly what the drift detector exists for.
    "docs/doctrine/*.md",
)


@dataclass(frozen=True)
class DriftReport:
    missing_in_runtime: tuple[str, ...] = field(default_factory=tuple)
    missing_in_source: tuple[str, ...] = field(default_factory=tuple)
    hash_mismatch: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None

    @property
    def is_clean(self) -> bool:
        return not (
            self.missing_in_runtime
            or self.missing_in_source
            or self.hash_mismatch
            or self.error
        )

    def summary(self) -> str:
        if self.error:
            return f"drift check error: {self.error}"
        if self.is_clean:
            return "source \u2194 runtime: clean"
        parts: list[str] = []
        if self.missing_in_runtime:
            parts.append(f"{len(self.missing_in_runtime)} missing in runtime")
        if self.missing_in_source:
            parts.append(f"{len(self.missing_in_source)} missing in source")
        if self.hash_mismatch:
            parts.append(f"{len(self.hash_mismatch)} hash mismatches")
        return "DRIFT DETECTED: " + ", ".join(parts)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_tree(root: Path) -> dict[str, str]:
    """Return {relative_path: sha256} for all files matching DRIFT_PATTERNS under root."""
    result: dict[str, str] = {}
    for pattern in DRIFT_PATTERNS:
        abs_pattern = str(root / pattern)
        for abs_path in glob.glob(abs_pattern, recursive=True):
            p = Path(abs_path)
            if p.is_file():
                rel = str(p.relative_to(root))
                try:
                    result[rel] = _sha256(p)
                except OSError as e:
                    log.warning("drift: cannot hash %s: %s", abs_path, e)
    return result


def compute_drift_report(
    source_root: Path = SOURCE_ROOT,
    runtime_root: Path | None = None,
) -> DriftReport:
    increment_module_counter("runtime_drift.compute_drift_report", tier=0)
    """Compare source and runtime file trees. Returns DriftReport.

    F3 of #1501: ``runtime_root`` defaults to ``None`` and is resolved at
    call time via ``_resolve_runtime_root()`` so callers always see the
    current runtime path (not whatever was bound at import time).
    """
    if runtime_root is None:
        runtime_root = _resolve_runtime_root()
    try:
        src = _hash_tree(source_root)
        run = _hash_tree(runtime_root)
    except Exception as exc:
        log.exception("drift: hash_tree failed")
        return DriftReport(error=str(exc))

    src_keys = set(src)
    run_keys = set(run)
    return DriftReport(
        missing_in_runtime=tuple(sorted(src_keys - run_keys)),
        missing_in_source=tuple(sorted(run_keys - src_keys)),
        hash_mismatch=tuple(
            sorted(k for k in src_keys & run_keys if src[k] != run[k])
        ),
    )


def generate_sync_script(
    report: DriftReport,
    output_path: Path | None = None,
) -> Path:
    """Write a deploy sync script for operator to run after inspecting drift.

    The script copies mismatched/missing files from source to runtime and
    regenerates the kernel baseline so the bridge does not alert on startup.
    """
    if output_path is None:
        output_path = Path("/tmp/deploy_drift_sync.sh")

    # F3 of #1501: resolve at call-time, not import-time. Older code path
    # used the module-level ``RUNTIME_ROOT`` constant which was frozen at
    # the first import.
    runtime_root_now = _resolve_runtime_root()
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Auto-generated drift sync script — review before running",
        "# Generated: $(date)",
        "",
        f'SOURCE="{SOURCE_ROOT}"',
        f'RUNTIME="{runtime_root_now}"',
        "",
    ]

    for path in sorted(report.hash_mismatch):
        # Ensure destination directory exists before copying
        dest_dir = str(Path(path).parent)
        lines.append(f'mkdir -p "$RUNTIME/{dest_dir}"')
        lines.append(f'cp "$SOURCE/{path}" "$RUNTIME/{path}"')

    for path in sorted(report.missing_in_runtime):
        dest_dir = str(Path(path).parent)
        lines.append(f'mkdir -p "$RUNTIME/{dest_dir}"')
        lines.append(f'cp "$SOURCE/{path}" "$RUNTIME/{path}"')

    lines += [
        "",
        "# Chown everything to bumba-agent",
        'chown -R bumba-agent:staff "$RUNTIME"',
        "",
        "# Clear pycache so stale bytecode does not linger",
        'find "$RUNTIME" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true',
        "",
        "# Regenerate kernel baseline after sync",
        'python3 "$SOURCE/scripts/regenerate_kernel_baseline.py" || { echo "ERROR: baseline regen failed"; exit 1; }',
        'echo "Drift sync complete."',
    ]

    output_path.write_text("\n".join(lines) + "\n")
    output_path.chmod(0o755)
    log.info("drift: sync script written to %s", output_path)
    return output_path
