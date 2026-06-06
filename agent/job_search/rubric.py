"""A-F rubric scoring engine for job listings.

Loads the operator-approved rubric (config/rubric.yaml) and evaluates a
JobListing against it via a Haiku subprocess call. Returns a frozen
``RubricResult`` with letter grade, weighted score, per-dimension scores,
rationale, and cost.

Concept-only port (career-ops, MIT). Subprocess invocation pattern is
modeled on ``cover_letter.generate_cover_letter`` and reuses the same
``claude -p`` stream-json plumbing. No code copied verbatim.

Sprint 06.02 of the 2026-04-25 reference-audit bundle. Engine only —
pipeline wiring lives in Sprint 06.03.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from bridge.cost_tracker import (
    parse_claude_stream_json_cost,
)
from bridge.paths import data_root

from .boards.base import JobListing
from .criteria import Candidate

log = logging.getLogger(__name__)

SECRETS_PATH = data_root() / ".secrets"
DEFAULT_RUBRIC_PATH = Path(__file__).parent / "config" / "rubric.yaml"
TIMEOUT_SECONDS = 120
COST_CAP_USD = 0.05
DEFAULT_MODEL = "claude-haiku-4-5"

_VALID_GRADES = ("A", "B", "C", "D", "F")
_SCORE_MIN = 1
_SCORE_MAX = 5


# ---------------------------------------------------------------------------
# Frozen dataclasses (matches JobListing style — no Pydantic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RubricDimension:
    """One scoring dimension from the operator-approved rubric."""

    name: str
    weight: float
    eval_prompt_fragment: str
    score_anchors: dict[int, str] = field(default_factory=dict)
    letter_grade_thresholds: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Rubric:
    """A frozen tuple of dimensions loaded from rubric.yaml."""

    dimensions: tuple[RubricDimension, ...]

    @classmethod
    def load_from_yaml(cls, path: Path | str = DEFAULT_RUBRIC_PATH) -> "Rubric":
        """Load and validate the rubric YAML file.

        Raises:
            FileNotFoundError: if path does not exist.
            ValueError: if structure is invalid or weights don't sum to 1.0.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Rubric YAML not found: {p}")
        data = yaml.safe_load(p.read_text())
        if not isinstance(data, dict) or "dimensions" not in data:
            raise ValueError("rubric.yaml must contain a top-level 'dimensions' key")

        raw_dims = data["dimensions"]
        if not isinstance(raw_dims, list) or not raw_dims:
            raise ValueError("rubric.yaml 'dimensions' must be a non-empty list")

        dims: list[RubricDimension] = []
        for entry in raw_dims:
            if not isinstance(entry, dict):
                raise ValueError(f"Invalid dimension entry (not a mapping): {entry!r}")
            name = entry.get("name")
            weight = entry.get("weight")
            fragment = entry.get("eval_prompt_fragment", "")
            anchors_raw = entry.get("score_anchors", {}) or {}
            thresholds_raw = entry.get("letter_grade_thresholds", {}) or {}

            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Dimension missing 'name': {entry!r}")
            if not isinstance(weight, (int, float)):
                raise ValueError(f"Dimension '{name}' missing numeric 'weight'")

            # Coerce keys to int / str respectively (YAML may give us str keys)
            anchors = {int(k): str(v) for k, v in anchors_raw.items()}
            thresholds = {str(k): float(v) for k, v in thresholds_raw.items()}

            dims.append(
                RubricDimension(
                    name=name.strip(),
                    weight=float(weight),
                    eval_prompt_fragment=str(fragment),
                    score_anchors=anchors,
                    letter_grade_thresholds=thresholds,
                )
            )

        total = sum(d.weight for d in dims)
        # Allow tiny float drift (e.g. 0.999999) but reject anything materially off.
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Rubric dimension weights must sum to 1.0; got {total:.6f}"
            )

        return cls(dimensions=tuple(dims))

    def thresholds(self) -> dict[str, float]:
        """Return the canonical letter-grade thresholds.

        The rubric.yaml format anchors thresholds per-dimension but in
        practice they are shared across all dimensions via a YAML anchor.
        We pull from the first dimension and fall back to a sane default
        if absent.
        """
        if self.dimensions and self.dimensions[0].letter_grade_thresholds:
            return dict(self.dimensions[0].letter_grade_thresholds)
        return {"A": 4.5, "B": 3.5, "C": 2.5, "D": 1.5, "F": 0.0}


@dataclass(frozen=True)
class RubricResult:
    """Output of evaluating a listing against a rubric."""

    letter_grade: str
    weighted_score: float
    per_dim_scores: dict[str, int]
    per_dim_rationale: dict[str, str]
    model_used: str
    cost_usd: float
    evaluated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_oauth_token(secrets_path: Path = SECRETS_PATH) -> str:
    """Load CLAUDE_CODE_OAUTH_TOKEN from .secrets (mirrors cover_letter)."""
    if not secrets_path.exists():
        return ""
    for raw in secrets_path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("claude_oauth_token="):
            return line.split("=", 1)[1].strip()
    return ""


def _find_claude_binary() -> str:
    """Locate the claude binary (mirrors cover_letter)."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("Claude Code binary not found")


def _build_prompt(
    listing: JobListing, candidate: Candidate, rubric: Rubric
) -> str:
    """Build a single Haiku prompt that asks for JSON-shaped scores.

    Truncates description to 2500 chars to stay well under any window.
    """
    desc = (listing.description or "")[:2500] or "(no description)"
    comp = listing.compensation or "(unstated)"
    location = listing.location or "(unstated)"
    remote = listing.remote or "(unstated)"

    cand_skills = ", ".join(candidate.skills[:10]) if candidate.skills else "(none listed)"

    dims_block_parts: list[str] = []
    for dim in rubric.dimensions:
        anchors = "\n".join(
            f"      {n}: {text}" for n, text in sorted(dim.score_anchors.items())
        )
        dims_block_parts.append(
            f"- name: {dim.name}\n"
            f"  question: {dim.eval_prompt_fragment}\n"
            f"  anchors:\n{anchors}"
        )
    dims_block = "\n".join(dims_block_parts)

    dim_names = [d.name for d in rubric.dimensions]
    schema_example = {
        n: {"score": 3, "rationale": "<one sentence>"} for n in dim_names
    }

    return (
        "You are scoring a job listing against a fixed rubric on behalf of a "
        "career-ops engine. Be concise and grounded in the listing text.\n\n"
        f"## Candidate\n"
        f"- Name: {candidate.name or '(unknown)'}\n"
        f"- Years experience: {candidate.years_experience}\n"
        f"- Skills: {cand_skills}\n"
        f"- Portfolio: {candidate.portfolio_url or '(none)'}\n\n"
        f"## Listing\n"
        f"- Title: {listing.title}\n"
        f"- Company: {listing.company}\n"
        f"- Location: {location}\n"
        f"- Remote: {remote}\n"
        f"- Compensation: {comp}\n"
        f"- Description (truncated):\n{desc}\n\n"
        f"## Rubric (score each dimension 1-5 using the anchors)\n"
        f"{dims_block}\n\n"
        "## Output\n"
        "Return ONLY a single JSON object — no markdown fences, no prose. "
        "Each dimension key must contain an integer 'score' in [1,5] and a "
        "one-sentence 'rationale' grounded in the listing text. Shape:\n"
        f"{json.dumps(schema_example)}\n"
    )


def _extract_payload(stdout: str) -> tuple[str | None, float]:
    """Extract (result_text, cost_usd) from claude stream-json NDJSON output.

    Sprint audit-2026-05-16.D.07 (#2068) — the cost half is now parsed by
    the shared :func:`bridge.cost_tracker.parse_claude_stream_json_cost`
    so this engine and the experiment-loop validator runner stop diverging
    on what the result-event shape looks like. The text half stays here
    because the assistant-text fallback is rubric-specific (only this
    engine cares about the last assistant chunk when the result event
    omits ``result``).

    Returns ``(None, cost)`` when no result text was produced. ``cost`` is
    a measured float when the result event carried ``cost_usd``;
    ``float('nan')`` when the shared parser returned ``source='unknown'``
    (no result event, missing cost field, malformed value). A NaN sentinel
    keeps the legacy ``(str | None, float)`` signature intact while
    refusing the SW-3 collapse the D.01 contract exists to prevent —
    callers comparing ``cost > cap`` get ``False`` for unknown, not a
    silent zero. ``_failed_result(model, cost, ...)`` stores the NaN on
    ``RubricResult.cost_usd`` so downstream observability can still see
    "this rubric run produced no measurable cost" without conflating it
    with a measured zero.
    """
    text_parts: list[str] = []
    result_text = ""

    # Text extraction stays inline — rubric-specific assistant-text
    # fallback. The shared parser handles the cost field below.
    for raw in stdout.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue

        msg_type = data.get("type", "")
        if msg_type == "assistant":
            message = data.get("message", {})
            if isinstance(message, dict):
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
        elif msg_type == "result":
            result_text = data.get("result", "") or ""

    # Cost: delegate to the shared parser. ``backend="claude"`` matches
    # the binary this engine invokes (haiku model, claude backend). The
    # parser tolerates the same total_cost_usd legacy spelling the old
    # ad-hoc code accepted, but the runtime stream always carries
    # ``cost_usd`` — total_cost_usd was a defensive fallback that never
    # actually fired (verified by grepping the Claude CLI source).
    measurement = parse_claude_stream_json_cost(stdout, backend="claude")
    if measurement.source == "measured" and measurement.amount_usd is not None:
        cost_value: float = float(measurement.amount_usd)
    else:
        # ``unknown`` (or estimated, which the runtime stream never
        # produces — Claude always emits cost_usd in the result event).
        # Log so the operator sees the failure mode; use NaN as the
        # legacy-float carrier so the SW-3 collapse to 0.0 is avoided.
        log.warning(
            "rubric: subprocess cost unknown (no result event or missing "
            "cost_usd field) — recording RubricResult.cost_usd=NaN instead "
            "of silent zero (SW-3 invariant)",
        )
        cost_value = float("nan")

    if result_text:
        return result_text, cost_value
    if text_parts:
        return text_parts[-1], cost_value
    return None, cost_value


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` fences if the model added them anyway."""
    s = text.strip()
    if s.startswith("```"):
        # Drop opening fence (with or without language tag).
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _clamp_score(raw: Any) -> int:
    """Coerce an arbitrary value into the integer score range [1,5]."""
    try:
        n = int(round(float(raw)))
    except (TypeError, ValueError):
        return _SCORE_MIN
    if n < _SCORE_MIN:
        return _SCORE_MIN
    if n > _SCORE_MAX:
        return _SCORE_MAX
    return n


def _grade_for_score(weighted: float, thresholds: dict[str, float]) -> str:
    """Map a weighted score to a letter grade using descending thresholds.

    Order is fixed A > B > C > D > F (the YAML uses this convention).
    Falls back to F if no threshold matches (defensive).
    """
    for grade in _VALID_GRADES:
        if grade in thresholds and weighted >= thresholds[grade]:
            return grade
    return "F"


def _failed_result(model: str, cost: float, reason: str) -> RubricResult:
    return RubricResult(
        letter_grade="F",
        weighted_score=0.0,
        per_dim_scores={},
        per_dim_rationale={"error": reason},
        model_used=model,
        cost_usd=cost,
        evaluated_at=datetime.now(timezone.utc),
    )


def _parse_llm_output(
    raw_text: str, rubric: Rubric, model: str, cost: float
) -> RubricResult:
    """Parse the JSON returned by Haiku into a RubricResult.

    Defensive: any malformed shape returns letter F with rubric_parse_failed.
    """
    cleaned = _strip_json_fences(raw_text or "")
    if not cleaned:
        return _failed_result(model, cost, "rubric_parse_failed")

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("rubric: malformed JSON from LLM (len=%d)", len(cleaned))
        return _failed_result(model, cost, "rubric_parse_failed")

    if not isinstance(payload, dict):
        return _failed_result(model, cost, "rubric_parse_failed")

    per_scores: dict[str, int] = {}
    per_rationale: dict[str, str] = {}
    weighted = 0.0

    for dim in rubric.dimensions:
        entry = payload.get(dim.name)
        if not isinstance(entry, dict):
            # Missing dimension — treat as floor score (1) with explicit note.
            per_scores[dim.name] = _SCORE_MIN
            per_rationale[dim.name] = "missing_from_llm_output"
            weighted += dim.weight * _SCORE_MIN
            continue
        score = _clamp_score(entry.get("score"))
        rationale = str(entry.get("rationale") or "").strip() or "(no rationale)"
        per_scores[dim.name] = score
        per_rationale[dim.name] = rationale
        weighted += dim.weight * score

    grade = _grade_for_score(weighted, rubric.thresholds())
    return RubricResult(
        letter_grade=grade,
        weighted_score=round(weighted, 4),
        per_dim_scores=per_scores,
        per_dim_rationale=per_rationale,
        model_used=model,
        cost_usd=cost,
        evaluated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def evaluate(
    listing: JobListing,
    candidate: Candidate,
    rubric: Rubric,
    *,
    secrets_path: Path = SECRETS_PATH,
    timeout: int = TIMEOUT_SECONDS,
    model: str = DEFAULT_MODEL,
    cost_cap_usd: float = COST_CAP_USD,
) -> RubricResult:
    """Score a listing against the rubric using a Haiku subprocess call.

    Never raises — failures collapse to a letter-F result with an error
    rationale. Logs a warning if measured cost exceeds ``cost_cap_usd``.
    """
    try:
        binary = _find_claude_binary()
    except FileNotFoundError as e:
        log.error("rubric: claude binary not found: %s", e)
        return _failed_result(model, 0.0, "claude_binary_not_found")

    prompt = _build_prompt(listing, candidate, rubric)

    cmd = [
        binary,
        "-p",
        "--verbose",
        "--output-format", "stream-json",
        "--max-turns", "1",
        "--model", model,
        "--dangerously-skip-permissions",
    ]

    env = os.environ.copy()
    token = _load_oauth_token(secrets_path)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        log.error(
            "rubric: subprocess timed out (%ds) for '%s' @ %s",
            timeout, listing.title, listing.company,
        )
        return _failed_result(model, 0.0, "subprocess_timeout")
    except Exception as e:  # pragma: no cover — defensive net
        log.error("rubric: subprocess error for '%s': %s", listing.title, e)
        return _failed_result(model, 0.0, "subprocess_error")

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        log.error(
            "rubric: subprocess failed (exit=%d) for '%s': %s",
            proc.returncode, listing.title, stderr[:500],
        )
        return _failed_result(model, 0.0, "subprocess_nonzero_exit")

    text, cost = _extract_payload(stdout)
    if cost > cost_cap_usd:
        log.warning(
            "rubric: cost cap exceeded (%.4f > %.4f) for '%s' @ %s",
            cost, cost_cap_usd, listing.title, listing.company,
        )

    if text is None:
        return _failed_result(model, cost, "rubric_parse_failed")

    return _parse_llm_output(text, rubric, model, cost)
