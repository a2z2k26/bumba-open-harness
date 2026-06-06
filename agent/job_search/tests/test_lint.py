"""Tests for the cover letter lint gate (Z2-S2.2)."""
from __future__ import annotations


from job_search.lint import lint_cover_letter, LintResult, MIN_WORD_COUNT


def _good_letter(company: str = "Stripe") -> str:
    """Return a valid cover letter that passes all checks (>150 words, company named)."""
    return (
        f"Dear Hiring Team at {company},\n\n"
        "I am writing to express my strong interest in the Senior Product Designer role "
        f"at {company}. Over the past eight years building product and design systems "
        "at companies including ExampleCo, Sample Labs, and several Series B startups, I have "
        "developed a rare combination of design leadership and engineering depth that I "
        "believe maps directly to what you are building at this company.\n\n"
        "My most relevant experience is leading end-to-end product design for a real-time "
        "collaboration tool used by 40,000 monthly active users, where I drove a 34 percent "
        "improvement in task completion rate through a systematic design-system overhaul. "
        "I am comfortable working at the intersection of product, design, and engineering, "
        "and I have shipped production code alongside the designs I create every week.\n\n"
        "Beyond the technical work, I have led cross-functional teams, run design sprints, "
        "and built component libraries that scaled across four separate product lines. "
        "The ability to think in systems while still sweating the details of a single "
        "interaction is something I bring to every project I take on.\n\n"
        "I would love to discuss how my background aligns with this role and what you are "
        "building next. Thank you for your time and consideration.\n\n"
        "Best regards,\nExample User"
    )


# ---------------------------------------------------------------------------
# Placeholder token check
# ---------------------------------------------------------------------------

class TestPlaceholderTokens:
    def test_bracket_placeholder_fails(self):
        text = _good_letter().replace("Stripe", "[COMPANY]")
        result = lint_cover_letter(text, company="Stripe")
        assert not result.ok
        assert "placeholder_token" in result.failures

    def test_double_brace_placeholder_fails(self):
        text = _good_letter() + " I am excited about {{role}}."
        result = lint_cover_letter(text)
        assert not result.ok
        assert "placeholder_token" in result.failures

    def test_todo_keyword_fails(self):
        text = _good_letter() + " TODO: add specific project here."
        result = lint_cover_letter(text)
        assert "placeholder_token" in result.failures

    def test_lorem_ipsum_fails(self):
        text = "Lorem ipsum dolor sit amet. " * 20
        result = lint_cover_letter(text)
        assert "placeholder_token" in result.failures

    def test_fixme_fails(self):
        text = _good_letter() + " FIXME"
        result = lint_cover_letter(text)
        assert "placeholder_token" in result.failures

    def test_xxx_fails(self):
        text = _good_letter() + " XXX placeholder"
        result = lint_cover_letter(text)
        assert "placeholder_token" in result.failures

    def test_clean_letter_no_placeholder_failure(self):
        result = lint_cover_letter(_good_letter("Stripe"), company="Stripe")
        assert "placeholder_token" not in result.failures


# ---------------------------------------------------------------------------
# Word count check
# ---------------------------------------------------------------------------

class TestWordCount:
    def test_short_letter_fails(self):
        text = "Dear hiring team, I am interested. Regards."
        result = lint_cover_letter(text, company="Stripe")
        assert "word_count_low" in result.failures

    def test_exactly_min_words_passes(self):
        # Build a letter with exactly MIN_WORD_COUNT words that mentions Stripe
        words = ["word"] * (MIN_WORD_COUNT - 1) + ["Stripe"]
        text = " ".join(words)
        result = lint_cover_letter(text, company="Stripe")
        assert "word_count_low" not in result.failures

    def test_custom_min_word_count(self):
        text = "one two three Stripe"
        # With min=3 it should pass (4 words >= 3)
        result = lint_cover_letter(text, company="Stripe", min_word_count=3)
        assert "word_count_low" not in result.failures
        # With min=10 it should fail
        result2 = lint_cover_letter(text, company="Stripe", min_word_count=10)
        assert "word_count_low" in result2.failures

    def test_good_letter_passes_word_count(self):
        letter = _good_letter()
        word_count = len(letter.split())
        assert word_count >= MIN_WORD_COUNT, (
            f"_good_letter() has only {word_count} words; must be >= {MIN_WORD_COUNT}"
        )
        result = lint_cover_letter(letter, company="Stripe")
        assert "word_count_low" not in result.failures


# ---------------------------------------------------------------------------
# Company name check
# ---------------------------------------------------------------------------

class TestCompanyName:
    def test_missing_company_name_fails(self):
        # Letter that mentions GenericCorp but we check for Stripe
        text = _good_letter("GenericCorp").replace("GenericCorp", "the company")
        result = lint_cover_letter(text, company="Stripe")
        assert "company_name_missing" in result.failures

    def test_company_name_present_passes(self):
        result = lint_cover_letter(_good_letter("Stripe"), company="Stripe")
        assert "company_name_missing" not in result.failures

    def test_company_name_check_case_insensitive(self):
        text = _good_letter("stripe")  # lowercase
        result = lint_cover_letter(text, company="Stripe")
        assert "company_name_missing" not in result.failures

    def test_no_company_arg_skips_check(self):
        text = "Dear team, " + "word " * 200
        result = lint_cover_letter(text, company="")
        assert "company_name_missing" not in result.failures

    def test_dear_hiring_team_fails_for_stripe(self):
        # Reproduce spec scenario exactly
        text = "Dear hiring team, " + "word " * 200
        result = lint_cover_letter(text, company="Stripe")
        assert not result.ok
        assert "company_name_missing" in result.failures


# ---------------------------------------------------------------------------
# Empty / null input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_string_fails(self):
        result = lint_cover_letter("")
        assert not result.ok
        assert "empty_text" in result.failures

    def test_whitespace_only_fails(self):
        result = lint_cover_letter("   \n  ")
        assert not result.ok
        assert "empty_text" in result.failures


# ---------------------------------------------------------------------------
# LintResult type
# ---------------------------------------------------------------------------

class TestLintResult:
    def test_ok_result_is_truthy(self):
        r = LintResult(ok=True)
        assert bool(r) is True

    def test_fail_result_is_falsy(self):
        r = LintResult(ok=False, failures=("placeholder_token",))
        assert bool(r) is False

    def test_failures_tuple_on_ok(self):
        result = lint_cover_letter(_good_letter("Stripe"), company="Stripe")
        assert result.ok
        assert result.failures == ()

    def test_details_populated_on_failure(self):
        text = _good_letter().replace("Stripe", "[COMPANY]")
        result = lint_cover_letter(text, company="Stripe")
        assert "placeholder_token" in result.details
        assert len(result.details["placeholder_token"]) > 0


# ---------------------------------------------------------------------------
# Multiple failures in one pass
# ---------------------------------------------------------------------------

class TestMultipleFailures:
    def test_placeholder_and_company_missing_both_reported(self):
        text = "Dear team, [ROLE] position at the company. " + "word " * 200
        result = lint_cover_letter(text, company="Stripe")
        assert "placeholder_token" in result.failures
        assert "company_name_missing" in result.failures
        assert not result.ok
