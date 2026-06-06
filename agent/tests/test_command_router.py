"""Tests for the Bumba command router."""

from bridge.command_router import CommandRouter, Intent


class TestIntentEnum:
    """Test the Intent enum."""

    def test_all_intents_defined(self):
        """All required intents are defined."""
        intents = [i.value for i in Intent]
        expected = ["build", "analyze", "fix", "optimize", "test", "deploy", "document", "unknown"]
        for intent in expected:
            assert intent in intents


class TestCommandRouterInitialization:
    """Test router initialization."""

    def test_router_creation(self):
        """Can create a router instance."""
        router = CommandRouter()
        assert router is not None
        assert router.compiled_patterns is not None

    def test_patterns_compiled(self):
        """Patterns are pre-compiled for performance."""
        router = CommandRouter()
        assert len(router.compiled_patterns) > 0
        assert Intent.BUILD in router.compiled_patterns


class TestIntentDetection:
    """Test intent detection."""

    def test_build_intent(self):
        """Detects BUILD intent."""
        router = CommandRouter()
        match = router.route("build the project")
        assert match.intent == Intent.BUILD
        assert match.confidence > 0.5

    def test_analyze_intent(self):
        """Detects ANALYZE intent."""
        router = CommandRouter()
        match = router.route("analyze the performance")
        assert match.intent == Intent.ANALYZE
        assert match.confidence > 0.5

    def test_fix_intent(self):
        """Detects FIX intent."""
        router = CommandRouter()
        match = router.route("fix the bug")
        assert match.intent == Intent.FIX
        assert match.confidence > 0.5

    def test_optimize_intent(self):
        """Detects OPTIMIZE intent."""
        router = CommandRouter()
        match = router.route("optimize the code")
        assert match.intent == Intent.OPTIMIZE
        assert match.confidence > 0.5

    def test_test_intent(self):
        """Detects TEST intent."""
        router = CommandRouter()
        match = router.route("test the implementation")
        assert match.intent == Intent.TEST
        assert match.confidence > 0.5

    def test_deploy_intent(self):
        """Detects DEPLOY intent."""
        router = CommandRouter()
        match = router.route("deploy to production")
        assert match.intent == Intent.DEPLOY
        assert match.confidence > 0.5

    def test_document_intent(self):
        """Detects DOCUMENT intent."""
        router = CommandRouter()
        match = router.route("write docs")
        assert match.intent == Intent.DOCUMENT
        assert match.confidence > 0.5


class TestPatternMatching:
    """Test pattern matching."""

    def test_multiple_patterns_increase_confidence(self):
        """Multiple matching patterns increase confidence."""
        router = CommandRouter()
        match1 = router.route("build")
        match2 = router.route("build and compile the project")
        assert match2.confidence >= match1.confidence

    def test_matched_patterns_recorded(self):
        """Matched patterns are recorded."""
        router = CommandRouter()
        match = router.route("build and construct the system")
        assert len(match.matchedPatterns) > 0
        assert any("build" in p for p in match.matchedPatterns)

    def test_case_insensitive_matching(self):
        """Pattern matching is case insensitive."""
        router = CommandRouter()
        match1 = router.route("build the system")
        match2 = router.route("BUILD THE SYSTEM")
        match3 = router.route("Build the System")
        assert match1.intent == match2.intent == match3.intent


class TestComplexityScoring:
    """Test complexity scoring."""

    def test_trivial_complexity(self):
        """Trivial commands score 1."""
        router = CommandRouter()
        match = router.route("list files")
        assert match.complexity == 1

    def test_simple_complexity(self):
        """Simple commands score 2."""
        router = CommandRouter()
        match = router.route("add new function")
        assert match.complexity >= 2

    def test_moderate_complexity(self):
        """Moderate commands score 3."""
        router = CommandRouter()
        match = router.route("refactor the module")
        assert match.complexity >= 3

    def test_complex_complexity(self):
        """Complex commands score 4."""
        router = CommandRouter()
        match = router.route("build the architecture")
        assert match.complexity >= 4

    def test_extreme_complexity(self):
        """Extreme commands score 5."""
        router = CommandRouter()
        match = router.route("implement distributed machine learning")
        assert match.complexity == 5

    def test_complexity_bounds(self):
        """Complexity is always between 1 and 5."""
        router = CommandRouter()
        commands = [
            "do something",
            "build the project",
            "optimize the code",
            "implement sharding",
            "list all files",
        ]
        for cmd in commands:
            match = router.route(cmd)
            assert 1 <= match.complexity <= 5


class TestConfidenceScoring:
    """Test confidence scoring."""

    def test_confidence_bounds(self):
        """Confidence is always between 0.0 and 1.0."""
        router = CommandRouter()
        commands = [
            "build",
            "fix the bug",
            "unknown random words",
            "",
            "deploy to production",
        ]
        for cmd in commands:
            match = router.route(cmd)
            assert 0.0 <= match.confidence <= 1.0

    def test_unknown_intent_low_confidence(self):
        """Unknown intents have low confidence."""
        router = CommandRouter()
        match = router.route("xyzabc unknown command")
        assert match.intent == Intent.UNKNOWN
        assert match.confidence < 0.5

    def test_clear_intent_high_confidence(self):
        """Clear intents have high confidence."""
        router = CommandRouter()
        match = router.route("build and compile and create the project")
        assert match.confidence > 0.7

    def test_empty_command_zero_confidence(self):
        """Empty commands have zero confidence."""
        router = CommandRouter()
        match = router.route("")
        assert match.confidence == 0.0
        assert match.intent == Intent.UNKNOWN


class TestConfidenceLevelLabels:
    """Test confidence level categorization."""

    def test_high_confidence_label(self):
        """Scores >= 0.8 are 'high'."""
        router = CommandRouter()
        assert router.get_confidence_level(0.9) == "high"
        assert router.get_confidence_level(0.8) == "high"

    def test_medium_confidence_label(self):
        """Scores 0.5-0.79 are 'medium'."""
        router = CommandRouter()
        assert router.get_confidence_level(0.7) == "medium"
        assert router.get_confidence_level(0.5) == "medium"

    def test_low_confidence_label(self):
        """Scores < 0.5 are 'low'."""
        router = CommandRouter()
        assert router.get_confidence_level(0.4) == "low"
        assert router.get_confidence_level(0.0) == "low"


class TestComplexityLabels:
    """Test complexity label generation."""

    def test_complexity_labels(self):
        """Complexity scores map to labels."""
        router = CommandRouter()
        assert router.get_complexity_label(1) == "trivial"
        assert router.get_complexity_label(2) == "simple"
        assert router.get_complexity_label(3) == "moderate"
        assert router.get_complexity_label(4) == "complex"
        assert router.get_complexity_label(5) == "extreme"

    def test_invalid_complexity_label(self):
        """Invalid complexity scores return 'unknown'."""
        router = CommandRouter()
        assert router.get_complexity_label(99) == "unknown"


class TestBatchRouting:
    """Test batch operations."""

    def test_batch_route(self):
        """Can route multiple commands at once."""
        router = CommandRouter()
        commands = [
            "build the project",
            "fix the bug",
            "test the code",
            "deploy to production",
        ]
        results = router.batch_route(commands)
        assert len(results) == 4
        assert results[0].intent == Intent.BUILD
        assert results[1].intent == Intent.FIX
        assert results[2].intent == Intent.TEST
        assert results[3].intent == Intent.DEPLOY

    def test_batch_route_with_unknown(self):
        """Batch routing handles unknown intents."""
        router = CommandRouter()
        commands = ["build", "xyzabc", "fix bug"]
        results = router.batch_route(commands)
        assert results[0].intent == Intent.BUILD
        assert results[1].intent == Intent.UNKNOWN
        assert results[2].intent == Intent.FIX


class TestFiltering:
    """Test filtering operations."""

    def test_filter_by_intent(self):
        """Can filter commands by intent."""
        router = CommandRouter()
        commands = [
            "build the project",
            "fix the bug",
            "build another thing",
            "test the code",
        ]
        build_commands = router.filter_by_intent(commands, Intent.BUILD)
        assert len(build_commands) >= 2
        assert all(match.intent == Intent.BUILD for _, match in build_commands)

    def test_filter_by_intent_with_confidence(self):
        """Can filter by intent with minimum confidence."""
        router = CommandRouter()
        commands = [
            "build",
            "might build",
            "build the project",
        ]
        high_confidence = router.filter_by_intent(commands, Intent.BUILD, min_confidence=0.7)
        assert len(high_confidence) > 0

    def test_filter_by_complexity(self):
        """Can filter commands by complexity range."""
        router = CommandRouter()
        commands = [
            "list files",
            "build project",
            "implement machine learning",
            "add function",
        ]
        complex_commands = router.filter_by_complexity(commands, min_complexity=3, max_complexity=5)
        assert len(complex_commands) >= 1
        assert all(3 <= match.complexity <= 5 for _, match in complex_commands)

    def test_filter_by_complexity_range(self):
        """Complexity filtering respects range bounds."""
        router = CommandRouter()
        commands = ["list", "build", "implement sharding"]
        simple = router.filter_by_complexity(commands, min_complexity=1, max_complexity=2)
        complex_cmds = router.filter_by_complexity(commands, min_complexity=3, max_complexity=5)
        assert len(simple) >= 1
        assert len(complex_cmds) >= 1


class TestExplanation:
    """Test routing explanation."""

    def test_explain_routing(self):
        """Can explain routing decision."""
        router = CommandRouter()
        explanation = router.explain_routing("build the project")
        assert explanation["intent"] == "build"
        assert "confidence" in explanation
        assert "complexity" in explanation
        assert "matchedPatterns" in explanation

    def test_explanation_contains_scores(self):
        """Explanation includes both scores and labels."""
        router = CommandRouter()
        explanation = router.explain_routing("build and compile")
        assert "score" in explanation["confidence"]
        assert "level" in explanation["confidence"]
        assert "score" in explanation["complexity"]
        assert "label" in explanation["complexity"]

    def test_explanation_for_unknown(self):
        """Explanation works for unknown intents."""
        router = CommandRouter()
        explanation = router.explain_routing("xyzabc unknown")
        assert explanation["intent"] == "unknown"
        assert explanation["confidence"]["score"] < 0.5


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_command(self):
        """Empty commands return unknown intent."""
        router = CommandRouter()
        match = router.route("")
        assert match.intent == Intent.UNKNOWN
        assert match.confidence == 0.0

    def test_whitespace_only_command(self):
        """Whitespace-only commands return unknown intent."""
        router = CommandRouter()
        match = router.route("   \t\n   ")
        assert match.intent == Intent.UNKNOWN

    def test_very_long_command(self):
        """Long commands are handled correctly."""
        router = CommandRouter()
        long_cmd = "build " * 100 + "the project"
        match = router.route(long_cmd)
        assert match.intent == Intent.BUILD
        assert match.confidence > 0.5

    def test_special_characters_in_command(self):
        """Special characters don't break routing."""
        router = CommandRouter()
        cmd = "build @#$%^&*() the project!!!"
        match = router.route(cmd)
        assert match.intent == Intent.BUILD

    def test_numbers_in_command(self):
        """Numbers in commands are handled."""
        router = CommandRouter()
        match = router.route("build 3 projects and test 2 modules")
        assert match.intent == Intent.BUILD


# ---------------------------------------------------------------------------
# Sprint 04.02 — broaden classifier to QA / Ops / Strategy / Design Zone 4
# departments. Patterns are intentionally narrow (slash-prefix or explicit
# verb-noun phrases). Tests pair each positive case with a false-positive
# sanity check that bare keywords do NOT route to the department intent —
# protecting Discord chat from getting accidentally routed to Opus via the
# DEPARTMENT environment.
# ---------------------------------------------------------------------------


class TestDepartmentIntents:
    """Sprint 04.02 — narrow department intent classification."""

    def test_qa_review_intent_classified(self) -> None:
        """``review code please`` and ``/qa ...`` route to QA_REVIEW."""
        router = CommandRouter()
        # Verb-noun phrase
        m1 = router.route("review code please")
        assert m1.intent == Intent.QA_REVIEW, (
            f"'review code please' must classify QA_REVIEW, got {m1.intent.value!r}"
        )
        # Slash-prefix
        m2 = router.route("/qa scan the bridge for vulns")
        assert m2.intent == Intent.QA_REVIEW
        # Other QA phrase
        m3 = router.route("security check the auth path")
        assert m3.intent == Intent.QA_REVIEW

    def test_qa_false_positives_rejected(self) -> None:
        """Bare ``qa`` and bare ``review`` must NOT classify QA_REVIEW.

        ``qa is a tester role`` is mundane chatter; ``review the system``
        is a legitimate ANALYZE intent and must not be hijacked.
        """
        router = CommandRouter()
        m1 = router.route("qa is a tester role")
        assert m1.intent != Intent.QA_REVIEW, (
            f"bare 'qa' must not match QA_REVIEW; got {m1.intent.value!r}"
        )
        m2 = router.route("review the system")
        # Bare review still belongs to ANALYZE (regression check).
        assert m2.intent == Intent.ANALYZE
        assert m2.intent != Intent.QA_REVIEW

    def test_ops_diagnose_intent_classified(self) -> None:
        """``/ops debug ...``, ``diagnose ...``, ``incident`` route to OPS_DIAGNOSE."""
        router = CommandRouter()
        m1 = router.route("/ops debug the bridge")
        assert m1.intent == Intent.OPS_DIAGNOSE
        m2 = router.route("diagnose the failing service")
        assert m2.intent == Intent.OPS_DIAGNOSE
        m3 = router.route("investigate the incident")
        assert m3.intent == Intent.OPS_DIAGNOSE

    def test_ops_false_positives_rejected(self) -> None:
        """Bare ``ops`` (no slash, no verb) must NOT classify OPS_DIAGNOSE."""
        router = CommandRouter()
        m1 = router.route("ops are a great team")
        assert m1.intent != Intent.OPS_DIAGNOSE, (
            f"bare 'ops' must not match OPS_DIAGNOSE; got {m1.intent.value!r}"
        )

    def test_strategy_analyze_intent_classified(self) -> None:
        """Competitor / positioning / market-analysis phrases route to STRATEGY."""
        router = CommandRouter()
        m1 = router.route("competitor analysis for X")
        assert m1.intent == Intent.STRATEGY_ANALYZE
        m2 = router.route("/strategy review positioning")
        assert m2.intent == Intent.STRATEGY_ANALYZE
        m3 = router.route("positioning for the launch")
        assert m3.intent == Intent.STRATEGY_ANALYZE

    def test_strategy_false_positives_rejected(self) -> None:
        """Bare ``strategy`` (no slash, no signal verb) must NOT classify."""
        router = CommandRouter()
        m1 = router.route("strategy meeting at 3pm")
        assert m1.intent != Intent.STRATEGY_ANALYZE, (
            f"bare 'strategy' must not match STRATEGY_ANALYZE; got {m1.intent.value!r}"
        )

    def test_design_review_intent_classified(self) -> None:
        """``design review``, ``ux review``, ``/design ...`` route to DESIGN_REVIEW."""
        router = CommandRouter()
        m1 = router.route("design review on this")
        assert m1.intent == Intent.DESIGN_REVIEW
        m2 = router.route("/design overhaul the modal")
        assert m2.intent == Intent.DESIGN_REVIEW
        m3 = router.route("ux review of the flow")
        assert m3.intent == Intent.DESIGN_REVIEW

    def test_design_false_positives_rejected(self) -> None:
        """Bare ``design`` (no two-word review phrase, no slash) must NOT classify."""
        router = CommandRouter()
        m1 = router.route("the design is good")
        assert m1.intent != Intent.DESIGN_REVIEW
        m2 = router.route("design pattern for caching")
        assert m2.intent != Intent.DESIGN_REVIEW

    def test_board_query_false_positive_unchanged(self) -> None:
        """Sprint 04.01 regression check — ``board game`` chatter must not
        route to BOARD_QUERY even after Sprint 04.02 adds 4 sibling intents.
        """
        router = CommandRouter()
        m = router.route("test message about a board game")
        assert m.intent != Intent.BOARD_QUERY

    def test_all_department_intents_present(self) -> None:
        """All 5 Zone 4 department intents must be defined on the Intent enum."""
        intent_values = {i.value for i in Intent}
        for v in (
            "board_query",
            "qa_review",
            "ops_diagnose",
            "strategy_analyze",
            "design_review",
        ):
            assert v in intent_values, f"Intent.{v.upper()} missing from enum"
