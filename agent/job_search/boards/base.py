"""Abstract base class for job board scrapers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class JobListing:
    url: str
    title: str
    company: str
    board: str
    location: str = ""
    remote: str = ""
    compensation: str = ""
    description: str = ""
    raw: dict = field(default_factory=dict)


class JobBoard(ABC):
    name: str = ""

    @abstractmethod
    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch job listings matching keywords."""
        ...
