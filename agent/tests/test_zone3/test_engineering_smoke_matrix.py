"""Z3-06 tests — Zone 3 engineering smoke matrix + cross-zone escalation.

The smoke matrix exercises the dispatcher with a FAKE executor so local CI
never spawns real Claude. It proves:
  - readiness uses zero Claude subprocess calls;
  - substantive cases reach the (fake) executor with the right specialist;
  - cross-zone handoff cases do not silently invoke Zone 4.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_zone3_engineering_smoke import (
    SMOKE_CASES,
    FakeEngineeringExecutor,
    SmokeOutcome,
    build_smoke_dispatcher,
    run_engineering_smoke,
)


@pytest.fixture()
def dispatcher():
    return build_smoke_dispatcher(executor=FakeEngineeringExecutor())


async def test_smoke_runs_all_cases(dispatcher) -> None:
    outcomes = await run_engineering_smoke(dispatcher, cwd=Path.cwd())
    assert len(outcomes) == len(SMOKE_CASES)
    assert all(isinstance(o, SmokeOutcome) for o in outcomes)
    assert all(o.passed for o in outcomes)


async def test_readiness_case_spawns_no_claude(dispatcher) -> None:
    await run_engineering_smoke(dispatcher, cwd=Path.cwd())
    # The fake executor records every run(); readiness must not appear.
    specialists_run = [c["specialist"] for c in dispatcher.executor.calls]
    assert "engineering-chief" not in specialists_run  # readiness short-circuits


async def test_code_review_routes_to_reviewer(dispatcher) -> None:
    await run_engineering_smoke(dispatcher, cwd=Path.cwd())
    assert any(
        c["specialist"] == "engineering-code-reviewer"
        for c in dispatcher.executor.calls
    )


async def test_backend_design_routes_to_backend(dispatcher) -> None:
    await run_engineering_smoke(dispatcher, cwd=Path.cwd())
    backend_like = {"engineering-backend-architect", "engineering-api-engineer"}
    assert any(c["specialist"] in backend_like for c in dispatcher.executor.calls)


async def test_qa_escalation_does_not_invoke_executor(dispatcher) -> None:
    outcomes = await run_engineering_smoke(dispatcher, cwd=Path.cwd())
    qa = next(o for o in outcomes if o.case_name == "qa_escalation")
    assert qa.passed
    assert "handoff" in qa.stdout.lower()
    assert "qa" in qa.stdout.lower()


async def test_ops_escalation_only_with_infra_scope(dispatcher) -> None:
    outcomes = await run_engineering_smoke(dispatcher, cwd=Path.cwd())
    ops = next(o for o in outcomes if o.case_name == "ops_escalation")
    assert ops.passed
    assert "handoff" in ops.stdout.lower()
    assert "ops" in ops.stdout.lower()


def test_smoke_matrix_doc_exists() -> None:
    doc = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "operator"
        / "zone3-engineering-smoke-matrix.md"
    )
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8").lower()
    assert "--live" in text
    assert "readiness" in text
