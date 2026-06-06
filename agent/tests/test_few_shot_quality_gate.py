"""Sprint 05.08 — verdict-aware few-shot ingest quality gate.

The bridge stores every successful interaction as a few-shot example.
Before this sprint, every row was inserted at quality 1.0 — which broke
``enforce_cap`` (it evicts by lowest quality first, so fresh rows
self-protected and older genuinely-better examples were dropped over
time).

These tests pin the verdict-aware ingest behaviour:

- ``"fail"``  -> skip ingest entirely (and bump the skip counter)
- ``"flag"``  -> ingest at quality 0.5
- ``"pass"``  -> ingest at quality 1.0 (prior default)
- ``None``    -> ingest at quality 0.75 (cautious default when no eval ran)
- unknown     -> treated as None (0.75) and a WARNING is logged

The gate is wrapped in try/except so a verdict-handling bug never blocks
ingest outright — it falls through to the 0.75 cautious default.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest

from bridge.app import BridgeApp
from bridge.few_shot import FewShotStore


# ── Helpers ──────────────────────────────────────────────────────────


def _make_app(few_shot, *, with_metrics: bool = True) -> BridgeApp:
    """Build a BridgeApp shell with just the collaborators _record_telemetry
    touches up through the few-shot block. Anomaly check / session health
    are stubbed enough that the call returns cleanly.
    """
    app = object.__new__(BridgeApp)
    app._few_shot = few_shot
    app._metrics = MagicMock() if with_metrics else None
    app._project_registry = None
    app._cost_tracker = None
    app._routing_feedback = None
    app._session_recovery = None
    app._reflexion_ctx = None

    security = MagicMock()
    security.check_anomalies = AsyncMock(return_value=[])
    app._security = security

    discord = MagicMock()
    discord.send_alert = AsyncMock()
    app._discord = discord

    session_mgr = MagicMock()
    session_mgr.check_session_file_size = AsyncMock(return_value=False)
    session_mgr.check_error_count = AsyncMock(return_value=False)
    session_mgr.context_pressure = AsyncMock(return_value=0.0)
    app._session_mgr = session_mgr

    return app


def _make_ctx_and_result(text: str = "explain how the auth system works"):
    """Minimal MessageContext + ClaudeResult duck-types for telemetry."""
    msg = SimpleNamespace(
        id=1,
        chat_id="chat-1",
        text=text,
        platform_message_id="m-1",
    )
    ctx = SimpleNamespace(
        msg=msg,
        session_id="sess-1",
        msg_start=0.0,
        correlation_id=None,
    )
    result = SimpleNamespace(
        response_text="here is a thoughtful and lengthy answer " * 5,
        duration_ms=120,
        cost_usd=0.0,
        tools_used=[],
        session_id="",
        model="sonnet",
        num_turns=1,
    )
    return ctx, result


@pytest.fixture
def fewshot_store(tmp_path: Path) -> FewShotStore:
    """Real FewShotStore on a tmp SQLite db — gives us a row count we can assert."""
    return FewShotStore(db_path=tmp_path / "few_shot.db")


# ── Verdict-gate unit tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_verdict_fail_skips_ingest(fewshot_store: FewShotStore):
    """verdict=fail must NOT add a row and must bump the skip counter."""
    app = _make_app(fewshot_store)
    ctx, result = _make_ctx_and_result()

    before = len(fewshot_store.list_all(limit=100))
    await app._record_telemetry(ctx, result, evaluator_verdict="fail")
    after = len(fewshot_store.list_all(limit=100))

    assert after == before, "verdict=fail must skip ingest"
    app._metrics.increment.assert_any_call("few_shot.ingest_skipped_fail")


@pytest.mark.asyncio
async def test_verdict_flag_ingests_at_quality_0_5(fewshot_store: FewShotStore):
    """verdict=flag should land at quality_score == 0.5."""
    app = _make_app(fewshot_store)
    ctx, result = _make_ctx_and_result()

    await app._record_telemetry(ctx, result, evaluator_verdict="flag")
    rows = fewshot_store.list_all(limit=10)

    assert len(rows) == 1
    assert rows[0].quality_score == pytest.approx(0.5)
    app._metrics.increment.assert_any_call("few_shot.ingest_quality_flag")


@pytest.mark.asyncio
async def test_verdict_pass_ingests_at_quality_1_0(fewshot_store: FewShotStore):
    """verdict=pass preserves the prior default quality of 1.0."""
    app = _make_app(fewshot_store)
    ctx, result = _make_ctx_and_result()

    await app._record_telemetry(ctx, result, evaluator_verdict="pass")
    rows = fewshot_store.list_all(limit=10)

    assert len(rows) == 1
    assert rows[0].quality_score == pytest.approx(1.0)
    app._metrics.increment.assert_any_call("few_shot.ingest_quality_pass")


@pytest.mark.asyncio
async def test_verdict_none_ingests_at_quality_0_75(fewshot_store: FewShotStore):
    """No evaluator (None) should still ingest, but at the cautious 0.75 default."""
    app = _make_app(fewshot_store)
    ctx, result = _make_ctx_and_result()

    await app._record_telemetry(ctx, result, evaluator_verdict=None)
    rows = fewshot_store.list_all(limit=10)

    assert len(rows) == 1
    assert rows[0].quality_score == pytest.approx(0.75)
    app._metrics.increment.assert_any_call("few_shot.ingest_quality_no_eval")


@pytest.mark.asyncio
async def test_unknown_verdict_falls_back_to_no_eval_and_warns(
    fewshot_store: FewShotStore,
    caplog: pytest.LogCaptureFixture,
):
    """An unrecognised verdict string is treated as None (0.75) with a WARNING."""
    app = _make_app(fewshot_store)
    ctx, result = _make_ctx_and_result()

    with caplog.at_level(logging.WARNING, logger="bridge.app"):
        await app._record_telemetry(ctx, result, evaluator_verdict="totally_made_up")

    rows = fewshot_store.list_all(limit=10)
    assert len(rows) == 1
    assert rows[0].quality_score == pytest.approx(0.75)
    app._metrics.increment.assert_any_call("few_shot.ingest_quality_no_eval")
    assert any(
        "unknown verdict" in record.getMessage().lower()
        for record in caplog.records
    ), "expected a WARNING log mentioning 'unknown verdict'"


# ── Integration: real store + real verdict=fail flow ────────────────


@pytest.mark.asyncio
async def test_integration_verdict_fail_does_not_grow_store(tmp_path: Path):
    """End-to-end-ish: real FewShotStore, real call, fail verdict -> 0 rows added."""
    store = FewShotStore(db_path=tmp_path / "few_shot.db")
    app = _make_app(store)
    ctx, result = _make_ctx_and_result(text="please review this code carefully")

    # Seed one example so we can prove the store survives the call without growing.
    from bridge.few_shot import FewShotExample

    store.store(
        FewShotExample(
            task_type="code_review",
            input_text="seed",
            output_text="seed-output",
            quality_score=0.9,
        )
    )
    seeded = len(store.list_all(limit=100))

    await app._record_telemetry(ctx, result, evaluator_verdict="fail")

    after = len(store.list_all(limit=100))
    assert after == seeded, "fail verdict must not add a row to a real store"


# ── Default-arg safety: omitting the kwarg behaves like None ─────────


@pytest.mark.asyncio
async def test_omitting_verdict_kwarg_uses_no_eval_quality(fewshot_store: FewShotStore):
    """Callers that don't pass evaluator_verdict (e.g. legacy paths) get 0.75."""
    app = _make_app(fewshot_store)
    ctx, result = _make_ctx_and_result()

    await app._record_telemetry(ctx, result)  # no kwarg

    rows = fewshot_store.list_all(limit=10)
    assert len(rows) == 1
    assert rows[0].quality_score == pytest.approx(0.75)
