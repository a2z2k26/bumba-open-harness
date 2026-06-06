"""Tests for listing relevance scoring."""
import json
from unittest.mock import patch

from job_search.agent import JobSearchAgent
from job_search.boards.base import JobListing


def _make_agent(tmp_path, roles=None, seniority=None):
    """Create a JobSearchAgent with test config files."""
    criteria = tmp_path / "criteria.json"
    criteria.write_text(json.dumps({
        "target_roles": roles or ["Product Designer", "Design Engineer", "Creative Technologist"],
        "seniority": seniority or ["senior", "staff", "principal", "lead", "director", "head"],
    }))
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"name": "Test"}))
    # Mock the Notion token loader to avoid .secrets permission error
    with patch("job_search.notifier._load_notion_token", return_value="fake-token"):
        return JobSearchAgent(
            criteria_path=criteria,
            candidate_path=candidate,
            db_path=tmp_path / "test.db",
            data_dir=tmp_path,  # P5.2 — isolate funnel/snapshot stores to tmp
        )


def _listing(**kw) -> JobListing:
    defaults = {
        "url": "https://example.com/job/1",
        "title": "Test Job",
        "company": "Acme",
        "board": "test",
    }
    defaults.update(kw)
    return JobListing(**defaults)


class TestScoreListing:
    def test_exact_role_match_scores_high(self, tmp_path):
        agent = _make_agent(tmp_path)
        listing = _listing(title="Product Designer")
        score = agent._score_listing(listing, "unknown")
        assert score >= 100

    def test_role_match_with_seniority_prefix(self, tmp_path):
        agent = _make_agent(tmp_path)
        listing = _listing(title="Senior Product Designer")
        score = agent._score_listing(listing, "unknown")
        # Role match (100) + seniority match (20)
        assert score >= 120

    def test_no_role_match_scores_zero(self, tmp_path):
        agent = _make_agent(tmp_path)
        listing = _listing(title="Nuclear Watch Keeper")
        score = agent._score_listing(listing, "unknown")
        assert score == 0

    def test_supported_ats_bonus(self, tmp_path):
        agent = _make_agent(tmp_path)
        listing = _listing(title="Product Designer")
        score_unknown = agent._score_listing(listing, "unknown")
        score_greenhouse = agent._score_listing(listing, "greenhouse")
        assert score_greenhouse > score_unknown
        assert score_greenhouse - score_unknown == 50

    def test_compensation_bonus(self, tmp_path):
        agent = _make_agent(tmp_path)
        listing_no_comp = _listing(title="Product Designer", compensation="")
        listing_comp = _listing(title="Product Designer", compensation="$150k")
        assert agent._score_listing(listing_comp, "unknown") > agent._score_listing(listing_no_comp, "unknown")

    def test_seniority_only_no_role_match(self, tmp_path):
        agent = _make_agent(tmp_path)
        listing = _listing(title="Senior Nurse Practitioner")
        score = agent._score_listing(listing, "unknown")
        # Only seniority match (20), no role match
        assert score == 20

    def test_ranking_order(self, tmp_path):
        """Verify that a good match outranks a bad one."""
        agent = _make_agent(tmp_path)
        good = _listing(title="Senior Product Designer", compensation="$180k")
        bad = _listing(title="Senior Accountant")
        assert agent._score_listing(good, "greenhouse") > agent._score_listing(bad, "unknown")

    def test_greenhouse_boosts_over_plain(self, tmp_path):
        """A role match with supported ATS outranks same role without."""
        agent = _make_agent(tmp_path)
        listing = _listing(title="Product Designer")
        assert agent._score_listing(listing, "greenhouse") > agent._score_listing(listing, "unknown")

    def test_case_insensitive(self, tmp_path):
        agent = _make_agent(tmp_path)
        listing = _listing(title="PRODUCT DESIGNER")
        score = agent._score_listing(listing, "unknown")
        assert score >= 100

    def test_account_required_board_penalized(self, tmp_path):
        """Dice listings get a heavy penalty — they require login to apply."""
        agent = _make_agent(tmp_path)
        dice_listing = _listing(title="Product Designer", board="dice")
        normal_listing = _listing(title="Product Designer", board="himalayas")
        dice_score = agent._score_listing(dice_listing, "unknown")
        normal_score = agent._score_listing(normal_listing, "unknown")
        assert normal_score > dice_score
        assert normal_score - dice_score == 200

    def test_dice_listing_ranks_below_no_match(self, tmp_path):
        """Even a role-matching Dice listing should rank below a non-Dice match."""
        agent = _make_agent(tmp_path)
        dice = _listing(title="Product Designer", board="dice")
        other = _listing(title="Product Designer", board="dribbble")
        assert agent._score_listing(other, "unknown") > agent._score_listing(dice, "unknown")

    def test_staffing_agency_penalized(self, tmp_path):
        """Staffing agencies should be deprioritized vs direct employers."""
        agent = _make_agent(tmp_path)
        staffing = _listing(title="Product Designer", company="BCforward")
        direct = _listing(title="Product Designer", company="Figma")
        assert agent._score_listing(direct, "unknown") > agent._score_listing(staffing, "unknown")

    def test_staffing_penalty_stacks_with_dice(self, tmp_path):
        """A Dice listing from a staffing agency gets both penalties."""
        agent = _make_agent(tmp_path)
        worst = _listing(title="Product Designer", board="dice", company="Apex Systems")
        score = agent._score_listing(worst, "unknown")
        # 100 (role) - 200 (dice) - 50 (staffing) = -150
        assert score < 0
