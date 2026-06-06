"""Criteria and candidate dataclasses for the job search agent."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SearchCriteria:
    """What the agent should look for."""
    roles: list[str] = field(default_factory=list)
    location: str = "remote"
    seniority: list[str] = field(default_factory=list)
    compensation_floor_usd: int = 0
    exclusions: list[str] = field(default_factory=list)
    remote_only: bool = True
    daily_cap: int = 10

    @classmethod
    def from_file(cls, path: str | Path) -> "SearchCriteria":
        """Load criteria from a JSON file."""
        data = json.loads(Path(path).read_text())

        # Handle both "target_roles" and "roles" keys
        roles = data.get("target_roles", data.get("roles", []))

        # Handle "locations" (list) falling back to "location" (string)
        location_raw = data.get("locations", data.get("location", "remote"))
        if isinstance(location_raw, list):
            location = location_raw[0] if location_raw else "remote"
        else:
            location = location_raw

        # Flatten nested exclusions dict into a flat list of strings
        raw_exc = data.get("exclusions", [])
        if isinstance(raw_exc, dict):
            exclusions: list[str] = []
            for val in raw_exc.values():
                if isinstance(val, list):
                    exclusions.extend(val)
                elif isinstance(val, str):
                    exclusions.append(val)
        else:
            exclusions = raw_exc

        # Handle "remote_ok" alias for "remote_only"
        remote_only = data.get("remote_only", data.get("remote_ok", True))

        return cls(
            roles=roles,
            location=location,
            seniority=data.get("seniority", []),
            compensation_floor_usd=data.get("compensation_floor_usd", 0),
            exclusions=exclusions,
            remote_only=remote_only,
            daily_cap=data.get("daily_cap", 10),
        )

    def matches_exclusions(self, text: str) -> bool:
        """Return True if text contains any excluded keyword."""
        text_lower = text.lower()
        return any(exc.lower() in text_lower for exc in self.exclusions)

    # Words that indicate the design/creative field (safe as standalone keywords)
    _FIELD_ROOTS = frozenset({"designer", "creative director"})

    def keyword_list(self) -> list[str]:
        """Return role keywords for board queries.

        Returns full role phrases (e.g. "Product Designer") plus field-specific
        root words extracted from the roles (e.g. "designer").  Root words are
        specific enough to the design field to avoid matching unrelated jobs
        (unlike seniority words like "senior" which match everything).

        "designer" alone restores matches for "UX Designer", "Visual Designer",
        "Senior Designer" etc. that the full role phrases miss.
        """
        # Extract field-relevant root words from role titles
        roots: list[str] = []
        for role in self.roles:
            role_lower = role.lower()
            for root in self._FIELD_ROOTS:
                if root in role_lower and root not in roots:
                    roots.append(root)
        return self.roles + roots


@dataclass
class Candidate:
    """Who is applying."""
    name: str = ""
    email: str = ""
    phone: str = ""
    resume_url: str = ""
    resume_local_path: str = ""
    portfolio_url: str = ""
    portfolio_links: list[str] = field(default_factory=list)
    linkedin_url: str = ""
    github_url: str = ""
    years_experience: int = 0
    skills: list[str] = field(default_factory=list)
    cover_letter_mode: str = "manual"
    cover_letter_template: str = ""

    @classmethod
    def from_file(cls, path: str | Path) -> "Candidate":
        """Load candidate from a JSON file."""
        data = json.loads(Path(path).read_text())
        return cls(
            name=data.get("name", ""),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            resume_url=data.get("resume_url", ""),
            resume_local_path=data.get("resume_local_path", ""),
            portfolio_url=data.get("portfolio_url", ""),
            portfolio_links=data.get("portfolio_links", []),
            linkedin_url=data.get("linkedin_url", ""),
            github_url=data.get("github_url", ""),
            years_experience=data.get("years_experience", 0),
            skills=data.get("skills", []),
            cover_letter_mode=data.get("cover_letter_mode", "manual"),
            cover_letter_template=data.get("cover_letter_template", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for use in ATS handlers."""
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "resume_url": self.resume_url,
            "resume_local_path": self.resume_local_path,
            "portfolio_url": self.portfolio_url,
            "portfolio_links": self.portfolio_links,
            "linkedin_url": self.linkedin_url,
            "github_url": self.github_url,
            "years_experience": self.years_experience,
            "skills": self.skills,
            "cover_letter_mode": self.cover_letter_mode,
        }
