"""Tests for MS4.3: Evidence-Driven Skill Evolution."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bridge.skill_evolution import (
    DEFAULT_MARKDOWN_SKILLS_DIR,
    MarkdownSkill,
    SkillEvolutionEngine,
    SkillProposal,
)


@pytest.fixture
def engine(tmp_path):
    return SkillEvolutionEngine(tmp_path / "evo.db")


# ── Failure Pattern Detection ──

class TestFailureDetection:
    def test_detect_recurring_failures(self, engine):
        for i in range(5):
            engine.record_failure("search", "timeout", f"Brave search timed out #{i}")
        patterns = engine.detect_recurring_failures(threshold=3)
        assert len(patterns) >= 1
        assert patterns[0].task_type == "search"
        assert patterns[0].error_type == "timeout"
        assert patterns[0].count >= 5

    def test_detect_below_threshold(self, engine):
        for i in range(2):
            engine.record_failure("search", "timeout", f"msg {i}")
        patterns = engine.detect_recurring_failures(threshold=3)
        assert len(patterns) == 0

    def test_detect_multiple_patterns(self, engine):
        for i in range(4):
            engine.record_failure("search", "timeout", f"t {i}")
        for i in range(3):
            engine.record_failure("deploy", "crash", f"c {i}")
        patterns = engine.detect_recurring_failures(threshold=3)
        assert len(patterns) == 2

    def test_sample_messages_capped(self, engine):
        for i in range(10):
            engine.record_failure("search", "timeout", f"msg {i}")
        patterns = engine.detect_recurring_failures(threshold=3)
        assert len(patterns[0].sample_messages) <= 5

    def test_failure_count(self, engine):
        assert engine.failure_count() == 0
        engine.record_failure("a", "b", "c")
        assert engine.failure_count() == 1


# ── Proposal Creation ──

class TestProposalCreation:
    def test_create_proposal(self, engine):
        p = SkillProposal(
            name="resilient-search",
            description="Search with retry and fallback",
            trigger_condition="Search task with previous timeouts",
            approach=["Check health", "Try primary", "Fallback to secondary"],
        )
        rid = engine.create_proposal(p)
        assert rid > 0

    def test_proposal_roundtrip(self, engine):
        p = SkillProposal(
            name="test-skill",
            description="A test skill",
            trigger_condition="When testing",
            approach=["Step 1", "Step 2"],
            failure_pattern={"count": 5, "error_type": "timeout"},
        )
        engine.create_proposal(p)
        got = engine.get_proposal_by_name("test-skill")
        assert got is not None
        assert got.name == "test-skill"
        assert got.approach == ["Step 1", "Step 2"]
        assert got.failure_pattern["count"] == 5

    def test_no_duplicate_proposals(self, engine):
        p = SkillProposal(
            name="unique-skill",
            description="v1",
            trigger_condition="t",
            approach=["a"],
        )
        engine.create_proposal(p)
        p.description = "v2"
        engine.create_proposal(p)  # REPLACE
        all_p = engine.get_proposals()
        names = [x.name for x in all_p]
        assert names.count("unique-skill") == 1

    def test_proposal_exists(self, engine):
        assert engine.proposal_exists("nope") is False
        engine.create_proposal(SkillProposal(
            name="exists", description="d", trigger_condition="t", approach=["a"],
        ))
        assert engine.proposal_exists("exists") is True


# ── Tier Classification ──

class TestTierClassification:
    def test_tier_a_normal_skill(self, engine):
        p = SkillProposal(
            name="search-retry",
            description="Retry search with exponential backoff",
            trigger_condition="Search timeout",
            approach=["Wait", "Retry"],
        )
        engine.create_proposal(p)
        got = engine.get_proposal_by_name("search-retry")
        assert got.tier == "A"

    def test_tier_b_kernel_adjacent(self, engine):
        p = SkillProposal(
            name="security-fix",
            description="Fix security vulnerability in bridge/ module",
            trigger_condition="Security alert",
            approach=["Patch the security issue"],
        )
        engine.create_proposal(p)
        got = engine.get_proposal_by_name("security-fix")
        assert got.tier == "B"


# ── Pareto Scoring ──

class TestParetoScoring:
    def test_high_frequency_crash_ranked_first(self, engine):
        proposals = [
            SkillProposal(
                name="a", description="", trigger_condition="", approach=[],
                failure_pattern={"count": 10, "error_type": "crash"},
            ),
            SkillProposal(
                name="b", description="", trigger_condition="", approach=[],
                failure_pattern={"count": 3, "error_type": "warning"},
            ),
        ]
        ranked = engine.prioritize_proposals(proposals)
        assert ranked[0].name == "a"
        assert ranked[0].score > ranked[1].score

    def test_top_n_limit(self, engine):
        proposals = [
            SkillProposal(
                name=f"p{i}", description="", trigger_condition="", approach=[],
                failure_pattern={"count": i, "error_type": "error"},
            )
            for i in range(10)
        ]
        ranked = engine.prioritize_proposals(proposals, top_n=3)
        assert len(ranked) == 3


# ── SKILL.md Generation ──

class TestSkillMdGeneration:
    def test_generate_skill_md_format(self, engine):
        p = SkillProposal(
            name="resilient-search",
            description="Search with retry and fallback sources",
            trigger_condition="Search task with previous timeout failures",
            approach=["Check brave-search health", "If degraded, use exa", "Return results"],
        )
        md = engine.generate_skill_md(p)
        assert "# resilient-search" in md
        assert "## Description" in md
        assert "## When to Use" in md
        assert "## Approach" in md
        assert "1. Check brave-search health" in md
        assert "2. If degraded, use exa" in md


# ── Validation ──

class TestValidation:
    def test_valid_skill_passes(self):
        content = (
            "# My Skill\n\n"
            "## Description\nA safe skill\n\n"
            "## Approach\n1. Do something safe\n"
        )
        result = SkillEvolutionEngine.validate_skill(content)
        assert result.passed is True
        assert result.errors == []

    def test_dangerous_rm_rf_fails(self):
        content = "# Bad\n\n## Steps\nRun rm -rf / to clean up\n"
        result = SkillEvolutionEngine.validate_skill(content)
        assert result.passed is False
        assert any("rm" in e for e in result.errors)

    def test_dangerous_sudo_fails(self):
        content = "# Bad\n\n## Steps\nRun sudo apt install\n"
        result = SkillEvolutionEngine.validate_skill(content)
        assert result.passed is False

    def test_missing_title_fails(self):
        content = "No headings here, just plain text."
        result = SkillEvolutionEngine.validate_skill(content)
        assert result.passed is False

    def test_no_verify_fails(self):
        content = "# Skill\n\n## Steps\ngit commit --no-verify\n"
        result = SkillEvolutionEngine.validate_skill(content)
        assert result.passed is False


# ── Proposal Status Management ──

class TestProposalStatus:
    def test_approve_proposal(self, engine):
        engine.create_proposal(SkillProposal(
            name="test", description="d", trigger_condition="t", approach=["a"],
        ))
        assert engine.update_proposal_status("test", "approved") is True
        got = engine.get_proposal_by_name("test")
        assert got.status == "approved"

    def test_reject_proposal_with_reason(self, engine):
        engine.create_proposal(SkillProposal(
            name="bad", description="d", trigger_condition="t", approach=["a"],
        ))
        engine.update_proposal_status("bad", "rejected", "Not useful")
        got = engine.get_proposal_by_name("bad")
        assert got.status == "rejected"
        assert got.reject_reason == "Not useful"

    def test_filter_by_status(self, engine):
        engine.create_proposal(SkillProposal(
            name="a", description="d", trigger_condition="t", approach=["x"],
        ))
        engine.create_proposal(SkillProposal(
            name="b", description="d", trigger_condition="t", approach=["x"],
        ))
        engine.update_proposal_status("a", "deployed")
        deployed = engine.get_proposals(status="deployed")
        assert len(deployed) == 1
        assert deployed[0].name == "a"

    def test_update_nonexistent(self, engine):
        assert engine.update_proposal_status("nope", "approved") is False


# ── Gotchas Generation ──

class TestGotchasGeneration:
    def test_generate_gotchas_returns_markdown(self, engine):
        # Same error_type + same message = single deduplicated entry with count 3
        for _ in range(3):
            engine.record_failure("webapp-testing", "timeout", "Request timed out")
        result = engine.generate_gotchas("webapp-testing")
        assert result.startswith("## Gotchas")
        assert "timeout" in result
        assert "3x" in result

    def test_generate_gotchas_empty_when_no_failures(self, engine):
        result = engine.generate_gotchas("webapp-testing")
        assert result == ""

    def test_generate_gotchas_deduplicates(self, engine):
        # Same error type + message repeated — should appear once with combined count
        for _ in range(4):
            engine.record_failure("webapp-testing", "auth_error", "401 Unauthorized")
        for _ in range(2):
            engine.record_failure("webapp-testing", "auth_error", "401 Unauthorized")
        result = engine.generate_gotchas("webapp-testing")
        assert result.count("auth_error") == 1
        assert "6x" in result

    def test_generate_gotchas_multiple_error_types(self, engine):
        for i in range(2):
            engine.record_failure("webapp-testing", "timeout", f"Timeout {i}")
        for i in range(3):
            engine.record_failure("webapp-testing", "crash", f"Crash {i}")
        result = engine.generate_gotchas("webapp-testing")
        assert "timeout" in result
        assert "crash" in result

    def test_get_failures_for_skill_normalises_hyphens(self, engine):
        # Record with underscores, query with hyphens
        engine.record_failure("webapp_testing", "ssl_error", "SSL handshake failed")
        failures = engine.get_failures_for_skill("webapp-testing")
        assert any(f["error_type"] == "ssl_error" for f in failures)

    def test_get_failures_for_skill_empty(self, engine):
        assert engine.get_failures_for_skill("no-such-skill") == []


# ── Sprint 03.08 (#998) — 3-trigger skill evolution loop ──

class _StubToolHealth:
    """Minimal ToolHealth-shaped stub for monitor_tool_degradation tests."""

    def __init__(
        self,
        invocations: int = 0,
        success_rate: float = 1.0,
        status: str = "healthy",
    ) -> None:
        self.invocations = invocations
        self.success_rate = success_rate
        self.status = status


class _StubRoutingFeedback:
    """Stub that mimics RoutingFeedbackEngine.get_tool_health()."""

    def __init__(self, health_by_tool: dict[str, _StubToolHealth]) -> None:
        self._health_by_tool = health_by_tool

    def get_tool_health(self, tool_name: str) -> _StubToolHealth:
        return self._health_by_tool.get(tool_name, _StubToolHealth())


class TestPostExecutionTrigger:
    def test_fires_on_failed_execution(self, engine):
        record = {
            "skill_name": "webapp-testing",
            "success": False,
            "error_type": "timeout",
            "error_message": "Request timed out after 30s",
        }
        proposal = engine.evaluate_post_execution(record)
        assert proposal is not None
        assert proposal.reason == "post_execution"
        assert "webapp-testing" in proposal.name
        assert "timeout" in proposal.name

    def test_fires_on_retry(self, engine):
        record = {
            "skill_name": "deploy",
            "success": True,
            "retry_count": 2,
        }
        proposal = engine.evaluate_post_execution(record)
        assert proposal is not None
        assert proposal.reason == "post_execution"

    def test_returns_none_on_clean_success(self, engine):
        record = {
            "skill_name": "deploy",
            "success": True,
            "retry_count": 0,
        }
        assert engine.evaluate_post_execution(record) is None

    def test_returns_none_when_skill_name_missing(self, engine):
        record = {"success": False, "error_type": "timeout"}
        assert engine.evaluate_post_execution(record) is None

    def test_returns_none_on_non_dict_input(self, engine):
        assert engine.evaluate_post_execution("not a dict") is None  # type: ignore[arg-type]

    def test_compose_with_create_proposal(self, engine):
        """evaluate → create_proposal composition matches the dispatch contract."""
        record = {"skill_name": "search", "success": False, "error_type": "rate_limit"}
        proposal = engine.evaluate_post_execution(record)
        assert proposal is not None
        rid = engine.create_proposal(proposal)
        assert rid > 0


class TestToolDegradationTrigger:
    def test_fires_on_high_failure_rate(self, engine):
        feedback = _StubRoutingFeedback(
            {"brave-search": _StubToolHealth(invocations=10, success_rate=0.4)}
        )
        proposal = engine.monitor_tool_degradation("brave-search", feedback)
        assert proposal is not None
        assert proposal.reason == "tool_degradation"
        assert "brave-search" in proposal.name

    def test_returns_none_when_healthy(self, engine):
        feedback = _StubRoutingFeedback(
            {"brave-search": _StubToolHealth(invocations=10, success_rate=0.95)}
        )
        assert engine.monitor_tool_degradation("brave-search", feedback) is None

    def test_returns_none_when_under_sampled(self, engine):
        feedback = _StubRoutingFeedback(
            {"brave-search": _StubToolHealth(invocations=2, success_rate=0.0)}
        )
        assert engine.monitor_tool_degradation("brave-search", feedback) is None

    def test_returns_none_when_feedback_missing(self, engine):
        assert engine.monitor_tool_degradation("brave-search", None) is None

    def test_returns_none_when_feedback_lacks_api(self, engine):
        class _Empty:
            pass

        assert engine.monitor_tool_degradation("brave-search", _Empty()) is None

    def test_reads_from_real_routing_feedback(self, engine, tmp_path):
        """Integration check: real RoutingFeedbackEngine.get_tool_health works."""
        from bridge.routing_feedback import RoutingFeedbackEngine

        rf = RoutingFeedbackEngine(tmp_path / "rf.db")
        # 3 successes, 7 failures = 30% success rate, 70% failure rate
        for _ in range(3):
            rf.record_tool_use("flaky-tool", success=True)
        for _ in range(7):
            rf.record_tool_use("flaky-tool", success=False)

        proposal = engine.monitor_tool_degradation("flaky-tool", rf)
        assert proposal is not None
        assert proposal.reason == "tool_degradation"


class TestPeriodicHealthCheck:
    def test_returns_empty_list_when_no_proposals(self, engine):
        assert engine.periodic_health_check() == []

    def test_returns_empty_list_when_all_fresh(self, engine):
        engine.create_proposal(SkillProposal(
            name="fresh", description="d", trigger_condition="t", approach=["a"],
        ))
        # Default cutoff is 30 days; fresh proposal should not match.
        assert engine.periodic_health_check() == []

    def test_finds_stale_proposals(self, engine):
        import sqlite3
        # Seed a stale proposal directly so we can backdate updated_at.
        engine.create_proposal(SkillProposal(
            name="stale-skill", description="d",
            trigger_condition="t", approach=["a"],
        ))
        conn = sqlite3.connect(engine._db_path)
        try:
            conn.execute(
                "UPDATE skill_proposals SET updated_at = "
                "datetime('now', '-60 days') WHERE name = ?",
                ("stale-skill",),
            )
            conn.commit()
        finally:
            conn.close()

        proposals = engine.periodic_health_check(stale_after_days=30)
        assert len(proposals) == 1
        assert proposals[0].reason == "periodic_health"
        assert "stale-skill" in proposals[0].name

    def test_returns_multiple_when_multiple_stale(self, engine):
        import sqlite3
        for name in ("alpha", "beta", "gamma"):
            engine.create_proposal(SkillProposal(
                name=name, description="d",
                trigger_condition="t", approach=["a"],
            ))
        conn = sqlite3.connect(engine._db_path)
        try:
            conn.execute(
                "UPDATE skill_proposals SET updated_at = "
                "datetime('now', '-90 days')"
            )
            conn.commit()
        finally:
            conn.close()

        proposals = engine.periodic_health_check(stale_after_days=30)
        assert len(proposals) == 3
        assert all(p.reason == "periodic_health" for p in proposals)

    def test_skips_terminal_status(self, engine):
        import sqlite3
        engine.create_proposal(SkillProposal(
            name="deployed-skill", description="d",
            trigger_condition="t", approach=["a"],
        ))
        engine.update_proposal_status("deployed-skill", "deployed")
        conn = sqlite3.connect(engine._db_path)
        try:
            conn.execute(
                "UPDATE skill_proposals SET updated_at = "
                "datetime('now', '-60 days')"
            )
            conn.commit()
        finally:
            conn.close()

        # 'deployed' is terminal — health check should ignore it.
        assert engine.periodic_health_check(stale_after_days=30) == []


class TestSkillProposalReasonField:
    def test_default_reason_blank(self):
        p = SkillProposal(name="x", description="d", trigger_condition="t", approach=[])
        assert p.reason == ""

    def test_reason_round_trips_in_memory(self):
        p = SkillProposal(
            name="x", description="d", trigger_condition="t", approach=[],
            reason="post_execution",
        )
        assert p.reason == "post_execution"

    def test_legacy_record_failure_unchanged_when_loop_off(self, engine):
        """Feature-flag-OFF path: existing record_failure / detect API
        keeps working byte-for-byte. The new trigger methods are
        opt-in and never invoked unless the caller composes them with
        create_proposal under the flag."""
        for i in range(4):
            engine.record_failure("legacy-search", "timeout", f"#{i}")
        patterns = engine.detect_recurring_failures(threshold=3)
        assert len(patterns) == 1
        assert patterns[0].task_type == "legacy-search"


# ── Sprint 03.09 (#999) — Crystallize-from-trace trigger ──

def _good_trace() -> list[dict]:
    """A 4-step trace with one tool call per step and no errors."""
    return [
        {"tool": "search", "input": {"q": "x"}, "output": {"hits": 3}, "ts": "t1"},
        {"tool": "fetch", "input": {"url": "u"}, "output": {"ok": True}, "ts": "t2"},
        {"tool": "summarize", "input": {"text": "..."}, "output": {"ok": True}, "ts": "t3"},
        {"tool": "write", "input": {"path": "/tmp/x"}, "output": {"ok": True}, "ts": "t4"},
    ]


class TestCrystallizeFromTrace:
    def test_valid_trace_emits_proposal(self, engine):
        proposal = engine.crystallize_from_trace(
            _good_trace(), "Research and summarize a topic"
        )
        assert proposal is not None
        assert proposal.reason == "crystallized_from_trace"
        assert "crystallized" in proposal.name
        # Tool sequence is recorded in failure_pattern for traceability.
        assert proposal.failure_pattern["tool_calls"] == 4
        assert proposal.failure_pattern["tool_sequence"] == [
            "search", "fetch", "summarize", "write",
        ]

    def test_returns_none_when_trace_too_short(self, engine):
        short = _good_trace()[:2]
        assert engine.crystallize_from_trace(short, "short task") is None

    def test_returns_none_when_too_many_bad_steps(self, engine):
        # 4-step trace with 3 retry/error markers = 75% bad → reject.
        trace = [
            {"tool": "search", "status": "ok"},
            {"tool": "search", "status": "retry", "retry_count": 1},
            {"tool": "search", "error": "boom"},
            {"tool": "search", "status": "failed"},
        ]
        assert engine.crystallize_from_trace(trace, "flaky task") is None

    def test_returns_none_when_no_tool_call(self, engine):
        # Pure-LLM trace — no `tool` keys present.
        trace = [
            {"thought": "step 1"},
            {"thought": "step 2"},
            {"thought": "step 3"},
        ]
        assert engine.crystallize_from_trace(trace, "pure thought") is None

    def test_skill_name_derived_from_summary(self, engine):
        proposal = engine.crystallize_from_trace(
            _good_trace(), "Summarize Cal.com bookings"
        )
        assert proposal is not None
        assert proposal.name.startswith("summarize-cal-com-bookings")
        assert proposal.name.endswith("-crystallized")

    def test_dedupe_against_existing_proposal(self, engine):
        # First call creates and persists the proposal.
        proposal = engine.crystallize_from_trace(
            _good_trace(), "Research and summarize a topic"
        )
        assert proposal is not None
        engine.create_proposal(proposal)
        # Second call with the same summary must dedupe to None.
        again = engine.crystallize_from_trace(
            _good_trace(), "Research and summarize a topic"
        )
        assert again is None

    def test_feature_flag_off_returns_none(self, engine):
        """When the caller passes ``enabled=False`` (mirrors
        config.skill_crystallization_enabled = False), the method
        short-circuits without inspecting the trace. Mirrors the
        03.08 caller-gates pattern."""
        proposal = engine.crystallize_from_trace(
            _good_trace(), "Research and summarize a topic", enabled=False
        )
        assert proposal is None

    def test_lineage_hook_called_when_both_flags_on(self, engine):
        """When skill_version_dag_enabled is True AND a store is passed,
        ``record_skill_version`` is called exactly once on the new
        proposal (Sprint 03.07 lineage hook)."""

        class _StubStore:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def record_skill_version(self, **kwargs):
                self.calls.append(kwargs)
                return None

        store = _StubStore()
        proposal = engine.crystallize_from_trace(
            _good_trace(),
            "Research and summarize a topic",
            skill_version_store=store,
            skill_version_dag_enabled=True,
        )
        assert proposal is not None
        assert len(store.calls) == 1
        assert store.calls[0]["skill_name"] == proposal.name
        assert store.calls[0]["created_by_trigger"] == "crystallized_from_trace"

    def test_lineage_hook_skipped_when_dag_flag_off(self, engine):
        """If skill_version_dag_enabled is False, the lineage hook is
        skipped even when a store is provided."""

        class _StubStore:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def record_skill_version(self, **kwargs):
                self.calls.append(kwargs)

        store = _StubStore()
        proposal = engine.crystallize_from_trace(
            _good_trace(),
            "Research and summarize a topic",
            skill_version_store=store,
            skill_version_dag_enabled=False,
        )
        assert proposal is not None
        assert store.calls == []

    def test_returns_none_for_empty_summary(self, engine):
        assert engine.crystallize_from_trace(_good_trace(), "   ") is None

    def test_returns_none_for_non_list_trace(self, engine):
        assert engine.crystallize_from_trace("not-a-list", "summary") is None  # type: ignore[arg-type]


# ── Sprint 07.04 (#1033) — Markdown-skill convention ──


def _good_proposal(name: str = "search-with-retry", domain: str = "search") -> SkillProposal:
    """A passing-validation SkillProposal for markdown round-trip tests."""
    return SkillProposal(
        name=name,
        description="Search with retry and fallback sources",
        trigger_condition="Search task with previous timeout failures",
        approach=[
            "Check brave-search health",
            "If degraded, fall back to exa",
            "Return aggregated results",
        ],
        failure_pattern={"domain": domain, "count": 3, "error_type": "timeout"},
    )


class TestPersistSkillToMarkdown:
    def test_writes_file_to_expected_path(self, engine, tmp_path):
        proposal = _good_proposal()
        path = engine.persist_skill_to_markdown(proposal, base_dir=tmp_path)
        # Layout: <base>/<domain>/<name>.md
        assert path == tmp_path / "search" / "search-with-retry.md"
        assert path.is_file()

    def test_file_contents_match_generate_skill_md(self, engine, tmp_path):
        proposal = _good_proposal()
        path = engine.persist_skill_to_markdown(proposal, base_dir=tmp_path)
        body = path.read_text(encoding="utf-8")
        assert body == engine.generate_skill_md(proposal)
        assert body.startswith("# search-with-retry\n")
        assert "## Approach" in body

    def test_atomic_write_no_partial_file_on_interruption(
        self, engine, tmp_path, monkeypatch
    ):
        """Simulate a mid-write crash and confirm we never leave a
        partially-written .md (only the .tmp sibling, which the next
        attempt overwrites)."""
        proposal = _good_proposal()
        target_dir = tmp_path / "search"

        original_write_text = Path.write_text

        def _explode(self, *args, **kwargs):
            # Write the bytes (the tmp file gets created), then crash
            # before the rename step would have run.
            original_write_text(self, *args, **kwargs)
            raise RuntimeError("simulated crash mid-write")

        monkeypatch.setattr(Path, "write_text", _explode)
        with pytest.raises(RuntimeError, match="simulated crash"):
            engine.persist_skill_to_markdown(proposal, base_dir=tmp_path)

        # The final target must NOT exist, only the .tmp leftover.
        assert not (target_dir / "search-with-retry.md").exists()
        # Cleanup leftover tmp before the next run would have overwritten it.
        monkeypatch.undo()
        path = engine.persist_skill_to_markdown(proposal, base_dir=tmp_path)
        assert path.is_file()

    def test_returns_path_object(self, engine, tmp_path):
        proposal = _good_proposal()
        path = engine.persist_skill_to_markdown(proposal, base_dir=tmp_path)
        assert isinstance(path, Path)

    def test_default_base_dir_constant(self):
        assert DEFAULT_MARKDOWN_SKILLS_DIR == Path("agent/config/domain-skills")

    def test_dual_write_populates_markdown_path_column(self, engine, tmp_path):
        proposal = _good_proposal()
        engine.create_proposal(proposal)
        path = engine.persist_skill_to_markdown(proposal, base_dir=tmp_path)

        conn = sqlite3.connect(engine._db_path)
        try:
            row = conn.execute(
                "SELECT markdown_path FROM skill_proposals WHERE name = ?",
                (proposal.name,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == str(path)

    def test_missing_proposal_name_raises(self, engine, tmp_path):
        empty = SkillProposal(
            name="", description="d", trigger_condition="t", approach=["a"],
        )
        with pytest.raises(ValueError):
            engine.persist_skill_to_markdown(empty, base_dir=tmp_path)

    def test_non_proposal_raises(self, engine, tmp_path):
        with pytest.raises(TypeError):
            engine.persist_skill_to_markdown(  # type: ignore[arg-type]
                "not a proposal", base_dir=tmp_path
            )

    def test_default_domain_when_unspecified(self, engine, tmp_path):
        proposal = SkillProposal(
            name="bare-skill",
            description="A skill without a domain hint",
            trigger_condition="Anywhere",
            approach=["Step 1"],
        )
        path = engine.persist_skill_to_markdown(proposal, base_dir=tmp_path)
        assert path.parent.name == "general"


class TestDiscoverMarkdownSkills:
    def test_finds_files_in_nested_domain_dirs(self, engine, tmp_path):
        engine.persist_skill_to_markdown(
            _good_proposal("search-skill", "search"), base_dir=tmp_path
        )
        engine.persist_skill_to_markdown(
            _good_proposal("deploy-skill", "deploy"), base_dir=tmp_path
        )
        skills = engine.discover_markdown_skills(base_dir=tmp_path)
        names = {s.name for s in skills}
        assert names == {"search-skill", "deploy-skill"}
        domains = {s.domain for s in skills}
        assert domains == {"search", "deploy"}
        assert all(isinstance(s, MarkdownSkill) for s in skills)

    def test_returns_empty_list_when_dir_missing(self, engine, tmp_path):
        ghost = tmp_path / "no-such-tree"
        assert engine.discover_markdown_skills(base_dir=ghost) == []

    def test_skips_invalid_skills_with_warning(
        self, engine, tmp_path, caplog
    ):
        # Write one valid + one invalid skill.
        engine.persist_skill_to_markdown(
            _good_proposal("good-skill", "search"), base_dir=tmp_path
        )
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        # No headings → fails validate_skill structure check.
        (bad_dir / "broken.md").write_text(
            "no headings here at all just plain text", encoding="utf-8"
        )

        with caplog.at_level("WARNING", logger="bridge.skill_evolution"):
            skills = engine.discover_markdown_skills(base_dir=tmp_path)

        names = {s.name for s in skills}
        assert names == {"good-skill"}
        assert any("invalid" in rec.message for rec in caplog.records)

    def test_frontmatter_parsed_when_present(self, engine, tmp_path):
        pytest.importorskip("yaml")
        skill_dir = tmp_path / "search"
        skill_dir.mkdir()
        (skill_dir / "with-front.md").write_text(
            "---\n"
            "domain: search\n"
            "confidence: 0.85\n"
            "---\n"
            "# with-front\n\n"
            "## Description\n"
            "A skill with frontmatter.\n\n"
            "## Approach\n"
            "1. Do the thing.\n",
            encoding="utf-8",
        )
        skills = engine.discover_markdown_skills(base_dir=tmp_path)
        assert len(skills) == 1
        assert skills[0].frontmatter == {"domain": "search", "confidence": 0.85}

    def test_frontmatter_absent_yields_empty_dict(self, engine, tmp_path):
        engine.persist_skill_to_markdown(
            _good_proposal("plain-skill", "search"), base_dir=tmp_path
        )
        skills = engine.discover_markdown_skills(base_dir=tmp_path)
        assert len(skills) == 1
        assert skills[0].frontmatter == {}


class TestMarkdownPathSchemaMigration:
    def test_column_added_idempotently(self, tmp_path):
        db = tmp_path / "migrate.db"
        # First construction creates the column.
        SkillEvolutionEngine(db)
        # Second construction is a no-op (idempotent).
        SkillEvolutionEngine(db)

        conn = sqlite3.connect(db)
        try:
            cols = {row[1] for row in conn.execute(
                "PRAGMA table_info(skill_proposals)"
            ).fetchall()}
        finally:
            conn.close()
        assert "markdown_path" in cols

    def test_pre_existing_db_gets_column_on_upgrade(self, tmp_path):
        """A DB created before 07.04 only has the legacy schema; the
        migration must add ``markdown_path`` without dropping data."""
        db = tmp_path / "legacy.db"
        # Simulate the pre-07.04 schema (no markdown_path column).
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "CREATE TABLE skill_proposals ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT NOT NULL UNIQUE, "
                "description TEXT NOT NULL, "
                "trigger_condition TEXT NOT NULL, "
                "approach TEXT NOT NULL, "
                "failure_pattern TEXT DEFAULT '{}', "
                "score REAL DEFAULT 0.0, "
                "status TEXT NOT NULL DEFAULT 'proposed', "
                "tier TEXT NOT NULL DEFAULT 'A', "
                "reject_reason TEXT, "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
                "updated_at TEXT NOT NULL DEFAULT (datetime('now'))"
                ")"
            )
            conn.execute(
                "INSERT INTO skill_proposals (name, description, "
                "trigger_condition, approach) VALUES (?, ?, ?, ?)",
                ("legacy-row", "d", "t", "[]"),
            )
            conn.commit()
        finally:
            conn.close()

        # Opening the engine must add the column.
        engine = SkillEvolutionEngine(db)
        # Existing row survives the migration.
        got = engine.get_proposal_by_name("legacy-row")
        assert got is not None
        # New column is present and NULL by default.
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT markdown_path FROM skill_proposals WHERE name = ?",
                ("legacy-row",),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] is None


class TestSkillNameSanitization:
    def test_lowercases(self):
        assert SkillEvolutionEngine._sanitize_skill_name("FooBar") == "foobar"

    def test_collapses_whitespace_to_dash(self):
        assert (
            SkillEvolutionEngine._sanitize_skill_name("foo bar  baz")
            == "foo-bar-baz"
        )

    def test_collapses_slashes_to_dash(self):
        assert (
            SkillEvolutionEngine._sanitize_skill_name("foo/bar\\baz")
            == "foo-bar-baz"
        )

    def test_strips_unicode_and_punctuation(self):
        # Em-dash and Unicode emoji collapse to a single dash run; the
        # outer dashes are then stripped.
        assert SkillEvolutionEngine._sanitize_skill_name("foo — bar") == "foo-bar"
        assert SkillEvolutionEngine._sanitize_skill_name("nice 🎉 day") == "nice-day"

    def test_preserves_dash_and_underscore(self):
        assert (
            SkillEvolutionEngine._sanitize_skill_name("foo-bar_baz")
            == "foo-bar_baz"
        )

    def test_strips_leading_trailing_dash(self):
        assert SkillEvolutionEngine._sanitize_skill_name("///foo///") == "foo"

    def test_empty_input_returns_empty(self):
        assert SkillEvolutionEngine._sanitize_skill_name("") == ""
        assert SkillEvolutionEngine._sanitize_skill_name("    ") == ""
        assert SkillEvolutionEngine._sanitize_skill_name(None) == ""  # type: ignore[arg-type]


class TestFeatureFlagOff:
    def test_default_flag_is_false(self):
        from bridge.config import BridgeConfig

        assert BridgeConfig().markdown_skills_enabled is False

    def test_existing_proposals_api_unchanged(self, engine):
        """Feature-flag-OFF path: legacy SQLite create/get/list flow is
        unaffected by the new markdown convention. The new methods are
        opt-in and never touched unless the caller invokes them."""
        proposal = _good_proposal("legacy-flow", "search")
        rid = engine.create_proposal(proposal)
        assert rid > 0
        got = engine.get_proposal_by_name("legacy-flow")
        assert got is not None
        assert got.name == "legacy-flow"
        # markdown_path stays NULL until persist_skill_to_markdown runs.
        conn = sqlite3.connect(engine._db_path)
        try:
            row = conn.execute(
                "SELECT markdown_path FROM skill_proposals WHERE name = ?",
                ("legacy-flow",),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] is None
