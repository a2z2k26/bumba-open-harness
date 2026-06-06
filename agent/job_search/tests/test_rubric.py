"""Tests for the A-F rubric scoring engine (Sprint 06.02)."""
from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_search.boards.base import JobListing
from job_search.criteria import Candidate
from job_search.rubric import (
    DEFAULT_RUBRIC_PATH,
    Rubric,
    RubricDimension,
    RubricResult,
    _clamp_score,
    _grade_for_score,
    _parse_llm_output,
    evaluate,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _listing(**kw) -> JobListing:
    defaults = {
        "url": "https://example.com/jobs/1",
        "title": "Senior Design Engineer",
        "company": "Acme Corp",
        "board": "remotive",
        "location": "Remote",
        "remote": "yes",
        "compensation": "$180k + equity",
        "description": "Build distinctive UI for our design tooling product.",
    }
    defaults.update(kw)
    return JobListing(**defaults)


def _candidate(**kw) -> Candidate:
    c = Candidate(
        name="Example User",
        years_experience=10,
        skills=["TypeScript", "React", "Python", "SwiftUI"],
        portfolio_url="https://portfolio.example.com",
    )
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _rubric_yaml(path: Path) -> Path:
    """Write a small valid rubric.yaml to ``path`` and return it."""
    path.write_text(
        """
dimensions:
  - name: dim-a
    weight: 0.5
    eval_prompt_fragment: "Question A?"
    score_anchors:
      1: low
      5: high
    letter_grade_thresholds: &t
      A: 4.5
      B: 3.5
      C: 2.5
      D: 1.5
      F: 0.0
  - name: dim-b
    weight: 0.5
    eval_prompt_fragment: "Question B?"
    score_anchors:
      1: low
      5: high
    letter_grade_thresholds: *t
""".lstrip()
    )
    return path


def _stream_json(payload: dict, cost_usd: float = 0.01) -> str:
    """Render an NDJSON stream that mimics ``claude -p`` output."""
    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "result": json.dumps(payload),
            "is_error": False,
            "cost_usd": cost_usd,
            "session_id": "s1",
        }),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rubric loading
# ---------------------------------------------------------------------------


class TestRubricLoadsYaml:
    def test_loads_real_rubric_yaml_from_main(self):
        """The operator-approved rubric.yaml shipped in 06.01 must load."""
        assert DEFAULT_RUBRIC_PATH.exists(), DEFAULT_RUBRIC_PATH
        r = Rubric.load_from_yaml(DEFAULT_RUBRIC_PATH)
        assert len(r.dimensions) == 10
        # Operator stated dimension names — verify a couple are present.
        names = {d.name for d in r.dimensions}
        assert "role-design-engineering-fit" in names
        assert "comp-band-fit" in names

    def test_real_rubric_weights_sum_to_one(self):
        r = Rubric.load_from_yaml(DEFAULT_RUBRIC_PATH)
        total = sum(d.weight for d in r.dimensions)
        assert abs(total - 1.0) < 1e-6

    def test_load_rejects_weights_that_do_not_sum_to_one(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "dimensions:\n"
            "  - name: x\n"
            "    weight: 0.4\n"
            "    eval_prompt_fragment: q\n"
            "    score_anchors: {1: a, 5: b}\n"
            "    letter_grade_thresholds: {A: 4.5, F: 0.0}\n"
        )
        with pytest.raises(ValueError, match="sum to 1"):
            Rubric.load_from_yaml(bad)

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Rubric.load_from_yaml(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# Frozen invariant
# ---------------------------------------------------------------------------


class TestFrozenDataclasses:
    def test_dimension_is_frozen(self):
        d = RubricDimension(
            name="x", weight=1.0, eval_prompt_fragment="q",
            score_anchors={}, letter_grade_thresholds={},
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.weight = 0.5  # type: ignore[misc]

    def test_rubric_is_frozen(self, tmp_path):
        r = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.dimensions = ()  # type: ignore[misc]

    def test_result_is_frozen(self):
        from datetime import datetime, timezone
        rr = RubricResult(
            letter_grade="A", weighted_score=4.6,
            per_dim_scores={}, per_dim_rationale={},
            model_used="m", cost_usd=0.01,
            evaluated_at=datetime.now(timezone.utc),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rr.letter_grade = "F"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Letter-grade thresholds
# ---------------------------------------------------------------------------


class TestLetterGradeThresholds:
    def test_each_letter_threshold_resolves(self):
        thresholds = {"A": 4.5, "B": 3.5, "C": 2.5, "D": 1.5, "F": 0.0}
        assert _grade_for_score(4.6, thresholds) == "A"
        assert _grade_for_score(3.6, thresholds) == "B"
        assert _grade_for_score(2.6, thresholds) == "C"
        assert _grade_for_score(1.6, thresholds) == "D"
        assert _grade_for_score(1.0, thresholds) == "F"

    def test_boundary_at_threshold_is_inclusive(self):
        thresholds = {"A": 4.5, "B": 3.5, "C": 2.5, "D": 1.5, "F": 0.0}
        # Spec says "A >= 4.5" — exactly 4.5 must score A.
        assert _grade_for_score(4.5, thresholds) == "A"
        assert _grade_for_score(3.5, thresholds) == "B"


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------


class TestScoreClamping:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (0, 1),       # below floor
            (1, 1),
            (3, 3),
            (5, 5),
            (7, 5),       # above ceiling
            (-2, 1),
            ("4", 4),     # string coercion
            ("not-a-number", 1),
            (None, 1),
            (4.6, 5),     # rounds up
            (4.4, 4),
        ],
    )
    def test_clamps_to_one_to_five(self, raw, expected):
        assert _clamp_score(raw) == expected


# ---------------------------------------------------------------------------
# evaluate() — happy path
# ---------------------------------------------------------------------------


class TestEvaluateReturnsLetterGrade:
    @pytest.mark.asyncio
    async def test_canned_haiku_response_yields_grade_A(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=t\n")
        rubric = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))

        # Both dims score 5 -> weighted = 5.0 -> grade A.
        canned = {
            "dim-a": {"score": 5, "rationale": "perfect fit"},
            "dim-b": {"score": 5, "rationale": "perfect fit"},
        }
        stream = _stream_json(canned, cost_usd=0.012)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stream.encode(), b"")
        mock_proc.returncode = 0

        with patch("job_search.rubric._find_claude_binary", return_value="/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await evaluate(
                _listing(), _candidate(), rubric, secrets_path=secrets,
            )

        assert result.letter_grade == "A"
        assert result.weighted_score == pytest.approx(5.0)
        assert result.per_dim_scores == {"dim-a": 5, "dim-b": 5}
        assert "perfect fit" in result.per_dim_rationale["dim-a"]
        assert result.cost_usd == pytest.approx(0.012)

    @pytest.mark.asyncio
    async def test_deterministic_at_temp_zero(self, tmp_path):
        """Identical mocked Haiku output -> identical scores/grades."""
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=t\n")
        rubric = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))

        canned = {
            "dim-a": {"score": 4, "rationale": "ok"},
            "dim-b": {"score": 3, "rationale": "ok"},
        }
        stream = _stream_json(canned, cost_usd=0.008)

        async def _run() -> RubricResult:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (stream.encode(), b"")
            mock_proc.returncode = 0
            with patch("job_search.rubric._find_claude_binary", return_value="/bin/claude"), \
                 patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                return await evaluate(
                    _listing(), _candidate(), rubric, secrets_path=secrets,
                )

        r1 = await _run()
        r2 = await _run()
        assert r1.letter_grade == r2.letter_grade
        assert r1.weighted_score == r2.weighted_score
        assert r1.per_dim_scores == r2.per_dim_scores


# ---------------------------------------------------------------------------
# evaluate() — defensive paths
# ---------------------------------------------------------------------------


class TestEvaluateDefensive:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_F_with_parse_failed(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=t\n")
        rubric = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))

        # Result text is not valid JSON.
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s"}),
            json.dumps({
                "type": "result", "subtype": "success",
                "result": "not-valid-json{{{",
                "is_error": False, "cost_usd": 0.005, "session_id": "s",
            }),
        ])

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stream.encode(), b"")
        mock_proc.returncode = 0

        with patch("job_search.rubric._find_claude_binary", return_value="/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await evaluate(
                _listing(), _candidate(), rubric, secrets_path=secrets,
            )

        assert result.letter_grade == "F"
        assert result.per_dim_rationale == {"error": "rubric_parse_failed"}
        # Cost is still captured even on parse failure.
        assert result.cost_usd == pytest.approx(0.005)

    @pytest.mark.asyncio
    async def test_subprocess_nonzero_exit_returns_F(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=t\n")
        rubric = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"oauth fail")
        mock_proc.returncode = 2

        with patch("job_search.rubric._find_claude_binary", return_value="/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await evaluate(
                _listing(), _candidate(), rubric, secrets_path=secrets,
            )

        assert result.letter_grade == "F"
        assert result.per_dim_rationale["error"] == "subprocess_nonzero_exit"

    def test_parse_clamps_out_of_range_scores(self):
        rubric = Rubric(
            dimensions=(
                RubricDimension(
                    name="dim-a", weight=0.5, eval_prompt_fragment="q",
                    score_anchors={}, letter_grade_thresholds={
                        "A": 4.5, "B": 3.5, "C": 2.5, "D": 1.5, "F": 0.0,
                    },
                ),
                RubricDimension(
                    name="dim-b", weight=0.5, eval_prompt_fragment="q",
                    score_anchors={}, letter_grade_thresholds={
                        "A": 4.5, "B": 3.5, "C": 2.5, "D": 1.5, "F": 0.0,
                    },
                ),
            ),
        )
        raw = json.dumps({
            "dim-a": {"score": 99, "rationale": "x"},   # clamps to 5
            "dim-b": {"score": -3, "rationale": "y"},   # clamps to 1
        })
        result = _parse_llm_output(raw, rubric, model="m", cost=0.01)
        assert result.per_dim_scores == {"dim-a": 5, "dim-b": 1}
        # 0.5*5 + 0.5*1 = 3.0 -> grade C
        assert result.weighted_score == pytest.approx(3.0)
        assert result.letter_grade == "C"


# ---------------------------------------------------------------------------
# Cost cap warning
# ---------------------------------------------------------------------------


class TestCostCapWarning:
    @pytest.mark.asyncio
    async def test_logs_warning_when_cost_exceeds_cap(self, tmp_path, caplog):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=t\n")
        rubric = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))

        canned = {
            "dim-a": {"score": 3, "rationale": "ok"},
            "dim-b": {"score": 3, "rationale": "ok"},
        }
        # 0.20 dollars >> 0.05 cap.
        stream = _stream_json(canned, cost_usd=0.20)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stream.encode(), b"")
        mock_proc.returncode = 0

        with caplog.at_level(logging.WARNING, logger="job_search.rubric"), \
             patch("job_search.rubric._find_claude_binary", return_value="/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await evaluate(
                _listing(), _candidate(), rubric, secrets_path=secrets,
            )

        # Result is still produced — cost cap is observability, not a hard stop.
        assert result.letter_grade in ("A", "B", "C", "D", "F")
        assert any("cost cap exceeded" in m for m in caplog.messages)

    @pytest.mark.asyncio
    async def test_no_warning_when_cost_under_cap(self, tmp_path, caplog):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=t\n")
        rubric = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))

        canned = {
            "dim-a": {"score": 3, "rationale": "ok"},
            "dim-b": {"score": 3, "rationale": "ok"},
        }
        stream = _stream_json(canned, cost_usd=0.01)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stream.encode(), b"")
        mock_proc.returncode = 0

        with caplog.at_level(logging.WARNING, logger="job_search.rubric"), \
             patch("job_search.rubric._find_claude_binary", return_value="/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await evaluate(
                _listing(), _candidate(), rubric, secrets_path=secrets,
            )

        assert not any("cost cap exceeded" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-16.D.07 — shared subprocess cost parser (#2068)
# ---------------------------------------------------------------------------
#
# M-4: ``_extract_payload`` now delegates the cost half to the shared
# parser in ``bridge.cost_tracker.parse_claude_stream_json_cost``. Pin the
# two behaviours that diverged from the experiment-loop parser before:
#
#   1. A subprocess stream that carries ``cost_usd`` produces a measured
#      float on the RubricResult (no regression).
#   2. A subprocess stream that LACKS a parseable result event or cost
#      field records ``RubricResult.cost_usd = NaN`` instead of a silent
#      0.0 — the SW-3 invariant from the D.01 contract.


import math  # noqa: E402

from job_search.rubric import _extract_payload  # noqa: E402


class TestSharedCostParserWiring:
    """Audit-2026-05-16.D.07 — rubric consumes shared cost parser."""

    def test_extract_payload_measured_cost_passthrough(self):
        """When the stream carries cost_usd, _extract_payload returns the
        measured float — wired through ``parse_claude_stream_json_cost``."""
        canned = {"dim-a": {"score": 4, "rationale": "x"}}
        stream = _stream_json(canned, cost_usd=0.0123)
        text, cost = _extract_payload(stream)
        assert text is not None
        assert cost == pytest.approx(0.0123)
        assert not math.isnan(cost)

    def test_extract_payload_unknown_cost_returns_nan_not_zero(self, caplog):
        """SW-3 invariant: when the result event omits cost_usd, the
        legacy ``cost = 0.0`` fallback is gone. The function returns NaN
        AND logs a warning so the operator can see the unknown state."""
        # Stream with a result event but no cost_usd field.
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s"}),
            json.dumps({
                "type": "result", "subtype": "success",
                "result": json.dumps({"dim-a": {"score": 4, "rationale": "x"}}),
                "is_error": False, "session_id": "s",
                # cost_usd intentionally absent.
            }),
        ])
        with caplog.at_level(logging.WARNING, logger="job_search.rubric"):
            text, cost = _extract_payload(stream)
        assert text is not None
        assert math.isnan(cost), (
            "missing cost_usd MUST surface as NaN, not 0.0 (SW-3 collapse)"
        )
        assert any(
            "cost unknown" in m or "SW-3" in m for m in caplog.messages
        ), "expected operator-visible warning when cost is unknown"

    def test_extract_payload_unknown_cost_when_no_result_event(self, caplog):
        """Stream with only assistant chunks and no terminal result event
        also collapses to NaN (timeout / crash mid-stream)."""
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s"}),
            json.dumps({
                "type": "assistant",
                "message": {"content": [
                    {"type": "text", "text": '{"dim-a": {"score": 3}}'},
                ]},
            }),
        ])
        with caplog.at_level(logging.WARNING, logger="job_search.rubric"):
            text, cost = _extract_payload(stream)
        # Assistant fallback recovered the text, but cost is unknown.
        assert text is not None
        assert math.isnan(cost)

    @pytest.mark.asyncio
    async def test_evaluate_records_measured_cost_via_shared_parser(self, tmp_path):
        """End-to-end: evaluate() returns RubricResult with the cost the
        shared parser produced from the result event."""
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=t\n")
        rubric = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))
        canned = {
            "dim-a": {"score": 5, "rationale": "x"},
            "dim-b": {"score": 5, "rationale": "x"},
        }
        stream = _stream_json(canned, cost_usd=0.042)
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stream.encode(), b"")
        mock_proc.returncode = 0
        with patch("job_search.rubric._find_claude_binary", return_value="/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await evaluate(
                _listing(), _candidate(), rubric, secrets_path=secrets,
            )
        assert result.cost_usd == pytest.approx(0.042)
        assert not math.isnan(result.cost_usd)

    @pytest.mark.asyncio
    async def test_evaluate_records_nan_cost_when_subprocess_lacks_cost(self, tmp_path):
        """End-to-end SW-3: when the subprocess produces a result event
        without cost_usd, the RubricResult carries NaN (not silent zero)."""
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=t\n")
        rubric = Rubric.load_from_yaml(_rubric_yaml(tmp_path / "r.yaml"))
        # Stream with a result event but no cost_usd.
        canned = {
            "dim-a": {"score": 5, "rationale": "x"},
            "dim-b": {"score": 5, "rationale": "x"},
        }
        stream = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s"}),
            json.dumps({
                "type": "result", "subtype": "success",
                "result": json.dumps(canned),
                "is_error": False, "session_id": "s",
                # cost_usd intentionally absent.
            }),
        ])
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stream.encode(), b"")
        mock_proc.returncode = 0
        with patch("job_search.rubric._find_claude_binary", return_value="/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await evaluate(
                _listing(), _candidate(), rubric, secrets_path=secrets,
            )
        assert math.isnan(result.cost_usd), (
            "RubricResult.cost_usd MUST be NaN (not 0.0) when subprocess "
            "omits cost_usd — preserves SW-3 invariant from D.01"
        )
