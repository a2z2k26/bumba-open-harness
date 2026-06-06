"""Message formatting and splitting for Discord (markdown-native).

D7.5 finding F-3: today's split fires *after* the model has been billed
for the full token output. D7.10 (#1422) adds a pre-emptive output-length
budget hint upstream so the model targets ≤1800 chars when channel=discord.

D7.5 finding F-1b → D7.7 #1419: this module is *mechanical* (split + fence
repair). Over-eager markdown / bullet-shaped prose in conversational replies
is a model-output concern, not a formatter concern — the fix lives in
`agent/config/system-prompt.md` Voice subsection ("default to prose; reach
for bullets only when the answer is genuinely list-shaped"). Do NOT add
voice/tone heuristics here; keep this module purely structural.
"""

from __future__ import annotations

import re
from bridge.dispatch_metrics import increment_module_counter

# Discord message limit
MAX_MESSAGE_LENGTH = 2000


def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    increment_module_counter("formatting.split_message", tier=0)
    """Split a message into chunks that fit Discord's limit.

    Split priority: paragraph break > newline > space > hard cut.
    Preserves code fences across chunks.
    Adds [1/N] part indicators when split.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Reserve space for part indicator "[XX/XX] "
        effective_max = max_length - 10

        # Try paragraph break
        cut = remaining.rfind("\n\n", 0, effective_max)
        if cut > 0:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 2:]
            continue

        # Try newline
        cut = remaining.rfind("\n", 0, effective_max)
        if cut > 0:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 1:]
            continue

        # Try space
        cut = remaining.rfind(" ", 0, effective_max)
        if cut > 0:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 1:]
            continue

        # Hard cut
        chunks.append(remaining[:effective_max])
        remaining = remaining[effective_max:]

    # Add part indicators if multiple chunks
    if len(chunks) > 1:
        total = len(chunks)
        chunks = [f"[{i + 1}/{total}] {chunk}" for i, chunk in enumerate(chunks)]

    return _repair_code_fences(chunks)


def _repair_code_fences(chunks: list[str]) -> list[str]:
    """Fix split code blocks by closing/reopening markdown fences across chunks."""
    repaired = []
    in_code_block = False
    fence_lang = ""

    for chunk in chunks:
        if in_code_block:
            chunk = f"```{fence_lang}\n{chunk}"

        # Count fence toggles to determine if chunk ends inside a code block
        fences = re.findall(r"```(\w*)", chunk)
        open_count = 0
        last_lang = ""
        for lang in fences:
            if open_count == 0:
                open_count += 1
                last_lang = lang
            else:
                open_count -= 1

        if open_count > 0:
            # Chunk ends with an unclosed code fence
            chunk = chunk + "\n```"
            in_code_block = True
            fence_lang = last_lang
        else:
            in_code_block = False
            fence_lang = ""

        repaired.append(chunk)

    return repaired


def format_response(text: str) -> list[str]:
    """Format response for Discord: split markdown at 2000 chars, repair fences."""
    return split_message(text)


def format_plain(text: str) -> list[str]:
    """Fallback: strip markdown formatting, split plain text."""
    clean = re.sub(r"```\w*\n?", "", text)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
    clean = re.sub(r"__(.+?)__", r"\1", clean)
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    clean = re.sub(r"_(.+?)_", r"\1", clean)
    clean = re.sub(r"~~(.+?)~~", r"\1", clean)
    return split_message(clean)
