"""Unit tests for the Sprint 01.02 lint guard.

Two contracts:
  1. The lint passes on agent/bridge/app.py (post-migration state)
  2. The lint fails on a synthetic file containing a scattered setter call
     outside _wire — this is the negative-test fixture required by the AC.
"""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path



REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LINT_SCRIPT = REPO_ROOT / "agent" / "scripts" / "lint_no_scattered_setters.py"
APP_PY = REPO_ROOT / "agent" / "bridge" / "app.py"
APP_INIT_PY = REPO_ROOT / "agent" / "bridge" / "app_init.py"


def _load_lint_module():
    spec = importlib.util.spec_from_file_location("lint_no_scattered_setters", LINT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lint_passes_on_migrated_app(tmp_path: Path) -> None:
    """Post-migration agent/bridge/app.py must have zero scattered setter calls."""
    lint = _load_lint_module()
    violations = lint.find_violations(APP_PY)
    assert violations == [], (
        f"agent/bridge/app.py has {len(violations)} scattered setter call(s) "
        f"outside _wire(). The Sprint 01.02 migration is incomplete: {violations}"
    )


def test_lint_passes_on_allowed_app_init_exceptions(tmp_path: Path) -> None:
    """Construction-time exceptions in app_init.py must be explicit."""
    lint = _load_lint_module()
    violations = lint.find_violations(APP_INIT_PY)
    assert violations == [], (
        f"agent/bridge/app_init.py has {len(violations)} unclassified "
        f"manifest-eligible setter call(s): {violations}"
    )


def test_lint_fails_on_violation_outside_wire(tmp_path: Path) -> None:
    """The lint MUST flag a self._commands.set_*(...) call outside _wire."""
    lint = _load_lint_module()
    fake = tmp_path / "fake_app.py"
    fake.write_text(textwrap.dedent("""
        class BridgeApp:
            def _wire(self):
                self._commands.set_session_hooks(None)  # OK — inside _wire

            def _initialize(self):
                self._commands.set_security(None)  # VIOLATION

            def some_other_method(self):
                self._commands.set_dispatcher(None)  # VIOLATION
    """))
    violations = lint.find_violations(fake)
    assert len(violations) == 2
    setter_names = sorted(snip for _, snip in violations)
    assert any("set_security" in s for s in setter_names)
    assert any("set_dispatcher" in s for s in setter_names)


def test_lint_fails_on_manifest_target_setter_outside_wire(tmp_path: Path) -> None:
    """The lint also guards non-CommandHandler manifest target setters."""
    lint = _load_lint_module()
    fake = tmp_path / "fake_app.py"
    fake.write_text(textwrap.dedent("""
        class BridgeApp:
            def _wire(self):
                self._dispatcher.set_recursive_decomposer(None)  # OK

            def _initialize(self):
                self._dispatcher.set_recursive_decomposer(None)  # VIOLATION
                self._memory.set_dual_write_pipeline(None)  # VIOLATION
    """))
    violations = lint.find_violations(fake)
    assert len(violations) == 2
    setter_names = sorted(snip for _, snip in violations)
    assert any("set_recursive_decomposer" in s for s in setter_names)
    assert any("set_dual_write_pipeline" in s for s in setter_names)


def test_manifest_setter_allowlist_entries_have_rationales() -> None:
    lint = _load_lint_module()
    assert lint.ALLOWED_SCATTERED_SETTERS
    for entry in lint.ALLOWED_SCATTERED_SETTERS:
        assert entry.rationale.strip(), entry


def test_lint_passes_when_all_setters_inside_wire(tmp_path: Path) -> None:
    lint = _load_lint_module()
    fake = tmp_path / "clean_app.py"
    fake.write_text(textwrap.dedent("""
        class BridgeApp:
            def _wire(self):
                self._commands.set_session_hooks(None)
                self._commands.set_security(None)
                self._commands.set_dispatcher(None)
    """))
    assert lint.find_violations(fake) == []


def test_lint_ignores_non_setter_calls_on_commands(tmp_path: Path) -> None:
    """Calls like self._commands.dispatch(...) or self._commands.foo() must
    not be flagged — the lint targets ONLY set_*-prefixed methods."""
    lint = _load_lint_module()
    fake = tmp_path / "non_setter.py"
    fake.write_text(textwrap.dedent("""
        class BridgeApp:
            def handle(self):
                self._commands.dispatch("ping")
                self._commands.list_commands()
                result = self._commands.run("foo")
    """))
    assert lint.find_violations(fake) == []


def test_lint_ignores_other_objects(tmp_path: Path) -> None:
    """Calls like self._other.set_x(...) must not match — only self._commands."""
    lint = _load_lint_module()
    fake = tmp_path / "other_obj.py"
    fake.write_text(textwrap.dedent("""
        class BridgeApp:
            def _initialize(self):
                self._claude.set_runner(None)
                self._discord.set_voice_manager(None)
                obj.set_foo(None)
    """))
    assert lint.find_violations(fake) == []
