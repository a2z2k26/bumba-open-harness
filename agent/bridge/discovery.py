"""MS5.3 — Capability Self-Discovery.

Scans research documents and compares against implemented features to
identify unimplemented capabilities.  Generates structured proposals
with feasibility scoring and deduplication.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROPOSAL_STATUSES = ("proposed", "approved", "rejected", "implemented", "deferred")

# Minimum thresholds for auto-proposal
MIN_VALUE = 3
MAX_COMPLEXITY = 4
SIMILARITY_THRESHOLD = 0.70  # above this = duplicate


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FeatureIdea:
    """A feature idea extracted from a research document."""

    name: str = ""
    source_doc: str = ""
    description: str = ""
    source_quote: str = ""
    doc_hash: str = ""


@dataclass
class FeasibilityScore:
    """Feasibility assessment for a feature idea."""

    complexity: int = 3  # 1-5
    value: int = 3  # 1-5
    risk: int = 2  # 1-5

    @property
    def priority_score(self) -> float:
        return self.value * 2 - self.complexity - self.risk


@dataclass
class FeatureProposal:
    """A structured feature proposal."""

    name: str = ""
    source_document: str = ""
    source_quote: str = ""
    description: str = ""
    implementation_sketch: str = ""
    prerequisites: list[str] = field(default_factory=list)
    feasibility: FeasibilityScore = field(default_factory=FeasibilityScore)
    status: str = "proposed"
    reject_reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def priority_score(self) -> float:
        return self.feasibility.priority_score


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

# Patterns that hint at feature descriptions
_FEATURE_PATTERNS = [
    re.compile(r"(?:should|could|can)\s+(?:implement|add|build|create|support)\s+(.+)", re.I),
    re.compile(r"(?:feature|capability|tool|skill):\s*(.+)", re.I),
    re.compile(r"(?:TODO|FUTURE|IDEA):\s*(.+)", re.I),
]


def extract_feature_ideas(
    text: str, source_doc: str = "", doc_hash: str = ""
) -> list[FeatureIdea]:
    """Extract feature ideas from a document's text."""
    ideas: list[FeatureIdea] = []
    seen_names: set[str] = set()

    for pattern in _FEATURE_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1).strip().rstrip(".")
            # Normalise to a short name
            name = _normalise_name(raw)
            if not name or name in seen_names or len(name) < 3:
                continue
            seen_names.add(name)

            # Get surrounding context as quote (up to 200 chars)
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 150)
            quote = text[start:end].replace("\n", " ").strip()

            ideas.append(FeatureIdea(
                name=name,
                source_doc=source_doc,
                description=raw,
                source_quote=quote,
                doc_hash=doc_hash,
            ))

    return ideas


def _normalise_name(raw: str) -> str:
    """Create a slug-style name from raw text."""
    # Take first 60 chars, lowercase, replace non-alnum with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", raw[:60].lower()).strip("-")
    return slug


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def keyword_overlap(a: str, b: str) -> float:
    """Compute word-overlap similarity between two strings."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def is_duplicate(
    new_name: str,
    new_desc: str,
    existing: list[FeatureProposal],
    threshold: float = SIMILARITY_THRESHOLD,
) -> FeatureProposal | None:
    """Check if a feature is a duplicate of an existing proposal.

    Returns the matching proposal or None.
    """
    combined_new = f"{new_name} {new_desc}"
    for prop in existing:
        combined_existing = f"{prop.name} {prop.description}"
        if keyword_overlap(combined_new, combined_existing) >= threshold:
            return prop
    return None


# ---------------------------------------------------------------------------
# Implementation check
# ---------------------------------------------------------------------------


def scan_implemented_features(project_root: Path) -> set[str]:
    """Scan the project for already-implemented feature names."""
    implemented: set[str] = set()

    # Check skills
    skills_dir = project_root / "skills"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                implemented.add(skill_dir.name)

    # Check bridge modules
    bridge_dir = project_root / "bridge"
    if bridge_dir.exists():
        for py_file in bridge_dir.glob("*.py"):
            name = py_file.stem
            if name != "__init__":
                implemented.add(name)

    # Check services
    services_dir = project_root / "bridge" / "services"
    if services_dir.exists():
        for py_file in services_dir.glob("*.py"):
            name = py_file.stem
            if name not in ("__init__", "runner"):
                implemented.add(name)

    return implemented


# ---------------------------------------------------------------------------
# Proposal store
# ---------------------------------------------------------------------------


class ProposalStore:
    """Manages feature proposals on disk."""

    def __init__(self, proposals_dir: Path) -> None:
        self._dir = proposals_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, proposal: FeatureProposal) -> Path:
        """Save or update a proposal."""
        now = datetime.now(timezone.utc).isoformat()
        if not proposal.created_at:
            proposal.created_at = now
        proposal.updated_at = now

        filename = f"{proposal.name}.json"
        path = self._dir / filename
        data = {
            "name": proposal.name,
            "source_document": proposal.source_document,
            "source_quote": proposal.source_quote,
            "description": proposal.description,
            "implementation_sketch": proposal.implementation_sketch,
            "prerequisites": proposal.prerequisites,
            "feasibility": {
                "complexity": proposal.feasibility.complexity,
                "value": proposal.feasibility.value,
                "risk": proposal.feasibility.risk,
            },
            "priority_score": proposal.priority_score,
            "status": proposal.status,
            "reject_reason": proposal.reject_reason,
            "created_at": proposal.created_at,
            "updated_at": proposal.updated_at,
        }
        path.write_text(json.dumps(data, indent=2))
        return path

    def load(self, name: str) -> FeatureProposal | None:
        """Load a proposal by name."""
        path = self._dir / f"{name}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            feas = data.get("feasibility", {})
            return FeatureProposal(
                name=data.get("name", ""),
                source_document=data.get("source_document", ""),
                source_quote=data.get("source_quote", ""),
                description=data.get("description", ""),
                implementation_sketch=data.get("implementation_sketch", ""),
                prerequisites=data.get("prerequisites", []),
                feasibility=FeasibilityScore(
                    complexity=feas.get("complexity", 3),
                    value=feas.get("value", 3),
                    risk=feas.get("risk", 2),
                ),
                status=data.get("status", "proposed"),
                reject_reason=data.get("reject_reason", ""),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            )
        except (json.JSONDecodeError, OSError):
            return None

    def list_all(self) -> list[FeatureProposal]:
        """List all proposals."""
        proposals: list[FeatureProposal] = []
        for path in sorted(self._dir.glob("*.json")):
            prop = self.load(path.stem)
            if prop:
                proposals.append(prop)
        return proposals

    def list_pending(self) -> list[FeatureProposal]:
        """List proposals with status=proposed."""
        return [p for p in self.list_all() if p.status == "proposed"]

    def approve(self, name: str) -> bool:
        """Approve a proposal."""
        prop = self.load(name)
        if not prop:
            return False
        prop.status = "approved"
        self.save(prop)
        return True

    def reject(self, name: str, reason: str = "") -> bool:
        """Reject a proposal."""
        prop = self.load(name)
        if not prop:
            return False
        prop.status = "rejected"
        prop.reject_reason = reason
        self.save(prop)
        return True

    def defer(self, name: str) -> bool:
        """Defer a proposal."""
        prop = self.load(name)
        if not prop:
            return False
        prop.status = "deferred"
        self.save(prop)
        return True

    def count(self, status: str | None = None) -> int:
        """Count proposals, optionally filtered by status."""
        if status:
            return len([p for p in self.list_all() if p.status == status])
        return len(list(self._dir.glob("*.json")))

    def format_proposals_table(self, proposals: list[FeatureProposal] | None = None) -> str:
        """Format proposals as a markdown table."""
        if proposals is None:
            proposals = self.list_pending()
        if not proposals:
            return "_No pending proposals._"
        lines = [
            "| Name | Priority | Complexity | Value | Risk | Status |",
            "|------|----------|-----------|-------|------|--------|",
        ]
        for p in sorted(proposals, key=lambda x: -x.priority_score):
            lines.append(
                f"| {p.name} | {p.priority_score:.1f} | {p.feasibility.complexity} "
                f"| {p.feasibility.value} | {p.feasibility.risk} | {p.status} |"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scan cache
# ---------------------------------------------------------------------------


def file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


class ScanCache:
    """Cache scan results to avoid re-scanning unchanged documents."""

    def __init__(self, cache_path: Path) -> None:
        self._path = cache_path
        self._cache: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._cache = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._cache, indent=2))

    def is_changed(self, doc_path: Path) -> bool:
        """Check if a document has changed since last scan."""
        current = file_hash(doc_path)
        key = str(doc_path)
        if self._cache.get(key) == current:
            return False
        return True

    def mark_scanned(self, doc_path: Path) -> None:
        """Record that a document has been scanned."""
        self._cache[str(doc_path)] = file_hash(doc_path)
        self._save()

    def count(self) -> int:
        return len(self._cache)
