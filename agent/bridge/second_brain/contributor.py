"""Second-brain contributor protocol — Sprint 05.04.

Defines the abstract ``SecondBrainContributor`` Protocol for any module
that wants to contribute notes to the operator's second-brain wiki, plus
an in-memory ``ContributorRegistry`` and the ``ensure_subtree`` helper
that creates the ``bumba-contributions/`` quarantine directory.

ADR Decision 3 (signed 2026-05-01, see
``agent/docs/architecture/second-brain.md``): Bumba never writes to
canonical pages directly. All Bumba contributions land in
``bumba-contributions/staging/`` (daily_log, reflection) or
``bumba-contributions/curated/`` (consolidation outputs). Operator
promotes via ``/promote`` (Sprint 05.10) or rejects via ``/reject_wiki``.

Schema (per PR #1129, ``agent/config/second-brain-schema.md``):
Bumba-authored notes carry YAML frontmatter with
``source: <ingest|reflection|consolidation|daily_log>``. Operator-edited
content drops the ``source`` field — that absence is the signal of
operator ownership.

This sprint ships **interface + wiring only**. Specific contributors
(daily_log, reflection, consolidation, ingest) wire in later sprints
(05.05, 05.06, 05.07, 05.11).

Concept-only port — no source copied (Karpathy gist informs the
markdown-wiki shape; nothing copied verbatim).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

ContributorSource = Literal["ingest", "reflection", "consolidation", "daily_log"]
"""Allowed values for ``Contribution.source`` — matches the schema doc."""

ContributorDestination = Literal["staging", "curated"]
"""Quarantine subdirectory under ``bumba-contributions/``.

- ``staging`` for new contributions awaiting operator review (daily_log,
  reflection, ingest).
- ``curated`` for consolidation outputs already curated by Bumba's
  consolidation pipeline.
"""


@dataclass(frozen=True)
class Contribution:
    """A proposed wiki note before it has been written to the vault.

    Contributors emit ``Contribution`` instances; the second-brain
    subsystem (later sprint) is responsible for writing them with
    correct YAML frontmatter to ``relpath`` under the vault root.

    Attributes:
        relpath: Path relative to the vault root. MUST start with
            ``bumba-contributions/<destination>/`` to honor ADR
            Decision 3 (hybrid quarantine — never write to canonical).
        body: Markdown body WITHOUT YAML frontmatter. The frontmatter
            block is added by the writer using ``source`` + provenance
            below.
        source: One of the four allowed source kinds (matches schema).
        destination: ``staging`` or ``curated``; must agree with the
            second segment of ``relpath``.
        session_id: Originating session id (for provenance + audit).
        authored_at: ISO8601 UTC timestamp when the contribution was
            produced by the contributor.
        provenance: Free-form one-line provenance string (e.g.
            "daily_log 2026-05-01 22:13:55 UTC", "reflection week-18").
    """

    relpath: str
    body: str
    source: ContributorSource
    destination: ContributorDestination
    session_id: str
    authored_at: str
    provenance: str


@runtime_checkable
class SecondBrainContributor(Protocol):
    """Any module that writes to the second-brain wiki implements this.

    Implementations MUST:
    - emit ``Contribution`` instances to
      ``bumba-contributions/staging/`` or ``bumba-contributions/curated/``,
      never to canonical paths.
    - never mutate operator-canonical content.
    - return ``[]`` when no contribution this cycle (a no-op is a
      valid state — do not raise).

    The Protocol is ``runtime_checkable`` so registries and tests can
    assert structural conformance via ``isinstance(obj, ...)``.
    """

    @property
    def contributor_name(self) -> str:
        """Stable identifier for this contributor (e.g. ``"daily_log"``)."""
        ...

    def collect(self, since: str | None) -> list[Contribution]:
        """Collect contributions since the given ISO8601 timestamp.

        Returns ``[]`` when no new content is available.
        ``since=None`` means a full sweep — the contributor returns
        every contribution it knows about. Implementations should not
        raise on a no-op cycle.
        """
        ...


class ContributorRegistry:
    """In-memory registry of second-brain contributors.

    Stable iteration order: ``all()`` and ``collect_all()`` return
    contributors sorted by ``contributor_name`` so wiring order does
    not influence behaviour.
    """

    def __init__(self) -> None:
        self._contribs: dict[str, SecondBrainContributor] = {}

    def register(self, contributor: SecondBrainContributor) -> None:
        """Register a contributor by ``contributor_name``.

        Raises:
            ValueError: a contributor with the same name is already
                registered. The caller must explicitly de-register
                before re-registering — silent overwrite is a footgun.
        """
        name = contributor.contributor_name
        if name in self._contribs:
            raise ValueError(
                f"Contributor already registered: {name!r}. "
                "Call .clear() or use a different contributor_name."
            )
        # Immutable update of the inner mapping.
        self._contribs = {**self._contribs, name: contributor}

    def all(self) -> list[SecondBrainContributor]:
        """All registered contributors, sorted by ``contributor_name``."""
        return [self._contribs[name] for name in sorted(self._contribs)]

    def collect_all(self, since: str | None = None) -> list[Contribution]:
        """Run ``collect()`` on every registered contributor.

        Flattens results into a single list. ``since=None`` triggers
        a full sweep on every contributor.
        """
        out: list[Contribution] = []
        for contrib in self.all():
            out.extend(contrib.collect(since))
        return out

    def clear(self) -> None:
        """Drop every registered contributor (test helper)."""
        self._contribs = {}


_SUBTREE_README = """\
# Bumba Contributions

This directory is auto-managed by the Bumba bridge. Do not edit.

- **staging/** — new contributions awaiting operator review.
- **curated/** — consolidation outputs (already curated by Bumba's consolidation pipeline).

Promote a staged note to canonical via `/promote <path>`. Reject via `/reject_wiki <path>`.

See `agent/config/second-brain-schema.md` for the schema convention.
"""


def ensure_subtree(vault_root: Path) -> None:
    """Create ``bumba-contributions/staging/`` + ``curated/`` if missing.

    Idempotent: re-running on a vault that already has the subtree is a
    no-op (no exception, no overwrite of an existing README).

    Adds ``bumba-contributions/README.md`` explaining the directory's
    purpose so a casual vault inspection makes the convention obvious.

    The function never touches anything above ``bumba-contributions/`` —
    operator-canonical content is preserved verbatim.

    Raises:
        FileNotFoundError: ``vault_root`` does not exist. The caller is
            responsible for ensuring the vault path is valid before
            calling (the second-brain subsystem stays disabled when the
            configured vault root is empty or missing).
    """
    if not vault_root.exists():
        raise FileNotFoundError(
            f"vault_root does not exist: {vault_root}"
        )
    base = vault_root / "bumba-contributions"
    base.mkdir(parents=True, exist_ok=True)
    (base / "staging").mkdir(parents=True, exist_ok=True)
    (base / "curated").mkdir(parents=True, exist_ok=True)
    readme = base / "README.md"
    if not readme.exists():
        readme.write_text(_SUBTREE_README, encoding="utf-8")


__all__ = [
    "Contribution",
    "ContributorDestination",
    "ContributorRegistry",
    "ContributorSource",
    "SecondBrainContributor",
    "ensure_subtree",
]
