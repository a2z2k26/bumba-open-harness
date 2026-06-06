"""Production headroom contracts for Zone 4 chiefs (#2566 hybrid fleet)."""

from __future__ import annotations

from pathlib import Path

from teams import DepartmentRegistry


_TEAMS_DIR = Path(__file__).parent.parent.parent / "config" / "teams"


def test_chiefs_have_validation_retry_headroom() -> None:
    """All chiefs need >1 retry for malformed tool/output calls.

    #2566: chiefs run anthropic-oauth (tool-calling tier); retry headroom
    still matters because tool/output validation can fail transiently.
    """
    registry = DepartmentRegistry.from_directory(_TEAMS_DIR)

    expected = {
        "board": "board-ceo",
        "design": "design-chief",
        "job_search": "job-search-chief",
        "ops": "ops-chief",
        "qa": "qa-chief",
        "strategy": "strategy-product-chief",
    }

    for department, chief_name in expected.items():
        manager = registry.get_config(department).manager
        assert manager.name == chief_name
        assert manager.retries >= 3, (
            f"{department} chief must keep retry headroom for "
            "tool/output validation"
        )


def test_all_chiefs_are_anthropic_oauth() -> None:
    """#2566 hybrid fleet: every dept chief runs anthropic-oauth.

    Chiefs REQUIRE tool-calling (delegate / final_result), which
    codex-exec cannot drive (it returns prose). Anthropic OAuth gives
    native tool support, subscription-billed. Strategy keeps a
    codex-exec fallback; the others have none.
    """
    registry = DepartmentRegistry.from_directory(_TEAMS_DIR)

    for department in ("board", "design", "job_search", "ops", "qa", "strategy"):
        manager = registry.get_config(department).manager
        assert manager.model == "anthropic-oauth:claude-sonnet-4-5", (
            f"{department} chief must be anthropic-oauth, got {manager.model}"
        )
        assert manager.adapter == "claude"
        assert manager.retries >= 3

    # Strategy chief carries a codex-exec fallback (the only chief with one).
    strategy_manager = registry.get_config("strategy").manager
    assert strategy_manager.name == "strategy-product-chief"
    assert strategy_manager.fallback_model == "codex-exec:"


def test_qa_request_token_limit_covers_observed_production_near_miss() -> None:
    """QA exceeded both 50k and 80k input caps in production."""
    registry = DepartmentRegistry.from_directory(_TEAMS_DIR)

    cfg = registry.get_config("qa")

    assert cfg.constraints.request_token_limit >= 250_000
    assert cfg.constraints.response_token_limit >= 250_000


def test_strategy_and_ops_caps_cover_observed_2026_05_21_smokes() -> None:
    """Strategy and Ops exceeded the 250k cap during readiness smokes."""
    registry = DepartmentRegistry.from_directory(_TEAMS_DIR)

    for department in ("strategy", "ops"):
        cfg = registry.get_config(department)
        assert cfg.constraints.request_token_limit >= 350_000, (
            f"{department} needs input-token headroom above the observed "
            "2026-05-21 readiness failures"
        )
        assert cfg.constraints.response_token_limit >= 250_000


def test_standard_production_departments_match_board_token_ceiling() -> None:
    """Standard production teams keep the board's proven 250k ceiling."""
    registry = DepartmentRegistry.from_directory(_TEAMS_DIR)
    board_limits = registry.get_config("board").constraints

    for department in ("board", "design", "job_search", "qa"):
        cfg = registry.get_config(department)
        assert cfg.constraints.request_token_limit == board_limits.request_token_limit, (
            f"{department} request_token_limit should match board's "
            f"{board_limits.request_token_limit}"
        )

    for department in ("board", "design", "job_search", "ops", "qa", "strategy"):
        cfg = registry.get_config(department)
        assert cfg.constraints.response_token_limit == board_limits.response_token_limit, (
            f"{department} response_token_limit should match board's "
            f"{board_limits.response_token_limit}"
        )


def test_ops_request_limit_covers_observed_readiness_smoke() -> None:
    """Ops exceeded the default 20-request cap on a production readiness ping."""
    registry = DepartmentRegistry.from_directory(_TEAMS_DIR)

    cfg = registry.get_config("ops")

    assert cfg.constraints.request_limit >= 50


def test_strategy_request_limit_covers_observed_oauth_canary_loop() -> None:
    """Strategy exhausted the 20-request cap during a readiness smoke."""
    registry = DepartmentRegistry.from_directory(_TEAMS_DIR)

    cfg = registry.get_config("strategy")

    assert cfg.constraints.request_limit >= 50


def test_qa_timeout_covers_observed_cheap_frontier_latency() -> None:
    """QA reached the 600s wall after the cheap-frontier stabilization work."""
    registry = DepartmentRegistry.from_directory(_TEAMS_DIR)

    cfg = registry.get_config("qa")

    assert cfg.constraints.timeout_seconds >= 900
