"""Shared test fixtures for Bumba bridge tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, TypeVar
from unittest.mock import patch

import pytest
import pytest_asyncio

from bridge.commands import BRIDGE_COMMANDS, apply_command_tier_gating
from bridge.config import BridgeConfig, load_config
from bridge.database import Database

_T = TypeVar("_T")


@pytest.fixture(autouse=True)
def _enable_all_tier_3_commands_for_tests():
    """#1071 Part 2 — production gates Tier 3 commands behind
    ``[commands]`` flags in ``bridge.toml``. Pre-existing tests
    predate that gating and exercise Tier 3 handlers via
    ``handle()``. Enable everything for tests; specific tests that
    care about gating manage their own state.
    """
    snapshot = set(BRIDGE_COMMANDS)
    apply_command_tier_gating({"all": True})
    yield
    BRIDGE_COMMANDS.clear()
    BRIDGE_COMMANDS.update(snapshot)

# Sample bridge.toml content for testing
SAMPLE_TOML = """\
[bridge]
data_dir = "{data_dir}"
log_dir = "{log_dir}"
heartbeat_interval = 60

[discord]
# guild_id = ""

[claude]
timeout = 120
hard_timeout = 600
absolute_timeout = 1800
max_turns = 25
output_format = "stream-json"
working_dir = "{working_dir}"
max_retries = 3

[session]
idle_timeout = 1800
max_file_size = 31457280
max_errors = 3

[memory]
context_window = 20
max_context_tokens = 4000
summary_count = 3

[security]
disallowed_tools = [
    "Bash(sudo *)",
    "Bash(rm -rf /)",
]
tool_failure_threshold = 5
tool_failure_window = 600
crash_loop_threshold = 5
crash_loop_window = 600
db_size_warn = 524288000
db_size_alert = 1073741824

[rate_limit]
initial_backoff = 30
max_backoff = 1800
multiplier = 2.0
jitter = 0.5

[checkin]
enabled = true
active_hours_start = 8
active_hours_end = 22
check_interval = 3600
quiet_after_message = 1800
minimum_gap = 7200

[briefing]
enabled = true
delivery_hour = 7
delivery_minute = 30

[fallback]
openrouter_model = "anthropic/claude-3.5-sonnet"

[budget]
daily_budget = 0.0

[agents]
max_invocation_depth = 3
"""


@pytest.fixture
def tmp_dirs(tmp_path: Path) -> dict[str, Path]:
    """Create temp directories mimicking bumba-agent layout."""
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    working_dir = tmp_path / "agent"
    data_dir.mkdir()
    log_dir.mkdir()
    working_dir.mkdir()
    return {"data_dir": data_dir, "log_dir": log_dir, "working_dir": working_dir}


@pytest.fixture
def sample_config_toml(tmp_path: Path, tmp_dirs: dict[str, Path]) -> Path:
    """Write a valid bridge.toml to tmp_path and return its path."""
    toml_path = tmp_path / "bridge.toml"
    content = SAMPLE_TOML.format(
        data_dir=str(tmp_dirs["data_dir"]),
        log_dir=str(tmp_dirs["log_dir"]),
        working_dir=str(tmp_dirs["working_dir"]),
    )
    toml_path.write_text(content)
    return toml_path


@pytest.fixture
def mock_keyring():
    """Mock secrets retrieval for Discord, Claude OAuth, and required API secrets.

    Wraps the original keychain subprocess mock and additionally augments
    ``_load_secrets`` to inject the secrets that B.03 + B.04's fail-closed
    validators now require at boot time:

    - ``claude_oauth_token`` — audit-2026-05-16.B.03 (#2052, HI-5).
    - ``api_token`` + ``github_webhook_secret`` — audit-2026-05-16.B.04
      (#2053, M-3). Required when ``api_enabled=True``; the SAMPLE_TOML
      fixture omits the ``[api]`` section so the default ``api_enabled=True``
      applies.

    Without these injections every test using ``sample_config`` would fail.
    The original subprocess mock is preserved so any test directly observing
    ``subprocess.run`` calls keeps working.
    """
    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        r = Result()
        if "bumba-discord-token" in cmd:
            r.stdout = "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.FAKE-DISCORD-TOKEN.abcdef\n"
        elif "bumba-operator-id" in cmd:
            r.stdout = "7565124764\n"
        else:
            r.returncode = 1
        return r

    # Capture the real _load_secrets so we can augment, not replace.
    from bridge import config as _config_mod
    _real_load_secrets = _config_mod._load_secrets
    required_secret_values = {
        _config_mod.REQUIRED_BOOT_SECRET_KEYS[0]: "sk-ant-fake-test-oauth-token",
        _config_mod.API_ENABLED_REQUIRED_SECRET_KEYS[0]: "test-api-token-b04",
        _config_mod.API_ENABLED_REQUIRED_SECRET_KEYS[1]: "test-gh-webhook-secret-b04",
    }

    def augmented_load_secrets(*args, **kwargs):
        secrets = _real_load_secrets(*args, **kwargs)
        for key, value in required_secret_values.items():
            secrets.setdefault(key, value)
        return secrets

    with patch("bridge.config.subprocess.run", side_effect=fake_run) as mock:
        with patch(
            "bridge.config._load_secrets", side_effect=augmented_load_secrets
        ):
            yield mock


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a temporary database file path."""
    return tmp_path / "test.db"


TEST_FIXTURE_TIMEOUT_SECONDS = 5.0


async def _fixture_timeout(label: str, awaitable: Awaitable[_T]) -> _T:
    try:
        return await asyncio.wait_for(
            awaitable,
            timeout=TEST_FIXTURE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise AssertionError(
            f"{label} fixture setup exceeded {TEST_FIXTURE_TIMEOUT_SECONDS:.1f}s"
        ) from exc


@pytest_asyncio.fixture
async def migrated_db(tmp_db_path: Path) -> Database:
    """Return a connected and migrated Database instance."""
    db = Database(tmp_db_path)
    await _fixture_timeout("migrated_db.connect", db.connect())
    await _fixture_timeout("migrated_db.migrate", db.migrate())
    try:
        yield db
    finally:
        await _fixture_timeout("migrated_db.close", db.close())


# -- Phase 2 fixtures --

@pytest.fixture
def sample_config(sample_config_toml: Path, mock_keyring) -> BridgeConfig:
    """Return a loaded BridgeConfig from sample TOML."""
    return load_config(sample_config_toml)


@pytest_asyncio.fixture
async def message_queue(migrated_db):
    """Return a MessageQueue instance."""
    from bridge.message_queue import MessageQueue
    return MessageQueue(migrated_db)


@pytest_asyncio.fixture
async def memory(migrated_db, sample_config):
    """Return a Memory instance."""
    from bridge.memory import Memory
    return Memory(migrated_db, sample_config)


@pytest_asyncio.fixture
async def session_manager(migrated_db, sample_config):
    """Return a SessionManager instance."""
    from bridge.session_manager import SessionManager

    async def _build() -> SessionManager:
        return SessionManager(migrated_db, sample_config)

    return await _fixture_timeout("session_manager", _build())


@pytest.fixture
def sample_stream_events() -> list[str]:
    """Sample NDJSON stream events from Claude Code."""
    return [
        json.dumps({"type": "system", "subtype": "init", "session_id": "sess-abc-123"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello!"}]}}),
        json.dumps({"type": "tool_use", "tool_name": "Read"}),
        json.dumps({"type": "tool_result", "tool_name": "Read"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}}),
        json.dumps({
            "type": "result", "session_id": "sess-abc-123",
            "cost_usd": 0.05, "num_turns": 3, "is_error": False,
            "duration_ms": 5000, "result": "Final result text.",
        }),
    ]


@pytest.fixture
def mock_claude_result():
    """Factory for ClaudeResult instances."""
    from bridge.claude_runner import ClaudeResult

    def _make(**kwargs):
        defaults = {
            "response_text": "Test response",
            "session_id": "sess-test-123",
            "cost_usd": 0.01,
            "num_turns": 1,
            "tools_used": [],
            "is_error": False,
            "error_type": "",
            "duration_ms": 1000,
            "exit_code": 0,
            "stderr_output": "",
        }
        defaults.update(kwargs)
        return ClaudeResult(**defaults)

    return _make


# -- Phase 3 fixtures --

@pytest_asyncio.fixture
async def security_manager(migrated_db, sample_config):
    """Return a SecurityManager instance."""
    from bridge.security import SecurityManager
    return SecurityManager(migrated_db, sample_config)


# -- Sprint #1112/4.03 (#2150) — SkillAllocator test helper --


def make_test_allocator():
    """Return a PERMISSIVE SkillAllocator for test fixtures.

    Default-deny is the security posture in production: an empty
    ``SkillAllocator(rules=[])`` returns ``set()`` for every query. The
    bridge's production manifest is at
    ``agent/config/skill-allocation/manifest.yaml`` (PR #2209). Existing
    tests construct ``DepartmentTeam`` / ``WarmChief`` / ``ChiefDispatcher``
    without an allocator (``None`` default) — the factory treats ``None``
    as "skip the filter" so tests stay green.

    Use this helper when a test needs to assert allocator-aware behavior
    (e.g. INFO log emission) without coupling to the production manifest.
    It returns an instance whose ``allowed_skills(...)`` query is wired
    to always return a fixed permissive set, mirroring a "manifest grants
    everything" configuration.

    Returns:
        A SkillAllocator-shaped object whose ``allowed_skills`` returns
        a non-empty set for every (zone, department, role, agent_name)
        query. ``rules`` is set so ``len(allocator.rules) > 0``.
    """
    from bridge.skill_allocator import AllocationRule, SkillAllocator

    # Two cascade-everywhere rules (one per zone) so every department,
    # role, and agent sees the same permissive "all-skills" set under
    # the allocator's matching semantics. The skill strings are
    # synthetic placeholders for the test surface.
    rules = [
        AllocationRule(
            skill="test:permissive-zone3",
            zone=3,
            department=None,
            role=None,
            agents=(),
        ),
        AllocationRule(
            skill="test:permissive-zone4",
            zone=4,
            department=None,
            role=None,
            agents=(),
        ),
    ]
    return SkillAllocator(rules=rules)


@pytest.fixture
def permissive_skill_allocator():
    """Pytest fixture returning a permissive SkillAllocator for tests.

    Most existing tests don't need this — they construct teams without
    an allocator (the None back-compat path). Use this only when the
    test asserts allocator-aware INFO logging or downstream filter
    behavior.
    """
    return make_test_allocator()
