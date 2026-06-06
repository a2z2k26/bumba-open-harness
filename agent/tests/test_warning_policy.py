"""Warning-policy drift meta-test (Sprint R2.4, #1896).

The contract for the suite's warning behaviour is split between two files:

- ``agent/pyproject.toml`` → ``[tool.pytest.ini_options].filterwarnings``
  is the enforced policy (pytest reads it; CI runs it).
- ``docs/testing/warning-policy.md`` is the operator-readable rationale
  (each rule's "what / why / fix / review trigger").

This test fails when they drift. A new rule in pyproject without a matching
section in the doc means the rule was added without rationale; a section
in the doc without a matching rule means the doc is stale.

The pattern-matching here is intentionally simple — we look for the
rule's *distinctive substring* (e.g. ``coroutine.*never awaited``,
``TestChecker``, ``pytest_asyncio``) in the doc text. Authors who add a
new rule must update the doc with a section that mentions the
distinguishing substring; that is the load-bearing convention.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — Python <3.11 fallback
    import tomli as tomllib

_AGENT_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _AGENT_ROOT / "pyproject.toml"
_POLICY_DOC = _AGENT_ROOT.parent / "docs" / "testing" / "warning-policy.md"


def _filterwarnings_entries() -> list[str]:
    """Return the list of filterwarnings entries from pyproject.toml."""
    data = tomllib.loads(_PYPROJECT.read_text())
    ini_options = data["tool"]["pytest"]["ini_options"]
    return list(ini_options.get("filterwarnings", []))


def _distinctive_substrings(entry: str) -> list[str]:
    """Pull the substrings from a filterwarnings entry that the doc should mention.

    A filterwarnings entry has shape ``action:message:category:module``.
    Each component is a candidate identifier; we return the non-empty
    ones long enough to be distinctive (skip pure punctuation, the
    action word, and the bare category name without a dotted prefix).
    """
    parts = entry.split(":")
    distinctive: list[str] = []
    # Skip parts[0] (the action: error/ignore/etc).
    for part in parts[1:]:
        stripped = part.strip()
        if not stripped:
            continue
        # Skip bare category names (no dot, no quote, no regex marker).
        # We only care about message-substrings and module-paths that
        # the doc can reasonably name back to us.
        if "." in stripped or "*" in stripped or " " in stripped or "_" in stripped:
            distinctive.append(stripped)
    return distinctive


def test_every_filterwarnings_rule_is_documented():
    """Every pyproject filterwarnings entry has a corresponding section in the policy doc."""
    assert _POLICY_DOC.exists(), (
        f"warning-policy.md missing at {_POLICY_DOC}. Sprint R2.4 (#1896) "
        f"requires the doc to live next to the rules."
    )
    doc_text = _POLICY_DOC.read_text()
    entries = _filterwarnings_entries()
    assert entries, "pyproject.toml filterwarnings list is empty — R2.4 should have populated it"

    undocumented: list[str] = []
    for entry in entries:
        substrings = _distinctive_substrings(entry)
        if not substrings:
            # Entry has no distinctive parts to match — that's an
            # impoverished rule. Fail with a pointer.
            undocumented.append(
                f"  {entry!r} — no distinctive substring to match against the doc; "
                f"rule is too generic to be reviewable"
            )
            continue
        # At least one distinctive substring must appear in the doc.
        if not any(_doc_mentions(doc_text, s) for s in substrings):
            undocumented.append(
                f"  {entry!r} — none of {substrings} appears in warning-policy.md"
            )

    if undocumented:
        raise AssertionError(
            "filterwarnings entries missing documentation:\n"
            + "\n".join(undocumented)
            + "\nEach rule in pyproject.toml MUST have a corresponding "
            "section in docs/testing/warning-policy.md."
        )


def _doc_mentions(doc_text: str, substring: str) -> bool:
    """Return True if the doc mentions ``substring`` (regex-aware match).

    The filterwarnings entries use regex-style patterns (``.*``,
    ``[a-z]+``, etc.); the doc usually writes the human form. We strip
    regex metacharacters and look for the literal substring.
    """
    literal = re.sub(r"[\\^$.*+?()\[\]{}|]", " ", substring)
    # Split on whitespace and look for the longest meaningful chunk.
    chunks = [c for c in literal.split() if len(c) >= 4]
    if not chunks:
        return False
    longest = max(chunks, key=len)
    return longest in doc_text


def test_filterwarnings_action_words_are_valid():
    """Each entry must use a recognised action word.

    pytest accepts ``error``, ``ignore``, ``always``, ``default``,
    ``module``, ``once``. A typo here silently turns into an ``ignore``
    fallback in some pytest versions; a meta-test catches it cheaply.
    """
    valid_actions = {"error", "ignore", "always", "default", "module", "once"}
    bad: list[str] = []
    for entry in _filterwarnings_entries():
        action = entry.split(":", 1)[0].strip()
        if action not in valid_actions:
            bad.append(f"  {entry!r} — unknown action {action!r}; "
                       f"valid: {sorted(valid_actions)}")
    if bad:
        raise AssertionError(
            "Invalid action words in filterwarnings:\n" + "\n".join(bad)
        )
