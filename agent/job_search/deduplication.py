"""URL and title fingerprinting for deduplication."""
from __future__ import annotations
import hashlib
import re


def _normalize_url(url: str) -> str:
    url = url.strip().lower()
    url = re.sub(r'[?#].*$', '', url)
    url = url.rstrip('/')
    return url


def _fingerprint(url: str, title: str = "", company: str = "") -> str:
    normalized = _normalize_url(url)
    raw = f"{normalized}|{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Deduplicator:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_duplicate(self, url: str, title: str = "", company: str = "") -> bool:
        return _fingerprint(url, title, company) in self._seen

    def mark_seen(self, url: str, title: str = "", company: str = "") -> str:
        fp = _fingerprint(url, title, company)
        self._seen.add(fp)
        return fp

    def fingerprint(self, url: str, title: str = "", company: str = "") -> str:
        return _fingerprint(url, title, company)

    def add_fingerprint(self, fp: str) -> None:
        """Directly add a known fingerprint (e.g., loaded from DB on startup)."""
        self._seen.add(fp)

    def seen_count(self) -> int:
        return len(self._seen)

    def reset(self) -> None:
        self._seen.clear()
