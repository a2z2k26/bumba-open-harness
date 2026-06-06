"""Tests for scripts/check_registry_completeness.py (Sprint E2.6).

Covers:
  - test_script_compiles: py_compile gate
  - test_known_good_bridge_passes: existing bridge passes when registry exists
  - test_synthetic_missing_event_fails: new fake event_type -> exit 1
  - test_extract_string_helper: string extraction from ast-grep metavar dict
  - test_suggested_stub_content: stub text for each kind
  - test_location_helper: location formatting
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_registry_completeness.py"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers to import the script as a module under test
# ──────────────────────────────────────────────────────────────────────────────


def _import_script():
    """Import check_registry_completeness.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("check_registry_completeness", SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ──────────────────────────────────────────────────────────────────────────────
# Test: script compiles cleanly
# ──────────────────────────────────────────────────────────────────────────────


def test_script_compiles():
    """py_compile gate — script must have no syntax errors."""
    import py_compile

    py_compile.compile(str(SCRIPT), doraise=True)


# ──────────────────────────────────────────────────────────────────────────────
# Test: _extract_string helper
# ──────────────────────────────────────────────────────────────────────────────


def test_extract_string_double_quotes():
    mod = _import_script()
    assert mod._extract_string({"text": '"session.started"'}) == "session.started"


def test_extract_string_single_quotes():
    mod = _import_script()
    assert mod._extract_string({"text": "'session.started'"}) == "session.started"


def test_extract_string_constant_returns_empty():
    """Constants (non-quoted) must return '' — gate limitation documented in README."""
    mod = _import_script()
    assert mod._extract_string({"text": "DEPARTMENT_TASK_STARTED"}) == ""


def test_extract_string_empty_dict():
    mod = _import_script()
    assert mod._extract_string({}) == ""


# ──────────────────────────────────────────────────────────────────────────────
# Test: _suggested_stub helper
# ──────────────────────────────────────────────────────────────────────────────


def test_suggested_stub_event():
    mod = _import_script()
    stub = mod._suggested_stub("event", "session.resumed", "bridge/x.py:10:0")
    assert "event_type: 'session.resumed'" in stub
    assert "events/<category>" in stub


def test_suggested_stub_action():
    mod = _import_script()
    stub = mod._suggested_stub("action", "GET /api/sessions", "bridge/x.py:10:0")
    assert "method: GET" in stub
    assert "path: '/api/sessions'" in stub


def test_suggested_stub_metric():
    mod = _import_script()
    stub = mod._suggested_stub("metric", "messages.processed", "bridge/x.py:10:0")
    assert "metric_name: 'messages.processed'" in stub
    assert "metrics/<category>" in stub


# ──────────────────────────────────────────────────────────────────────────────
# Test: _location helper
# ──────────────────────────────────────────────────────────────────────────────


def test_location_formats_file_line_col():
    mod = _import_script()
    match = {
        "file": "agent/bridge/app.py",
        "range": {"start": {"line": 42, "column": 8}},
    }
    assert mod._location(match) == "agent/bridge/app.py:42:8"


def test_location_unknown_when_missing():
    mod = _import_script()
    loc = mod._location({})
    assert "<unknown>" in loc


# ──────────────────────────────────────────────────────────────────────────────
# Test: main() — synthetic missing event → exit 1
# ──────────────────────────────────────────────────────────────────────────────


def _make_fake_match(rule_id: str, event_type: str, file: str = "agent/bridge/fake.py") -> dict:
    """Construct a minimal ast-grep match dict for testing."""
    return {
        "ruleId": rule_id,
        "file": file,
        "range": {"start": {"line": 1, "column": 0}},
        "metaVariables": {
            "single": {
                "EVENT_TYPE": {"text": f'"{event_type}"'},
            }
        },
    }


def _make_fake_registry_index(event_types: list[str], metric_names: list[str] = None, actions=None):
    """Build a minimal RegistryIndex-like mock."""
    from dataclasses import dataclass, field

    @dataclass
    class _FakeIndex:
        _events: list[str] = field(default_factory=list)
        _metrics: list[str] = field(default_factory=list)
        _actions: list[tuple] = field(default_factory=list)

        def find_event_by_type(self, event_type: str):
            return event_type if event_type in self._events else None

        def find_metric_by_name(self, name: str):
            return name if name in self._metrics else None

        def find_action_by_path(self, method: str, path: str):
            return (method, path) if (method, path) in self._actions else None

    idx = _FakeIndex(
        _events=event_types,
        _metrics=metric_names or [],
        _actions=actions or [],
    )
    return idx


def test_synthetic_missing_event_fails(capsys):
    """A fake event_type not in registry should produce exit code 1."""
    mod = _import_script()

    fake_match = _make_fake_match("event-bus-publish-via-bus", "ci_smoke.fake")
    fake_index = _make_fake_registry_index(event_types=[])  # empty registry

    with (
        patch.object(mod, "run_ast_grep", return_value=[fake_match]),
        patch.object(mod, "load_registry_index", return_value=fake_index),
        patch.object(mod, "REGISTRY_DIR", REPO_ROOT / "agent" / "config" / "registry"),
    ):
        # Make REGISTRY_DIR appear to exist and be non-empty for this test
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.iterdir.return_value = iter([MagicMock()])
        with patch.object(mod, "REGISTRY_DIR", mock_path):
            result = mod.main()

    assert result == 1
    captured = capsys.readouterr()
    assert "ci_smoke.fake" in captured.out
    assert "missing registry" in captured.out


def test_known_good_no_matches_passes(capsys):
    """When ast-grep finds no call sites, gate exits 0."""
    mod = _import_script()

    fake_index = _make_fake_registry_index(event_types=[])

    with (
        patch.object(mod, "run_ast_grep", return_value=[]),
        patch.object(mod, "load_registry_index", return_value=fake_index),
    ):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.iterdir.return_value = iter([MagicMock()])
        with patch.object(mod, "REGISTRY_DIR", mock_path):
            result = mod.main()

    assert result == 0


def test_registry_empty_dir_skips(capsys):
    """When REGISTRY_DIR does not exist, gate skips gracefully (exit 0)."""
    mod = _import_script()

    mock_path = MagicMock()
    mock_path.exists.return_value = False

    with patch.object(mod, "REGISTRY_DIR", mock_path):
        result = mod.main()

    assert result == 0
    captured = capsys.readouterr()
    assert "Skipping" in captured.out or "does not exist" in captured.out


def test_all_events_found_passes(capsys):
    """When all call sites are in the registry, gate exits 0."""
    mod = _import_script()

    fake_match = _make_fake_match("event-bus-publish-via-bus", "message.received")
    fake_index = _make_fake_registry_index(event_types=["message.received"])

    with (
        patch.object(mod, "run_ast_grep", return_value=[fake_match]),
        patch.object(mod, "load_registry_index", return_value=fake_index),
    ):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.iterdir.return_value = iter([MagicMock()])
        with patch.object(mod, "REGISTRY_DIR", mock_path):
            result = mod.main()

    assert result == 0


def test_metric_missing_fails(capsys):
    """A metric call site not in registry should produce exit code 1."""
    mod = _import_script()

    fake_match = {
        "ruleId": "metric-record",
        "file": "agent/bridge/metrics.py",
        "range": {"start": {"line": 5, "column": 4}},
        "metaVariables": {
            "single": {
                "NAME": {"text": '"messages.sent"'},
            }
        },
    }
    fake_index = _make_fake_registry_index(event_types=[], metric_names=[])

    with (
        patch.object(mod, "run_ast_grep", return_value=[fake_match]),
        patch.object(mod, "load_registry_index", return_value=fake_index),
    ):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.iterdir.return_value = iter([MagicMock()])
        with patch.object(mod, "REGISTRY_DIR", mock_path):
            result = mod.main()

    assert result == 1
    captured = capsys.readouterr()
    assert "messages.sent" in captured.out


def test_action_missing_fails(capsys):
    """A route registration not in registry should produce exit code 1."""
    mod = _import_script()

    fake_match = {
        "ruleId": "route-registration-get",
        "file": "agent/bridge/api_server.py",
        "range": {"start": {"line": 99, "column": 8}},
        "metaVariables": {
            "single": {
                "PATH": {"text": '"/api/test/fake"'},
                "HANDLER": {"text": "handle_fake"},
                "APP": {"text": "app"},
            }
        },
    }
    fake_index = _make_fake_registry_index(event_types=[], metric_names=[], actions=[])

    with (
        patch.object(mod, "run_ast_grep", return_value=[fake_match]),
        patch.object(mod, "load_registry_index", return_value=fake_index),
    ):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.iterdir.return_value = iter([MagicMock()])
        with patch.object(mod, "REGISTRY_DIR", mock_path):
            result = mod.main()

    assert result == 1
    captured = capsys.readouterr()
    assert "/api/test/fake" in captured.out
