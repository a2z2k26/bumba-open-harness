"""Tests for bridge-native primer writer (#488).

Spec: docs/specs/2026-04-17-488-primer-writer-spec.md

TDD order: these tests are written before the implementation. Each test class
corresponds to a section in the spec's "Test Plan (TDD)" area.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.primer_writer import (
    MAX_CONSECUTIVE_FAILURES,
    PrimerSynthesisError,
    PrimerV1,
    _atomic_write,
    _collect_deterministic_facts,
    _extract_json_object,
    _merge,
    _synthesize_narrative,
    get_primer_health,
    read_primer,
    write_primer,
)


# ─────────────────────────────────────────────────────────────────────
# Test fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_primer_path(tmp_path, monkeypatch):
    """Redirect PRIMER_PATH into tmp dir for each test."""
    from bridge import primer_writer
    new_path = tmp_path / "primer.json"
    monkeypatch.setattr(primer_writer, "PRIMER_PATH", new_path)
    monkeypatch.setattr(primer_writer, "PRIMER_STATE_PATH", tmp_path / "primer_state.json")
    return new_path


@pytest.fixture
def mock_deps():
    """Minimal BridgeDeps-like object with the fields primer_writer reads."""
    deps = MagicMock()
    deps.memory_store = MagicMock()
    deps.project_registry = MagicMock()
    deps.task_queue = MagicMock()
    deps.plan_state = MagicMock()
    deps.daily_log_tail = MagicMock(return_value="")
    deps.event_bus = MagicMock()
    deps.claude_runner = MagicMock()
    deps.cost_tracker = MagicMock()
    return deps


# ─────────────────────────────────────────────────────────────────────
# Section 1 — PrimerV1 dataclass contract
# ─────────────────────────────────────────────────────────────────────


class TestPrimerV1:
    def test_is_frozen(self):
        p = PrimerV1(
            schema_version="1.0",
            generated_at="2026-04-17T12:00:00+00:00",
            session_id="sess-abc",
            expires_at="2026-04-18T12:00:00+00:00",
            current_track={"name": "System", "type": "system", "switched_at": None},
            active_projects=[],
            recent_decisions=[],
            open_blockers=[],
            pending_tasks=[],
            session_summary="test",
            operator_context={"mood": "focused", "last_seen": "2026-04-17T12:00:00+00:00", "notes": None},
            trigger_source="expire",
        )
        with pytest.raises(AttributeError):
            p.schema_version = "2.0"  # type: ignore[misc]

    def test_to_json_produces_schema(self):
        p = PrimerV1(
            schema_version="1.0",
            generated_at="2026-04-17T12:00:00+00:00",
            session_id="sess-abc",
            expires_at="2026-04-18T12:00:00+00:00",
            current_track={"name": "System", "type": "system", "switched_at": None},
            active_projects=[{"name": "bumba-open-harness", "status": "active"}],
            recent_decisions=[],
            open_blockers=[],
            pending_tasks=[],
            session_summary="Did work.",
            operator_context={"mood": "focused", "last_seen": "2026-04-17T12:00:00+00:00", "notes": None},
            trigger_source="expire",
        )
        data = json.loads(p.to_json())
        # All schema keys present
        assert data["schema_version"] == "1.0"
        assert data["session_id"] == "sess-abc"
        assert data["active_projects"] == [{"name": "bumba-open-harness", "status": "active"}]
        assert data["session_summary"] == "Did work."
        assert data["trigger_source"] == "expire"


# ─────────────────────────────────────────────────────────────────────
# Section 2 — Deterministic facts collection
# ─────────────────────────────────────────────────────────────────────


class TestCollectDeterministicFacts:
    def test_populates_all_keys(self, mock_deps):
        mock_deps.project_registry.list_active.return_value = [
            {"name": "bumba-open-harness", "status": "active", "current_phase": "planning",
             "next_action": "review plan", "github_branch": "main"}
        ]
        mock_deps.memory_store.recent_decisions.return_value = [
            {"topic": "path", "decision": "use data/", "rationale": "bridge native", "made_at": "2026-04-17T12:00:00+00:00"}
        ]
        mock_deps.task_queue.pending.return_value = []
        mock_deps.plan_state.pending_tasks.return_value = []

        facts = _collect_deterministic_facts(mock_deps, session_id="sess-42")

        assert facts["session_id"] == "sess-42"
        assert facts["schema_version"] == "1.0"
        assert isinstance(facts["active_projects"], list)
        assert len(facts["active_projects"]) == 1
        assert isinstance(facts["recent_decisions"], list)
        assert facts["recent_decisions"][0]["topic"] == "path"
        assert isinstance(facts["open_blockers"], list)
        assert isinstance(facts["pending_tasks"], list)

    def test_empty_data_returns_empty_lists_not_none(self, mock_deps):
        mock_deps.project_registry.list_active.return_value = []
        mock_deps.memory_store.recent_decisions.return_value = []
        mock_deps.task_queue.pending.return_value = []
        mock_deps.plan_state.pending_tasks.return_value = []

        facts = _collect_deterministic_facts(mock_deps, session_id="sess-42")

        assert facts["active_projects"] == []
        assert facts["recent_decisions"] == []
        assert facts["open_blockers"] == []
        assert facts["pending_tasks"] == []

    def test_expires_at_is_24h_after_generated_at(self, mock_deps):
        mock_deps.project_registry.list_active.return_value = []
        mock_deps.memory_store.recent_decisions.return_value = []
        mock_deps.task_queue.pending.return_value = []
        mock_deps.plan_state.pending_tasks.return_value = []

        facts = _collect_deterministic_facts(mock_deps, session_id="sess-42")

        generated = datetime.fromisoformat(facts["generated_at"])
        expires = datetime.fromisoformat(facts["expires_at"])
        # Allow 1 second wiggle for clock edges
        assert timedelta(hours=23, minutes=59) <= (expires - generated) <= timedelta(hours=24, seconds=1)

    def test_survives_deps_collection_errors(self, mock_deps):
        """If one backend throws, others still contribute; errors degrade to empty."""
        mock_deps.project_registry.list_active.side_effect = RuntimeError("boom")
        mock_deps.memory_store.recent_decisions.return_value = []
        mock_deps.task_queue.pending.return_value = []
        mock_deps.plan_state.pending_tasks.return_value = []

        facts = _collect_deterministic_facts(mock_deps, session_id="sess-42")

        # active_projects degrades to empty on error
        assert facts["active_projects"] == []


# ─────────────────────────────────────────────────────────────────────
# Section 3 — LLM narrative synthesis
# ─────────────────────────────────────────────────────────────────────


class TestSynthesizeNarrative:
    @pytest.mark.asyncio
    async def test_happy_path_returns_three_fields(self, mock_deps):
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": json.dumps({
                "session_summary": "Planned Zone 2/3/4 hardening.",
                "mood": "focused",
                "notes": "Clean issue board at end.",
            }),
            "cost_usd": 0.008,
        })

        facts = {"session_id": "sess-42", "active_projects": []}
        narrative = await _synthesize_narrative(mock_deps, facts, log_tail="")

        assert narrative["session_summary"] == "Planned Zone 2/3/4 hardening."
        assert narrative["mood"] == "focused"
        assert narrative["notes"] == "Clean issue board at end."

    @pytest.mark.asyncio
    async def test_llm_error_raises(self, mock_deps):
        mock_deps.claude_runner.invoke = AsyncMock(side_effect=RuntimeError("claude subprocess failed"))
        with pytest.raises(PrimerSynthesisError):
            await _synthesize_narrative(mock_deps, {"session_id": "s"}, log_tail="")

    @pytest.mark.asyncio
    async def test_malformed_response_raises(self, mock_deps):
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": "not json at all",
            "cost_usd": 0.001,
        })
        with pytest.raises(PrimerSynthesisError):
            await _synthesize_narrative(mock_deps, {"session_id": "s"}, log_tail="")

    @pytest.mark.asyncio
    async def test_empty_response_raises(self, mock_deps):
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": "",
            "cost_usd": 0.001,
        })
        with pytest.raises(PrimerSynthesisError, match="empty response"):
            await _synthesize_narrative(mock_deps, {"session_id": "s"}, log_tail="")

    @pytest.mark.asyncio
    async def test_is_error_true_raises(self, mock_deps):
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": "ok",
            "cost_usd": 0.001,
            "is_error": True,
        })
        with pytest.raises(PrimerSynthesisError, match="is_error"):
            await _synthesize_narrative(mock_deps, {"session_id": "s"}, log_tail="")

    @pytest.mark.asyncio
    async def test_markdown_fenced_json_extracted(self, mock_deps):
        """Claude often wraps JSON in ```json fences — must still parse."""
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": '```json\n{"session_summary": "ok", "mood": "focused", "notes": null}\n```',
            "cost_usd": 0.001,
        })
        narrative = await _synthesize_narrative(mock_deps, {"session_id": "s"}, log_tail="")
        assert narrative["session_summary"] == "ok"
        assert narrative["mood"] == "focused"
        assert narrative["notes"] is None

    @pytest.mark.asyncio
    async def test_prose_prefix_json_extracted(self, mock_deps):
        """Preface text before JSON — first { to matching } still extracted."""
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": 'Here is the primer:\n{"session_summary": "did stuff", "mood": "focused", "notes": null}\nThat should help.',
            "cost_usd": 0.001,
        })
        narrative = await _synthesize_narrative(mock_deps, {"session_id": "s"}, log_tail="")
        assert narrative["session_summary"] == "did stuff"

    @pytest.mark.asyncio
    async def test_cost_cap_enforced_on_return(self, mock_deps):
        """If LLM returns cost above cap, the synthesis is rejected."""
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": json.dumps({"session_summary": "ok", "mood": "unknown", "notes": None}),
            "cost_usd": 0.50,  # way over the $0.01 cap
        })
        with pytest.raises(PrimerSynthesisError, match="cost"):
            await _synthesize_narrative(mock_deps, {"session_id": "s"}, log_tail="")


# ─────────────────────────────────────────────────────────────────────
# Section 3b — _extract_json_object helper robustness
# ─────────────────────────────────────────────────────────────────────


class TestExtractJsonObject:
    def test_clean_json(self):
        assert _extract_json_object('{"a": 1}') == '{"a": 1}'

    def test_code_fence_stripped(self):
        assert _extract_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_generic_fence_stripped(self):
        assert _extract_json_object('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_prose_prefix(self):
        assert _extract_json_object('Here you go: {"a": 1}') == '{"a": 1}'

    def test_prose_suffix(self):
        assert _extract_json_object('{"a": 1} — that is the answer') == '{"a": 1}'

    def test_nested_objects(self):
        assert _extract_json_object('{"a": {"b": 1}}') == '{"a": {"b": 1}}'

    def test_braces_in_strings_ignored(self):
        assert _extract_json_object('{"a": "text with } inside"}') == '{"a": "text with } inside"}'

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _extract_json_object("")

    def test_no_braces_raises(self):
        with pytest.raises(ValueError, match="no object-open brace"):
            _extract_json_object("just prose, no JSON")

    def test_unclosed_object_raises(self):
        with pytest.raises(ValueError, match="no matching close brace"):
            _extract_json_object('{"a": 1')


# ─────────────────────────────────────────────────────────────────────
# Section 4 — Atomic write
# ─────────────────────────────────────────────────────────────────────


class TestAtomicWrite:
    def test_writes_file_at_primer_path(self, tmp_primer_path):
        primer = PrimerV1(
            schema_version="1.0",
            generated_at="2026-04-17T12:00:00+00:00",
            session_id="sess-abc",
            expires_at="2026-04-18T12:00:00+00:00",
            current_track={"name": "System", "type": "system", "switched_at": None},
            active_projects=[],
            recent_decisions=[],
            open_blockers=[],
            pending_tasks=[],
            session_summary="Test",
            operator_context={"mood": "focused", "last_seen": "2026-04-17T12:00:00+00:00", "notes": None},
            trigger_source="expire",
        )
        _atomic_write(primer, path=tmp_primer_path)
        assert tmp_primer_path.is_file()
        data = json.loads(tmp_primer_path.read_text())
        assert data["session_id"] == "sess-abc"

    def test_no_leftover_temp_files(self, tmp_primer_path):
        primer = PrimerV1(
            schema_version="1.0", generated_at="2026-04-17T12:00:00+00:00",
            session_id="s", expires_at="2026-04-18T12:00:00+00:00",
            current_track={"name": "s", "type": "system", "switched_at": None},
            active_projects=[], recent_decisions=[], open_blockers=[], pending_tasks=[],
            session_summary="", operator_context={"mood": "unknown", "last_seen": "", "notes": None},
            trigger_source="expire",
        )
        _atomic_write(primer, path=tmp_primer_path)
        tmps = list(tmp_primer_path.parent.glob("*.tmp"))
        assert tmps == []

    def test_overwrites_existing(self, tmp_primer_path):
        tmp_primer_path.write_text('{"stale": true}')
        primer = PrimerV1(
            schema_version="1.0", generated_at="2026-04-17T12:00:00+00:00",
            session_id="fresh", expires_at="2026-04-18T12:00:00+00:00",
            current_track={"name": "s", "type": "system", "switched_at": None},
            active_projects=[], recent_decisions=[], open_blockers=[], pending_tasks=[],
            session_summary="", operator_context={"mood": "unknown", "last_seen": "", "notes": None},
            trigger_source="expire",
        )
        _atomic_write(primer, path=tmp_primer_path)
        data = json.loads(tmp_primer_path.read_text())
        assert data["session_id"] == "fresh"
        assert "stale" not in data


# ─────────────────────────────────────────────────────────────────────
# Section 5 — write_primer orchestration
# ─────────────────────────────────────────────────────────────────────


class TestWritePrimerOrchestration:
    @pytest.mark.asyncio
    async def test_happy_path_writes_and_returns_path(self, mock_deps, tmp_primer_path):
        mock_deps.project_registry.list_active.return_value = []
        mock_deps.memory_store.recent_decisions.return_value = []
        mock_deps.task_queue.pending.return_value = []
        mock_deps.plan_state.pending_tasks.return_value = []
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": json.dumps({"session_summary": "ok", "mood": "focused", "notes": None}),
            "cost_usd": 0.005,
        })

        path = await write_primer(mock_deps, session_id="sess-abc", trigger_source="expire")

        assert path is not None
        assert path == tmp_primer_path
        assert tmp_primer_path.is_file()
        data = json.loads(tmp_primer_path.read_text())
        assert data["session_id"] == "sess-abc"
        assert data["session_summary"] == "ok"
        assert data["trigger_source"] == "expire"

    @pytest.mark.asyncio
    async def test_llm_failure_writes_degraded(self, mock_deps, tmp_primer_path):
        """If LLM fails, primer is still written with empty narrative."""
        mock_deps.project_registry.list_active.return_value = []
        mock_deps.memory_store.recent_decisions.return_value = []
        mock_deps.task_queue.pending.return_value = []
        mock_deps.plan_state.pending_tasks.return_value = []
        mock_deps.claude_runner.invoke = AsyncMock(side_effect=RuntimeError("llm down"))

        path = await write_primer(mock_deps, session_id="sess-abc", trigger_source="reset")

        # Degraded mode still writes the primer
        assert path is not None
        data = json.loads(tmp_primer_path.read_text())
        assert data["session_id"] == "sess-abc"
        # Narrative fields degraded to defaults
        assert data["session_summary"] == ""
        assert data["operator_context"]["mood"] == "unknown"
        assert data["operator_context"]["notes"] is None

    @pytest.mark.asyncio
    async def test_total_failure_returns_none(self, mock_deps, tmp_primer_path, monkeypatch):
        """If even the atomic write fails, returns None."""
        mock_deps.project_registry.list_active.return_value = []
        mock_deps.memory_store.recent_decisions.return_value = []
        mock_deps.task_queue.pending.return_value = []
        mock_deps.plan_state.pending_tasks.return_value = []
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": json.dumps({"session_summary": "ok", "mood": "focused", "notes": None}),
            "cost_usd": 0.005,
        })

        # Force write to fail
        from bridge import primer_writer
        monkeypatch.setattr(primer_writer, "_atomic_write",
                            MagicMock(side_effect=OSError("disk full")))

        path = await write_primer(mock_deps, session_id="sess-abc", trigger_source="expire")
        assert path is None

    @pytest.mark.asyncio
    async def test_three_consecutive_failures_fires_alert(self, mock_deps, tmp_primer_path, monkeypatch):
        """After MAX_CONSECUTIVE_FAILURES, emit a Discord-worthy event."""
        from bridge import primer_writer
        monkeypatch.setattr(primer_writer, "_atomic_write",
                            MagicMock(side_effect=OSError("persistent disk full")))
        mock_deps.project_registry.list_active.return_value = []
        mock_deps.memory_store.recent_decisions.return_value = []
        mock_deps.task_queue.pending.return_value = []
        mock_deps.plan_state.pending_tasks.return_value = []
        mock_deps.claude_runner.invoke = AsyncMock(return_value={
            "response_text": json.dumps({"session_summary": "ok", "mood": "focused", "notes": None}),
            "cost_usd": 0.005,
        })

        for _ in range(MAX_CONSECUTIVE_FAILURES):
            await write_primer(mock_deps, session_id="s", trigger_source="expire")

        # After N failures, the event bus saw a primer.write.alert event
        publish_calls = [c for c in mock_deps.event_bus.publish.call_args_list
                         if c.args and c.args[0] == "primer.write.alert"]
        assert len(publish_calls) >= 1


# ─────────────────────────────────────────────────────────────────────
# Section 6 — read_primer + get_primer_health
# ─────────────────────────────────────────────────────────────────────


class TestReadAndHealth:
    def test_read_primer_missing_returns_none(self, tmp_primer_path):
        assert read_primer() is None

    def test_read_primer_returns_parsed(self, tmp_primer_path):
        tmp_primer_path.write_text(json.dumps({
            "schema_version": "1.0",
            "generated_at": "2026-04-17T12:00:00+00:00",
            "session_id": "s",
            "expires_at": "2026-04-18T12:00:00+00:00",
            "current_track": {"name": "s", "type": "system", "switched_at": None},
            "active_projects": [],
            "recent_decisions": [],
            "open_blockers": [],
            "pending_tasks": [],
            "session_summary": "did stuff",
            "operator_context": {"mood": "focused", "last_seen": "", "notes": None},
            "trigger_source": "expire",
        }))
        p = read_primer()
        assert p is not None
        assert p.session_id == "s"

    def test_health_when_no_primer(self, tmp_primer_path):
        health = get_primer_health()
        assert health["primer_last_write_success"] is False
        assert health["primer_last_write_age_minutes"] is None

    def test_health_with_primer(self, tmp_primer_path):
        now = datetime.now(timezone.utc).isoformat()
        tmp_primer_path.write_text(json.dumps({
            "schema_version": "1.0",
            "generated_at": now,
            "session_id": "s",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "current_track": {"name": "s", "type": "system", "switched_at": None},
            "active_projects": [], "recent_decisions": [], "open_blockers": [], "pending_tasks": [],
            "session_summary": "ok",
            "operator_context": {"mood": "focused", "last_seen": "", "notes": None},
            "trigger_source": "expire",
        }))
        health = get_primer_health()
        assert health["primer_last_write_success"] is True
        assert health["primer_last_write_age_minutes"] is not None
        assert health["primer_last_write_age_minutes"] < 1  # just written


# ─────────────────────────────────────────────────────────────────────
# Section 7 — _merge helper
# ─────────────────────────────────────────────────────────────────────


class TestMerge:
    def test_merge_produces_primer_v1(self):
        facts = {
            "schema_version": "1.0",
            "generated_at": "2026-04-17T12:00:00+00:00",
            "session_id": "s",
            "expires_at": "2026-04-18T12:00:00+00:00",
            "current_track": {"name": "System", "type": "system", "switched_at": None},
            "active_projects": [],
            "recent_decisions": [],
            "open_blockers": [],
            "pending_tasks": [],
            "operator_last_seen": "2026-04-17T12:00:00+00:00",
        }
        narrative = {"session_summary": "did stuff", "mood": "focused", "notes": "clean"}
        primer = _merge(facts, narrative, trigger_source="expire")

        assert isinstance(primer, PrimerV1)
        assert primer.session_id == "s"
        assert primer.session_summary == "did stuff"
        assert primer.operator_context["mood"] == "focused"
        assert primer.operator_context["notes"] == "clean"
        assert primer.trigger_source == "expire"

    def test_merge_empty_narrative_defaults(self):
        """Degraded-mode merge — no narrative at all — produces valid primer."""
        facts = {
            "schema_version": "1.0",
            "generated_at": "2026-04-17T12:00:00+00:00",
            "session_id": "s",
            "expires_at": "2026-04-18T12:00:00+00:00",
            "current_track": {"name": "System", "type": "system", "switched_at": None},
            "active_projects": [],
            "recent_decisions": [],
            "open_blockers": [],
            "pending_tasks": [],
            "operator_last_seen": "2026-04-17T12:00:00+00:00",
        }
        primer = _merge(facts, {}, trigger_source="expire")
        assert primer.session_summary == ""
        assert primer.operator_context["mood"] == "unknown"
        assert primer.operator_context["notes"] is None
