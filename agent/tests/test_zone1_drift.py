"""Tests for the Zone 1 drift detector (Sprint 2.07 / #2142).

Heuristic-focused: each scan pass (dead_ref / stale_count / outdated_stamp)
gets a positive + negative case. Plus the safety-rule invariants:
  - Service NEVER opens a PR itself (only renders pr_body text)
  - Default-disabled (enabled=False) returns 'skipped'
  - Empty findings record skipped, not success
  - Render produces NO auto-apply instructions
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from bridge.services.zone1_drift import (
    DriftFinding,
    OUTDATED_STAMP_DAYS,
    ZONE1_FILES,
    Zone1DriftService,
    render_pr_body,
    scan_file,
)


def _make_zone1_layout(tmp_path: Path, soul_content: str | None = None) -> Path:
    """Construct a minimal repo-root with the Zone 1 file set populated."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "config" / "zone1").mkdir(parents=True)
    for rel in ZONE1_FILES:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if soul_content is not None and rel.endswith("SOUL.md"):
            f.write_text(soul_content)
        else:
            f.write_text(f"# {Path(rel).stem}\n\nMinimal content.\n")
    return tmp_path


class TestScanFileDeadRef:
    def test_cited_path_that_exists_does_not_flag(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        (repo / "agent" / "real-file.md").write_text("hi")
        (repo / "agent" / "SOUL.md").write_text(
            "Reference to a real file: `agent/real-file.md`\n"
        )
        findings = scan_file(repo, "agent/SOUL.md")
        dead_refs = [f for f in findings if f.kind == "dead_ref"]
        assert dead_refs == []

    def test_cited_path_that_does_not_exist_flags_dead_ref(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        (repo / "agent" / "SOUL.md").write_text(
            "Reference to a missing file: `agent/missing-file.md`\n"
        )
        findings = scan_file(repo, "agent/SOUL.md")
        dead_refs = [f for f in findings if f.kind == "dead_ref"]
        assert len(dead_refs) == 1
        assert "agent/missing-file.md" in dead_refs[0].description
        assert dead_refs[0].line == 1

    def test_missing_zone1_file_itself_flags_dead_ref(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        # Remove SOUL.md to simulate a Zone 1 file that's been deleted
        (repo / "agent" / "SOUL.md").unlink()
        findings = scan_file(repo, "agent/SOUL.md")
        assert len(findings) == 1
        assert findings[0].kind == "dead_ref"
        assert findings[0].line is None


class TestScanFileStaleCount:
    def test_count_matching_live_count_within_10pct_does_not_flag(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        # Make a workflows dir with exactly 10 yamls
        wf_dir = repo / "agent" / "config" / "workflows"
        wf_dir.mkdir(parents=True)
        for i in range(10):
            (wf_dir / f"wf-{i}.yaml").write_text("name: x")
        (repo / "agent" / "SOUL.md").write_text("Today we have 10 workflows registered.")
        findings = scan_file(repo, "agent/SOUL.md")
        stale = [f for f in findings if f.kind == "stale_count"]
        assert stale == []

    def test_count_diverging_by_more_than_10pct_flags_stale(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        wf_dir = repo / "agent" / "config" / "workflows"
        wf_dir.mkdir(parents=True)
        for i in range(20):
            (wf_dir / f"wf-{i}.yaml").write_text("name: x")
        # Doc claims 5 workflows; live is 20 → 75% drift
        (repo / "agent" / "SOUL.md").write_text(
            "Today we have 5 workflows registered.\n"
        )
        findings = scan_file(repo, "agent/SOUL.md")
        stale = [f for f in findings if f.kind == "stale_count"]
        assert len(stale) == 1
        assert "5" in stale[0].description
        assert "20" in stale[0].description

    def test_unmappable_noun_silently_skips(self, tmp_path):
        """Unknown noun (no live-count mapping) → no finding, not error."""
        repo = _make_zone1_layout(tmp_path)
        (repo / "agent" / "SOUL.md").write_text(
            "Today we have 47 widgets in the system.\n"
        )
        findings = scan_file(repo, "agent/SOUL.md")
        stale = [f for f in findings if f.kind == "stale_count"]
        assert stale == []


class TestScanFileOutdatedStamp:
    def test_recent_stamp_does_not_flag(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (repo / "agent" / "SOUL.md").write_text(
            f"Counts verified at HEAD abc1234 on {today}.\n"
        )
        findings = scan_file(repo, "agent/SOUL.md")
        stamps = [f for f in findings if f.kind == "outdated_stamp"]
        assert stamps == []

    def test_old_stamp_flags_outdated(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        old = (datetime.now(timezone.utc) - timedelta(days=OUTDATED_STAMP_DAYS + 5)).strftime("%Y-%m-%d")
        (repo / "agent" / "SOUL.md").write_text(
            f"Counts verified at HEAD abc1234 on {old}.\n"
        )
        findings = scan_file(repo, "agent/SOUL.md")
        stamps = [f for f in findings if f.kind == "outdated_stamp"]
        assert len(stamps) == 1
        assert "days old" in stamps[0].description

    def test_stamp_without_date_does_not_flag(self, tmp_path):
        """No date present → can't compute age → skip (don't false-positive)."""
        repo = _make_zone1_layout(tmp_path)
        (repo / "agent" / "SOUL.md").write_text(
            "Counts verified at HEAD abc1234.\n"
        )
        findings = scan_file(repo, "agent/SOUL.md")
        stamps = [f for f in findings if f.kind == "outdated_stamp"]
        assert stamps == []


class TestZone1DriftServiceSafetyRule:
    """The non-negotiable safety rule: service NEVER auto-writes or auto-merges."""

    def test_default_disabled_returns_skipped(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        svc = Zone1DriftService(data_dir=tmp_path, repo_root=repo, enabled=False)
        result = svc.run()
        assert result.state == "skipped"
        assert result.pr_body is None
        assert result.findings == ()

    def test_enabled_clean_run_returns_clean(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        svc = Zone1DriftService(data_dir=tmp_path, repo_root=repo, enabled=True)
        result = svc.run()
        assert result.state == "clean"
        assert result.pr_body is None

    def test_enabled_with_findings_renders_pr_body_but_does_not_write(self, tmp_path):
        repo = _make_zone1_layout(tmp_path)
        (repo / "agent" / "SOUL.md").write_text(
            "Reference to missing file: `agent/missing-file.md`\n"
        )
        svc = Zone1DriftService(data_dir=tmp_path, repo_root=repo, enabled=True)
        result = svc.run()
        assert result.state == "findings_ready"
        assert result.pr_body is not None
        assert "dead_ref" in result.pr_body
        # The PR body is TEXT; no FS or git mutation happened during run()
        # (no way to assert this perfectly, but the result.state value is the
        # contract — only operator command surface opens the actual PR).

    def test_render_pr_body_has_no_auto_apply_instructions(self):
        findings = [
            DriftFinding(
                file="agent/SOUL.md",
                line=10,
                kind="dead_ref",
                description="cited path does not exist: foo.md",
            ),
        ]
        body = render_pr_body(findings)
        body_lower = body.lower()
        # Operator-action language present (positive assertions)
        assert "operator review required" in body_lower
        assert "edit the cited file" in body_lower
        # "auto" appears ONLY inside "NEVER auto-merges" — never as instruction
        # Strip the safety-rule line and re-check for stray auto-apply language
        safety_line = "never auto-merges"
        assert safety_line in body_lower
        sanitized = body_lower.replace(safety_line, "")
        # After removing the safety-rule mention, there should be no "auto" /
        # "apply" / "execute" language that could be misread as actionable
        assert "auto-apply" not in sanitized
        assert "auto-merge" not in sanitized
        assert "auto-fix" not in sanitized
        # No imperative "merge this" or "apply this" phrasing
        assert "apply this" not in sanitized
        assert "merge this" not in sanitized

    def test_render_pr_body_empty_findings_returns_empty_string(self):
        assert render_pr_body([]) == ""

    def test_service_does_not_call_gh_pr_create(self, tmp_path, monkeypatch):
        """Belt-and-suspenders — verify the service doesn't shell to gh during run."""
        repo = _make_zone1_layout(tmp_path)
        (repo / "agent" / "SOUL.md").write_text(
            "Reference: `agent/missing.md`\n"
        )

        called = {"yes": False}

        def _no_subprocess(*args, **kwargs):
            called["yes"] = True
            raise RuntimeError("Service should not be invoking subprocess in run()")

        import subprocess as _sp
        monkeypatch.setattr(_sp, "run", _no_subprocess)
        monkeypatch.setattr(_sp, "Popen", _no_subprocess)
        monkeypatch.setattr(_sp, "check_output", _no_subprocess)

        svc = Zone1DriftService(data_dir=tmp_path, repo_root=repo, enabled=True)
        svc.run()  # must NOT raise
        assert not called["yes"], "Service called subprocess — violates safety rule"


class TestZone1DriftServiceShouldRun:
    def test_should_run_false_when_disabled(self, tmp_path):
        svc = Zone1DriftService(data_dir=tmp_path, repo_root=tmp_path, enabled=False)
        assert svc.should_run() is False

    def test_should_run_true_when_enabled(self, tmp_path):
        svc = Zone1DriftService(data_dir=tmp_path, repo_root=tmp_path, enabled=True)
        assert svc.should_run() is True
