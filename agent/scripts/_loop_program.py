"""Loop-as-markdown program definition for the experiment loop.

Concept-only port of karpathy/autoresearch's "loop-as-markdown" pattern.
The iteration body lives in `agent/config/experiment-program.md` so the
operator can tune objective, mutation surface, loop steps, and keep/discard
criteria without redeploying the Python orchestrator.

The Python side keeps:
- Budget gating, kernel integrity, OAuth, signal handling, DB writes,
  worktree creation, pytest invocation, plist supervision.
- A baked-in default ``LoopProgram`` that backs parse failures so a
  malformed markdown edit cannot brick the loop.

This module ships only the parser + prompt builders. The orchestrator
(``experiment_loop.py``) calls ``LoopProgram.from_markdown(PROGRAM_PATH)``
at the start of each iteration; subsequent ``proposal_prompt()`` and
``apply_prompt()`` calls assemble the literal strings handed to the
``claude -p`` subprocess.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("experiment-loop._loop_program")


REQUIRED_SECTIONS: tuple[str, ...] = (
    "Objective",
    "Mutation Surface",
    "Loop Steps",
    "Keep Criteria",
    "Discard Criteria",
    "Doctrine References",
    "NEVER STOP",
)


_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class LoopProgram:
    """Parsed representation of ``experiment-program.md``.

    Frozen so the loop cannot mutate program state mid-iteration; reload
    by calling ``from_markdown`` again at iteration start.
    """

    objective: str
    mutation_globs: tuple[str, ...]
    loop_steps: tuple[str, ...]
    keep_criteria: str
    discard_criteria: str
    doctrine_refs: tuple[str, ...]
    never_stop: str
    raw_markdown: str = field(default="", repr=False, compare=False)

    @classmethod
    def from_markdown(cls, path: Path) -> "LoopProgram":
        """Parse the program file. Falls back to the default on any error.

        The fallback path keeps the loop alive when the operator ships a
        broken edit; the warning is written to the loop's log so the
        operator notices on the next Discord notification.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning(
                "Could not read program at %s (%s) — using baked-in default",
                path,
                exc,
            )
            return _default_program()

        try:
            return cls._parse(text)
        except _LoopProgramParseError as exc:
            log.warning(
                "Program parse failed (%s) — using baked-in default. "
                "Fix %s and the next iteration picks up your edit.",
                exc,
                path,
            )
            return _default_program()

    @classmethod
    def _parse(cls, text: str) -> "LoopProgram":
        sections = _split_sections(text)
        missing = [name for name in REQUIRED_SECTIONS if name not in sections]
        if missing:
            raise _LoopProgramParseError(
                f"missing required sections: {', '.join(missing)}"
            )

        objective = sections["Objective"].strip()
        keep_criteria = sections["Keep Criteria"].strip()
        discard_criteria = sections["Discard Criteria"].strip()
        never_stop = sections["NEVER STOP"].strip()

        mutation_globs = tuple(_extract_bullets(sections["Mutation Surface"]))
        loop_steps = tuple(_extract_numbered(sections["Loop Steps"]))
        doctrine_refs = tuple(_extract_bullets(sections["Doctrine References"]))

        if not objective:
            raise _LoopProgramParseError("Objective section is empty")
        if not loop_steps:
            raise _LoopProgramParseError("Loop Steps has no numbered items")

        return cls(
            objective=objective,
            mutation_globs=mutation_globs,
            loop_steps=loop_steps,
            keep_criteria=keep_criteria,
            discard_criteria=discard_criteria,
            doctrine_refs=doctrine_refs,
            never_stop=never_stop,
            raw_markdown=text,
        )

    def proposal_prompt(self, history: list[dict]) -> str:
        """Build the prompt for the proposal subprocess.

        Equivalent to ``experiment_loop.pick_experiment``'s pre-port prompt
        construction at lines 242-249, but assembled from the markdown
        program rather than embedded literals.
        """
        history_text = ""
        if history:
            lines = ["", "## Recent Experiment History"]
            for h in history:
                lines.append(
                    f"- [{h.get('status', '?')}] {h.get('description', 'N/A')} "
                    f"(tests: {h.get('tests_passed', '?')}/{h.get('tests_total', '?')})"
                )
            history_text = "\n".join(lines) + "\n"

        return (
            f"{self.raw_markdown}\n"
            f"{history_text}\n"
            "IMPORTANT: You have NO tools available. Do NOT attempt to read or "
            "edit any files. Just output a text description of ONE specific, "
            "small code change to propose, consistent with the program above.\n\n"
            "Format your response exactly like this:\n"
            "FILE: <path relative to agent/>\n"
            "CHANGE: <what to do, in 2-3 sentences>\n"
        )

    def apply_prompt(self, description: str, forbidden_files: list[str]) -> str:
        """Build the prompt for the apply subprocess.

        Equivalent to ``experiment_loop.run_experiment``'s pre-port prompt
        construction at lines 311-319, but pulls mutation surface +
        never-stop directive from the markdown program.
        """
        surface = ", ".join(self.mutation_globs) if self.mutation_globs else "(see program)"
        forbidden = ", ".join(sorted(forbidden_files))
        return (
            "You are in a git worktree. Apply the following change:\n\n"
            f"{description}\n\n"
            "Rules:\n"
            f"- Mutation surface: {surface}\n"
            f"- Forbidden files: {forbidden}\n"
            "- Make the change and nothing else\n"
            "- Do not commit — just edit the files\n\n"
            f"Doctrine: {' / '.join(self.doctrine_refs) if self.doctrine_refs else '(none)'}\n"
            f"NEVER STOP: {self.never_stop}"
        )


class _LoopProgramParseError(ValueError):
    """Raised when the program markdown does not satisfy the contract."""


def _split_sections(text: str) -> dict[str, str]:
    """Split markdown into ``{heading: body}`` for ``## Heading`` blocks.

    H1 (``# ...``) is treated as the title and ignored. Body content
    after the final H2 runs to EOF.
    """
    matches = list(_HEADING_RE.finditer(text))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections[name] = text[start:end]
    return sections


def _extract_bullets(block: str) -> list[str]:
    """Extract bullet lines (``- item`` or ``* item``)."""
    items: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            items.append(stripped[2:].strip())
    return items


def _extract_numbered(block: str) -> list[str]:
    """Extract numbered lines (``1. item``, ``2. item``, ...)."""
    items: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if re.match(r"^\d+\.\s+", stripped):
            items.append(re.sub(r"^\d+\.\s+", "", stripped).strip())
    return items


def _default_program() -> LoopProgram:
    """Baked-in fallback when the markdown program cannot be parsed.

    Mirrors the historical embedded prompts so a parse failure leaves the
    loop running with pre-Sprint-02.01 behavior.
    """
    objective = (
        "Propose and implement ONE small, focused code change that improves "
        "the Bumba codebase. All existing tests must pass after the change."
    )
    mutation_globs = (
        "bridge/*.py",
        "bridge/services/*.py",
        "tests/*.py",
    )
    loop_steps = (
        "Read the recent experiment history and pick a target file consistent "
        "with the mutation surface.",
        "Propose ONE specific change in `FILE: <path>` / `CHANGE: <2-3 sentences>` "
        "format.",
        "Apply the change in the provided git worktree and stop — do not commit.",
    )
    keep_criteria = (
        "All existing tests pass; ruff stays clean; no forbidden file is touched."
    )
    discard_criteria = (
        "Any test fails, ruff regresses, or a forbidden file is modified."
    )
    doctrine_refs = (
        "CLAUDE.md#behavioral-doctrine",
        "CLAUDE.md#effectiveness-indicators",
    )
    never_stop = (
        "Do not pause for permission inside an iteration. If a step fails, "
        "log the failure and let the orchestrator handle the discard."
    )
    raw = (
        "# Experiment Program (default — markdown parse failed)\n\n"
        f"## Objective\n\n{objective}\n\n"
        "## Mutation Surface\n\n"
        + "\n".join(f"- {g}" for g in mutation_globs)
        + "\n\n## Loop Steps\n\n"
        + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(loop_steps))
        + f"\n\n## Keep Criteria\n\n{keep_criteria}\n\n"
        f"## Discard Criteria\n\n{discard_criteria}\n\n"
        "## Doctrine References\n\n"
        + "\n".join(f"- {r}" for r in doctrine_refs)
        + f"\n\n## NEVER STOP\n\n{never_stop}\n"
    )
    return LoopProgram(
        objective=objective,
        mutation_globs=mutation_globs,
        loop_steps=loop_steps,
        keep_criteria=keep_criteria,
        discard_criteria=discard_criteria,
        doctrine_refs=doctrine_refs,
        never_stop=never_stop,
        raw_markdown=raw,
    )
