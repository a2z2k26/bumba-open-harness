"""Tests for modality intent detector."""

from bridge.modality_detector import ModalityDetector, Modality


class TestModalityEnum:
    """Test modality enum."""

    def test_all_modalities_defined(self):
        """All modalities are defined."""
        modalities = [m.value for m in Modality]
        expected = ["solo", "orchestrated", "sequential", "parallel", "review"]
        for m in expected:
            assert m in modalities


class TestModalityDetectorBasics:
    """Test basic modality detection."""

    def test_create_detector(self):
        """Can create a detector."""
        detector = ModalityDetector()
        assert detector is not None

    def test_solo_modality(self):
        """Detects SOLO modality."""
        detector = ModalityDetector()
        match = detector.detect("execute the task")
        assert match.modality == Modality.SOLO

    def test_orchestrated_modality(self):
        """Detects ORCHESTRATED modality."""
        detector = ModalityDetector()
        match = detector.detect("coordinate the team")
        assert match.modality == Modality.ORCHESTRATED

    def test_sequential_modality(self):
        """Detects SEQUENTIAL modality."""
        detector = ModalityDetector()
        match = detector.detect("step by step execution")
        assert match.modality == Modality.SEQUENTIAL

    def test_parallel_modality(self):
        """Detects PARALLEL modality."""
        detector = ModalityDetector()
        match = detector.detect("run in parallel")
        assert match.modality == Modality.PARALLEL

    def test_review_modality(self):
        """Detects REVIEW modality."""
        detector = ModalityDetector()
        match = detector.detect("review and approve")
        assert match.modality == Modality.REVIEW


class TestConfidenceScoring:
    """Test confidence scoring."""

    def test_confidence_bounds(self):
        """Confidence is between 0.0 and 1.0."""
        detector = ModalityDetector()
        commands = [
            "execute",
            "orchestrate",
            "step by step",
            "parallel",
            "review",
            "unknown xyz",
        ]
        for cmd in commands:
            match = detector.detect(cmd)
            assert 0.0 <= match.confidence <= 1.0

    def test_empty_command(self):
        """Empty command returns low confidence."""
        detector = ModalityDetector()
        match = detector.detect("")
        assert match.modality == Modality.SOLO
        assert match.confidence == 0.0

    def test_clear_intent_high_confidence(self):
        """Clear intent has high confidence."""
        detector = ModalityDetector()
        match = detector.detect("orchestrate coordinate team together")
        assert match.confidence > 0.7


class TestConfidenceLevels:
    """Test confidence level categorization."""

    def test_high_confidence_level(self):
        """Scores >= 0.8 are 'high'."""
        detector = ModalityDetector()
        assert detector.get_confidence_level(0.9) == "high"
        assert detector.get_confidence_level(0.8) == "high"

    def test_medium_confidence_level(self):
        """Scores 0.5-0.79 are 'medium'."""
        detector = ModalityDetector()
        assert detector.get_confidence_level(0.7) == "medium"
        assert detector.get_confidence_level(0.5) == "medium"

    def test_low_confidence_level(self):
        """Scores < 0.5 are 'low'."""
        detector = ModalityDetector()
        assert detector.get_confidence_level(0.4) == "low"
        assert detector.get_confidence_level(0.0) == "low"


class TestMultiAgentDetection:
    """Test multi-agent modality detection."""

    def test_solo_is_not_multi_agent(self):
        """SOLO is not multi-agent."""
        detector = ModalityDetector()
        assert detector.is_multi_agent(Modality.SOLO) is False

    def test_orchestrated_is_multi_agent(self):
        """ORCHESTRATED is multi-agent."""
        detector = ModalityDetector()
        assert detector.is_multi_agent(Modality.ORCHESTRATED) is True

    def test_sequential_is_multi_agent(self):
        """SEQUENTIAL is multi-agent."""
        detector = ModalityDetector()
        assert detector.is_multi_agent(Modality.SEQUENTIAL) is True

    def test_parallel_is_multi_agent(self):
        """PARALLEL is multi-agent."""
        detector = ModalityDetector()
        assert detector.is_multi_agent(Modality.PARALLEL) is True

    def test_review_is_not_multi_agent(self):
        """REVIEW is not necessarily multi-agent."""
        detector = ModalityDetector()
        assert detector.is_multi_agent(Modality.REVIEW) is False


class TestCoordinationRequirements:
    """Test coordination requirement detection."""

    def test_solo_requires_no_coordination(self):
        """SOLO requires no coordination."""
        detector = ModalityDetector()
        assert detector.requires_coordination(Modality.SOLO) is False

    def test_orchestrated_requires_coordination(self):
        """ORCHESTRATED requires coordination."""
        detector = ModalityDetector()
        assert detector.requires_coordination(Modality.ORCHESTRATED) is True

    def test_sequential_requires_coordination(self):
        """SEQUENTIAL requires coordination."""
        detector = ModalityDetector()
        assert detector.requires_coordination(Modality.SEQUENTIAL) is True

    def test_parallel_requires_coordination(self):
        """PARALLEL requires coordination."""
        detector = ModalityDetector()
        assert detector.requires_coordination(Modality.PARALLEL) is True

    def test_review_requires_no_coordination(self):
        """REVIEW doesn't require coordination (different kind)."""
        detector = ModalityDetector()
        assert detector.requires_coordination(Modality.REVIEW) is False


class TestReviewRequirements:
    """Test review requirement detection."""

    def test_review_requires_review(self):
        """REVIEW modality requires review."""
        detector = ModalityDetector()
        assert detector.requires_review(Modality.REVIEW) is True

    def test_other_modalities_not_review(self):
        """Other modalities don't require review."""
        detector = ModalityDetector()
        assert detector.requires_review(Modality.SOLO) is False
        assert detector.requires_review(Modality.ORCHESTRATED) is False
        assert detector.requires_review(Modality.SEQUENTIAL) is False
        assert detector.requires_review(Modality.PARALLEL) is False


class TestBatchDetection:
    """Test batch modality detection."""

    def test_detect_multi(self):
        """Can detect modality for multiple commands."""
        detector = ModalityDetector()
        commands = [
            "execute the task",
            "coordinate the team",
            "step by step",
            "run in parallel",
            "review and approve",
        ]
        results = detector.detect_multi(commands)
        assert len(results) == 5
        assert results[0].modality == Modality.SOLO
        assert results[1].modality == Modality.ORCHESTRATED
        assert results[2].modality == Modality.SEQUENTIAL
        assert results[3].modality == Modality.PARALLEL
        assert results[4].modality == Modality.REVIEW


class TestExplanation:
    """Test modality explanation."""

    def test_explain(self):
        """Can explain modality detection."""
        detector = ModalityDetector()
        explanation = detector.explain("coordinate the team")
        assert explanation["modality"] == "orchestrated"
        assert "confidence" in explanation
        assert "matched_keywords" in explanation
        assert explanation["is_multi_agent"] is True
        assert explanation["requires_coordination"] is True

    def test_explanation_for_solo(self):
        """Explanation for SOLO modality."""
        detector = ModalityDetector()
        explanation = detector.explain("execute this")
        assert explanation["modality"] == "solo"
        assert explanation["is_multi_agent"] is False
        assert explanation["requires_coordination"] is False

    def test_explanation_for_review(self):
        """Explanation for REVIEW modality."""
        detector = ModalityDetector()
        explanation = detector.explain("review and validate")
        assert explanation["modality"] == "review"
        assert explanation["requires_review"] is True


class TestKeywordMatching:
    """Test keyword matching."""

    def test_matched_keywords_recorded(self):
        """Matched keywords are recorded."""
        detector = ModalityDetector()
        match = detector.detect("orchestrate and coordinate")
        assert len(match.matched_keywords) > 0

    def test_case_insensitive_matching(self):
        """Keyword matching is case insensitive."""
        detector = ModalityDetector()
        match1 = detector.detect("execute the task")
        match2 = detector.detect("EXECUTE THE TASK")
        assert match1.modality == match2.modality


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_string(self):
        """Empty string returns SOLO with low confidence."""
        detector = ModalityDetector()
        match = detector.detect("")
        assert match.modality == Modality.SOLO
        assert match.confidence == 0.0

    def test_whitespace_only(self):
        """Whitespace-only string returns SOLO."""
        detector = ModalityDetector()
        match = detector.detect("   \t\n   ")
        assert match.modality == Modality.SOLO

    def test_unknown_keywords(self):
        """Unknown keywords default to SOLO."""
        detector = ModalityDetector()
        match = detector.detect("xyzabc unknown command")
        assert match.modality == Modality.SOLO

    def test_very_long_command(self):
        """Long commands are handled."""
        detector = ModalityDetector()
        long_cmd = "execute " * 100 + "the task"
        match = detector.detect(long_cmd)
        assert match.modality == Modality.SOLO

    def test_special_characters(self):
        """Special characters don't break detection."""
        detector = ModalityDetector()
        match = detector.detect("execute @#$%^&*() the task!!!")
        assert match.modality == Modality.SOLO
