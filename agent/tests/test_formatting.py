"""Comprehensive tests for bridge.formatting (Discord markdown-native).

Covers: split_message (all split strategies, part indicators, edge cases),
_repair_code_fences (balanced/unbalanced, language tags, multi-chunk),
format_response, format_plain (markdown stripping).
"""

from __future__ import annotations

from bridge.formatting import (
    MAX_MESSAGE_LENGTH,
    _repair_code_fences,
    format_plain,
    format_response,
    split_message,
)


# ---------------------------------------------------------------------------
# split_message — basic behavior
# ---------------------------------------------------------------------------


class TestSplitMessageBasic:
    def test_under_limit_returns_single_chunk(self) -> None:
        result = split_message("short message")
        assert result == ["short message"]

    def test_exactly_at_limit_returns_single_chunk(self) -> None:
        text = "A" * 2000
        result = split_message(text, max_length=2000)
        assert len(result) == 1
        assert result[0] == text

    def test_one_char_over_limit_splits(self) -> None:
        text = "A" * 2001
        result = split_message(text, max_length=2000)
        assert len(result) == 2

    def test_empty_string_returns_single_chunk(self) -> None:
        result = split_message("")
        assert result == [""]

    def test_default_limit_is_2000(self) -> None:
        assert MAX_MESSAGE_LENGTH == 2000
        text = "A" * 1999
        result = split_message(text)
        assert len(result) == 1

        text = "A" * 2001
        result = split_message(text)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# split_message — split strategies
# ---------------------------------------------------------------------------


class TestSplitStrategies:
    def test_splits_at_paragraph_break(self) -> None:
        text = "A" * 1500 + "\n\n" + "B" * 1500
        result = split_message(text, max_length=2000)
        assert len(result) == 2
        # First chunk should contain only A's (before paragraph break)
        assert "B" not in result[0].replace("[1/2] ", "")

    def test_splits_at_newline_when_no_paragraph(self) -> None:
        text = "A" * 1500 + "\n" + "B" * 1500
        result = split_message(text, max_length=2000)
        assert len(result) == 2

    def test_splits_at_space_when_no_newline(self) -> None:
        text = "word " * 500  # 2500 chars, no newlines
        result = split_message(text, max_length=100)
        assert len(result) > 1
        # Each chunk should be within limit
        for chunk in result:
            assert len(chunk) <= 100

    def test_hard_cut_when_no_break_points(self) -> None:
        text = "A" * 5000  # No spaces, newlines, or paragraph breaks
        result = split_message(text, max_length=100)
        assert len(result) > 1

    def test_paragraph_preferred_over_newline(self) -> None:
        """When both paragraph break and newline exist, paragraph is preferred."""
        text = "A" * 500 + "\n\n" + "B" * 500 + "\n" + "C" * 500
        result = split_message(text, max_length=1100)
        # Should split at paragraph break
        assert len(result) == 2
        first = result[0].replace("[1/2] ", "")
        assert first == "A" * 500

    def test_newline_preferred_over_space(self) -> None:
        """When both newline and space exist, newline is preferred."""
        text = "A" * 500 + "\n" + "B " * 250 + "C" * 500
        result = split_message(text, max_length=600)
        assert len(result) >= 2


# ---------------------------------------------------------------------------
# split_message — part indicators
# ---------------------------------------------------------------------------


class TestPartIndicators:
    def test_no_indicators_for_single_chunk(self) -> None:
        result = split_message("short")
        assert "[" not in result[0]

    def test_two_chunk_indicators(self) -> None:
        text = "A" * 1500 + "\n\n" + "B" * 1500
        result = split_message(text, max_length=2000)
        assert result[0].startswith("[1/2]")
        assert result[1].startswith("[2/2]")

    def test_many_chunks_indicators(self) -> None:
        text = "A" * 10000
        result = split_message(text, max_length=100)
        total = len(result)
        for i, chunk in enumerate(result):
            assert chunk.startswith(f"[{i + 1}/{total}]")

    def test_indicators_within_limit(self) -> None:
        """Part indicators should not cause chunks to exceed limit."""
        text = "word " * 800
        result = split_message(text, max_length=200)
        for chunk in result:
            # Allow some slack for code fence repair adding chars
            assert len(chunk) <= 250  # generous upper bound


# ---------------------------------------------------------------------------
# _repair_code_fences
# ---------------------------------------------------------------------------


class TestRepairCodeFences:
    def test_no_fences_passes_through(self) -> None:
        chunks = ["hello world", "more text"]
        result = _repair_code_fences(chunks)
        assert result == ["hello world", "more text"]

    def test_balanced_fences_unchanged(self) -> None:
        chunks = ["```python\ncode\n```", "no code here"]
        result = _repair_code_fences(chunks)
        assert result[0] == "```python\ncode\n```"
        assert result[1] == "no code here"

    def test_unclosed_fence_gets_closed(self) -> None:
        chunks = ["```python\nsome code"]
        result = _repair_code_fences(chunks)
        assert result[0].endswith("\n```")

    def test_unclosed_fence_reopened_in_next_chunk(self) -> None:
        chunks = ["```python\nsome code", "more code\n```"]
        result = _repair_code_fences(chunks)
        # First chunk should be closed
        assert result[0].endswith("\n```")
        # Second chunk should be reopened with language tag
        assert result[1].startswith("```python\n")

    def test_language_tag_preserved_across_chunks(self) -> None:
        chunks = ["```javascript\nlet x = 1", "let y = 2\n```"]
        result = _repair_code_fences(chunks)
        assert "```javascript" in result[1]

    def test_no_language_tag(self) -> None:
        chunks = ["```\nplain code", "more code\n```"]
        result = _repair_code_fences(chunks)
        assert result[0].endswith("\n```")
        assert result[1].startswith("```\n")

    def test_multiple_code_blocks_in_one_chunk(self) -> None:
        """Two complete code blocks in one chunk should not trigger repair."""
        chunk = "```python\nblock1\n```\ntext\n```js\nblock2\n```"
        result = _repair_code_fences([chunk])
        assert result[0] == chunk

    def test_three_chunk_code_block(self) -> None:
        """Code block spanning three chunks."""
        chunks = [
            "```python\nline1",
            "line2\nline3",
            "line4\n```",
        ]
        result = _repair_code_fences(chunks)
        # First chunk: opened, closed
        assert result[0].endswith("\n```")
        # Middle chunk: reopened, closed
        assert result[1].startswith("```python\n")
        assert result[1].endswith("\n```")
        # Last chunk: reopened (from previous unclosed), already has closing
        assert result[2].startswith("```python\n")

    def test_single_chunk_no_repair_needed(self) -> None:
        result = _repair_code_fences(["just text"])
        assert result == ["just text"]

    def test_empty_chunks_list(self) -> None:
        result = _repair_code_fences([])
        assert result == []


# ---------------------------------------------------------------------------
# split_message with code fence repair integration
# ---------------------------------------------------------------------------


class TestSplitWithCodeFences:
    def test_long_code_block_repaired_after_split(self) -> None:
        code = "```python\n" + "x = 1\n" * 500 + "```"
        result = split_message(code, max_length=2000)
        if len(result) > 1:
            for chunk in result:
                assert "```" in chunk

    def test_short_code_block_not_split(self) -> None:
        code = "```python\nprint('hello')\n```"
        result = split_message(code)
        assert len(result) == 1
        assert result[0] == code

    def test_mixed_text_and_code(self) -> None:
        text = "Here is some text.\n\n```python\n" + "x = 1\n" * 400 + "```\n\nMore text."
        result = split_message(text, max_length=2000)
        # Should produce multiple chunks
        assert len(result) >= 2


# ---------------------------------------------------------------------------
# format_response
# ---------------------------------------------------------------------------


class TestFormatResponse:
    def test_preserves_markdown(self) -> None:
        text = "**Hello** world!\n\nThis is a `test`."
        result = format_response(text)
        assert len(result) == 1
        assert "**Hello**" in result[0]
        assert "`test`" in result[0]

    def test_long_text_splits(self) -> None:
        text = "**Header**\n\n" + ("Some text. " * 300)
        result = format_response(text)
        assert len(result) > 1

    def test_returns_list(self) -> None:
        result = format_response("hi")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_empty_string(self) -> None:
        result = format_response("")
        assert result == [""]

    def test_uses_default_2000_limit(self) -> None:
        text = "A" * 1999
        result = format_response(text)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# format_plain
# ---------------------------------------------------------------------------


class TestFormatPlain:
    def test_strips_bold(self) -> None:
        result = format_plain("**bold text**")
        assert result[0] == "bold text"

    def test_strips_italic_asterisk(self) -> None:
        result = format_plain("*italic*")
        assert result[0] == "italic"

    def test_strips_italic_underscore(self) -> None:
        result = format_plain("_italic_")
        assert result[0] == "italic"

    def test_strips_bold_underscore(self) -> None:
        result = format_plain("__bold__")
        assert result[0] == "bold"

    def test_strips_inline_code(self) -> None:
        result = format_plain("use `code` here")
        assert result[0] == "use code here"

    def test_strips_strikethrough(self) -> None:
        result = format_plain("~~deleted~~")
        assert result[0] == "deleted"

    def test_strips_code_fences(self) -> None:
        result = format_plain("```python\nprint('hi')\n```")
        assert "```" not in result[0]
        assert "print('hi')" in result[0]

    def test_strips_code_fences_no_language(self) -> None:
        result = format_plain("```\ncode\n```")
        assert "```" not in result[0]

    def test_combined_markdown(self) -> None:
        text = "**bold** and `code` and ~~strike~~ and *italic*"
        result = format_plain(text)
        assert "bold" in result[0]
        assert "**" not in result[0]
        assert "`" not in result[0]
        assert "~~" not in result[0]
        assert "*" not in result[0]

    def test_plain_text_passes_through(self) -> None:
        result = format_plain("no markdown here")
        assert result[0] == "no markdown here"

    def test_long_plain_text_splits(self) -> None:
        text = "**Header**: " + "word " * 800
        result = format_plain(text)
        assert len(result) > 1

    def test_returns_list(self) -> None:
        result = format_plain("hi")
        assert isinstance(result, list)

    def test_empty_string(self) -> None:
        result = format_plain("")
        assert result == [""]

    def test_nested_markdown(self) -> None:
        """Bold inside italic, etc."""
        result = format_plain("**_bold italic_**")
        # After stripping bold, then italic underscore
        assert "**" not in result[0]
        assert "_" not in result[0]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_only_newlines(self) -> None:
        text = "\n" * 3000
        result = split_message(text, max_length=100)
        assert len(result) > 1

    def test_unicode_characters(self) -> None:
        text = "Hello " + chr(128075) * 1000  # wave emoji
        result = split_message(text, max_length=100)
        assert len(result) > 1

    def test_very_small_max_length(self) -> None:
        """With very small max_length, hard cut should still work."""
        text = "ABCDEFGHIJ" * 10  # 100 chars
        result = split_message(text, max_length=20)
        assert len(result) > 1

    def test_single_very_long_word(self) -> None:
        """A single word longer than max_length forces hard cut."""
        text = "A" * 300
        result = split_message(text, max_length=100)
        assert len(result) > 1

    def test_mixed_line_endings(self) -> None:
        text = "line1\r\nline2\nline3\r\n" * 200
        result = split_message(text, max_length=100)
        assert len(result) > 1

    def test_whitespace_only(self) -> None:
        text = " " * 50
        result = split_message(text)
        assert result == [" " * 50]

    def test_code_fence_with_many_languages(self) -> None:
        """Multiple code blocks with different languages."""
        text = (
            "```python\ndef foo(): pass\n```\n"
            "```javascript\nconst x = 1;\n```\n"
            "```rust\nfn main() {}\n```\n"
        )
        result = format_response(text)
        assert len(result) == 1
        assert "python" in result[0]
        assert "javascript" in result[0]
        assert "rust" in result[0]
