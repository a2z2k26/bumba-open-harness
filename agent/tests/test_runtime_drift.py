"""Tests for runtime_drift.py source↔runtime comparison.

History: bridge.runtime_drift first shipped at the (shadow) /bridge/ root
in PR #634, was deleted in Plan 00 Sprint 00.05's shadow-tree sweep
(commit 5584583), and was restored at the canonical agent/bridge/
location in PR #832. These tests are kept as the regression net for the
restoration.
"""
from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# DriftReport unit tests
# ---------------------------------------------------------------------------


def test_drift_report_is_clean_when_empty():
    """A default DriftReport with no fields set is clean."""
    from bridge.runtime_drift import DriftReport

    report = DriftReport()
    assert report.is_clean is True
    assert report.summary() == "source \u2194 runtime: clean"


def test_drift_report_is_dirty_on_hash_mismatch():
    """hash_mismatch populated → is_clean is False."""
    from bridge.runtime_drift import DriftReport

    report = DriftReport(hash_mismatch=("bridge/app.py",))
    assert report.is_clean is False
    assert "DRIFT DETECTED" in report.summary()
    assert "1 hash mismatches" in report.summary()


def test_drift_report_is_dirty_on_missing_in_runtime():
    """missing_in_runtime populated → is_clean is False."""
    from bridge.runtime_drift import DriftReport

    report = DriftReport(missing_in_runtime=("bridge/new_module.py",))
    assert report.is_clean is False
    assert "1 missing in runtime" in report.summary()


def test_drift_report_is_dirty_on_missing_in_source():
    """missing_in_source populated → is_clean is False."""
    from bridge.runtime_drift import DriftReport

    report = DriftReport(missing_in_source=("bridge/orphan.py",))
    assert report.is_clean is False
    assert "1 missing in source" in report.summary()


def test_drift_report_error_summary():
    """error field returns error summary string."""
    from bridge.runtime_drift import DriftReport

    report = DriftReport(error="permission denied")
    assert report.is_clean is False
    assert "permission denied" in report.summary()
    assert "drift check error" in report.summary()


def test_drift_report_summary_combines_all_fields():
    """Summary includes counts for all three drift types."""
    from bridge.runtime_drift import DriftReport

    report = DriftReport(
        missing_in_runtime=("a.py", "b.py"),
        missing_in_source=("c.py",),
        hash_mismatch=("d.py", "e.py", "f.py"),
    )
    summary = report.summary()
    assert "2 missing in runtime" in summary
    assert "1 missing in source" in summary
    assert "3 hash mismatches" in summary


# ---------------------------------------------------------------------------
# _sha256 / _hash_tree
# ---------------------------------------------------------------------------


def test_sha256_consistent(tmp_path):
    """Same file content → same SHA-256 on two calls."""
    from bridge.runtime_drift import _sha256

    f = tmp_path / "test.py"
    f.write_bytes(b"hello world")
    h1 = _sha256(f)
    h2 = _sha256(f)
    assert h1 == h2
    assert len(h1) == 64  # hex SHA-256


def test_sha256_differs_for_different_content(tmp_path):
    """Different file contents → different SHA-256."""
    from bridge.runtime_drift import _sha256

    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_bytes(b"original")
    b.write_bytes(b"modified")
    assert _sha256(a) != _sha256(b)


def test_hash_tree_returns_relative_paths(tmp_path):
    """_hash_tree keys are relative to the root, not absolute."""
    from bridge.runtime_drift import _hash_tree

    # Create a file that matches the 'bridge/**/*.py' pattern
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "app.py").write_text("# app")

    result = _hash_tree(tmp_path)
    for key in result:
        assert not Path(key).is_absolute(), f"Expected relative path, got: {key}"


def test_hash_tree_empty_when_no_matches(tmp_path):
    """_hash_tree returns empty dict when no DRIFT_PATTERNS files exist."""
    from bridge.runtime_drift import _hash_tree

    result = _hash_tree(tmp_path)
    assert result == {}


def test_hash_tree_detects_content_difference(tmp_path):
    """Two trees with different content for the same file produce different hashes."""
    from bridge.runtime_drift import _hash_tree

    src = tmp_path / "source"
    run = tmp_path / "runtime"
    for root in (src, run):
        (root / "bridge").mkdir(parents=True)

    (src / "bridge" / "app.py").write_text("original content")
    (run / "bridge" / "app.py").write_text("modified content")

    src_hashes = _hash_tree(src)
    run_hashes = _hash_tree(run)

    assert src_hashes != run_hashes


# ---------------------------------------------------------------------------
# compute_drift_report
# ---------------------------------------------------------------------------


def test_compute_drift_report_clean_on_identical_trees(tmp_path):
    """Identical source and runtime trees produce a clean report."""
    from bridge.runtime_drift import compute_drift_report

    src = tmp_path / "source"
    run = tmp_path / "runtime"
    for root in (src, run):
        (root / "bridge").mkdir(parents=True)
        (root / "bridge" / "module.py").write_text("# same content")

    report = compute_drift_report(source_root=src, runtime_root=run)
    assert report.error is None
    assert report.is_clean is True


def test_compute_drift_report_detects_hash_mismatch(tmp_path):
    """Modified file in runtime shows up as hash_mismatch."""
    from bridge.runtime_drift import compute_drift_report

    src = tmp_path / "source"
    run = tmp_path / "runtime"
    for root in (src, run):
        (root / "bridge").mkdir(parents=True)

    (src / "bridge" / "module.py").write_text("original")
    (run / "bridge" / "module.py").write_text("modified")

    report = compute_drift_report(source_root=src, runtime_root=run)
    assert report.error is None
    assert "bridge/module.py" in report.hash_mismatch
    assert report.is_clean is False


def test_compute_drift_report_detects_missing_in_runtime(tmp_path):
    """File in source but not runtime shows up as missing_in_runtime."""
    from bridge.runtime_drift import compute_drift_report

    src = tmp_path / "source"
    run = tmp_path / "runtime"
    (src / "bridge").mkdir(parents=True)
    (run / "bridge").mkdir(parents=True)

    (src / "bridge" / "new_module.py").write_text("# new")
    # NOT created in run/bridge/

    report = compute_drift_report(source_root=src, runtime_root=run)
    assert report.error is None
    assert "bridge/new_module.py" in report.missing_in_runtime
    assert report.is_clean is False


def test_compute_drift_report_detects_missing_in_source(tmp_path):
    """File in runtime but not source shows up as missing_in_source."""
    from bridge.runtime_drift import compute_drift_report

    src = tmp_path / "source"
    run = tmp_path / "runtime"
    (src / "bridge").mkdir(parents=True)
    (run / "bridge").mkdir(parents=True)

    # NOT created in src/bridge/
    (run / "bridge" / "orphan.py").write_text("# orphan")

    report = compute_drift_report(source_root=src, runtime_root=run)
    assert report.error is None
    assert "bridge/orphan.py" in report.missing_in_source
    assert report.is_clean is False


def test_compute_drift_report_returns_error_on_exception():
    """When source root is completely invalid, report contains error string."""
    from bridge.runtime_drift import compute_drift_report

    # Provide a nonexistent path — glob just returns nothing, so result is clean.
    # To force an error we monkeypatch _hash_tree.
    import bridge.runtime_drift as drift_mod

    original = drift_mod._hash_tree

    def explode(root: Path) -> dict:
        raise RuntimeError("simulated failure")

    drift_mod._hash_tree = explode
    try:
        report = compute_drift_report()
        assert report.error is not None
        assert "simulated failure" in report.error
    finally:
        drift_mod._hash_tree = original


# ---------------------------------------------------------------------------
# generate_sync_script
# ---------------------------------------------------------------------------


def test_generate_sync_script_creates_executable(tmp_path):
    """generate_sync_script writes an executable bash script."""
    from bridge.runtime_drift import DriftReport, generate_sync_script

    report = DriftReport(
        hash_mismatch=("bridge/app.py",),
        missing_in_runtime=("bridge/new_module.py",),
    )
    script_path = tmp_path / "sync.sh"
    result = generate_sync_script(report, output_path=script_path)

    assert result.exists()
    assert result.stat().st_mode & 0o111  # executable bit set


def test_generate_sync_script_contains_changed_files(tmp_path):
    """Script content references all drifted files."""
    from bridge.runtime_drift import DriftReport, generate_sync_script

    report = DriftReport(
        hash_mismatch=("bridge/app.py",),
        missing_in_runtime=("bridge/new_module.py",),
    )
    script_path = tmp_path / "sync.sh"
    generate_sync_script(report, output_path=script_path)
    content = script_path.read_text()

    assert "bridge/app.py" in content
    assert "bridge/new_module.py" in content


def test_generate_sync_script_includes_baseline_regen(tmp_path):
    """Script includes kernel baseline regeneration step."""
    from bridge.runtime_drift import DriftReport, generate_sync_script

    report = DriftReport(hash_mismatch=("bridge/app.py",))
    script_path = tmp_path / "sync.sh"
    generate_sync_script(report, output_path=script_path)
    content = script_path.read_text()

    assert "regenerate_kernel_baseline" in content


def test_generate_sync_script_default_path(tmp_path):
    """Default output path is /tmp/deploy_drift_sync.sh (or overridden for test)."""
    from bridge.runtime_drift import DriftReport, generate_sync_script

    report = DriftReport()
    # Override output to avoid writing to /tmp during tests
    result = generate_sync_script(report, output_path=tmp_path / "out.sh")
    assert result.exists()


def test_generate_sync_script_has_set_e(tmp_path):
    """Script starts with set -euo pipefail for safe execution."""
    from bridge.runtime_drift import DriftReport, generate_sync_script

    report = DriftReport(hash_mismatch=("bridge/app.py",))
    script_path = tmp_path / "sync.sh"
    generate_sync_script(report, output_path=script_path)
    content = script_path.read_text()

    assert "set -euo pipefail" in content


# ---------------------------------------------------------------------------
# F3 of #1501 — lazy RUNTIME_ROOT resolution via PEP 562
# ---------------------------------------------------------------------------


def _make_fake_agent_tree(root: Path) -> None:
    """Build the minimum tree shape that ``bridge.paths.agent_root`` validates."""
    (root / "bridge").mkdir(parents=True, exist_ok=True)
    (root / "bridge" / "__init__.py").write_text("")


def test_runtime_root_re_resolves_between_reads(tmp_path, monkeypatch):
    """F3 of #1501 — back-to-back ``RUNTIME_ROOT`` reads pick up an env-var change.

    Pre-fix the constant was bound at import time and froze for the lifetime
    of the process. Post-fix the PEP 562 ``__getattr__`` re-resolves on each
    attribute read so a test that mutates ``BUMBA_AGENT_ROOT`` between reads
    sees the new value.
    """
    import bridge.runtime_drift as drift

    first = tmp_path / "first"
    second = tmp_path / "second"
    _make_fake_agent_tree(first)
    _make_fake_agent_tree(second)

    monkeypatch.setenv("BUMBA_AGENT_ROOT", str(first))
    value_a = drift.RUNTIME_ROOT
    monkeypatch.setenv("BUMBA_AGENT_ROOT", str(second))
    value_b = drift.RUNTIME_ROOT

    assert value_a == first
    assert value_b == second
    assert value_a != value_b


def test_runtime_root_unknown_attribute_raises():
    """PEP 562 only catches ``RUNTIME_ROOT`` — other attribute names error."""
    import bridge.runtime_drift as drift

    try:
        drift.NOPE  # noqa: B018
    except AttributeError as exc:
        assert "NOPE" in str(exc)
    else:  # pragma: no cover — defensive
        raise AssertionError("Expected AttributeError for unknown attribute")


def test_compute_drift_report_default_runtime_root_re_resolves(tmp_path, monkeypatch):
    """F3 — calling ``compute_drift_report()`` without args resolves runtime at call time."""
    from bridge.runtime_drift import compute_drift_report

    src = tmp_path / "src"
    rt = tmp_path / "rt"
    for root in (src, rt):
        (root / "bridge").mkdir(parents=True)
        (root / "bridge" / "__init__.py").write_text("")
        (root / "bridge" / "module.py").write_text("# same")

    # Point the lazy resolver at our temp runtime tree. ``compute_drift_report``
    # should see this value because its default param is resolved at call time.
    monkeypatch.setenv("BUMBA_AGENT_ROOT", str(rt))

    report = compute_drift_report(source_root=src)  # runtime_root defaults to None → re-resolves
    assert report.error is None
    assert report.is_clean is True
