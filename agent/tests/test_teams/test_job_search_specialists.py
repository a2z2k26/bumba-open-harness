"""Tests for Zone 4 job-search specialist implementations (D5.3 / D5.4 / D5.6)."""
from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teams.job_search._specialists import (
    AcquireAndPrepareSpecialist,
    BrowserUseSpecialist,
    EmailVerificationSpecialist,
    OutreachExecuteSpecialist,
    _append_progress,
    _conversation_log_path,
    _extract_code_heuristic,
)
from teams.job_search._types import (
    AcquireInput,
    AcquireOutput,
    BrowserInput,
    BrowserOutput,
    BrowserStatus,
    ExecuteInput,
    ExecuteOutput,
    VerifyInput,
    VerifyOutput,
    VerifyStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_acquire_input(**kwargs) -> AcquireInput:
    defaults = {"run_id": str(uuid.uuid4())}
    defaults.update(kwargs)
    return AcquireInput(**defaults)


def _fake_raw_result(pages: list[dict] | None = None) -> dict:
    if pages is None:
        pages = [
            {
                "fingerprint": "fp-001",
                "board": "remotive",
                "company": "Acme",
                "title": "Staff Engineer",
                "url": "https://example.com/1",
                "ats": "greenhouse",
                "rubric_grade": "A",
                "cover_letter_chars": 800,
                "notion_page_id": "np-001",
                "cost_usd": 0.04,
            },
            {
                "fingerprint": "fp-002",
                "board": "himalayas",
                "company": "Beta Corp",
                "title": "Design Engineer",
                "url": "https://example.com/2",
                "ats": None,
                "rubric_grade": "B",
                "cover_letter_chars": 600,
                "notion_page_id": "np-002",
                "cost_usd": 0.02,
            },
        ]
    return {
        "run_at": "2026-05-06T08:00:00",
        "phases": {
            "staging": {"staged_pages": pages},
            "research": {"skipped_dup": 3, "skipped_excluded": 1},
            "rubric_gate": {"passed": len(pages), "filtered": 2},
        },
        "errors": [],
    }


# ---------------------------------------------------------------------------
# _conversation_log_path
# ---------------------------------------------------------------------------

def test_conversation_log_path_uses_base_dir():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        path = _conversation_log_path("run-abc", base_dir=base)
        assert path == base / "teams" / "job_search" / "conversations" / "run-abc.jsonl"


def test_conversation_log_path_default_root():
    path = _conversation_log_path("run-xyz", base_dir=None)
    assert "conversations/run-xyz.jsonl" in str(path)


# ---------------------------------------------------------------------------
# _append_progress
# ---------------------------------------------------------------------------

def test_append_progress_writes_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        run_id = "test-run"
        _append_progress(run_id, {"event": "test_event", "x": 42}, base_dir=base)

        log_path = _conversation_log_path(run_id, base_dir=base)
        assert log_path.exists()
        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "test_event"
        assert record["x"] == 42
        assert record["run_id"] == run_id
        assert "ts" in record


def test_append_progress_appends_multiple_lines():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        run_id = "multi-run"
        for i in range(3):
            _append_progress(run_id, {"event": f"ev_{i}"}, base_dir=base)

        log_path = _conversation_log_path(run_id, base_dir=base)
        lines = log_path.read_text().splitlines()
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# AcquireAndPrepareSpecialist.run — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_specialist_returns_acquire_output():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = _fake_raw_result()
        mock_agent = MagicMock()
        mock_agent.prepare = AsyncMock(return_value=raw)

        with patch(
            "job_search.agent.JobSearchAgent",
            return_value=mock_agent,
        ):
            specialist = AcquireAndPrepareSpecialist(log_base_dir=base)
            inp = _make_acquire_input()
            out = await specialist.run(inp)

        assert isinstance(out, AcquireOutput)
        assert out.run_id == inp.run_id
        assert len(out.prepared_listings) == 2


@pytest.mark.asyncio
async def test_acquire_specialist_listing_fields():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = _fake_raw_result()
        mock_agent = MagicMock()
        mock_agent.prepare = AsyncMock(return_value=raw)

        with patch(
            "job_search.agent.JobSearchAgent",
            return_value=mock_agent,
        ):
            out = await AcquireAndPrepareSpecialist(log_base_dir=base).run(_make_acquire_input())

        first = out.prepared_listings[0]
        assert first.listing_id == "fp-001"
        assert first.board == "remotive"
        assert first.company == "Acme"
        assert first.title == "Staff Engineer"
        assert first.rubric_grade == "A"
        assert first.ats_kind == "greenhouse"
        assert first.cost_usd == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_acquire_specialist_cost_summation():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = _fake_raw_result()
        mock_agent = MagicMock()
        mock_agent.prepare = AsyncMock(return_value=raw)

        with patch(
            "job_search.agent.JobSearchAgent",
            return_value=mock_agent,
        ):
            out = await AcquireAndPrepareSpecialist(log_base_dir=base).run(_make_acquire_input())

        assert out.total_cost_usd == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_acquire_specialist_skipped_count():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = _fake_raw_result()  # skipped_dup=3, skipped_excluded=1
        mock_agent = MagicMock()
        mock_agent.prepare = AsyncMock(return_value=raw)

        with patch(
            "job_search.agent.JobSearchAgent",
            return_value=mock_agent,
        ):
            out = await AcquireAndPrepareSpecialist(log_base_dir=base).run(_make_acquire_input())

        assert out.skipped_count == 4


@pytest.mark.asyncio
async def test_acquire_specialist_emits_per_listing_progress():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = _fake_raw_result()
        mock_agent = MagicMock()
        mock_agent.prepare = AsyncMock(return_value=raw)
        inp = _make_acquire_input()

        with patch(
            "job_search.agent.JobSearchAgent",
            return_value=mock_agent,
        ):
            await AcquireAndPrepareSpecialist(log_base_dir=base).run(inp)

        log_path = _conversation_log_path(inp.run_id, base_dir=base)
        lines = [json.loads(l) for l in log_path.read_text().splitlines()]
        events = [l["event"] for l in lines]

        assert events[0] == "acquire_started"
        listing_events = [l for l in lines if l["event"] == "listing_progress"]
        assert len(listing_events) == 2
        assert events[-1] == "acquire_completed"


@pytest.mark.asyncio
async def test_acquire_specialist_emits_acquire_completed_summary():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = _fake_raw_result()
        mock_agent = MagicMock()
        mock_agent.prepare = AsyncMock(return_value=raw)
        inp = _make_acquire_input()

        with patch(
            "job_search.agent.JobSearchAgent",
            return_value=mock_agent,
        ):
            await AcquireAndPrepareSpecialist(log_base_dir=base).run(inp)

        log_path = _conversation_log_path(inp.run_id, base_dir=base)
        lines = [json.loads(l) for l in log_path.read_text().splitlines()]
        completed = next(l for l in lines if l["event"] == "acquire_completed")

        assert completed["prepared"] == 2
        assert completed["skipped"] == 4
        assert completed["rubric_passed"] == 2
        assert completed["rubric_filtered"] == 2


@pytest.mark.asyncio
async def test_acquire_specialist_empty_pages():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = _fake_raw_result(pages=[])
        mock_agent = MagicMock()
        mock_agent.prepare = AsyncMock(return_value=raw)

        with patch(
            "job_search.agent.JobSearchAgent",
            return_value=mock_agent,
        ):
            out = await AcquireAndPrepareSpecialist(log_base_dir=base).run(_make_acquire_input())

        assert out.prepared_listings == ()
        assert out.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# AcquireAndPrepareSpecialist.run — failure path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_specialist_captures_agent_error():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        with patch(
            "job_search.agent.JobSearchAgent",
            side_effect=RuntimeError("network timeout"),
        ):
            out = await AcquireAndPrepareSpecialist(log_base_dir=base).run(_make_acquire_input())

        assert len(out.errors) == 1
        assert "network timeout" in out.errors[0]
        assert out.prepared_listings == ()


@pytest.mark.asyncio
async def test_acquire_specialist_error_still_emits_started_event():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        inp = _make_acquire_input()

        with patch(
            "job_search.agent.JobSearchAgent",
            side_effect=RuntimeError("oops"),
        ):
            await AcquireAndPrepareSpecialist(log_base_dir=base).run(inp)

        log_path = _conversation_log_path(inp.run_id, base_dir=base)
        lines = [json.loads(l) for l in log_path.read_text().splitlines()]
        assert lines[0]["event"] == "acquire_started"


# ---------------------------------------------------------------------------
# OutreachExecuteSpecialist — D5.3 smoke tests (updated for D5.4 schema)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_specialist_returns_execute_output():
    raw = {"run_at": "2026-05-06T10:00:00", "outreach_sent": 3, "approved_count": 3, "errors": []}
    mock_agent = MagicMock()
    mock_agent.execute = AsyncMock(return_value=raw)

    with patch(
        "job_search.agent.JobSearchAgent",
        return_value=mock_agent,
    ):
        out = await OutreachExecuteSpecialist().run(ExecuteInput(run_id="run-exe-001"))

    assert isinstance(out, ExecuteOutput)
    assert out.run_id == "run-exe-001"
    assert len(out.sent) == 3


@pytest.mark.asyncio
async def test_execute_specialist_captures_error():
    with patch(
        "job_search.agent.JobSearchAgent",
        side_effect=RuntimeError("smtp down"),
    ):
        out = await OutreachExecuteSpecialist().run(ExecuteInput(run_id="run-exe-err"))

    assert "smtp down" in out.errors[0]


# ---------------------------------------------------------------------------
# OutreachExecuteSpecialist — D5.4 new tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_specialist_returns_structured_execute_output():
    """Returns ExecuteOutput with correct run_id."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = {"run_at": "2026-05-06T10:00:00", "outreach_sent": 0, "approved_count": 0, "errors": []}
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=raw)

        with patch("job_search.agent.JobSearchAgent", return_value=mock_agent):
            out = await OutreachExecuteSpecialist(log_base_dir=base).run(
                ExecuteInput(run_id="d54-run-001")
            )

    assert isinstance(out, ExecuteOutput)
    assert out.run_id == "d54-run-001"


@pytest.mark.asyncio
async def test_execute_specialist_emits_execute_started_and_completed():
    """JSONL log has execute_started and execute_completed events."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = {"run_at": "2026-05-06T10:00:00", "outreach_sent": 1, "approved_count": 1, "errors": []}
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=raw)
        inp = ExecuteInput(run_id="d54-run-002")

        with patch("job_search.agent.JobSearchAgent", return_value=mock_agent):
            await OutreachExecuteSpecialist(log_base_dir=base).run(inp)

        log_path = _conversation_log_path(inp.run_id, base_dir=base)
        lines = [json.loads(l) for l in log_path.read_text().splitlines()]
        events = [l["event"] for l in lines]

        assert events[0] == "execute_started"
        assert events[-1] == "execute_completed"


@pytest.mark.asyncio
async def test_execute_specialist_handles_integer_errors_field():
    """Raw result with errors=3 (int) produces non-empty errors tuple."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = {"run_at": "", "outreach_sent": 0, "approved_count": 0, "errors": 3}
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=raw)

        with patch("job_search.agent.JobSearchAgent", return_value=mock_agent):
            out = await OutreachExecuteSpecialist(log_base_dir=base).run(
                ExecuteInput(run_id="d54-run-003")
            )

    assert len(out.errors) > 0
    assert "3" in out.errors[0]


@pytest.mark.asyncio
async def test_execute_specialist_handles_list_errors_field():
    """Raw result with errors=['msg'] (list) puts the message in errors tuple."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        raw = {"run_at": "", "outreach_sent": 0, "approved_count": 0, "errors": ["smtp refused"]}
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=raw)

        with patch("job_search.agent.JobSearchAgent", return_value=mock_agent):
            out = await OutreachExecuteSpecialist(log_base_dir=base).run(
                ExecuteInput(run_id="d54-run-004")
            )

    assert out.errors == ("smtp refused",)


@pytest.mark.asyncio
async def test_execute_specialist_captures_exception():
    """Exception during execute() populates ExecuteOutput.errors."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        with patch(
            "job_search.agent.JobSearchAgent",
            side_effect=RuntimeError("connection refused"),
        ):
            out = await OutreachExecuteSpecialist(log_base_dir=base).run(
                ExecuteInput(run_id="d54-run-005")
            )

    assert len(out.errors) == 1
    assert "connection refused" in out.errors[0]


# ---------------------------------------------------------------------------
# D5.6 — EmailVerificationSpecialist tests
# ---------------------------------------------------------------------------

def _fresh_ts() -> str:
    """ISO-8601 UTC timestamp less than 60 seconds old."""
    return datetime.now(timezone.utc).isoformat()


def test_verify_input_rejects_missing_sender_domain():
    """Empty sender_domain raises ValueError at construction."""
    with pytest.raises(ValueError, match="sender_domain"):
        VerifyInput(
            listing_id="x",
            sender_domain="",
            after_timestamp_iso=_fresh_ts(),
        )


def test_verify_input_rejects_missing_timestamp():
    """Empty after_timestamp_iso raises ValueError at construction."""
    with pytest.raises(ValueError, match="after_timestamp_iso"):
        VerifyInput(
            listing_id="x",
            sender_domain="@noreply.greenhouse.io",
            after_timestamp_iso="",
        )


def test_verify_input_rejects_stale_timestamp():
    """Timestamp older than 10 minutes raises ValueError."""
    stale = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    with pytest.raises(ValueError, match="max allowed"):
        VerifyInput(
            listing_id="x",
            sender_domain="@noreply.greenhouse.io",
            after_timestamp_iso=stale,
        )


def test_verify_input_accepts_valid_input():
    """Valid recent timestamp and sender_domain constructs without error."""
    vi = VerifyInput(
        listing_id="listing-abc",
        sender_domain="@noreply.greenhouse.io",
        after_timestamp_iso=_fresh_ts(),
    )
    assert vi.listing_id == "listing-abc"
    assert vi.sender_domain == "@noreply.greenhouse.io"


@pytest.mark.asyncio
async def test_email_specialist_returns_extraction_failed_when_gws_missing():
    """When gws CLI is absent, returns EXTRACTION_FAILED immediately."""
    vi = VerifyInput(
        listing_id="listing-xyz",
        sender_domain="@noreply.greenhouse.io",
        after_timestamp_iso=_fresh_ts(),
    )
    with patch("teams.job_search._specialists.shutil.which", return_value=None):
        specialist = EmailVerificationSpecialist()
        out = await specialist.run(vi)

    assert isinstance(out, VerifyOutput)
    assert out.status == VerifyStatus.EXTRACTION_FAILED
    assert "gws" in out.error_detail


def test_heuristic_extraction_finds_6digit_code():
    """Heuristic regex extracts a 6-digit code from email body."""
    body = "Hello, Your code is 847291. Please enter it to verify your email."
    code = _extract_code_heuristic(body)
    assert code == "847291"


# ---------------------------------------------------------------------------
# BrowserUseSpecialist — D5.5 tests
# ---------------------------------------------------------------------------

def _make_browser_input(**kwargs) -> BrowserInput:
    defaults = {
        "listing_id": "listing-001",
        "url": "https://example.com/jobs/123",
        "cover_letter": "I am excited to apply for this role.",
        "run_id": str(uuid.uuid4()),
        "dry_run": True,
        "max_turns": 40,
    }
    defaults.update(kwargs)
    return BrowserInput(**defaults)


def _fake_stream_json_output(status: str = "submitted") -> bytes:
    """Build a minimal stream-json subprocess output that contains a result JSON."""
    assistant_block = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "status": status,
                        "last_step": "post_submit_confirm",
                        "blocker_reason": "",
                        "confirmation_text": "Application submitted",
                    }),
                }
            ]
        },
    })
    result_block = json.dumps({
        "type": "result",
        "result": json.dumps({
            "status": status,
            "last_step": "post_submit_confirm",
            "blocker_reason": "",
            "confirmation_text": "Application submitted",
        }),
    })
    return (assistant_block + "\n" + result_block + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_browser_specialist_returns_browser_output():
    """Mock subprocess returns stream-json → BrowserUseSpecialist returns BrowserOutput."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(_fake_stream_json_output("submitted"), b"")
        )

        with (
            patch(
                "teams.job_search._specialists._find_claude_binary",
                return_value="/usr/local/bin/claude",
            ),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            specialist = BrowserUseSpecialist(log_base_dir=base)
            out = await specialist.run(_make_browser_input())

    assert isinstance(out, BrowserOutput)
    assert out.status == BrowserStatus.SUBMITTED


@pytest.mark.asyncio
async def test_browser_specialist_dry_run_flag_in_output():
    """dry_run=True propagates through to BrowserOutput.dry_run."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(_fake_stream_json_output("submitted"), b"")
        )

        with (
            patch(
                "teams.job_search._specialists._find_claude_binary",
                return_value="/usr/local/bin/claude",
            ),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            out = await BrowserUseSpecialist(log_base_dir=base).run(
                _make_browser_input(dry_run=True)
            )

    assert out.dry_run is True


@pytest.mark.asyncio
async def test_browser_specialist_blocked_on_subprocess_error():
    """Non-zero subprocess exit → BrowserOutput with status=ERROR."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"claude: something went wrong")
        )

        with (
            patch(
                "teams.job_search._specialists._find_claude_binary",
                return_value="/usr/local/bin/claude",
            ),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            out = await BrowserUseSpecialist(log_base_dir=base).run(
                _make_browser_input()
            )

    assert out.status == BrowserStatus.ERROR


@pytest.mark.asyncio
async def test_browser_specialist_emits_browser_started_event():
    """JSONL log contains a browser_started event."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(_fake_stream_json_output("submitted"), b"")
        )
        inp = _make_browser_input()

        with (
            patch(
                "teams.job_search._specialists._find_claude_binary",
                return_value="/usr/local/bin/claude",
            ),
            patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            await BrowserUseSpecialist(log_base_dir=base).run(inp)

        log_path = _conversation_log_path(inp.run_id, base_dir=base)
        lines = [json.loads(ln) for ln in log_path.read_text().splitlines()]
        events = [ln["event"] for ln in lines]

        assert "browser_started" in events


@pytest.mark.asyncio
async def test_browser_specialist_max_turns_passed_to_subprocess():
    """--max-turns <N> appears in the subprocess command."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        captured_cmd: list[str] = []

        async def fake_exec(*args: str, **kwargs):  # noqa: ANN001, ANN202
            captured_cmd.extend(args)
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(
                return_value=(_fake_stream_json_output("submitted"), b"")
            )
            return mock_proc

        with (
            patch(
                "teams.job_search._specialists._find_claude_binary",
                return_value="/usr/local/bin/claude",
            ),
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
        ):
            await BrowserUseSpecialist(log_base_dir=base).run(
                _make_browser_input(max_turns=40)
            )

    assert "--max-turns" in captured_cmd
    turns_idx = captured_cmd.index("--max-turns")
    assert captured_cmd[turns_idx + 1] == "40"
