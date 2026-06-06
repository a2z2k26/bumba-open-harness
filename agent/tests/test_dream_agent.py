"""Tests for DreamAgent — restricted Claude subprocess for deep memory consolidation."""
from __future__ import annotations

import dataclasses
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path):
    """Minimal BridgeConfig with data_dir pointing to tmp."""
    from bridge.config import BridgeConfig
    return dataclasses.replace(BridgeConfig(), data_dir=str(tmp_path))


@pytest.fixture
def dream_agent(config):
    """DreamAgent instance with tmp data_dir."""
    from bridge.dream_agent import DreamAgent
    return DreamAgent(config)


# ---------------------------------------------------------------------------
# Test 1: __init__ sets memory_dir to data/memory/
# ---------------------------------------------------------------------------

def test_init_sets_memory_dir(config, tmp_path):
    """DreamAgent.__init__ sets _memory_dir to data/memory/."""
    from bridge.dream_agent import DreamAgent
    agent = DreamAgent(config)
    assert agent._memory_dir == Path(tmp_path) / "memory"


# ---------------------------------------------------------------------------
# Test 2: _build_prompt includes memory_dir, session count, 4 phases
# ---------------------------------------------------------------------------

def test_build_prompt_contains_required_elements(dream_agent, tmp_path):
    """_build_prompt includes memory_dir path, session count, and 4 phases."""
    session_ids = ["s1", "s2", "s3"]
    prompt = dream_agent._build_prompt(session_ids)

    # Contains memory dir path
    assert str(tmp_path / "memory") in prompt
    # Contains session count
    assert "3" in prompt
    # Contains 4 phases
    assert "Phase 1" in prompt
    assert "Phase 2" in prompt
    assert "Phase 3" in prompt
    assert "Phase 4" in prompt


# ---------------------------------------------------------------------------
# Test 3: _build_prompt includes DREAM_ALLOWED_BASH
# ---------------------------------------------------------------------------

def test_build_prompt_includes_allowed_bash(dream_agent):
    """_build_prompt includes the DREAM_ALLOWED_BASH constant."""
    from bridge.dream_agent import DREAM_ALLOWED_BASH
    prompt = dream_agent._build_prompt([])
    assert DREAM_ALLOWED_BASH in prompt


# ---------------------------------------------------------------------------
# Test 4: run() with valid JSON → DreamResult(success=True, ...)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_valid_json_returns_success(dream_agent):
    """run() with mocked ClaudeRunner returning valid JSON → DreamResult(success=True)."""
    from bridge.dream_agent import DreamResult
    from bridge.claude_runner import ClaudeResult

    json_payload = (
        '{"summary": "done", "files_touched": ["a.md"], '
        '"entries_pruned": 3, "contradictions_resolved": 1, "merges_performed": 2}'
    )
    mock_result = ClaudeResult(response_text=json_payload, is_error=False)

    with patch("bridge.dream_agent.ClaudeRunner") as MockRunner:
        instance = MockRunner.return_value
        instance.invoke = AsyncMock(return_value=mock_result)

        result = await dream_agent.run(["s1", "s2"])

    assert isinstance(result, DreamResult)
    assert result.success is True
    assert result.summary == "done"
    assert result.files_touched == ["a.md"]
    assert result.entries_pruned == 3
    assert result.contradictions_resolved == 1
    assert result.merges_performed == 2
    assert result.error is None


# ---------------------------------------------------------------------------
# Test 5: run() with plain text (not JSON) → DreamResult(success=True, summary=text[:500])
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_plain_text_returns_success_with_truncated_summary(dream_agent):
    """run() with plain text response → DreamResult(success=True, summary=text[:500])."""
    from bridge.dream_agent import DreamResult
    from bridge.claude_runner import ClaudeResult

    plain_text = "This is not JSON at all, just a plain consolidation report."
    mock_result = ClaudeResult(response_text=plain_text, is_error=False)

    with patch("bridge.dream_agent.ClaudeRunner") as MockRunner:
        instance = MockRunner.return_value
        instance.invoke = AsyncMock(return_value=mock_result)

        result = await dream_agent.run([])

    assert isinstance(result, DreamResult)
    assert result.success is True
    assert result.summary == plain_text[:500]
    assert result.files_touched == []
    assert result.entries_pruned == 0
    assert result.contradictions_resolved == 0
    assert result.merges_performed == 0


# ---------------------------------------------------------------------------
# Test 6: run() with error → DreamResult(success=False, error=...)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_error_returns_failure(dream_agent):
    """run() with is_error=True → DreamResult(success=False, error=error_type)."""
    from bridge.dream_agent import DreamResult
    from bridge.claude_runner import ClaudeResult

    mock_result = ClaudeResult(
        response_text="",
        is_error=True,
        error_type="timeout",
    )

    with patch("bridge.dream_agent.ClaudeRunner") as MockRunner:
        instance = MockRunner.return_value
        instance.invoke = AsyncMock(return_value=mock_result)

        result = await dream_agent.run(["s1"])

    assert isinstance(result, DreamResult)
    assert result.success is False
    assert result.error is not None
    assert len(result.error) > 0


# ---------------------------------------------------------------------------
# Test 7: run() passes config with disallowed_tools including "Bash(rm *)"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_disallowed_tools_includes_rm(dream_agent):
    """run() passes a config to ClaudeRunner that includes 'Bash(rm *)' in disallowed tools."""
    from bridge.claude_runner import ClaudeResult

    mock_result = ClaudeResult(
        response_text=(
            '{"summary": "ok", "files_touched": [], '
            '"entries_pruned": 0, "contradictions_resolved": 0, "merges_performed": 0}'
        ),
        is_error=False,
    )

    captured_configs = []

    def capture_runner(cfg):
        captured_configs.append(cfg)
        runner = MagicMock()
        runner.invoke = AsyncMock(return_value=mock_result)
        return runner

    with patch("bridge.dream_agent.ClaudeRunner", side_effect=capture_runner):
        await dream_agent.run([])

    assert len(captured_configs) == 1
    cfg_used = captured_configs[0]
    disallowed = list(cfg_used.security_disallowed_tools)
    assert "Bash(rm *)" in disallowed


# ---------------------------------------------------------------------------
# Test 8: DreamResult is frozen dataclass
# ---------------------------------------------------------------------------

def test_dream_result_is_frozen():
    """DreamResult is a frozen dataclass — mutation raises FrozenInstanceError or TypeError."""
    from bridge.dream_agent import DreamResult

    result = DreamResult(
        success=True,
        summary="test",
        files_touched=[],
        entries_pruned=0,
        contradictions_resolved=0,
        merges_performed=0,
    )

    with pytest.raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
        result.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 9: _ensure_memory_dir() creates data/memory/ and data/memory/snapshots/
# ---------------------------------------------------------------------------

def test_ensure_memory_dir_creates_directories(dream_agent, tmp_path):
    """_ensure_memory_dir() creates data/memory/ and data/memory/snapshots/."""
    memory_dir = tmp_path / "memory"
    snapshots_dir = memory_dir / "snapshots"

    assert not memory_dir.exists()
    assert not snapshots_dir.exists()

    dream_agent._ensure_memory_dir()

    assert memory_dir.exists()
    assert memory_dir.is_dir()
    assert snapshots_dir.exists()
    assert snapshots_dir.is_dir()


# ---------------------------------------------------------------------------
# Test 10: Integration — consolidation service deep mode calls DreamAgent.run
# ---------------------------------------------------------------------------

def test_consolidation_service_deep_mode_calls_dream_agent(tmp_path):
    """ConsolidationService.run(deep) calls DreamAgent.run() when injected via set_dream_agent."""
    import sqlite3
    import dataclasses
    from bridge.services.consolidation_service import ConsolidationService
    from bridge.dream_agent import DreamAgent, DreamResult
    from bridge.config import BridgeConfig

    db_path = tmp_path / "memory.db"

    # Create a minimal DB with knowledge table
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE knowledge "
        "(key TEXT, value TEXT, category TEXT, source TEXT, salience REAL, "
        "access_count INTEGER, created_at TEXT, updated_at TEXT, accessed_at TEXT, archived INTEGER)"
    )
    conn.commit()
    conn.close()

    service = ConsolidationService(
        data_dir=str(tmp_path),
        db_path=str(db_path),
        chat_id="123",
        mode="deep",
    )

    # Build a mock DreamAgent
    mock_dream_agent = MagicMock(spec=DreamAgent)
    mock_dream_agent.run = AsyncMock(return_value=DreamResult(
        success=True,
        summary="deep consolidation done",
        files_touched=["memory/test.md"],
        entries_pruned=5,
        contradictions_resolved=2,
        merges_performed=1,
    ))

    # Inject mock via setter
    service.set_dream_agent(mock_dream_agent)

    # Inject config
    cfg = dataclasses.replace(BridgeConfig(), data_dir=str(tmp_path))
    service.set_config(cfg)

    # Override lock to always allow
    service._lock.try_acquire = MagicMock(
        return_value=MagicMock(acquired=True, holder_pid=None, prior_mtime=0)
    )
    service._lock.record_completion = MagicMock()
    service._lock.release = MagicMock()

    # Run the service in deep mode
    service.run(mode="deep")

    # DreamAgent.run must have been called
    assert mock_dream_agent.run.called
