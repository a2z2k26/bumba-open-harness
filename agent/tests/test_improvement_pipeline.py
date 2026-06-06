"""Integration test for the full improvement pipeline.

End-to-end chain:
  failure recording → pattern detection → gotchas generation →
  context pressure → proactive reset → progress tracking → hooks

All in-memory, no external dependencies, < 5 seconds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.config import BridgeConfig
from bridge.database import Database
from bridge.hooks import SessionHookRegistry
from bridge.project_registry import ProjectRegistry
from bridge.session_manager import SessionManager
from bridge.skill_evolution import SkillEvolutionEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_db(tmp_path: Path) -> Database:
    """Create an in-memory-like DB with schema applied."""
    db = Database(tmp_path / "pipeline_test.db")
    await db.connect()
    await db.migrate()
    return db


def _make_config(**overrides) -> BridgeConfig:
    """Create a minimal BridgeConfig with small limits for fast testing."""
    defaults = {
        "session_max_messages": 40,
        "session_max_duration": 7200,
        "session_max_file_size": 31457280,
        "session_idle_timeout": 1800,
        "session_max_errors": 3,
    }
    defaults.update(overrides)
    return BridgeConfig(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_improvement_pipeline(tmp_path: Path):
    """End-to-end: failures → patterns → gotchas → pressure → reset → progress → hooks."""

    # --- Stage 1: Failure recording & pattern detection ---

    engine = SkillEvolutionEngine(db_path=tmp_path / "evolution.db")

    # Record 5 failures for the same skill with the same message so they
    # aggregate into a single pattern entry with count=5.
    for _ in range(5):
        engine.record_failure(
            task_type="webapp-testing",
            error_type="TimeoutError",
            error_message="Page load timed out after 30s",
        )

    # Detect recurring patterns — should find our TimeoutError pattern
    patterns = engine.detect_recurring_failures(window_days=7, threshold=3)
    assert len(patterns) >= 1
    timeout_pattern = next(
        (p for p in patterns if p.error_type == "TimeoutError"), None
    )
    assert timeout_pattern is not None
    assert timeout_pattern.count >= 5

    # --- Stage 2: Gotchas generation ---

    gotchas = engine.generate_gotchas("webapp-testing")
    assert gotchas.startswith("## Gotchas")
    assert "TimeoutError" in gotchas
    assert "5x" in gotchas

    # Verify no gotchas for a skill with no failures
    assert engine.generate_gotchas("nonexistent-skill") == ""

    # --- Stage 3: Context pressure simulation ---

    db = await _make_db(tmp_path)
    config = _make_config(session_max_messages=40)
    sm = SessionManager(db, config)

    chat_id = "integration-test-chat"
    session_id = await sm.create_session(chat_id)

    # Simulate 35 messages to push pressure above 0.7 (35/40 = 0.875)
    for _ in range(35):
        await sm.update_session(session_id, cost_usd=0.001)

    pressure = await sm.context_pressure(session_id)
    assert pressure >= 0.7, f"Expected pressure >= 0.7, got {pressure}"

    # --- Stage 4: Proactive reset (session expiry + new session) ---

    new_session_id = await sm.handle_reset(chat_id)
    assert new_session_id != session_id

    # Old session should no longer resolve
    resolved = await sm.resolve_session(chat_id)
    assert resolved == new_session_id

    # New session should have zero pressure
    new_pressure = await sm.context_pressure(new_session_id)
    assert new_pressure < 0.1

    # --- Stage 5: Progress tracking ---

    registry = ProjectRegistry(tmp_path / "project_data")
    registry.register("test-project", {"description": "Integration test project"})

    # Record session start
    registry.record_session_start("test-project", session_id)
    progress = registry.get_progress("test-project")
    assert len(progress["sessions"]) == 1
    assert progress["sessions"][0]["session_id"] == session_id

    # Record session completion with summary
    registry.record_session(
        "test-project",
        summary="Completed improvement pipeline integration test",
        feature="gotchas-injection",
        changes=["Added gotchas to webapp-testing"],
        blockers=[],
    )
    progress = registry.get_progress("test-project")
    assert len(progress["sessions"]) == 2
    assert progress["current_feature"] == "gotchas-injection"
    assert "Added gotchas" in progress["recent_changes"][0]

    # --- Stage 6: Session hook lifecycle ---

    hooks = SessionHookRegistry()
    activated_hooks: list[str] = []
    deactivated_hooks: list[str] = []

    hooks.register(
        "careful",
        "Force Opus model for critical operations",
        on_activate=lambda: activated_hooks.append("careful"),
        on_deactivate=lambda: deactivated_hooks.append("careful"),
    )
    hooks.register(
        "freeze",
        "Block file writes during review",
        on_activate=lambda: activated_hooks.append("freeze"),
        on_deactivate=lambda: deactivated_hooks.append("freeze"),
    )

    # Activate both
    assert hooks.activate("careful") is True
    assert hooks.activate("freeze") is True
    assert hooks.is_active("careful")
    assert hooks.is_active("freeze")
    assert len(hooks.get_active()) == 2
    assert activated_hooks == ["careful", "freeze"]

    # Deactivate one
    assert hooks.deactivate("careful") is True
    assert not hooks.is_active("careful")
    assert hooks.is_active("freeze")
    assert deactivated_hooks == ["careful"]

    # Reset all (simulates session expiry)
    hooks.reset()
    assert len(hooks.get_active()) == 0
    assert deactivated_hooks == ["careful", "freeze"]

    # --- Cleanup ---
    await db.close()


@pytest.mark.asyncio
async def test_gotchas_injection_idempotent(tmp_path: Path):
    """Verify that injecting gotchas twice doesn't duplicate the section."""

    engine = SkillEvolutionEngine(db_path=tmp_path / "idempotent.db")

    for _ in range(3):
        engine.record_failure(
            task_type="error-diagnosis",
            error_type="ParseError",
            error_message="Malformed JSON in log line",
        )

    gotchas = engine.generate_gotchas("error-diagnosis")
    assert gotchas != ""

    # Import the injection helper from the script
    from scripts.inject_gotchas import _inject_gotchas

    original = "---\nname: test\n---\n# Test Skill\n\n## When to Use\nAlways.\n"

    # First injection
    result1 = _inject_gotchas(original, gotchas)
    assert result1.count("## Gotchas") == 1

    # Second injection (should replace, not duplicate)
    result2 = _inject_gotchas(result1, gotchas)
    assert result2.count("## Gotchas") == 1


@pytest.mark.asyncio
async def test_gotchas_before_references(tmp_path: Path):
    """Verify gotchas are inserted before ## References."""

    engine = SkillEvolutionEngine(db_path=tmp_path / "refs.db")

    for _ in range(3):
        engine.record_failure(
            task_type="log-analysis",
            error_type="FileNotFound",
            error_message="Log file rotated away",
        )

    gotchas = engine.generate_gotchas("log-analysis")
    assert gotchas != ""

    from scripts.inject_gotchas import _inject_gotchas

    original = "---\nname: test\n---\n# Log Analysis\n\n## Steps\nDo things.\n\n## References\n- Link 1\n"

    result = _inject_gotchas(original, gotchas)
    gotchas_pos = result.index("## Gotchas")
    refs_pos = result.index("## References")
    assert gotchas_pos < refs_pos, "Gotchas should appear before References"
