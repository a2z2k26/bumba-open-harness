"""Cost tracking for three-tier smart model routing (MS3.10).

Logs per-request cost data to ``data/cost_tracking.jsonl`` with atomic
writes, and provides daily/weekly summary aggregation.

Sprint 04.04 (issue #1005) — added a per-feature daily budget cap layer
that composes alongside the global daily budget enforcer in
``bridge.budget``. Each ``CostEntry`` may carry an optional ``feature``
label; ``CostTracker.check_feature_cap`` returns whether the next call
for a feature would breach its registered daily cap. Default Board cap
is $1.00/day, registered automatically when ``board_v2_enabled`` is True.

Sprint 02.09 (issue #984) — added an ``experiment_iter`` attribution tag
on ``CostEntry`` and a ``get_experiment_summary`` aggregation method so
operators can compute cost-per-fitness-improvement for the experiment
loop. Tag is independent of ``feature``: an entry can carry both, one,
or neither. Per-call (not global) — concurrent experiment + non-experiment
subprocesses don't race because the tag rides on the record() call.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)

# Sprint 02.09 — env var the experiment loop sets on every Claude
# subprocess invocation so cost recording inside that subprocess can
# attribute the call to a specific iteration without explicit wiring.
EXPERIMENT_ITER_ENV: str = "BUMBA_EXPERIMENT_ITER"

# Pricing per 1M tokens (input / output) — USD
PRICING: dict[str, tuple[float, float]] = {
    "haiku": (0.25, 1.25),
    "sonnet": (3.0, 15.0),
    "opus": (15.0, 75.0),
}

# Default per-feature daily cap (USD) for the Board of Directors deliberation
# path. Registered at CostTracker init when board_v2_enabled is True.
DEFAULT_BOARD_DAILY_CAP_USD: float = 1.00

# Model runtime validation default caps (VAL-16). These are intentionally
# conservative daemon/relaunch defaults; individual live validation sprints may
# set a lower explicit cap in their operator-approved command.
DEFAULT_OPENROUTER_DAILY_CAP_USD: Decimal = Decimal("1.00")
DEFAULT_OPENROUTER_SMOKE_CAP_USD: Decimal = Decimal("0.05")


@dataclass
class CostEntry:
    """Single cost log entry."""

    timestamp: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    task_type: str
    was_override: bool
    agent_id: str = ""
    # Sprint 04.04 — per-feature attribution. Empty string means
    # no feature attached (existing JSONL lines parse cleanly via dataclass
    # defaults).
    feature: str = ""
    session_id: str = ""
    # Sprint 02.09 — per-experiment attribution. Empty string means
    # the call did not originate from the experiment loop. Independent
    # of ``feature``: an entry may carry both, one, or neither.
    experiment_iter: str = ""
    # D2.5 — per-team attribution. Empty string = "unattributed" bucket.
    team: str = ""
    # WS3.1 (#2570) — per-workflow attribution. Empty string means no
    # workflow attached (existing JSONL lines parse cleanly via the
    # dataclass default). Independent of every other tag.
    workflow: str = ""
    # Z4-S40 — per-WorkOrder and per-ChiefSession attribution. Empty
    # string = "no work order attached" / "not a chief session call".
    # Independent of every other tag — an entry can carry any subset.
    # Keeping defaults as "" (not None) preserves the JSON shape so
    # existing tooling (rtk aggregator, baseline scripts) parses cleanly.
    work_order_id: str = ""
    chief_session_id: str = ""
    # Codex-6 (#1840) — per-backend attribution. Empty string is treated
    # as ``"claude"`` by the summary aggregators below for historical
    # accuracy: every pre-Codex entry was produced by the Claude backend.
    # Codex turns carry ``backend="codex"`` and ``estimated_cost=0.0``
    # (subscription-billed; per the #1841 broadcast we do NOT invent
    # per-token pricing for Codex). Token counts are still recorded so
    # the operator can see Codex utilization without a dollar figure.
    backend: str = ""


# ----------------------------------------------------------------------
# Sprint audit-2026-05-16.D.01 — CostMeasurement data contract (#2062)
# ----------------------------------------------------------------------
# SW-3 in docs/audits/2026-05-16-whole-codebase-audit-expanded.md flags that
# the bridge collapses four distinct cost-knowledge states into one number:
# (a) measured (a parser returned a confirmed amount, possibly zero),
# (b) estimated (we computed an amount from token pricing — not measured),
# (c) unknown (no parser produced a value; we have no idea), and
# (d) not_applicable (the call deliberately does not incur charge —
# subscription-billed, internal stub, etc.). When all four flatten into
# ``float | None`` with ``None`` and ``0.0`` interchangeable, budget gates
# cannot tell "this turn cost nothing" from "we lost track of this turn."
#
# ``CostMeasurement`` is the shared value object that keeps them distinct.
# This keystone introduces the type plus three conversion helpers; it does
# NOT wire it into existing recording paths. Downstream sprints
# audit-2026-05-16.D.02 / D.04 / D.06 / D.07 thread CostMeasurement through
# the backend parsers, validator subprocess accounting, and job-search
# parsing. Wiring before they ship would break the contract-only invariant.

CostSource = Literal["measured", "estimated", "unknown", "not_applicable"]


@dataclass(frozen=True)
class CostMeasurement:
    """Four-state cost-knowledge contract.

    Budget-gate semantics (callers should treat each state explicitly):

    - ``measured``: a parser returned a confirmed dollar amount (possibly
      ``Decimal('0')`` — e.g. a Codex subscription turn that genuinely cost
      no incremental USD). Strict budget gates count this against the cap.
    - ``estimated``: an amount derived from token pricing without per-call
      cost confirmation. Strict budget gates count this against the cap;
      operators may opt to flag estimated-only spend separately.
    - ``unknown``: no parser produced a value. The amount is ``None`` and
      MUST NOT be coerced to ``0.0`` downstream. Strict budget gates
      should refuse to charge an unknown — either fail-closed (block the
      call) or fail-open (allow but tag for forensic review). Pick one
      per surface; never silently treat it as zero.
    - ``not_applicable``: the call is structurally off-meter (internal
      stub, no-op service, subscription-only by design). The amount is
      ``None``. Strict gates exclude this from cap arithmetic but should
      log it so an unexpected drift in volume is visible.

    Equality and hashing are by-field (the dataclass default). Two
    ``CostMeasurement`` values are equal only when all four fields match,
    so ``unknown`` (amount=None, source='unknown') is never equal to a
    measured zero (amount=Decimal('0'), source='measured') — the exact
    invariant SW-3 calls out. Two unknown values are equal when their
    backends match and differ when they don't: the epistemic state
    "we don't know what the Codex backend charged" is not the same as
    "we don't know what the Claude backend charged."
    """

    amount_usd: Decimal | None
    source: CostSource
    backend: str
    raw_usage_id: str | None = None


BudgetDecisionReason = Literal[
    "within_cap",
    "over_cap",
    "unknown_cost",
    "not_applicable",
]


@dataclass(frozen=True)
class BudgetDecision:
    """Result of applying a strict cap to one cost measurement."""

    allowed: bool
    reason: BudgetDecisionReason
    source: CostSource
    amount_usd: Decimal | None
    cap_usd: Decimal | None


def from_legacy_float(
    value: float | None,
    *,
    backend: str,
    raw_usage_id: str | None = None,
) -> CostMeasurement:
    """Convert a legacy ``float | None`` cost value into a CostMeasurement.

    A concrete ``float`` (including ``0.0``) becomes ``source='measured'``
    — the legacy parser produced a number, so by definition that number
    was measured. A ``None`` becomes ``source='unknown'``; this is the
    collapse SW-3 exists to surface, NOT a measured zero.

    Args:
        value: Legacy cost in USD as a float, or ``None`` if the parser
            failed to produce a value.
        backend: Backend name (e.g. ``"claude"``, ``"codex"``). Required
            because the unknown-state equality semantics differ per
            backend — see ``CostMeasurement`` docstring.
        raw_usage_id: Optional opaque parser-side correlator (stream id,
            usage event id, etc.) for forensic trace.

    Returns:
        A frozen ``CostMeasurement`` carrying the source state explicitly.
    """
    if value is None:
        return CostMeasurement(
            amount_usd=None,
            source="unknown",
            backend=backend,
            raw_usage_id=None,
        )
    # ``Decimal(str(float))`` avoids binary-float widening artefacts
    # (``Decimal(0.1) == Decimal('0.1000000000000000055511151231257827021181583404541015625')``).
    return CostMeasurement(
        amount_usd=Decimal(str(value)),
        source="measured",
        backend=backend,
        raw_usage_id=raw_usage_id,
    )


def to_legacy_float(m: CostMeasurement) -> float | None:
    """Coerce a CostMeasurement back to ``float | None`` for legacy storage.

    Discipline: ``unknown`` and ``not_applicable`` MUST NOT silently
    return ``0.0`` (or any other comparable number). Either would re-
    introduce the SW-3 collapse this contract exists to prevent. Both
    raise ``ValueError`` so callers either widen their storage schema or
    consciously branch on the source state before recording.

    Args:
        m: The CostMeasurement to coerce.

    Returns:
        ``float`` for ``measured`` / ``estimated`` states.

    Raises:
        ValueError: when *m.source* is ``unknown`` or ``not_applicable``.
            The caller must handle the off-meter case explicitly.
    """
    if m.source in ("unknown", "not_applicable"):
        raise ValueError(
            f"Cannot coerce CostMeasurement(source={m.source!r}) to legacy "
            f"float — the off-meter state must be handled explicitly. "
            f"Either widen the storage schema or branch on source before "
            f"calling to_legacy_float()."
        )
    # By invariant of from_legacy_float and the dataclass field type,
    # measured/estimated states carry a non-None amount_usd. Belt-and-
    # suspenders: assert rather than silently float(None).
    if m.amount_usd is None:
        raise ValueError(
            f"CostMeasurement(source={m.source!r}) has amount_usd=None — "
            f"measured/estimated states must carry a Decimal amount."
        )
    return float(m.amount_usd)


def aggregate_measurements(
    measurements: list["CostMeasurement"],
) -> tuple[float, bool]:
    """Sum measured/estimated amounts; report whether any were unknown.

    Branches on the four-state ``source`` so the SW-3 collapse never recurs:
    an ``unknown`` measurement contributes ``0.0`` to the numeric total but
    flips ``had_unknown`` True, so callers can never mistake "we don't know
    what this cost" for "this was free." ``not_applicable`` (structurally
    off-meter) contributes nothing and is *not* an unknown — it is known to
    be off-meter by design.

    Args:
        measurements: CostMeasurements to aggregate.

    Returns:
        ``(total_usd, had_unknown)``. ``total_usd`` sums only the
        ``measured``/``estimated`` amounts; ``had_unknown`` is True iff at
        least one measurement carried ``source='unknown'``.
    """
    total = 0.0
    had_unknown = False
    for m in measurements:
        if m.source in ("measured", "estimated") and m.amount_usd is not None:
            total += float(m.amount_usd)
        elif m.source == "unknown":
            had_unknown = True
        # not_applicable: contributes nothing, not an unknown — skip silently.
    return total, had_unknown


def is_chargeable_under_strict_budget(m: CostMeasurement) -> bool:
    """Strict budget gate: does this measurement count against a cap?

    Returns ``True`` only when the source state names a known amount
    (``measured`` or ``estimated``). ``unknown`` and ``not_applicable``
    return ``False`` — the strict gate refuses to charge a value it
    cannot trust. Callers that want fail-closed behaviour (block the
    call when cost is unknown) should branch on this returning False AND
    the source being ``unknown`` (vs ``not_applicable``, which is
    structurally off-meter and should not block).
    """
    return m.source in ("measured", "estimated")


def evaluate_cost_measurement_against_cap(
    measurement: CostMeasurement,
    *,
    cap_usd: Decimal,
) -> BudgetDecision:
    """Apply the VAL-16 strict OpenRouter budget policy to one measurement.

    Measured and estimated costs are chargeable and must be at or below the
    cap. Unknown cost fails closed; it is never treated as zero. not_applicable
    is structurally off-meter and may pass without contributing to cap math.
    """
    if measurement.source == "unknown":
        return BudgetDecision(
            allowed=False,
            reason="unknown_cost",
            source=measurement.source,
            amount_usd=None,
            cap_usd=cap_usd,
        )
    if measurement.source == "not_applicable":
        return BudgetDecision(
            allowed=True,
            reason="not_applicable",
            source=measurement.source,
            amount_usd=None,
            cap_usd=cap_usd,
        )
    if measurement.amount_usd is None:
        return BudgetDecision(
            allowed=False,
            reason="unknown_cost",
            source=measurement.source,
            amount_usd=None,
            cap_usd=cap_usd,
        )
    if measurement.amount_usd > cap_usd:
        return BudgetDecision(
            allowed=False,
            reason="over_cap",
            source=measurement.source,
            amount_usd=measurement.amount_usd,
            cap_usd=cap_usd,
        )
    return BudgetDecision(
        allowed=True,
        reason="within_cap",
        source=measurement.source,
        amount_usd=measurement.amount_usd,
        cap_usd=cap_usd,
    )


# ----------------------------------------------------------------------
# Sprint audit-2026-05-16.D.07 — shared subprocess cost parser (#2068)
# ----------------------------------------------------------------------
# M-4 in docs/audits/2026-05-16-whole-codebase-audit-expanded.md flags that
# ``job_search/rubric.py::_extract_payload`` and ``experiment_loop.py``'s
# validator-subprocess parser are two ad-hoc implementations of the same
# logic. Both walk a Claude ``stream-json`` stdout, look for the terminal
# ``result`` event, and read ``cost_usd``. They diverge on edge cases
# (missing field, empty stdout, malformed value) and on how missing-cost
# is surfaced (one falls back to 0.0, the other to NaN).
#
# This is the shared, source-aware parser they both consume. Discipline:
#
# - ``cost_usd`` present and parseable → ``source='measured'`` (preserves
#   measured zero — Codex subscription-billed turns will eventually hit
#   this with ``Decimal('0')``).
# - ``cost_usd`` absent BUT a ``usage`` block with token counts is
#   present AND ``PRICING`` knows the backend → ``source='estimated'``.
# - No usable signal → ``source='unknown'`` with ``amount_usd=None``.
#   Callers MUST branch on the source state before recording; silent
#   coercion to ``0.0`` is the SW-3 collapse this contract prevents.
#
# Both helpers are module-level pure functions for testability. They do
# NOT mutate any tracker state — recording is the caller's responsibility.


_SUBPROCESS_COST_MISSING: object = object()
"""Module-level sentinel — distinguishes ``cost_usd`` key absent from
``cost_usd: None`` without colliding with any JSON-deserialised payload."""


def parse_subprocess_result_cost(
    event: dict,
    *,
    backend: str,
) -> CostMeasurement:
    """Convert a Claude ``-p`` result event into a CostMeasurement.

    The result event is the terminal ``{"type": "result", ...}`` line
    Claude Code emits once per ``-p`` invocation. This function is a
    pure transform — feed it the parsed dict and it returns the cost-
    knowledge state. The stream-walking helper
    :func:`parse_claude_stream_json_cost` calls this on the last result
    event it finds in the NDJSON stream.

    Args:
        event: The result event as a Python dict (already parsed from
            JSON). Non-dicts and event types other than ``result`` are
            still tolerated — they just collapse to ``unknown``.
        backend: Backend identifier (e.g. ``"claude"``, ``"codex"``,
            ``"haiku"``, ``"sonnet"``). Required for the unknown-state
            equality semantics AND for the ``PRICING`` lookup when the
            event lacks a measured ``cost_usd`` but carries a usage
            block. ``backend`` here is matched against the keys of
            :data:`PRICING` — pass the model tier name (haiku/sonnet/
            opus) when you want estimated-fallback to fire.

    Returns:
        A frozen :class:`CostMeasurement` carrying ``source`` explicitly.
        ``measured`` / ``estimated`` carry a non-None ``amount_usd``;
        ``unknown`` carries ``amount_usd=None``.
    """
    raw_usage_id: str | None = None
    if isinstance(event, dict):
        sid = event.get("session_id")
        if isinstance(sid, str) and sid:
            raw_usage_id = sid

    if not isinstance(event, dict):
        return CostMeasurement(
            amount_usd=None, source="unknown",
            backend=backend, raw_usage_id=raw_usage_id,
        )

    # First branch: explicit ``cost_usd`` field → measured.
    cost_raw = event.get("cost_usd", _SUBPROCESS_COST_MISSING)
    if cost_raw is not _SUBPROCESS_COST_MISSING and cost_raw is not None:
        try:
            amount = Decimal(str(cost_raw))
        except (ArithmeticError, ValueError, TypeError):
            # Malformed value (e.g. "n/a", object()) — fall through to
            # the unknown branch rather than fake a measured zero.
            amount = None  # type: ignore[assignment]
        if amount is not None:
            return CostMeasurement(
                amount_usd=amount, source="measured",
                backend=backend, raw_usage_id=raw_usage_id,
            )

    # Second branch: no cost_usd, but a usage block with token counts.
    # Estimate from PRICING if the backend is known; otherwise unknown.
    usage = event.get("usage")
    if isinstance(usage, dict):
        in_tok = usage.get("input_tokens")
        out_tok = usage.get("output_tokens")
        if isinstance(in_tok, int) and isinstance(out_tok, int):
            key = backend.lower()
            if key in PRICING:
                input_price, output_price = PRICING[key]
                # Float arithmetic mirrors ``estimate_cost`` above, then
                # widens via ``str()`` to dodge binary-float artefacts.
                est = (in_tok * input_price + out_tok * output_price) / 1_000_000
                return CostMeasurement(
                    amount_usd=Decimal(str(est)),
                    source="estimated",
                    backend=backend,
                    raw_usage_id=raw_usage_id,
                )

    # Third branch: no signal we can trust.
    return CostMeasurement(
        amount_usd=None, source="unknown",
        backend=backend, raw_usage_id=raw_usage_id,
    )


def parse_claude_stream_json_cost(
    stdout: str,
    *,
    backend: str = "claude",
) -> CostMeasurement:
    """Walk Claude ``-p --output-format stream-json`` stdout for cost.

    Reads every NDJSON line, keeps the last ``type == "result"`` event,
    and delegates to :func:`parse_subprocess_result_cost`. Non-JSON
    lines (rare; stderr leaking onto stdout) are silently skipped — they
    do NOT collapse the result to unknown when a real result event is
    also present.

    Args:
        stdout: The raw subprocess stdout. Empty / whitespace-only input
            returns ``source='unknown'``.
        backend: Backend identifier; see
            :func:`parse_subprocess_result_cost`.

    Returns:
        A :class:`CostMeasurement`. ``unknown`` when no parseable result
        event survives the scan.
    """
    if not stdout or not stdout.strip():
        return CostMeasurement(
            amount_usd=None, source="unknown",
            backend=backend, raw_usage_id=None,
        )

    last_result: dict | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            # Keep the last result event seen. Claude currently emits
            # one per ``-p`` invocation; defensive against future
            # multi-result streams.
            last_result = event

    if last_result is None:
        return CostMeasurement(
            amount_usd=None, source="unknown",
            backend=backend, raw_usage_id=None,
        )
    return parse_subprocess_result_cost(last_result, backend=backend)


@dataclass(frozen=True)
class FeatureCostSummary:
    """Per-feature aggregated cost summary."""

    feature: str
    period: str
    total_cost: float
    request_count: int
    by_model: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentCostSummary:
    """Per-experiment-iteration aggregated cost summary (Sprint 02.09).

    ``started_at`` and ``ended_at`` are the ISO-8601 timestamps of the first
    and last cost entry attributed to *iter_id*. They are empty strings when
    no entries match (zero-spend summary).
    """

    iter_id: str
    total_usd: float
    call_count: int
    started_at: str = ""
    ended_at: str = ""
    model_breakdown: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class RtkGainSummary:
    """Token savings reported by rtk for a period."""

    tokens_saved: int
    dollars_saved_estimated: float
    period_start: str  # ISO-8601
    period_end: str  # ISO-8601


def read_rtk_gain(period: str = "1d") -> "RtkGainSummary | None":
    """Call `rtk gain --json --period <period>` and parse the result.

    Returns None if rtk is not installed, times out, or returns unexpected JSON.
    Never raises.
    """
    import shutil
    import subprocess

    if not shutil.which("rtk"):
        return None
    try:
        result = subprocess.run(
            ["rtk", "gain", "--json", "--period", period],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            log.debug("rtk gain exited %d: %s", result.returncode, result.stderr[:200])
            return None
        data = json.loads(result.stdout)
        return RtkGainSummary(
            tokens_saved=int(data.get("tokens_saved", 0)),
            dollars_saved_estimated=float(data.get("dollars_saved_estimated", 0.0)),
            period_start=str(data.get("period_start", "")),
            period_end=str(data.get("period_end", "")),
        )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        log.debug("read_rtk_gain failed: %s", exc)
        return None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    increment_module_counter("cost_tracker.estimate_cost", tier=0)
    """Calculate estimated cost in USD for a request.

    Args:
        model: Model tier name (haiku/sonnet/opus).
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    key = model.lower()
    if key not in PRICING:
        log.warning("Unknown model tier '%s', defaulting to sonnet pricing", model)
        key = "sonnet"
    input_price, output_price = PRICING[key]
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


class CostTracker:
    """Append-only JSONL cost logger with summary methods.

    Args:
        data_dir: Directory where ``cost_tracking.jsonl`` will be stored.
        feature_caps_enabled: When True, ``check_feature_cap`` enforces
            registered per-feature daily caps. When False (default), it
            always returns ``(True, "")`` — bypass mode. Composes with the
            global daily-budget enforcement in ``bridge.budget`` rather
            than replacing it.
        board_v2_enabled: When True at construction, register the
            DEFAULT_BOARD_DAILY_CAP_USD (= $1.00) cap for ``feature="board"``.
            Operators can override at runtime via ``register_feature_cap``.
    """

    FILENAME = "cost_tracking.jsonl"

    def __init__(
        self,
        data_dir: str | Path,
        feature_caps_enabled: bool = False,
        board_v2_enabled: bool = False,
        team_limits: dict[str, float] | None = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / self.FILENAME
        self._feature_caps_enabled: bool = feature_caps_enabled
        self._feature_caps: dict[str, float] = {}
        if board_v2_enabled:
            # Default Board cap is auto-registered when the v2 board is on.
            # Operator can re-tune via register_feature_cap() at runtime.
            self._feature_caps["board"] = DEFAULT_BOARD_DAILY_CAP_USD
        self._team_limits: dict[str, float] = dict(team_limits or {})

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        task_type: str = "",
        was_override: bool = False,
        agent_id: str = "",
        session_id: str = "",
        feature: str = "",
        experiment_iter: str = "",
        team: str = "",
        work_order_id: str = "",
        chief_session_id: str = "",
        backend: str = "",
        workflow: str = "",
    ) -> CostEntry:
        """Record a cost entry with atomic JSONL append.

        Args:
            model: Model tier (haiku/sonnet/opus).
            input_tokens: Input token count.
            output_tokens: Output token count.
            task_type: Free-form label for the task (e.g. "code_review").
            was_override: True if the user forced this tier via @override.
            agent_id: Identifier for the agent that incurred this cost.
            session_id: Identifier for the session this cost belongs to.
            feature: Optional feature label for per-feature aggregation
                and per-feature daily cap enforcement (Sprint 04.04).
                Empty string means no feature is attached.
            experiment_iter: Optional iteration id from the experiment loop
                (Sprint 02.09). Empty string means the call did not
                originate from an experiment iteration. Independent of
                ``feature`` — an entry may carry both, one, or neither.
            work_order_id: Optional WorkOrder id (Z4-S40). Empty string
                means the call is not attached to a WorkOrder.
            chief_session_id: Optional ChiefSession id (Z4-S40). Empty
                string means the call did not originate from a chief
                session. Pairs with ``get_session_cost`` for per-session
                cost extraction by ``WarmChief``.
            backend: Optional backend name (Codex-6, #1840). Typical
                values are ``"claude"`` and ``"codex"``. Empty string
                means "unattributed" — the summary aggregators bucket
                this as ``"claude"`` for historical accuracy. For
                ``"codex"``, ``estimated_cost`` will be ``0.0``
                regardless of token counts (subscription-billed; per
                the #1841 broadcast we do NOT invent per-token pricing
                for Codex turns).
            workflow: Optional workflow label (WS3.1, #2570) for
                per-workflow aggregation. Empty string means no
                workflow is attached. Independent of every other tag.

        Returns:
            The recorded CostEntry.
        """
        # Codex-6 (#1840): Codex turns are subscription-billed — track
        # token-count but force estimated_cost to 0.0 regardless of model
        # pricing. Pre-existing Claude behaviour unchanged (empty backend
        # falls through to the standard PRICING-based estimate).
        if backend == "codex":
            cost = 0.0
        else:
            cost = estimate_cost(model, input_tokens, output_tokens)
        # Sprint 02.09 — fall back to env-var attribution when the caller
        # doesn't pass an explicit iter id. Lets the bridge daemon record
        # cost entries for cost incurred inside an experiment-loop-spawned
        # subprocess without each call site threading the kwarg through.
        if not experiment_iter:
            experiment_iter = os.environ.get(EXPERIMENT_ITER_ENV, "")
        entry = CostEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model.lower(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            task_type=task_type,
            was_override=was_override,
            agent_id=agent_id,
            feature=feature,
            session_id=session_id,
            experiment_iter=experiment_iter,
            team=team,
            work_order_id=work_order_id,
            chief_session_id=chief_session_id,
            backend=backend,
            workflow=workflow,
        )
        self._atomic_append(entry)
        log.debug("Cost recorded: %s %d/%d tokens $%.6f", model, input_tokens, output_tokens, cost)
        return entry

    def _atomic_append(self, entry: CostEntry) -> None:
        """Atomically append a JSONL line using write-to-temp + rename/append."""
        line = json.dumps(asdict(entry)) + "\n"
        # Use direct append with os-level write for atomicity of a single line
        fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    # ------------------------------------------------------------------
    # Read / summarize
    # ------------------------------------------------------------------

    # Fields the dataclass knows about — recomputed lazily via
    # ``CostEntry.__dataclass_fields__`` to keep this in sync if the schema
    # ever evolves again (e.g. Sprint 02.09 ``experiment_iter``).
    @classmethod
    def _known_entry_fields(cls) -> set[str]:
        return set(CostEntry.__dataclass_fields__.keys())

    def _read_entries(self) -> list[CostEntry]:
        """Read all entries from the JSONL file.

        Tolerates legacy lines: unknown keys are dropped; missing keys
        with dataclass defaults (``agent_id``, ``feature``, ``session_id``)
        fall back to those defaults so older lines parse cleanly.
        """
        entries: list[CostEntry] = []
        if not self._path.exists():
            return entries
        known = self._known_entry_fields()
        with open(self._path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    log.warning("Skipping malformed line %d in %s: %s", lineno, self._path, exc)
                    continue
                # Drop any keys the dataclass doesn't know about so a
                # forward-compatible writer (e.g. 02.09 experiment_iter
                # written before this branch lands in runtime) doesn't
                # blow up the reader. Missing keys fall through to
                # dataclass defaults.
                filtered = {k: v for k, v in data.items() if k in known}
                try:
                    entries.append(CostEntry(**filtered))
                except TypeError as exc:
                    log.warning("Skipping malformed line %d in %s: %s", lineno, self._path, exc)
        return entries

    def get_daily_summary(self) -> dict:
        """Summarize costs for the current UTC day.

        Returns:
            Dict with keys: date, total_cost, total_input_tokens,
            total_output_tokens, request_count, by_model, and optionally
            rtk_savings when rtk is installed.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        summary = self._summarize_for_date_prefix(today)
        rtk = read_rtk_gain("1d")
        if rtk is not None:
            summary["rtk_savings"] = {
                "tokens_saved": rtk.tokens_saved,
                "dollars_saved_estimated": rtk.dollars_saved_estimated,
                "period": "1d",
            }
        return summary

    def get_weekly_summary(self) -> dict:
        """Summarize costs for the last 7 days (rolling).

        Returns:
            Dict with keys: period, total_cost, total_input_tokens,
            total_output_tokens, request_count, by_model, by_day.
        """
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - 7 * 86400
        entries = self._read_entries()

        total_cost = 0.0
        total_in = 0
        total_out = 0
        by_model: dict[str, dict] = {}
        by_day: dict[str, dict] = {}
        # Codex-6 (#1840): per-backend weekly aggregate. Same bucket
        # shape as the daily summary's by_backend so the /cost
        # formatter renders identically across the two windows.
        by_backend: dict[str, dict] = {}
        count = 0

        for e in entries:
            try:
                ts = datetime.fromisoformat(e.timestamp).timestamp()
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                continue
            count += 1
            total_cost += e.estimated_cost
            total_in += e.input_tokens
            total_out += e.output_tokens

            # By model
            m = by_model.setdefault(e.model, {"cost": 0.0, "count": 0})
            m["cost"] += e.estimated_cost
            m["count"] += 1

            # By day
            day_str = e.timestamp[:10]
            d = by_day.setdefault(day_str, {"cost": 0.0, "count": 0})
            d["cost"] += e.estimated_cost
            d["count"] += 1

            # By backend (Codex-6)
            bk = by_backend.setdefault(
                self._backend_key(e),
                {
                    "cost": 0.0,
                    "count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
            bk["cost"] += e.estimated_cost
            bk["count"] += 1
            bk["input_tokens"] += e.input_tokens
            bk["output_tokens"] += e.output_tokens

        for stats in by_backend.values():
            stats["cost"] = round(stats["cost"], 6)

        weekly = {
            "period": "7d",
            "total_cost": round(total_cost, 6),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "request_count": count,
            "by_model": by_model,
            "by_day": by_day,
            "by_backend": by_backend,
        }
        rtk = read_rtk_gain("7d")
        if rtk is not None:
            weekly["rtk_savings"] = {
                "tokens_saved": rtk.tokens_saved,
                "dollars_saved_estimated": rtk.dollars_saved_estimated,
                "period": "7d",
            }
        return weekly

    def get_cost_by_agent(self) -> dict[str, dict]:
        """Aggregate costs grouped by agent_id.

        Entries with an empty ``agent_id`` are excluded from the result.

        Returns:
            Dict mapping agent_id to a summary dict with keys:
            cost, count, input_tokens, output_tokens.
        """
        entries = self._read_entries()
        by_agent: dict[str, dict] = {}

        for e in entries:
            if not e.agent_id:
                continue
            bucket = by_agent.setdefault(
                e.agent_id,
                {"cost": 0.0, "count": 0, "input_tokens": 0, "output_tokens": 0},
            )
            bucket["cost"] += e.estimated_cost
            bucket["count"] += 1
            bucket["input_tokens"] += e.input_tokens
            bucket["output_tokens"] += e.output_tokens

        # Round cost values for clean output
        for stats in by_agent.values():
            stats["cost"] = round(stats["cost"], 6)

        return by_agent

    def get_cost_by_workflow(self) -> dict[str, dict]:
        """Aggregate costs grouped by workflow (WS3.1, #2570).

        Entries with an empty ``workflow`` are excluded from the result.

        Returns:
            Dict mapping workflow to a summary dict with keys:
            cost, count, input_tokens, output_tokens.
        """
        entries = self._read_entries()
        by_workflow: dict[str, dict] = {}

        for e in entries:
            if not e.workflow:
                continue
            bucket = by_workflow.setdefault(
                e.workflow,
                {"cost": 0.0, "count": 0, "input_tokens": 0, "output_tokens": 0},
            )
            bucket["cost"] += e.estimated_cost
            bucket["count"] += 1
            bucket["input_tokens"] += e.input_tokens
            bucket["output_tokens"] += e.output_tokens

        # Round cost values for clean output
        for stats in by_workflow.values():
            stats["cost"] = round(stats["cost"], 6)

        return by_workflow

    @staticmethod
    def _backend_key(entry: CostEntry) -> str:
        """Codex-6 (#1840) — bucket key for ``by_backend`` aggregates.

        Legacy entries written before Codex-6 carry ``backend=""``. We
        bucket those as ``"claude"`` because every pre-Codex entry was
        produced by the Claude backend; reporting ``""`` would surface
        the migration artifact instead of the historical truth.
        """
        return entry.backend or "claude"

    def _summarize_for_date_prefix(self, date_prefix: str) -> dict:
        """Aggregate entries whose timestamp starts with *date_prefix*."""
        entries = self._read_entries()
        total_cost = 0.0
        total_in = 0
        total_out = 0
        by_model: dict[str, dict] = {}
        # Codex-6 (#1840): per-backend aggregate alongside the existing
        # per-model breakdown. Claude entries roll up by $ + token-count;
        # Codex entries roll up by token-count only (cost stays 0 because
        # estimated_cost is forced to 0.0 in record()).
        by_backend: dict[str, dict] = {}
        count = 0

        for e in entries:
            if not e.timestamp.startswith(date_prefix):
                continue
            count += 1
            total_cost += e.estimated_cost
            total_in += e.input_tokens
            total_out += e.output_tokens
            m = by_model.setdefault(e.model, {"cost": 0.0, "count": 0})
            m["cost"] += e.estimated_cost
            m["count"] += 1
            bk = by_backend.setdefault(
                self._backend_key(e),
                {
                    "cost": 0.0,
                    "count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
            bk["cost"] += e.estimated_cost
            bk["count"] += 1
            bk["input_tokens"] += e.input_tokens
            bk["output_tokens"] += e.output_tokens

        # Round per-backend cost mirroring the precedent in
        # get_cost_by_agent / get_feature_summary (4-digit rounding for
        # clean Discord output).
        for stats in by_backend.values():
            stats["cost"] = round(stats["cost"], 6)

        return {
            "date": date_prefix,
            "total_cost": round(total_cost, 6),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "request_count": count,
            "by_model": by_model,
            "by_backend": by_backend,
        }

    # ------------------------------------------------------------------
    # Sprint 04.04 — per-feature daily caps
    # ------------------------------------------------------------------

    def register_feature_cap(self, feature: str, daily_cap_usd: float) -> None:
        """Register or update the daily cap (USD) for *feature*.

        Operator-tunable at runtime — the cap registry is in-process state,
        not persisted. Reset on bridge restart unless wired to config.
        """
        if not feature:
            raise ValueError("feature must be a non-empty string")
        if daily_cap_usd < 0:
            raise ValueError("daily_cap_usd must be >= 0")
        self._feature_caps[feature] = float(daily_cap_usd)

    def get_feature_cap(self, feature: str) -> float | None:
        """Return the registered cap (USD) for *feature*, or None if unset."""
        return self._feature_caps.get(feature)

    def get_feature_summary(
        self, feature: str, period: str = "1d"
    ) -> FeatureCostSummary:
        """Aggregate costs for a single feature over *period*.

        Args:
            feature: Feature label to aggregate (matches ``CostEntry.feature``).
            period: ``"1d"`` (default — current UTC calendar day, matches
                ``get_daily_summary`` semantics) or ``"7d"`` (rolling 7-day
                window, matches ``get_weekly_summary``).

        Returns:
            ``FeatureCostSummary`` — empty (zero cost / zero count) if the
            feature has no entries in the window.
        """
        if period not in ("1d", "7d"):
            raise ValueError(f"Unsupported feature-summary period: {period!r}")

        now = datetime.now(timezone.utc)
        if period == "1d":
            today_prefix = now.strftime("%Y-%m-%d")

            def _in_window(entry: CostEntry) -> bool:
                return entry.timestamp.startswith(today_prefix)
        else:  # "7d" rolling
            cutoff = now.timestamp() - 7 * 86400.0

            def _in_window(entry: CostEntry) -> bool:
                try:
                    ts = datetime.fromisoformat(entry.timestamp).timestamp()
                except (ValueError, TypeError):
                    return False
                return ts >= cutoff

        entries = self._read_entries()
        total_cost = 0.0
        count = 0
        by_model: dict[str, dict] = {}

        for e in entries:
            if e.feature != feature:
                continue
            if not _in_window(e):
                continue
            count += 1
            total_cost += e.estimated_cost
            m = by_model.setdefault(e.model, {"cost": 0.0, "count": 0})
            m["cost"] += e.estimated_cost
            m["count"] += 1

        # Round model-level cost for clean output, mirroring get_cost_by_agent.
        for stats in by_model.values():
            stats["cost"] = round(stats["cost"], 6)

        return FeatureCostSummary(
            feature=feature,
            period=period,
            total_cost=round(total_cost, 6),
            request_count=count,
            by_model=by_model,
        )

    def check_feature_cap(self, feature: str, cost_usd: float) -> tuple[bool, str]:
        """Check whether a pending call for *feature* would breach its daily cap.

        Returns:
            ``(allowed, reason)``:
            - ``(True, "")`` if the call is permitted (within cap, no cap
              registered, feature flag disabled, or empty feature label).
            - ``(False, "feature_cap_exceeded:<feature>:<cap>")`` if the
              projected cost (today's spend + ``cost_usd``) would exceed
              the registered cap.

        Composes alongside ``bridge.budget`` global daily-budget enforcement.
        Bypass mode: when ``feature_caps_enabled`` is False, always returns
        ``(True, "")``.
        """
        if not self._feature_caps_enabled:
            return (True, "")
        if not feature:
            # No feature label = no per-feature cap to check.
            return (True, "")
        cap = self._feature_caps.get(feature)
        if cap is None:
            return (True, "")
        # Sum today's UTC spend for this feature plus the proposed call.
        today_spend = self.get_feature_summary(feature, period="1d").total_cost
        if (today_spend + max(0.0, cost_usd)) > cap:
            return (False, f"feature_cap_exceeded:{feature}:{cap:.2f}")
        return (True, "")

    # ------------------------------------------------------------------
    # Sprint 02.09 — per-experiment-iteration cost attribution
    # ------------------------------------------------------------------

    def get_experiment_summary(self, iter_id: str) -> ExperimentCostSummary:
        """Aggregate costs for a single experiment iteration.

        Args:
            iter_id: Iteration id matching ``CostEntry.experiment_iter``.
                Non-experiment entries (empty ``experiment_iter``) are
                excluded regardless of *iter_id*.

        Returns:
            ``ExperimentCostSummary`` with total spend, call count,
            per-model breakdown, and the timestamp window. When *iter_id*
            is empty or has no matching entries, returns a zero-spend
            summary with empty timestamps and an empty breakdown rather
            than raising.
        """
        if not iter_id:
            return ExperimentCostSummary(
                iter_id=iter_id,
                total_usd=0.0,
                call_count=0,
                started_at="",
                ended_at="",
                model_breakdown={},
            )

        entries = self._read_entries()
        total_usd = 0.0
        call_count = 0
        model_breakdown: dict[str, dict] = {}
        first_ts: str | None = None
        last_ts: str | None = None

        for e in entries:
            if e.experiment_iter != iter_id:
                continue
            call_count += 1
            total_usd += e.estimated_cost
            m = model_breakdown.setdefault(e.model, {"cost": 0.0, "count": 0})
            m["cost"] += e.estimated_cost
            m["count"] += 1
            if first_ts is None or e.timestamp < first_ts:
                first_ts = e.timestamp
            if last_ts is None or e.timestamp > last_ts:
                last_ts = e.timestamp

        for stats in model_breakdown.values():
            stats["cost"] = round(stats["cost"], 6)

        return ExperimentCostSummary(
            iter_id=iter_id,
            total_usd=round(total_usd, 6),
            call_count=call_count,
            started_at=first_ts or "",
            ended_at=last_ts or "",
            model_breakdown=model_breakdown,
        )

    def list_experiment_iters(self) -> list[str]:
        """Return distinct non-empty experiment_iter ids in chronological order.

        Used by ``/cost --experiments`` to enumerate per-iteration spend.
        """
        seen: dict[str, str] = {}  # iter_id -> earliest timestamp
        for e in self._read_entries():
            if not e.experiment_iter:
                continue
            prev = seen.get(e.experiment_iter)
            if prev is None or e.timestamp < prev:
                seen[e.experiment_iter] = e.timestamp
        return sorted(seen, key=lambda k: seen[k])

    # ------------------------------------------------------------------
    # Z4-S40 — per-ChiefSession cost extraction
    # ------------------------------------------------------------------

    def get_session_cost(self, session_id: str) -> float:
        """Return total cost_usd charged to a chief_session_id.

        Reads ``cost_tracking.jsonl`` linearly — no in-memory cache.
        Intended for post-run cost extraction by ``WarmChief`` (Z4-S11),
        not for hot-path queries. Empty *session_id* returns 0.0 to
        avoid matching legacy rows whose ``chief_session_id`` defaulted
        to "".
        """
        if not session_id:
            return 0.0
        total = 0.0
        for entry in self._read_entries():
            if entry.chief_session_id == session_id:
                total += entry.estimated_cost
        return total

    # ------------------------------------------------------------------
    # Sprint audit-2026-05-16.D.05 — per-ChiefSession measurement lookup
    # ------------------------------------------------------------------

    def last_session_measurement(
        self, chief_session_id: str
    ) -> CostMeasurement | None:
        """Return the most recent CostMeasurement for *chief_session_id*.

        D.04's strict-mode budget gate (`ChiefDispatcher.dispatch`,
        audit-2026-05-16 M-1) uses ``hasattr`` to no-op when this accessor
        is missing; shipping it here activates the gate. The strict gate
        consults the source state to decide whether to charge against a
        cap — ``unknown`` fails closed (refuse to dispatch), ``measured``
        and ``estimated`` are chargeable (see
        ``is_chargeable_under_strict_budget``).

        Reads the JSONL log linearly; like ``get_session_cost`` this is
        intended for post-run lookups, not hot-path queries. Empty
        *chief_session_id* returns ``None`` to avoid matching legacy rows
        whose ``chief_session_id`` defaulted to "".

        Args:
            chief_session_id: ChiefSession id to look up. Empty string
                short-circuits to None.

        Returns:
            The newest ``CostMeasurement`` derived from a ``CostEntry``
            whose ``chief_session_id`` matches, or ``None`` when no
            matching entry exists. Until D.06 / D.07 thread an explicit
            ``source`` signal through the recording paths, every entry
            wraps as ``source='measured'`` via ``from_legacy_float`` —
            the legacy float path produced a number, so by the
            CostMeasurement contract that number was measured.
        """
        if not chief_session_id:
            return None
        latest: CostEntry | None = None
        latest_ts: str = ""
        for entry in self._read_entries():
            if entry.chief_session_id != chief_session_id:
                continue
            # Lexicographic compare is safe here because every timestamp
            # is an ISO-8601 string with timezone offset (always UTC in
            # this writer via ``datetime.now(timezone.utc).isoformat()``).
            if latest is None or entry.timestamp > latest_ts:
                latest = entry
                latest_ts = entry.timestamp
        if latest is None:
            return None
        return from_legacy_float(
            latest.estimated_cost,
            backend=latest.backend or "claude",
        )

    # ------------------------------------------------------------------
    # D2.5 — per-team daily aggregation and cap enforcement
    # ------------------------------------------------------------------

    def get_team_summary(
        self, date: str | None = None
    ) -> dict[str, dict]:
        """Aggregate one day's entries into ``{team: {cost, count, limit, breach}}``.

        Args:
            date: UTC date string ``YYYY-MM-DD``. Defaults to today.

        Returns:
            Mapping from team name (``"unattributed"`` for entries with no
            team) to a dict with keys ``cost``, ``count``, ``limit``, and
            ``breach``. Only teams with at least one entry on *date* appear.
        """
        if date is None:
            date = datetime.now(timezone.utc).date().isoformat()
        out: dict[str, dict] = {}
        for entry in self._read_entries():
            if not entry.timestamp.startswith(date):
                continue
            team = entry.team or "unattributed"
            bucket = out.setdefault(
                team,
                {
                    "cost": 0.0,
                    "count": 0,
                    "limit": self._team_limits.get(team, 0.0),
                    "breach": False,
                },
            )
            bucket["cost"] += entry.estimated_cost
            bucket["count"] += 1
        for b in out.values():
            b["breach"] = b["limit"] > 0 and b["cost"] >= b["limit"]
        return out

    def check_team_budget(self, team: str) -> tuple[bool, float, float]:
        """Return ``(within_budget, today_spend, limit)``.

        ``within_budget`` is True when no limit is configured for *team* or
        when today's spend is strictly below the limit. Callers are
        responsible for acting on the returned values (alert at 80%, block
        at 100%).

        Args:
            team: Team name matching ``CostEntry.team`` (e.g. ``"design"``).

        Returns:
            Three-tuple: budget OK flag, today's total spend in USD, and
            the configured daily limit in USD. Limit is ``0.0`` when no cap
            is registered for *team*.
        """
        limit = self._team_limits.get(team, 0.0)
        if limit <= 0:
            return (True, 0.0, 0.0)
        summary = self.get_team_summary()
        spend = summary.get(team, {}).get("cost", 0.0)
        return (spend < limit, spend, limit)
