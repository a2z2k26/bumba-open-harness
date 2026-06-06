"""Unit + integration tests for Sprint 4.2 — harness-observed evidence hook.

Run from the repo root:
    python3 -m pytest tests/test_evidence.py -v

Acceptance criteria verified here:
    [AC1] EvidenceRecord dataclass and capture_evidence() function exist
    [AC2] capture_evidence() writes raw output to .harness/evidence/pr-<N>/
    [AC3] EvidenceRecord.to_pr_section() returns a PR body block with EVIDENCE_SECTION_MARKER
    [AC4] capture_evidence() returns FAIL record when exit_code != 0 (does NOT raise)
    [AC5] create_pr_with_evidence() raises EvidenceFailedError when any command fails
    [AC6] EvidenceFailedError contains the failing records
    [AC7] Output is truncated to OUTPUT_TAIL_LINES lines (not more)
    [AC8] EvidenceConfig.load() parses evidence.toml correctly
    [AC9] EvidenceConfig.commands_for_repo() returns empty tuple for unknown repos
    [AC10] create_pr_with_evidence() builds the PR body with the harness section appended
    [AC11] create_pr_with_evidence() blocks PR when evidence fails and notifies dialogue
    [AC12] dry_run=True runs evidence commands but does NOT call gh pr create
    [AC13] EVIDENCE_SECTION_MARKER appears in the PR body section
    [AC14] The harness section says "not the agent" (authorship clarity)
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.evidence import (
    EVIDENCE_SECTION_MARKER,
    OUTPUT_TAIL_LINES,
    EvidenceConfig,
    EvidenceConfigError,
    EvidenceFailedError,
    EvidenceRecord,
    _tail,
    capture_evidence,
    create_pr_with_evidence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_record(
    *,
    exit_code: int = 0,
    command: str = "pytest tests/",
    stdout_tail: str = "1 passed",
    stderr_tail: str = "",
    duration: float = 1.5,
    host: str = "test-host",
    evidence_path: str = "/tmp/evidence/pr-0/1234_pytest.txt",
) -> EvidenceRecord:
    return EvidenceRecord(
        command=command,
        exit_code=exit_code,
        duration_seconds=duration,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        captured_at=datetime.now(timezone.utc),
        host=host,
        evidence_path=evidence_path,
    )


def make_subprocess_runner(
    *,
    returncode: int = 0,
    stdout: bytes = b"all tests pass",
    stderr: bytes = b"",
    delay: float = 0.0,
):
    """Build a mock subprocess.run compatible callable."""

    def runner(cmd, *, capture_output=True, timeout=300, cwd=None):
        if delay:
            time.sleep(delay)
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    return runner


def make_gh_runner(*, returncode: int = 0, stdout: str = "https://github.com/test/repo/pull/42"):
    """Build a mock runner for `gh pr create` calls."""

    def runner(cmd, *, capture_output=True, text=True):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = "" if returncode == 0 else "gh error"
        return proc

    return runner


def make_evidence_toml(repos: list[dict], tmp_path: Path) -> Path:
    """Write a minimal evidence.toml to tmp_path and return its path."""
    lines = []
    for repo in repos:
        lines.append('\n[[repos]]')
        lines.append(f'name = "{repo["name"]}"')
        cmds = repo.get("commands", [])
        cmd_strs = [f'[{", ".join(repr(c) for c in cmd)}]' for cmd in cmds]
        lines.append(f'commands = [{", ".join(cmd_strs)}]')
        if "timeout_seconds" in repo:
            lines.append(f'timeout_seconds = {repo["timeout_seconds"]}')
    toml_path = tmp_path / "evidence.toml"
    toml_path.write_text("\n".join(lines))
    return toml_path


# ---------------------------------------------------------------------------
# _tail helper
# ---------------------------------------------------------------------------


class TestTailHelper:
    def test_fewer_lines_than_limit_returns_all(self):
        text = "line1\nline2\nline3"
        assert _tail(text, 40) == text

    def test_more_lines_truncated_to_limit(self):
        lines = [f"line{i}" for i in range(100)]
        text = "\n".join(lines)
        result = _tail(text, OUTPUT_TAIL_LINES)
        result_lines = result.splitlines()
        assert len(result_lines) == OUTPUT_TAIL_LINES
        # Should be the LAST N lines
        assert result_lines[0] == f"line{100 - OUTPUT_TAIL_LINES}"
        assert result_lines[-1] == "line99"

    def test_empty_string(self):
        assert _tail("", 40) == ""

    def test_exactly_limit_lines_returns_all(self):
        lines = [f"L{i}" for i in range(OUTPUT_TAIL_LINES)]
        text = "\n".join(lines)
        assert _tail(text, OUTPUT_TAIL_LINES) == text

    def test_one_more_than_limit(self):
        lines = [f"L{i}" for i in range(OUTPUT_TAIL_LINES + 1)]
        text = "\n".join(lines)
        result = _tail(text, OUTPUT_TAIL_LINES)
        result_lines = result.splitlines()
        assert len(result_lines) == OUTPUT_TAIL_LINES
        assert result_lines[0] == "L1"


# ---------------------------------------------------------------------------
# EvidenceRecord
# ---------------------------------------------------------------------------


class TestEvidenceRecord:
    def test_passed_property_true_on_exit_0(self):
        record = make_record(exit_code=0)
        assert record.passed is True

    def test_passed_property_false_on_nonzero(self):
        record = make_record(exit_code=1)
        assert record.passed is False

    def test_to_pr_section_contains_marker(self):
        record = make_record()
        section = record.to_pr_section()
        assert EVIDENCE_SECTION_MARKER in section

    def test_to_pr_section_opens_and_closes_with_marker(self):
        record = make_record()
        section = record.to_pr_section()
        assert section.startswith(EVIDENCE_SECTION_MARKER)
        assert section.endswith(EVIDENCE_SECTION_MARKER)

    def test_to_pr_section_contains_header(self):
        record = make_record()
        section = record.to_pr_section()
        assert "## Harness-Observed Evidence" in section

    def test_to_pr_section_says_not_the_agent(self):
        """AC14 — authorship clarity."""
        record = make_record()
        section = record.to_pr_section()
        assert "not the agent" in section

    def test_to_pr_section_includes_command(self):
        record = make_record(command="pytest tests/ -q")
        section = record.to_pr_section()
        assert "pytest tests/ -q" in section

    def test_to_pr_section_shows_pass_status(self):
        record = make_record(exit_code=0)
        section = record.to_pr_section()
        assert "PASS" in section

    def test_to_pr_section_shows_fail_status(self):
        record = make_record(exit_code=1)
        section = record.to_pr_section()
        assert "FAIL" in section

    def test_to_pr_section_includes_duration(self):
        record = make_record(duration=12.3)
        section = record.to_pr_section()
        assert "12.3" in section

    def test_to_pr_section_includes_stdout_tail(self):
        record = make_record(stdout_tail="PASSED 42 tests")
        section = record.to_pr_section()
        assert "PASSED 42 tests" in section

    def test_to_pr_section_includes_stderr_when_present(self):
        record = make_record(stderr_tail="some warning here")
        section = record.to_pr_section()
        assert "some warning here" in section

    def test_to_pr_section_omits_stderr_separator_when_empty(self):
        record = make_record(stdout_tail="ok", stderr_tail="")
        section = record.to_pr_section()
        assert "--- stderr ---" not in section

    def test_to_pr_section_includes_evidence_path(self):
        record = make_record(evidence_path="/tmp/.harness/evidence/pr-0/abc.txt")
        section = record.to_pr_section()
        assert "/tmp/.harness/evidence/pr-0/abc.txt" in section

    def test_record_is_immutable(self):
        record = make_record()
        with pytest.raises((AttributeError, TypeError)):
            record.exit_code = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# capture_evidence (sync)
# ---------------------------------------------------------------------------


class TestCaptureEvidence:
    def test_successful_capture_returns_passing_record(self, tmp_path):
        runner = make_subprocess_runner(returncode=0, stdout=b"3 passed")
        record = capture_evidence(
            ["pytest", "tests/"],
            cwd=tmp_path,
            pr_number=42,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        assert record.exit_code == 0
        assert record.passed is True
        assert "pytest tests/" in record.command

    def test_failed_capture_returns_failing_record_not_raises(self, tmp_path):
        """AC4 — capture_evidence returns the record; it does NOT raise."""
        runner = make_subprocess_runner(returncode=2, stdout=b"", stderr=b"SyntaxError")
        record = capture_evidence(
            ["python", "-m", "pytest"],
            cwd=tmp_path,
            pr_number=7,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        assert record.exit_code == 2
        assert record.passed is False

    def test_evidence_file_written_to_pr_directory(self, tmp_path):
        """AC2 — raw output written to .harness/evidence/pr-<N>/."""
        runner = make_subprocess_runner(returncode=0, stdout=b"ok")
        record = capture_evidence(
            ["pytest"],
            cwd=tmp_path,
            pr_number=99,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        evidence_path = Path(record.evidence_path)
        assert evidence_path.exists()
        assert evidence_path.parent.name == "pr-99"

    def test_evidence_file_contains_stdout_and_stderr(self, tmp_path):
        runner = make_subprocess_runner(
            returncode=0, stdout=b"stdout content", stderr=b"stderr content"
        )
        record = capture_evidence(
            ["pytest"],
            cwd=tmp_path,
            pr_number=1,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        raw = Path(record.evidence_path).read_bytes()
        assert b"stdout content" in raw
        assert b"stderr content" in raw

    def test_evidence_file_contains_command(self, tmp_path):
        runner = make_subprocess_runner(returncode=0)
        record = capture_evidence(
            ["python", "-m", "pytest", "tests/"],
            cwd=tmp_path,
            pr_number=1,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        raw = Path(record.evidence_path).read_bytes()
        assert b"python" in raw

    def test_stdout_tail_truncated_to_limit(self, tmp_path):
        """AC7 — stdout_tail is at most OUTPUT_TAIL_LINES lines."""
        many_lines = "\n".join(f"line{i}" for i in range(200))
        runner = make_subprocess_runner(returncode=0, stdout=many_lines.encode())
        record = capture_evidence(
            ["pytest"],
            cwd=tmp_path,
            pr_number=1,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        assert len(record.stdout_tail.splitlines()) <= OUTPUT_TAIL_LINES

    def test_stderr_tail_truncated_to_limit(self, tmp_path):
        many_lines = "\n".join(f"err{i}" for i in range(200))
        runner = make_subprocess_runner(returncode=0, stderr=many_lines.encode())
        record = capture_evidence(
            ["pytest"],
            cwd=tmp_path,
            pr_number=1,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        assert len(record.stderr_tail.splitlines()) <= OUTPUT_TAIL_LINES

    def test_host_is_populated(self, tmp_path):
        runner = make_subprocess_runner()
        record = capture_evidence(
            ["pytest"],
            cwd=tmp_path,
            pr_number=1,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        assert record.host != ""

    def test_captured_at_is_utc(self, tmp_path):
        runner = make_subprocess_runner()
        record = capture_evidence(
            ["pytest"],
            cwd=tmp_path,
            pr_number=1,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        assert record.captured_at.tzinfo is not None
        assert record.captured_at.tzinfo == timezone.utc

    def test_duration_is_positive(self, tmp_path):
        runner = make_subprocess_runner()
        record = capture_evidence(
            ["pytest"],
            cwd=tmp_path,
            pr_number=1,
            evidence_root=tmp_path / ".harness" / "evidence",
            runner=runner,
        )
        assert record.duration_seconds >= 0.0

    def test_bad_command_returns_nonzero(self, tmp_path):
        """A missing executable returns a non-zero exit without crashing."""
        # Use the real subprocess here with a definitely-absent command
        record = capture_evidence(
            ["__bumba_nonexistent_command_xyz__"],
            cwd=tmp_path,
            pr_number=1,
            evidence_root=tmp_path / ".harness" / "evidence",
        )
        assert record.exit_code != 0
        assert record.passed is False


# ---------------------------------------------------------------------------
# EvidenceConfig
# ---------------------------------------------------------------------------


class TestEvidenceConfig:
    def test_load_parses_repos(self, tmp_path):
        """AC8 — loads evidence.toml correctly."""
        toml_path = make_evidence_toml(
            [{"name": "your-org/bumba-open-harness", "commands": [["pytest", "tests/"]]}],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        assert len(config.specs) == 1
        assert config.specs[0].name == "your-org/bumba-open-harness"

    def test_load_parses_commands(self, tmp_path):
        toml_path = make_evidence_toml(
            [
                {
                    "name": "your-org/bumba-open-harness",
                    "commands": [["pytest", "tests/"], ["python", "-m", "mypy"]],
                }
            ],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        cmds = config.commands_for_repo("your-org/bumba-open-harness")
        assert len(cmds) == 2
        assert cmds[0] == ("pytest", "tests/")
        assert cmds[1] == ("python", "-m", "mypy")

    def test_commands_for_unknown_repo_returns_empty(self, tmp_path):
        """AC9 — unknown repos get empty tuple."""
        toml_path = make_evidence_toml(
            [{"name": "your-org/bumba-open-harness", "commands": [["pytest"]]}],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        cmds = config.commands_for_repo("your-org/nonexistent-repo")
        assert cmds == ()

    def test_load_raises_config_error_on_missing_file(self, tmp_path):
        with pytest.raises(EvidenceConfigError, match="not found"):
            EvidenceConfig.load(tmp_path / "does_not_exist.toml")

    def test_load_raises_config_error_on_invalid_toml(self, tmp_path):
        bad_toml = tmp_path / "evidence.toml"
        bad_toml.write_text("this is not [ valid toml <<<")
        with pytest.raises(EvidenceConfigError):
            EvidenceConfig.load(bad_toml)

    def test_timeout_defaults_to_300(self, tmp_path):
        toml_path = make_evidence_toml(
            [{"name": "your-org/bumba-open-harness", "commands": [["pytest"]]}],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        assert config.timeout_for_repo("your-org/bumba-open-harness") == 300

    def test_timeout_custom_value_loaded(self, tmp_path):
        toml_path = make_evidence_toml(
            [{"name": "your-org/bumba-open-harness", "commands": [["pytest"]], "timeout_seconds": 60}],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        assert config.timeout_for_repo("your-org/bumba-open-harness") == 60

    def test_timeout_for_unknown_repo_returns_default(self, tmp_path):
        toml_path = make_evidence_toml(
            [{"name": "your-org/bumba-open-harness", "commands": [["pytest"]]}],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        assert config.timeout_for_repo("other/repo") == 300

    def test_multiple_repos_all_loaded(self, tmp_path):
        toml_path = make_evidence_toml(
            [
                {"name": "your-org/bumba-open-harness", "commands": [["pytest"]]},
                {"name": "your-org/bumba-desktop", "commands": [["swift", "build"]]},
            ],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        assert len(config.specs) == 2
        assert config.commands_for_repo("your-org/bumba-desktop") == (("swift", "build"),)

    def test_config_is_immutable(self, tmp_path):
        toml_path = make_evidence_toml(
            [{"name": "your-org/bumba-open-harness", "commands": [["pytest"]]}],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        with pytest.raises((AttributeError, TypeError)):
            config.specs = ()  # type: ignore[misc]

    def test_real_evidence_toml_is_parseable(self):
        """Smoke test: the committed evidence.toml loads without error."""
        from pathlib import Path as _Path
        real_toml = _Path(__file__).resolve().parent.parent / "agent" / "config" / "evidence.toml"
        if not real_toml.exists():
            pytest.skip("evidence.toml not present in this checkout")
        config = EvidenceConfig.load(real_toml)
        # bumba-open-harness must be in there
        cmds = config.commands_for_repo("your-org/bumba-open-harness")
        assert len(cmds) >= 1


# ---------------------------------------------------------------------------
# create_pr_with_evidence
# ---------------------------------------------------------------------------


class TestCreatePrWithEvidence:
    """Tests for the only sanctioned PR-creation path."""

    def _make_config(self, tmp_path: Path, commands=None) -> EvidenceConfig:
        cmds = commands or [["pytest", "tests/"]]
        toml_path = make_evidence_toml(
            [{"name": "your-org/bumba-open-harness", "commands": cmds}],
            tmp_path,
        )
        return EvidenceConfig.load(toml_path)

    def test_happy_path_returns_pr_url(self, tmp_path):
        """AC10 — successful evidence => PR created => URL returned."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=0, stdout=b"5 passed")
        gh_runner = make_gh_runner(stdout="https://github.com/your-org/bumba-open-harness/pull/100")

        url = asyncio.run(
            create_pr_with_evidence(
                title="fix: the bug",
                body="## Summary\nFixed it.",
                repo="your-org/bumba-open-harness",
                config=config,
                cwd=tmp_path,
                evidence_root=tmp_path / ".harness" / "evidence",
                subprocess_runner=subprocess_runner,
                gh_runner=gh_runner,
            )
        )
        assert url == "https://github.com/your-org/bumba-open-harness/pull/100"

    def test_evidence_section_marker_in_pr_body(self, tmp_path):
        """AC13 — EVIDENCE_SECTION_MARKER appears in the body sent to gh."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=0, stdout=b"ok")

        captured_body: list[str] = []

        def gh_runner(cmd, *, capture_output=True, text=True):
            # Extract the --body argument from the command
            for i, arg in enumerate(cmd):
                if arg == "--body" and i + 1 < len(cmd):
                    captured_body.append(cmd[i + 1])
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = "https://github.com/test/pull/1"
            proc.stderr = ""
            return proc

        asyncio.run(
            create_pr_with_evidence(
                title="test",
                body="## Summary\nAgent body.",
                repo="your-org/bumba-open-harness",
                config=config,
                cwd=tmp_path,
                evidence_root=tmp_path / ".harness" / "evidence",
                subprocess_runner=subprocess_runner,
                gh_runner=gh_runner,
            )
        )
        assert len(captured_body) == 1
        assert EVIDENCE_SECTION_MARKER in captured_body[0]
        assert "## Harness-Observed Evidence" in captured_body[0]

    def test_agent_body_preserved_above_evidence(self, tmp_path):
        """Agent's body content appears before the harness section."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=0)
        captured_body: list[str] = []

        def gh_runner(cmd, *, capture_output=True, text=True):
            for i, arg in enumerate(cmd):
                if arg == "--body" and i + 1 < len(cmd):
                    captured_body.append(cmd[i + 1])
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = "https://github.com/test/pull/1"
            proc.stderr = ""
            return proc

        asyncio.run(
            create_pr_with_evidence(
                title="test",
                body="## Summary\nAgent-authored content.",
                repo="your-org/bumba-open-harness",
                config=config,
                cwd=tmp_path,
                evidence_root=tmp_path / ".harness" / "evidence",
                subprocess_runner=subprocess_runner,
                gh_runner=gh_runner,
            )
        )
        body = captured_body[0]
        agent_pos = body.find("Agent-authored content.")
        evidence_pos = body.find(EVIDENCE_SECTION_MARKER)
        assert agent_pos < evidence_pos, "Agent body must appear before evidence section"

    def test_raises_evidence_failed_error_on_failure(self, tmp_path):
        """AC5 — EvidenceFailedError raised when command fails."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=1, stderr=b"AssertionError")

        with pytest.raises(EvidenceFailedError):
            asyncio.run(
                create_pr_with_evidence(
                    title="fix",
                    body="body",
                    repo="your-org/bumba-open-harness",
                    config=config,
                    cwd=tmp_path,
                    evidence_root=tmp_path / ".harness" / "evidence",
                    subprocess_runner=subprocess_runner,
                )
            )

    def test_evidence_failed_error_contains_failing_records(self, tmp_path):
        """AC6 — EvidenceFailedError.records contains the failing EvidenceRecords."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=2, stderr=b"compile error")

        exc_caught: list[EvidenceFailedError] = []
        try:
            asyncio.run(
                create_pr_with_evidence(
                    title="fix",
                    body="body",
                    repo="your-org/bumba-open-harness",
                    config=config,
                    cwd=tmp_path,
                    evidence_root=tmp_path / ".harness" / "evidence",
                    subprocess_runner=subprocess_runner,
                )
            )
        except EvidenceFailedError as exc:
            exc_caught.append(exc)

        assert len(exc_caught) == 1
        assert len(exc_caught[0].records) >= 1
        assert exc_caught[0].records[0].exit_code == 2

    def test_dialogue_notify_called_on_failure(self, tmp_path):
        """AC11 — operator notified via dialogue channel when evidence fails."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=1)

        notifications: list[str] = []

        try:
            asyncio.run(
                create_pr_with_evidence(
                    title="fix",
                    body="body",
                    repo="your-org/bumba-open-harness",
                    config=config,
                    cwd=tmp_path,
                    evidence_root=tmp_path / ".harness" / "evidence",
                    subprocess_runner=subprocess_runner,
                    dialogue_notify=notifications.append,
                )
            )
        except EvidenceFailedError:
            pass

        assert len(notifications) == 1
        assert "blocked" in notifications[0].lower() or "failed" in notifications[0].lower()

    def test_gh_not_called_on_failure(self, tmp_path):
        """PR creation must be blocked — gh runner never fires on failure."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=1)

        gh_called: list[bool] = []

        def gh_runner(cmd, **kwargs):
            gh_called.append(True)
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = "https://github.com/test/pull/1"
            proc.stderr = ""
            return proc

        try:
            asyncio.run(
                create_pr_with_evidence(
                    title="fix",
                    body="body",
                    repo="your-org/bumba-open-harness",
                    config=config,
                    cwd=tmp_path,
                    evidence_root=tmp_path / ".harness" / "evidence",
                    subprocess_runner=subprocess_runner,
                    gh_runner=gh_runner,
                )
            )
        except EvidenceFailedError:
            pass

        assert len(gh_called) == 0, "gh pr create must not be called when evidence fails"

    def test_dry_run_skips_gh_create(self, tmp_path):
        """AC12 — dry_run=True captures evidence but does NOT call gh pr create."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=0)

        gh_called: list[bool] = []

        def gh_runner(cmd, **kwargs):
            gh_called.append(True)
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = "https://github.com/test/pull/1"
            proc.stderr = ""
            return proc

        result = asyncio.run(
            create_pr_with_evidence(
                title="test",
                body="body",
                repo="your-org/bumba-open-harness",
                config=config,
                cwd=tmp_path,
                evidence_root=tmp_path / ".harness" / "evidence",
                subprocess_runner=subprocess_runner,
                gh_runner=gh_runner,
                dry_run=True,
            )
        )
        assert len(gh_called) == 0, "dry_run must not call gh pr create"
        assert "DRY RUN" in result

    def test_dry_run_still_runs_evidence_commands(self, tmp_path):
        """Evidence commands fire even in dry-run mode."""
        config = self._make_config(tmp_path)
        calls: list[list] = []

        def subprocess_runner(cmd, *, capture_output=True, timeout=300, cwd=None):
            calls.append(cmd)
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = b"ok"
            proc.stderr = b""
            return proc

        asyncio.run(
            create_pr_with_evidence(
                title="test",
                body="body",
                repo="your-org/bumba-open-harness",
                config=config,
                cwd=tmp_path,
                evidence_root=tmp_path / ".harness" / "evidence",
                subprocess_runner=subprocess_runner,
                dry_run=True,
            )
        )
        assert len(calls) >= 1

    def test_empty_commands_still_creates_pr(self, tmp_path):
        """Repos with no configured commands get a PR with no evidence section."""
        # Config with empty commands
        toml_path = make_evidence_toml(
            [{"name": "your-org/bumba-open-harness", "commands": []}],
            tmp_path,
        )
        config = EvidenceConfig.load(toml_path)
        gh_runner = make_gh_runner(stdout="https://github.com/test/pull/2")

        url = asyncio.run(
            create_pr_with_evidence(
                title="test",
                body="body",
                repo="your-org/bumba-open-harness",
                config=config,
                cwd=tmp_path,
                evidence_root=tmp_path / ".harness" / "evidence",
                gh_runner=gh_runner,
            )
        )
        assert "https://" in url

    def test_gh_failure_raises_runtime_error(self, tmp_path):
        """gh pr create failure raises RuntimeError (not EvidenceFailedError)."""
        config = self._make_config(tmp_path)
        subprocess_runner = make_subprocess_runner(returncode=0)
        gh_runner = make_gh_runner(returncode=1, stdout="")

        with pytest.raises(RuntimeError, match="gh pr create failed"):
            asyncio.run(
                create_pr_with_evidence(
                    title="test",
                    body="body",
                    repo="your-org/bumba-open-harness",
                    config=config,
                    cwd=tmp_path,
                    evidence_root=tmp_path / ".harness" / "evidence",
                    subprocess_runner=subprocess_runner,
                    gh_runner=gh_runner,
                )
            )

    def test_multiple_commands_all_run(self, tmp_path):
        """All configured commands are run before creating the PR."""
        config = self._make_config(
            tmp_path,
            commands=[["pytest", "tests/"], ["python", "-m", "mypy", "."]],
        )
        calls: list[list] = []

        def subprocess_runner(cmd, *, capture_output=True, timeout=300, cwd=None):
            calls.append(cmd)
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = b"ok"
            proc.stderr = b""
            return proc

        gh_runner = make_gh_runner()

        asyncio.run(
            create_pr_with_evidence(
                title="test",
                body="body",
                repo="your-org/bumba-open-harness",
                config=config,
                cwd=tmp_path,
                evidence_root=tmp_path / ".harness" / "evidence",
                subprocess_runner=subprocess_runner,
                gh_runner=gh_runner,
            )
        )
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# Integration-style test: real pytest run against our own test suite
# ---------------------------------------------------------------------------


class TestIntegrationRealPytestCapture:
    """Run a real subprocess against a sandboxed 'test' that always passes.

    This confirms the end-to-end pipeline captures live output correctly —
    not a mock, but a real process.  Lightweight: uses a tiny Python one-liner.
    """

    def test_real_process_capture(self, tmp_path):
        # Write a minimal test file that pytest can run
        test_file = tmp_path / "test_canary.py"
        test_file.write_text(
            "def test_always_passes():\n    assert 1 + 1 == 2\n"
        )

        record = capture_evidence(
            [sys.executable, "-m", "pytest", str(test_file), "-q"],
            cwd=tmp_path,
            pr_number=0,
            evidence_root=tmp_path / ".harness" / "evidence",
        )
        assert record.exit_code == 0
        assert record.passed is True
        assert "passed" in record.stdout_tail.lower() or "1 passed" in record.stdout_tail.lower()
        # Evidence file must exist and contain real output
        raw = Path(record.evidence_path).read_bytes()
        assert b"passed" in raw.lower()

    def test_real_process_failure_capture(self, tmp_path):
        # Write a test that fails
        test_file = tmp_path / "test_fail_canary.py"
        test_file.write_text(
            "def test_always_fails():\n    assert False, 'expected failure'\n"
        )

        record = capture_evidence(
            [sys.executable, "-m", "pytest", str(test_file), "-q"],
            cwd=tmp_path,
            pr_number=0,
            evidence_root=tmp_path / ".harness" / "evidence",
        )
        assert record.exit_code != 0
        assert record.passed is False
        # The failure reason must appear somewhere in captured output
        combined = record.stdout_tail + record.stderr_tail
        assert "fail" in combined.lower() or "assert" in combined.lower()
