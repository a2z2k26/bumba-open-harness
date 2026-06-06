#!/usr/bin/env python3
"""Wiring-manifest setter guard.

Fails CI if a manifest-managed ``set_*`` call is made outside the ``_wire()``
method of ``BridgeApp`` without an explicit exception.

The migration to a declarative wiring manifest only pays off if it stays
declarative. Any new scattered setter call regresses the audit posture
("what got wired" hidden across 200 lines again). This lint runs before the
test suite so the regression surfaces at PR time, not in production.

Exit codes:
    0 — clean (no scattered setter calls outside _wire)
    1 — one or more violations found

Usage:
    python3 agent/scripts/lint_no_scattered_setters.py [<file> ...]

Default targets: agent/bridge/app.py and agent/bridge/app_init.py.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TARGET = Path(__file__).parent.parent / "bridge" / "app.py"
DEFAULT_TARGETS = (
    DEFAULT_TARGET,
    Path(__file__).parent.parent / "bridge" / "app_init.py",
)
ALLOWED_METHOD = "_wire"


@dataclass(frozen=True)
class AllowedScatteredSetter:
    """A classified construction-time setter exception.

    These entries are intentionally narrow and live in one place so future
    audits can distinguish "known wiring shape" from "new scattered setter".
    """

    path_suffix: str
    target_expr: str
    setter_name: str
    enclosing_function: str
    rationale: str


MANIFEST_SETTER_TARGETS: frozenset[tuple[str, str | None]] = frozenset(
    {
        # Sprint 01.02: all CommandHandler setters belong in BridgeApp._wire.
        ("self._commands", None),
        # Post-#1614 manifest-managed target surfaces from #2519.
        ("self", "set_daily_log"),
        ("self", "set_memory_file"),
        ("self", "set_skill_allocator"),
        ("self._discord", "set_stream_coalescer"),
        ("self._memory", "set_hybrid_search"),
        ("self._memory", "set_dual_write_pipeline"),
        ("event_bus_target", "set_remote_event_bridge"),
        ("vapi_target", "set_tool_handler"),
        ("self._vapi", "set_tool_handler"),
        ("self._dispatcher", "set_recursive_decomposer"),
        # Construction-time proactive scheduler wires are not manifest entries
        # themselves, but #2519 tracks them as setter-discipline surfaces.
        ("self._proactive_scheduler", "set_dispatch"),
        ("self._proactive_scheduler", "set_inbox_pending_refresh"),
    }
)


ALLOWED_SCATTERED_SETTERS: tuple[AllowedScatteredSetter, ...] = (
    AllowedScatteredSetter(
        path_suffix="agent/bridge/app_init.py",
        target_expr="self._vapi",
        setter_name="set_tool_handler",
        enclosing_function="run",
        rationale=(
            "VAPIClient is constructed only when voice is enabled; BridgeApp._wire "
            "adds a manifest mirror when the target exists."
        ),
    ),
    AllowedScatteredSetter(
        path_suffix="agent/bridge/app_init.py",
        target_expr="self._dispatcher",
        setter_name="set_recursive_decomposer",
        enclosing_function="run",
        rationale=(
            "RecursiveDecomposer is constructed under the dispatcher feature gate; "
            "BridgeApp._wire mirrors the dependency in the manifest."
        ),
    ),
    AllowedScatteredSetter(
        path_suffix="agent/bridge/app_init.py",
        target_expr="self._proactive_scheduler",
        setter_name="set_dispatch",
        enclosing_function="run",
        rationale=(
            "AutonomousPlanDrafter dispatch is an optional construction-time "
            "callback for the ProactiveScheduler."
        ),
    ),
    AllowedScatteredSetter(
        path_suffix="agent/bridge/app_init.py",
        target_expr="self._proactive_scheduler",
        setter_name="set_inbox_pending_refresh",
        enclosing_function="run",
        rationale=(
            "OperatorInbox is async while the scheduler skip policy reads a "
            "sync provider; this construction-time setter bridges the two."
        ),
    ),
    AllowedScatteredSetter(
        path_suffix="agent/bridge/app_init.py",
        target_expr="self",
        setter_name="set_memory_file",
        enclosing_function="run",
        rationale=(
            "#2599: MemoryFile is constructed against config.data_dir, which is "
            "only resolved inside run(); the construction-time setter activates "
            "the previously-dormant MEMORY.md injection wire. BridgeApp._wire "
            "mirrors the dependency in the WIRING_MANIFEST."
        ),
    ),
)


def find_violations(source_path: Path) -> list[tuple[int, str]]:
    """Walk the AST of ``source_path`` and return manifest setter violations.

    Returns a list of ``(line, code_snippet)`` tuples — empty means clean.
    """
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    violations: list[tuple[int, str]] = []

    # Track the function-def stack as we walk so we know whether a Call node
    # lives inside _wire() or outside it.
    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.func_stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.func_stack.append(node.name)
            self.generic_visit(node)
            self.func_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.func_stack.append(node.name)
            self.generic_visit(node)
            self.func_stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            if self._is_scattered_setter(node):
                if ALLOWED_METHOD not in self.func_stack:
                    target_expr, setter_name = self._setter_call_shape(node)
                    if not self._is_allowed_exception(target_expr, setter_name):
                        snippet = ast.unparse(node) if hasattr(ast, "unparse") else "<call>"
                        violations.append((node.lineno, snippet))
            self.generic_visit(node)

        def _is_allowed_exception(
            self, target_expr: str | None, setter_name: str | None
        ) -> bool:
            if target_expr is None or setter_name is None:
                return False
            source = source_path.as_posix()
            for entry in ALLOWED_SCATTERED_SETTERS:
                if not source.endswith(entry.path_suffix):
                    continue
                if entry.target_expr != target_expr:
                    continue
                if entry.setter_name != setter_name:
                    continue
                if entry.enclosing_function not in self.func_stack:
                    continue
                return True
            return False

        def _is_scattered_setter(self, node: ast.Call) -> bool:
            target_expr, setter_name = self._setter_call_shape(node)
            if target_expr is None or setter_name is None:
                return False
            return (
                (target_expr, None) in MANIFEST_SETTER_TARGETS
                or (target_expr, setter_name) in MANIFEST_SETTER_TARGETS
            )

        @staticmethod
        def _setter_call_shape(node: ast.Call) -> tuple[str | None, str | None]:
            func = node.func
            if not isinstance(func, ast.Attribute):
                return None, None
            if not func.attr.startswith("set_"):
                return None, None
            target_expr = ast.unparse(func.value) if hasattr(ast, "unparse") else None
            return target_expr, func.attr

    Visitor().visit(tree)
    return violations


def find_all_violations(source_paths: list[Path]) -> dict[Path, list[tuple[int, str]]]:
    """Return violations for every requested path."""
    return {path: find_violations(path) for path in source_paths}


def main(argv: list[str]) -> int:
    targets = [Path(arg) for arg in argv[1:]] if len(argv) > 1 else list(DEFAULT_TARGETS)
    for target in targets:
        if not target.exists():
            print(
                f"lint_no_scattered_setters: target not found: {target}",
                file=sys.stderr,
            )
            return 1

    violations_by_path = find_all_violations(targets)
    total = sum(len(v) for v in violations_by_path.values())
    if total == 0:
        joined = ", ".join(str(target) for target in targets)
        print(
            "lint_no_scattered_setters: clean — no unclassified "
            f"manifest setter calls in {joined}"
        )
        return 0

    print(
        f"lint_no_scattered_setters: FAIL — {total} unclassified manifest "
        f"setter call(s) found outside {ALLOWED_METHOD}():",
        file=sys.stderr,
    )
    for target, violations in violations_by_path.items():
        for lineno, snippet in violations:
            print(f"  {target}:{lineno}: {snippet}", file=sys.stderr)
    print(
        "\n  Manifest-managed setters must live inside the WIRING_MANIFEST in "
        f"BridgeApp.{ALLOWED_METHOD}(), or be added to "
        "ALLOWED_SCATTERED_SETTERS with a rationale.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
