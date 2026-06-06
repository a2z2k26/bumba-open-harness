"""Tests for MS5.3: Capability Self-Discovery."""

from __future__ import annotations


from bridge.discovery import (
    FeatureProposal,
    FeasibilityScore,
    ProposalStore,
    ScanCache,
    extract_feature_ideas,
    is_duplicate,
    keyword_overlap,
    scan_implemented_features,
)


# ── Feature Extraction ──


class TestFeatureExtraction:
    def test_extract_should_implement(self):
        text = "The system should implement automatic retry logic for failed API calls."
        ideas = extract_feature_ideas(text, source_doc="test.md")
        assert len(ideas) >= 1
        assert any("retry" in i.name for i in ideas)

    def test_extract_feature_label(self):
        text = "Feature: dark mode support for the dashboard"
        ideas = extract_feature_ideas(text)
        assert len(ideas) >= 1
        assert any("dark" in i.name for i in ideas)

    def test_extract_todo(self):
        text = "TODO: add rate limiting to the API gateway"
        ideas = extract_feature_ideas(text)
        assert len(ideas) >= 1

    def test_extract_multiple(self):
        text = (
            "Feature: caching layer\n"
            "TODO: add monitoring dashboard\n"
            "The system could implement webhook support."
        )
        ideas = extract_feature_ideas(text)
        assert len(ideas) >= 2

    def test_no_features_in_plain_text(self):
        text = "This is a regular paragraph about the weather today."
        ideas = extract_feature_ideas(text)
        assert len(ideas) == 0

    def test_source_doc_preserved(self):
        text = "Feature: test feature"
        ideas = extract_feature_ideas(text, source_doc="research.md")
        assert ideas[0].source_doc == "research.md"

    def test_source_quote_captured(self):
        text = "Feature: real-time notifications"
        ideas = extract_feature_ideas(text)
        assert ideas[0].source_quote != ""

    def test_deduplicates_within_doc(self):
        text = "Feature: caching\nFeature: caching support"
        ideas = extract_feature_ideas(text)
        # Should not produce exact duplicates
        names = [i.name for i in ideas]
        assert len(names) == len(set(names))


# ── Keyword Overlap ──


class TestKeywordOverlap:
    def test_identical(self):
        assert keyword_overlap("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert keyword_overlap("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        sim = keyword_overlap("add caching layer", "implement caching system")
        assert 0.0 < sim < 1.0

    def test_empty_string(self):
        assert keyword_overlap("", "hello") == 0.0


# ── Deduplication ──


class TestDeduplication:
    def test_exact_duplicate(self):
        existing = [FeatureProposal(name="auto-retry", description="automatic retry logic")]
        dup = is_duplicate("auto-retry", "automatic retry logic", existing)
        assert dup is not None

    def test_near_duplicate(self):
        existing = [FeatureProposal(name="auto-retry", description="automatic retry for failed API calls")]
        dup = is_duplicate("auto-retry", "automatic retry for failed API calls with backoff", existing)
        assert dup is not None

    def test_not_duplicate(self):
        existing = [FeatureProposal(name="auto-retry", description="automatic retry logic")]
        dup = is_duplicate("dark-mode", "dark mode support for dashboard", existing)
        assert dup is None

    def test_empty_existing(self):
        dup = is_duplicate("anything", "any description", [])
        assert dup is None


# ── Feasibility Score ──


class TestFeasibilityScore:
    def test_priority_computation(self):
        fs = FeasibilityScore(complexity=2, value=5, risk=1)
        # priority = value*2 - complexity - risk = 10 - 2 - 1 = 7
        assert fs.priority_score == 7.0

    def test_low_priority(self):
        fs = FeasibilityScore(complexity=5, value=1, risk=5)
        # priority = 2 - 5 - 5 = -8
        assert fs.priority_score == -8.0

    def test_neutral_priority(self):
        fs = FeasibilityScore(complexity=3, value=3, risk=3)
        # priority = 6 - 3 - 3 = 0
        assert fs.priority_score == 0.0


# ── Implemented Features Scan ──


class TestScanImplemented:
    def test_scan_bridge_modules(self, tmp_path):
        bridge = tmp_path / "bridge"
        bridge.mkdir()
        (bridge / "metrics.py").write_text("# metrics")
        (bridge / "security.py").write_text("# security")
        (bridge / "__init__.py").write_text("")
        implemented = scan_implemented_features(tmp_path)
        assert "metrics" in implemented
        assert "security" in implemented
        assert "__init__" not in implemented

    def test_scan_skills(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "code-review").mkdir()
        (skills / "validate").mkdir()
        implemented = scan_implemented_features(tmp_path)
        assert "code-review" in implemented
        assert "validate" in implemented

    def test_scan_services(self, tmp_path):
        services = tmp_path / "bridge" / "services"
        services.mkdir(parents=True)
        (services / "briefing.py").write_text("")
        (services / "runner.py").write_text("")
        implemented = scan_implemented_features(tmp_path)
        assert "briefing" in implemented
        assert "runner" not in implemented  # runner is excluded


# ── Proposal Store ──


class TestProposalStore:
    def test_save_and_load(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        prop = FeatureProposal(
            name="auto-retry",
            description="Automatic retry for failed API calls",
            feasibility=FeasibilityScore(complexity=2, value=4, risk=1),
        )
        store.save(prop)
        loaded = store.load("auto-retry")
        assert loaded is not None
        assert loaded.name == "auto-retry"
        assert loaded.feasibility.complexity == 2

    def test_list_all(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        for name in ["alpha", "beta", "gamma"]:
            store.save(FeatureProposal(name=name))
        assert len(store.list_all()) == 3

    def test_list_pending(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        store.save(FeatureProposal(name="a", status="proposed"))
        store.save(FeatureProposal(name="b", status="approved"))
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].name == "a"

    def test_approve(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        store.save(FeatureProposal(name="x", status="proposed"))
        assert store.approve("x") is True
        loaded = store.load("x")
        assert loaded.status == "approved"

    def test_reject(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        store.save(FeatureProposal(name="y", status="proposed"))
        assert store.reject("y", reason="Too complex") is True
        loaded = store.load("y")
        assert loaded.status == "rejected"
        assert loaded.reject_reason == "Too complex"

    def test_defer(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        store.save(FeatureProposal(name="z", status="proposed"))
        assert store.defer("z") is True
        loaded = store.load("z")
        assert loaded.status == "deferred"

    def test_count(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        assert store.count() == 0
        store.save(FeatureProposal(name="a", status="proposed"))
        store.save(FeatureProposal(name="b", status="approved"))
        assert store.count() == 2
        assert store.count(status="proposed") == 1

    def test_nonexistent_load(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        assert store.load("nonexistent") is None

    def test_approve_nonexistent(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        assert store.approve("nonexistent") is False


# ── Proposal Formatting ──


class TestProposalFormatting:
    def test_format_table(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        store.save(FeatureProposal(
            name="retry",
            feasibility=FeasibilityScore(complexity=2, value=5, risk=1),
        ))
        table = store.format_proposals_table()
        assert "retry" in table
        assert "Priority" in table

    def test_format_empty(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        table = store.format_proposals_table()
        assert "No pending" in table

    def test_format_sorted_by_priority(self, tmp_path):
        store = ProposalStore(tmp_path / "proposals")
        store.save(FeatureProposal(
            name="low",
            feasibility=FeasibilityScore(complexity=5, value=1, risk=5),
        ))
        store.save(FeatureProposal(
            name="high",
            feasibility=FeasibilityScore(complexity=1, value=5, risk=1),
        ))
        table = store.format_proposals_table(store.list_all())
        # High priority should come first
        high_idx = table.index("high")
        low_idx = table.index("low")
        assert high_idx < low_idx


# ── Scan Cache ──


class TestScanCache:
    def test_new_file_is_changed(self, tmp_path):
        cache = ScanCache(tmp_path / "cache.json")
        doc = tmp_path / "doc.md"
        doc.write_text("content")
        assert cache.is_changed(doc) is True

    def test_scanned_file_not_changed(self, tmp_path):
        cache = ScanCache(tmp_path / "cache.json")
        doc = tmp_path / "doc.md"
        doc.write_text("content")
        cache.mark_scanned(doc)
        assert cache.is_changed(doc) is False

    def test_modified_file_is_changed(self, tmp_path):
        cache = ScanCache(tmp_path / "cache.json")
        doc = tmp_path / "doc.md"
        doc.write_text("content v1")
        cache.mark_scanned(doc)
        doc.write_text("content v2")
        assert cache.is_changed(doc) is True

    def test_cache_persists(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        doc = tmp_path / "doc.md"
        doc.write_text("content")

        cache1 = ScanCache(cache_path)
        cache1.mark_scanned(doc)

        cache2 = ScanCache(cache_path)
        assert cache2.is_changed(doc) is False

    def test_count(self, tmp_path):
        cache = ScanCache(tmp_path / "cache.json")
        assert cache.count() == 0
        doc = tmp_path / "doc.md"
        doc.write_text("x")
        cache.mark_scanned(doc)
        assert cache.count() == 1
