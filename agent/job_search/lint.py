"""Cover Letter Lint Gate — Z2-S2.2.

Three checks run before a cover letter is staged or submitted:

  1. placeholder_token  — unresolved bracket/brace/keyword tokens
  2. company_name_missing — letter doesn't mention the target company
  3. word_count_low  — letter is suspiciously short (< MIN_WORD_COUNT)

A fourth check (claim_not_grounded) is reserved for a future sprint that
adds resume-parsing; the hook is scaffolded here so callers don't need to
change their interface.

Usage:
    from job_search.lint import lint_cover_letter, LintResult

    result = lint_cover_letter(text, company="Stripe")
    if not result.ok:
        print(result.failures)  # e.g. ["placeholder_token", "company_name_missing"]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Configuration knobs
# ---------------------------------------------------------------------------

MIN_WORD_COUNT = 150

# Regex patterns that identify unresolved placeholder tokens.
_PLACEHOLDER_PATTERNS: list[re.Pattern] = [
    re.compile(r"\[[\w\s]+\]"),               # [COMPANY], [Role], [NAME]
    re.compile(r"\{\{[\w\s]+\}\}"),            # {{company}}, {{role}}
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bFIXME\b", re.IGNORECASE),
    re.compile(r"\bXXX\b"),
    re.compile(r"\bLorem ipsum\b", re.IGNORECASE),
    re.compile(r"<[\w\s]+>"),                  # <Company Name>
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LintResult:
    """Result of running the cover-letter lint gate.

    ok=True means no blocking failures were found.
    failures is a list of short tag strings (never empty when ok=False).
    details maps each failure tag to a human-readable explanation.
    """

    ok: bool
    failures: tuple[str, ...] = field(default_factory=tuple)
    details: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lint_cover_letter(
    text: str,
    company: str = "",
    *,
    min_word_count: int = MIN_WORD_COUNT,
) -> LintResult:
    """Run all lint checks on a cover letter.

    Parameters
    ----------
    text:
        The cover letter body.
    company:
        The target company name (used for company_name_missing check).
        If empty the company-name check is skipped.
    min_word_count:
        Minimum acceptable word count.

    Returns
    -------
    LintResult with ok=True if all checks pass, ok=False otherwise.
    """
    failures: list[str] = []
    details: dict[str, str] = {}

    # --- check 1: empty / null text ---
    if not text or not text.strip():
        return LintResult(
            ok=False,
            failures=("empty_text",),
            details={"empty_text": "Cover letter is empty or whitespace-only."},
        )

    # --- check 2: placeholder tokens ---
    found_placeholders = _find_placeholders(text)
    if found_placeholders:
        failures.append("placeholder_token")
        details["placeholder_token"] = (
            f"Unresolved placeholder tokens found: {', '.join(found_placeholders[:5])}"
        )

    # --- check 3: word count ---
    word_count = len(text.split())
    if word_count < min_word_count:
        failures.append("word_count_low")
        details["word_count_low"] = (
            f"Word count {word_count} is below minimum {min_word_count}."
        )

    # --- check 4: company name present ---
    if company and company.strip():
        if not _company_name_present(text, company):
            failures.append("company_name_missing")
            details["company_name_missing"] = (
                f"Company name '{company}' does not appear in the letter."
            )

    # --- check 5: claim_not_grounded (reserved — always passes for now) ---
    # Future: parse resume and cross-check quantified claims.

    ok = len(failures) == 0
    return LintResult(ok=ok, failures=tuple(failures), details=details)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_placeholders(text: str) -> list[str]:
    """Return list of placeholder token matches found in *text*."""
    found: list[str] = []
    for pattern in _PLACEHOLDER_PATTERNS:
        matches = pattern.findall(text)
        found.extend(str(m) for m in matches)
    return found


def _company_name_present(text: str, company: str) -> bool:
    """Return True if *company* appears verbatim (case-insensitive) in *text*."""
    return company.lower() in text.lower()
