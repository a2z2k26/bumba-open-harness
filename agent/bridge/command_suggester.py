"""Suggest relevant commands/skills based on message content and tool-use patterns."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandEntry:
    name: str
    description: str
    keywords: frozenset[str] = field(default_factory=frozenset)


# Tool-to-command mapping: if Claude used these tools, suggest these commands
_TOOL_SUGGESTIONS: dict[str, list[str]] = {
    "git": ["git/feature-branch", "gh/create-pr"],
    "pytest": ["testing/all", "testing/feature"],
    "deploy": ["bumba"],
    "sqlite3": ["search-knowledge", "memory-action"],
}

# Minimum Jaccard similarity for keyword match
_JACCARD_THRESHOLD = 0.2


_STOP_WORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "his", "how", "its", "may",
    "new", "now", "old", "see", "way", "who", "did", "get", "got", "let",
    "say", "she", "too", "use", "what", "when", "with", "from", "that",
    "this", "will", "your", "have", "been", "each", "make", "like", "been",
    "than", "them", "then", "these", "into", "some", "could", "other",
})


def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase alphabetic tokens (3+ chars, no stop words) from text."""
    return {
        w.lower() for w in re.findall(r"[a-zA-Z]{3,}", text)
        if w.lower() not in _STOP_WORDS
    }


def _jaccard(a: set[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


class CommandSuggester:
    """Index commands and skills, suggest relevant ones based on context."""

    def __init__(self, commands_dir: Path, skills_dir: Path) -> None:
        self._index: list[CommandEntry] = []
        self._build_index(commands_dir, skills_dir)

    def _build_index(self, commands_dir: Path, skills_dir: Path) -> None:
        """Scan command/skill .md files, extract name + description from frontmatter."""
        # Index commands
        if commands_dir.is_dir():
            for md_file in commands_dir.rglob("*.md"):
                entry = self._parse_frontmatter(md_file, prefix="")
                if entry:
                    self._index.append(entry)

        # Index skills
        if skills_dir.is_dir():
            for md_file in skills_dir.rglob("SKILL.md"):
                entry = self._parse_frontmatter(md_file, prefix="")
                if entry:
                    self._index.append(entry)

        log.info("CommandSuggester indexed %d entries", len(self._index))

    @staticmethod
    def _parse_frontmatter(path: Path, prefix: str = "") -> CommandEntry | None:
        """Extract name and description from YAML frontmatter."""
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return None

        if not text.startswith("---"):
            return None

        end = text.find("---", 3)
        if end == -1:
            return None

        try:
            fm = yaml.safe_load(text[3:end])
        except Exception:
            return None

        if not isinstance(fm, dict):
            return None

        name = fm.get("name", "")
        if not name:
            # Derive name from filename
            name = path.stem
            if name == "SKILL":
                name = path.parent.name

        description = fm.get("description", "")
        keywords = _extract_keywords(f"{name} {description}")

        return CommandEntry(
            name=f"{prefix}{name}",
            description=description,
            keywords=frozenset(keywords),
        )

    def suggest(
        self,
        message: str,
        tools_used: list[str] | None = None,
        num_turns: int = 0,
    ) -> list[str]:
        """Return up to 3 command suggestions based on message content and tool patterns."""
        suggestions: dict[str, float] = {}
        msg_keywords = _extract_keywords(message)

        # Keyword similarity matching
        for entry in self._index:
            score = _jaccard(msg_keywords, entry.keywords)
            if score >= _JACCARD_THRESHOLD:
                suggestions[entry.name] = max(suggestions.get(entry.name, 0), score)

        # Tool-use pattern matching
        if tools_used:
            for tool in tools_used:
                tool_lower = tool.lower()
                for pattern, cmds in _TOOL_SUGGESTIONS.items():
                    if pattern in tool_lower:
                        for cmd in cmds:
                            suggestions[cmd] = max(suggestions.get(cmd, 0), 0.5)

        # Complexity signal: suggest planning for complex tasks
        if num_turns >= 5:
            suggestions["orc/plan-feature"] = max(
                suggestions.get("orc/plan-feature", 0), 0.4
            )

        # Sort by score descending, return top 3
        ranked = sorted(suggestions.items(), key=lambda x: x[1], reverse=True)
        return [name for name, _ in ranked[:3]]
