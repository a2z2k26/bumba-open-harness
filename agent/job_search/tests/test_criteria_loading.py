"""Tests for criteria and candidate field mapping from JSON config files."""
import json

from job_search.criteria import SearchCriteria, Candidate


class TestSearchCriteriaFromFile:
    def test_target_roles_maps_to_roles(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "target_roles": ["Product Designer", "Design Engineer"],
            "seniority": ["senior"],
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.roles == ["Product Designer", "Design Engineer"]

    def test_roles_key_still_works(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "roles": ["Backend Engineer"],
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.roles == ["Backend Engineer"]

    def test_target_roles_takes_precedence(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "target_roles": ["Designer"],
            "roles": ["Engineer"],
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.roles == ["Designer"]

    def test_nested_exclusions_flattened(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "exclusions": {
                "companies": ["BadCorp"],
                "industries": ["Oil"],
                "company_types": ["Startup"],
            }
        }))
        sc = SearchCriteria.from_file(cfg)
        assert "BadCorp" in sc.exclusions
        assert "Oil" in sc.exclusions
        assert "Startup" in sc.exclusions
        assert isinstance(sc.exclusions, list)

    def test_flat_exclusions_still_work(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "exclusions": ["C++", "embedded"],
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.exclusions == ["C++", "embedded"]

    def test_empty_nested_exclusions(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "exclusions": {
                "companies": [],
                "industries": [],
                "company_types": [],
            }
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.exclusions == []

    def test_locations_list_uses_first(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "locations": ["Remote", "NYC"],
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.location == "Remote"

    def test_remote_ok_alias(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "remote_ok": True,
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.remote_only is True

    def test_matches_exclusions_with_flattened(self, tmp_path):
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "exclusions": {
                "companies": ["EvilCorp"],
                "industries": ["tobacco"],
            }
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.matches_exclusions("Job at EvilCorp is hiring")
        assert not sc.matches_exclusions("Job at GoodCorp is hiring")

    def test_real_criteria_format(self, tmp_path):
        """Test with the actual criteria.json format from the deployed config."""
        cfg = tmp_path / "criteria.json"
        cfg.write_text(json.dumps({
            "target_roles": ["Product Designer", "Senior Product Designer"],
            "locations": ["Remote", "Hybrid", "New York City, NY"],
            "remote_ok": True,
            "seniority": ["senior", "staff", "principal"],
            "compensation_floor_usd": 175000,
            "exclusions": {"industries": [], "company_types": [], "companies": []},
            "daily_cap": 100,
        }))
        sc = SearchCriteria.from_file(cfg)
        assert sc.roles == ["Product Designer", "Senior Product Designer"]
        assert sc.location == "Remote"
        assert sc.remote_only is True
        assert sc.compensation_floor_usd == 175000
        assert sc.exclusions == []
        assert sc.daily_cap == 100


class TestCandidateFromFile:
    def test_loads_new_fields(self, tmp_path):
        cfg = tmp_path / "candidate.json"
        cfg.write_text(json.dumps({
            "name": "the operator",
            "resume_local_path": "/path/to/resume.pdf",
            "portfolio_links": ["https://a.com", "https://b.com"],
            "cover_letter_mode": "ai_generated",
            "cover_letter_template": "",
            "skills": ["Design"],
        }))
        c = Candidate.from_file(cfg)
        assert c.resume_local_path == "/path/to/resume.pdf"
        assert c.portfolio_links == ["https://a.com", "https://b.com"]
        assert c.cover_letter_mode == "ai_generated"

    def test_defaults_for_new_fields(self, tmp_path):
        cfg = tmp_path / "candidate.json"
        cfg.write_text(json.dumps({"name": "Test"}))
        c = Candidate.from_file(cfg)
        assert c.resume_local_path == ""
        assert c.portfolio_links == []
        assert c.cover_letter_mode == "manual"
        assert c.cover_letter_template == ""

    def test_to_dict_includes_new_fields(self, tmp_path):
        cfg = tmp_path / "candidate.json"
        cfg.write_text(json.dumps({
            "name": "the operator",
            "resume_local_path": "/resume.pdf",
            "portfolio_links": ["https://a.com"],
            "cover_letter_mode": "ai_generated",
        }))
        c = Candidate.from_file(cfg)
        d = c.to_dict()
        assert d["resume_local_path"] == "/resume.pdf"
        assert d["portfolio_links"] == ["https://a.com"]
        assert d["cover_letter_mode"] == "ai_generated"

    def test_real_candidate_format(self, tmp_path):
        """Test with the actual candidate.json format from the deployed config."""
        cfg = tmp_path / "candidate.json"
        cfg.write_text(json.dumps({
            "name": "Example User",
            "email": "",
            "phone": "",
            "resume_url": "https://drive.google.com/file/d/xxx/view",
            "resume_local_path": "/opt/bumba-harness/data/resume.pdf",
            "portfolio_url": "https://portfolio.example.com",
            "portfolio_links": ["https://notion.site/history", "https://figma.com/slides/xxx"],
            "linkedin_url": "https://www.linkedin.com/in/example-operator/",
            "cover_letter_mode": "ai_generated",
            "cover_letter_template": "",
            "skills": ["Product Design", "UX Design"],
        }))
        c = Candidate.from_file(cfg)
        assert c.name == "Example User"
        assert c.resume_local_path == "/opt/bumba-harness/data/resume.pdf"
        assert len(c.portfolio_links) == 2
        assert c.cover_letter_mode == "ai_generated"
