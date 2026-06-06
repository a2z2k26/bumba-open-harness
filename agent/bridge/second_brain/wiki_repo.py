"""WikiRepo — read/write surface for the operator's Obsidian vault.

Sprint 05.03 (issue #1012) of the 2026-04-25 reference-audit bundle.
ADR sign-off: ``agent/docs/architecture/second-brain.md``
Decisions 1, 3, 5 (``__AZ__`` 2026-05-01).
Schema doc: ``agent/config/second-brain-schema.md`` (PR #1129, schema_version=1).

Why this exists
---------------
The second-brain subsystem needs ONE place that knows how to talk to
the operator's vault. Direct file I/O scattered across ingest, query,
lint, and operator commands invites mistakes — wrong path prefix, half-
written ``.md`` files, racing writes, missing frontmatter.

This module funnels every read/write through a single repo type:

- All Bumba writes are forced into ``bumba-contributions/staging/``
  or ``bumba-contributions/curated/`` (per ADR Decision 3 — hybrid
  quarantine, reversible by deleting the directory).
- Every write auto-attaches the schema-required YAML frontmatter
  (``source``, ``session_id``, ``authored_at``, ``provenance``,
  ``schema_version``).
- Writes are atomic (``<target>.tmp`` + ``os.replace``) so a crash mid-
  write never leaves a half-rendered ``.md`` file.
- An exclusive ``fcntl.flock`` is held for the duration of every write
  so two concurrent ``write()`` calls to the same file serialize
  cleanly.
- The operator-owned sections of ``index.md`` are never overwritten —
  only the auto-maintained "Bumba contributions (staged for review)"
  section is rewritten in place.

Concept-only port
-----------------
The wiki shape is informed by the Karpathy gist (no source copy —
``concept-only-no-license``). Specifically: a single repo type that
owns the markdown surface, with frontmatter as the lingua franca and
``index.md`` + ``log.md`` as durable narrative anchors.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .baseline import BaselineRecord

logger = logging.getLogger(__name__)


# Quarantine subtree prefixes (per ADR Decision 3). Written paths must
# begin with one of these — the path validator refuses anything else.
STAGING_PREFIX = "bumba-contributions/staging/"
CURATED_PREFIX = "bumba-contributions/curated/"

# Frontmatter ``source`` enum — must match second-brain-schema.md.
_VALID_SOURCES = frozenset({"ingest", "reflection", "consolidation", "daily_log"})

# Schema version this module emits. Bumps require an ADR addendum +
# migration script under ``second_brain/migrations/`` (per schema doc).
_CURRENT_SCHEMA_VERSION = 1

# Section heading inside index.md that Bumba auto-maintains. Operator-
# owned sections are everything else.
_BUMBA_INDEX_HEADING = "## Bumba contributions (staged for review)"

# How many trailing bytes ``append_log`` reads to detect a same-session
# duplicate line. 4 KiB is plenty for the most recent session header
# plus its bullets without re-reading the whole log.
_LOG_DEDUP_TAIL_BYTES = 4096


@dataclass(frozen=True)
class WikiNote:
    """A note staged or curated for the operator's vault.

    ``content_body`` is the markdown body **without** YAML frontmatter
    — :meth:`WikiRepo.write` regenerates frontmatter on every write so
    callers cannot accidentally drift the schema.
    """

    relpath: str
    content_body: str
    source: str
    session_id: str
    authored_at: str
    provenance: str
    schema_version: int = _CURRENT_SCHEMA_VERSION


@dataclass(frozen=True)
class WikiReadResult:
    """A note read from the vault — frontmatter parsed, body separate.

    ``frontmatter`` is an empty dict when the file has no frontmatter
    block. ``is_grandfathered`` is ``True`` either when a
    :class:`BaselineRecord` matched the file (operator-owned content
    that predates the schema) or when the read target itself is missing
    (callers handle the empty case uniformly).
    """

    relpath: str
    body: str
    frontmatter: dict[str, str | int]
    is_grandfathered: bool


@dataclass
class _IndexSections:
    """Parsed index.md sections — operator-owned + auto-maintained."""

    preamble: str
    operator_sections: list[str] = field(default_factory=list)
    has_bumba_section: bool = False


def _validate_relpath(relpath: str) -> str:
    """Reject relpaths that escape the quarantine subtree.

    Returns the validated relpath unchanged. Raises ``ValueError`` for
    anything outside ``bumba-contributions/{staging,curated}/`` or any
    path traversal attempt.
    """
    if not relpath:
        raise ValueError("relpath must be non-empty")
    if relpath.startswith("/"):
        raise ValueError(f"relpath must be relative, got absolute: {relpath!r}")
    if "\\" in relpath:
        # Windows-style separators in a posix vault are almost always a
        # traversal probe. Refuse.
        raise ValueError(f"relpath must use forward slashes: {relpath!r}")
    parts = relpath.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"relpath must not contain '.' or '..': {relpath!r}")
    if not (
        relpath.startswith(STAGING_PREFIX) or relpath.startswith(CURATED_PREFIX)
    ):
        raise ValueError(
            f"relpath must start with {STAGING_PREFIX!r} or "
            f"{CURATED_PREFIX!r}, got {relpath!r}",
        )
    return relpath


def _resolve_inside_vault(vault_root: Path, relpath: str) -> Path:
    """Resolve ``relpath`` to an absolute path inside ``vault_root``.

    Refuses any resolved path that escapes the vault — protects against
    symlink traversal that bypasses the textual ``..`` check.
    """
    target = (vault_root / relpath).resolve()
    vault_resolved = vault_root.resolve()
    try:
        target.relative_to(vault_resolved)
    except ValueError as exc:
        raise ValueError(
            f"resolved path {target} escapes vault root {vault_resolved}",
        ) from exc
    return target


def _format_frontmatter(note: WikiNote) -> str:
    """Render a :class:`WikiNote`'s schema-required frontmatter block.

    Output ends with a single trailing newline so the body can be
    appended directly. Values are emitted verbatim (callers control
    quoting via free-form prose; YAML special chars in single-line
    fields are tolerated by Obsidian's parser).
    """
    if note.source not in _VALID_SOURCES:
        raise ValueError(
            f"source must be one of {sorted(_VALID_SOURCES)}, got {note.source!r}",
        )
    if not note.session_id:
        raise ValueError("session_id must be non-empty")
    if not note.authored_at:
        raise ValueError("authored_at must be non-empty")
    if not note.provenance:
        raise ValueError("provenance must be non-empty")
    if "\n" in note.provenance:
        raise ValueError("provenance must be single-line")
    lines = [
        "---",
        f"source: {note.source}",
        f"session_id: {note.session_id}",
        f"authored_at: {note.authored_at}",
        f"provenance: {note.provenance}",
        f"schema_version: {note.schema_version}",
        "---",
        "",
    ]
    return "\n".join(lines)


def _split_frontmatter(text: str) -> tuple[dict[str, str | int], str]:
    """Parse a YAML-frontmatter block off the head of ``text``.

    Returns ``(frontmatter_dict, body)``. If ``text`` does not begin
    with a ``---`` fence, returns ``({}, text)``. The parser is
    intentionally minimal — single ``key: value`` lines, no nesting,
    no quoted strings (the schema doc constrains values to single-line
    primitives, so this matches the contract exactly).
    """
    if not text.startswith("---"):
        return {}, text
    # Split into at most three parts: pre-fence (empty), block, body.
    rest = text[3:]
    # Tolerate either ``\n`` or ``\r\n`` after the opening fence.
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    else:
        # Opening fence not followed by a newline — not a real block.
        return {}, text
    closing = rest.find("\n---")
    if closing == -1:
        # Unterminated frontmatter block. Treat as no frontmatter; the
        # lint subsystem (Sprint 05.09) will flag this as malformed.
        return {}, text
    block = rest[:closing]
    after = rest[closing + len("\n---"):]
    # Strip the line terminator after the closing fence.
    if after.startswith("\r\n"):
        after = after[2:]
    elif after.startswith("\n"):
        after = after[1:]
    fm: dict[str, str | int] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            # Malformed line — skip but do not abort. Lint will catch.
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key == "schema_version":
            try:
                fm[key] = int(value)
            except ValueError:
                fm[key] = value
        else:
            fm[key] = value
    return fm, after


def _atomic_write_locked(target: Path, contents: str) -> None:
    """Write ``contents`` to ``target`` atomically under an exclusive lock.

    Strategy:

    1. Take an exclusive ``fcntl.flock`` on a sibling ``.<name>.lock``
       sentinel. The sentinel survives the rename — locking the target
       directly would race because ``os.replace`` swaps inodes out from
       under the lock.
    2. Write contents to ``<target>.tmp`` via ``mkstemp`` in the target
       directory (same filesystem so ``os.replace`` is atomic).
    3. ``fsync`` the tmp file, then ``os.replace`` it onto ``target``.
    4. Best-effort ``fsync`` the target directory so the rename is
       durable across power loss.

    Lock release happens in the ``finally`` of the context manager
    regardless of how the body exits, including exceptions.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(target):
        fd, tmp_name = tempfile.mkstemp(
            prefix="." + target.name + ".",
            suffix=".tmp",
            dir=str(target.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(contents)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
            _fsync_dir(target.parent)
        except BaseException:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise


def _fsync_dir(directory: Path) -> None:
    """Best-effort ``fsync`` on a directory entry. Swallows EINVAL on FSes
    that don't support directory fsync (e.g. some network mounts)."""
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            if exc.errno != errno.EINVAL:
                # EINVAL on fsync(directory) is platform/FS dependent;
                # any other errno is worth surfacing.
                logger.debug("fsync(dir) failed: %s", exc)
    finally:
        os.close(dir_fd)


@contextmanager
def _exclusive_lock(target: Path):
    """Acquire an exclusive ``fcntl.flock`` on a sentinel beside ``target``.

    The sentinel path is ``<target_dir>/.<target_name>.lock``. The
    sentinel file is created on demand and left in place; deleting it
    would race with another process trying to lock it. The lock itself
    is released by closing the file descriptor in ``finally``.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / f".{target.name}.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        # flock is automatically released on close, but be explicit so
        # a misconfigured filesystem (NFS) without close-implies-unlock
        # still does the right thing.
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _parse_index_sections(text: str) -> _IndexSections:
    """Split ``index.md`` into preamble + sections.

    The preamble is everything before the first ``## `` heading.
    Each section is the heading line plus its body up to the next
    ``## `` heading (or EOF). The Bumba-managed section is identified
    by exact heading match against :data:`_BUMBA_INDEX_HEADING`.
    """
    lines = text.splitlines(keepends=True)
    preamble_lines: list[str] = []
    sections: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## "):
            if current is None:
                # Transition from preamble to first section.
                pass
            else:
                sections.append(current)
            current = [line]
            continue
        if current is None:
            preamble_lines.append(line)
        else:
            current.append(line)
    if current is not None:
        sections.append(current)

    operator_sections: list[str] = []
    has_bumba = False
    for section in sections:
        heading = section[0].rstrip("\r\n")
        if heading == _BUMBA_INDEX_HEADING:
            has_bumba = True
            continue
        operator_sections.append("".join(section))
    return _IndexSections(
        preamble="".join(preamble_lines),
        operator_sections=operator_sections,
        has_bumba_section=has_bumba,
    )


def _format_index_bumba_section(staging_relpaths: list[str]) -> str:
    """Render the auto-maintained Bumba-contributions section."""
    out = [_BUMBA_INDEX_HEADING + "\n"]
    if not staging_relpaths:
        out.append("- _(no notes pending operator review)_\n")
    else:
        for relpath in sorted(staging_relpaths):
            out.append(f"- [[{relpath}]] — operator review pending\n")
    return "".join(out)


class WikiRepo:
    """Read/write interface to the operator's Obsidian vault.

    Every write is path-validated, frontmatter-stamped, atomically
    rendered, and protected by an exclusive ``fcntl.flock``. Reads are
    plain (markdown is read-mostly; locking on read would block lint
    behind operator edits without buying anything).
    """

    STAGING_PREFIX: str = STAGING_PREFIX
    CURATED_PREFIX: str = CURATED_PREFIX
    CURRENT_SCHEMA_VERSION: int = _CURRENT_SCHEMA_VERSION

    def __init__(
        self,
        vault_root: Path,
        baseline: dict[Path, BaselineRecord] | None = None,
    ):
        """Bind a repo to ``vault_root``.

        Args:
            vault_root: Absolute path to the operator's Obsidian vault.
                Must exist and be a directory.
            baseline: Optional output of
                :func:`second_brain.baseline.load_baseline`. When
                provided, :meth:`read` consults it to flag operator-owned
                files that predate the schema.

        Raises:
            FileNotFoundError: vault_root does not exist.
            NotADirectoryError: vault_root exists but is not a directory.
        """
        vault_root = Path(vault_root)
        if not vault_root.exists():
            raise FileNotFoundError(f"vault_root does not exist: {vault_root}")
        if not vault_root.is_dir():
            raise NotADirectoryError(
                f"vault_root is not a directory: {vault_root}",
            )
        self._vault_root = vault_root
        self._baseline = baseline or {}

    @property
    def vault_root(self) -> Path:
        """Absolute path to the bound vault."""
        return self._vault_root

    # ---------------- read paths ---------------- #

    def read(self, relpath: str) -> WikiReadResult:
        """Read a vault note, parsing frontmatter off the head.

        Raises:
            FileNotFoundError: the note does not exist.
        """
        target = self._resolve(relpath)
        if not target.is_file():
            raise FileNotFoundError(f"vault note not found: {relpath}")
        text = target.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(text)
        is_grandfathered = self._is_grandfathered(target, frontmatter)
        return WikiReadResult(
            relpath=relpath,
            body=body,
            frontmatter=frontmatter,
            is_grandfathered=is_grandfathered,
        )

    def read_index(self) -> WikiReadResult:
        """Read ``vault/index.md``.

        Returns an empty result with ``is_grandfathered=True`` if the
        file is missing — the schema doc explicitly allows the operator
        to defer seeding ``index.md``.
        """
        target = self._vault_root / "index.md"
        if not target.is_file():
            return WikiReadResult(
                relpath="index.md",
                body="",
                frontmatter={},
                is_grandfathered=True,
            )
        text = target.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(text)
        # ``index.md`` is operator-owned at the file level; it carries no
        # frontmatter and is grandfathered iff the baseline says so or
        # if frontmatter is absent (the common case).
        is_grandfathered = self._is_grandfathered(target, frontmatter)
        return WikiReadResult(
            relpath="index.md",
            body=body,
            frontmatter=frontmatter,
            is_grandfathered=is_grandfathered,
        )

    def list_staging(self) -> list[str]:
        """Relpaths of every ``.md`` under ``bumba-contributions/staging/``."""
        return self._list_under(STAGING_PREFIX)

    def list_curated(self) -> list[str]:
        """Relpaths of every ``.md`` under ``bumba-contributions/curated/``."""
        return self._list_under(CURATED_PREFIX)

    # ---------------- write paths ---------------- #

    def write(self, note: WikiNote) -> Path:
        """Atomically write a Bumba-authored note.

        Auto-prepends YAML frontmatter; refuses any path outside the
        quarantine subtree; refuses ``..`` traversal and absolute paths.

        Returns:
            The absolute file path written.

        Raises:
            ValueError: relpath outside ``bumba-contributions/`` or
                contains a traversal token, or frontmatter fields are
                missing/invalid.
        """
        relpath = _validate_relpath(note.relpath)
        target = self._resolve(relpath)
        # Body separator: ensure exactly one blank line between
        # frontmatter close and body content. If the body already
        # starts with a newline, don't double up.
        body = note.content_body
        if body and not body.endswith("\n"):
            body = body + "\n"
        contents = _format_frontmatter(note) + body
        _atomic_write_locked(target, contents)
        logger.info("wiki write: %s (source=%s)", relpath, note.source)
        return target

    def append_knowledge(
        self,
        *,
        key: str,
        value: str,
        tier: str,
        category: str = "reference",
        metadata: dict[str, object] | None = None,
    ) -> str:
        """Append a single knowledge entry to the operator's vault.

        Sprint Mem-4.5 (issue #1867) — single-entry adapter consumed by
        :class:`bridge.advanced_memory.destinations.SecondBrainDestination`.
        The DualWritePipeline calls this on every PREFERENCE-tier knowledge
        write when ``memory_tiers_enabled = true``.

        Per-entry files (one ``.md`` per knowledge entry) give the operator
        a clean review surface in Obsidian. Per-tier append-log was the
        alternative but is less debuggable.

        The output sits under the existing ``bumba-contributions/staging/``
        quarantine subtree at ``staging/memory-tier/{tier}/{date}-{slug}.md``
        so the operator can mass-promote or mass-reject memory-tier
        contributions independently of daily-log / reflection /
        consolidation streams.

        Frontmatter carries ``source: ingest`` (the closest valid value in
        the schema enum — Bumba-authored), ``provenance:
        memory-tier-dual-write`` (the semantic signal for promote/lint
        tooling), and free-form metadata items as flat top-level keys.

        Args:
            key: The operator-supplied key of the knowledge entry.
                Used both as the slug source for the relpath and as a
                frontmatter field.
            value: The body of the knowledge entry. Written verbatim
                after the frontmatter block.
            tier: Memory-tier label (``"preference"`` / ``"decision"`` /
                ``"context"``). Becomes a frontmatter field and a path
                segment.
            category: Knowledge category (``"preference"`` / ``"decision"``
                / ``"reference"``). Becomes a frontmatter field.
            metadata: Optional flat metadata dict; serialized as flat
                top-level frontmatter keys. Non-serializable items are
                skipped with a debug log.

        Returns:
            The relpath written to (relative to the vault root).

        Raises:
            ValueError: ``key`` is empty or contains only invalid slug
                characters.
        """
        import re
        from datetime import datetime, timezone

        if not key:
            raise ValueError("key must be non-empty")

        now = datetime.now(timezone.utc)
        date = now.strftime("%Y-%m-%d")
        # Replace ``:`` / ``/`` / whitespace with ``-``; allow ASCII
        # letters, digits, underscore, hyphen. Trim to 80 chars so the
        # filename stays well under POSIX 255 even with the date prefix.
        key_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", key).strip("-")[:80]
        if not key_slug:
            raise ValueError(f"key {key!r} produces an empty slug")
        # Per ADR Decision 3 — every Bumba write lands under
        # ``bumba-contributions/staging/`` or ``bumba-contributions/curated/``.
        # ``_validate_relpath`` (called by :meth:`write` below) enforces this.
        relpath = (
            f"{STAGING_PREFIX}memory-tier/{tier}/{date}-{key_slug}.md"
        )

        # Build the body. Frontmatter lives in ``WikiNote.content_body``
        # ONLY as an additional human-readable header — the structural
        # frontmatter that :meth:`write` regenerates is the schema-mandated
        # one (source/session_id/authored_at/provenance/schema_version).
        # We add a SECOND frontmatter-like block below the structural one
        # by inlining ``tier:`` + ``category:`` + ``key:`` + flattened
        # metadata at the top of the body. Obsidian shows this as
        # markdown text, not parsed frontmatter — that's fine, the
        # structural frontmatter is what tooling reads.
        md = metadata or {}
        header_lines: list[str] = [
            f"**tier:** {tier}",
            f"**category:** {category}",
            f"**key:** `{key}`",
        ]
        if md:
            header_lines.append("")
            header_lines.append("**metadata:**")
            for k in sorted(md.keys()):
                v = md[k]
                # Single-line stringification only. Multi-line / complex
                # values get repr'd to keep the markdown readable.
                try:
                    s = str(v)
                except Exception:  # noqa: BLE001 — defensive
                    logger.debug(
                        "append_knowledge: skipping non-stringifiable "
                        "metadata key %r",
                        k,
                    )
                    continue
                if "\n" in s:
                    s = repr(s)
                header_lines.append(f"- `{k}`: {s}")
        header_block = "\n".join(header_lines)
        content_body = header_block + "\n\n" + value

        # ``source`` enum is constrained to {ingest, reflection,
        # consolidation, daily_log} — see ``_VALID_SOURCES``. Bumba-
        # authored memory-tier writes are closest to "ingest"; the
        # semantic signal lives in ``provenance``.
        session_id = ""
        if isinstance(md, dict):
            sess = md.get("session_id", "")
            if isinstance(sess, str) and sess:
                session_id = sess
        if not session_id:
            session_id = "memory-tier-dual-write"

        note = WikiNote(
            relpath=relpath,
            content_body=content_body,
            source="ingest",
            session_id=session_id,
            authored_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            provenance="memory-tier-dual-write",
        )
        self.write(note)
        return relpath

    def append_log(self, line: str) -> None:
        """Append a line to ``vault/log.md`` under the current session header.

        - Same-line dedup: if the bottom of the log already contains
          ``line``, no-op (idempotent re-append within a session).
        - Session header: per the schema doc, each write session emits
          ``## YYYY-MM-DD HH:MM — session <id>`` once. The line argument
          is expected to be a body bullet OR a full session header (the
          caller decides; this method just appends).

        File-locked via the same sentinel-flock pattern as :meth:`write`
        so concurrent appends serialize.
        """
        if not line:
            raise ValueError("line must be non-empty")
        if "\n" in line.rstrip("\n"):
            raise ValueError("line must be single-line (no embedded newlines)")
        normalized = line if line.endswith("\n") else line + "\n"
        target = self._vault_root / "log.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_lock(target):
            existing = b""
            if target.exists():
                with target.open("rb") as fh:
                    fh.seek(0, os.SEEK_END)
                    size = fh.tell()
                    fh.seek(max(0, size - _LOG_DEDUP_TAIL_BYTES))
                    existing = fh.read()
            tail = existing.decode("utf-8", errors="replace")
            if normalized.strip() and normalized in tail:
                logger.debug("append_log: dedup hit, skipping %r", line)
                return
            with target.open("a", encoding="utf-8") as fh:
                fh.write(normalized)
                fh.flush()
                os.fsync(fh.fileno())

    def update_index_staging_section(
        self,
        staging_relpaths: list[str],
    ) -> None:
        """Rewrite the ``Bumba contributions`` section of ``index.md`` in place.

        Operator-owned sections (``## Active threads``, ``## Reference
        docs``, etc.) are preserved verbatim. If the Bumba-managed
        section does not yet exist, it is appended to the end. If
        ``index.md`` does not exist, a minimal file is created with
        only the Bumba section (the operator can later pre-pend their
        own sections; their sections will be preserved on the next call).
        """
        target = self._vault_root / "index.md"
        with _exclusive_lock(target):
            if target.is_file():
                text = target.read_text(encoding="utf-8")
                parsed = _parse_index_sections(text)
            else:
                parsed = _IndexSections(preamble="", operator_sections=[])

            bumba_section = _format_index_bumba_section(staging_relpaths)
            # Ensure operator sections are joined with consistent spacing.
            # Each operator section already ends with the leading newline
            # of the next section (or EOF).
            preamble = parsed.preamble
            if preamble and not preamble.endswith("\n"):
                preamble += "\n"

            chunks: list[str] = []
            if preamble:
                chunks.append(preamble)
            for sec in parsed.operator_sections:
                # Guarantee a blank line before each section heading.
                if chunks and not chunks[-1].endswith("\n\n"):
                    if chunks[-1].endswith("\n"):
                        chunks.append("\n")
                    else:
                        chunks.append("\n\n")
                chunks.append(sec.rstrip("\n") + "\n")
            # Bumba section last so the operator's narrative sections
            # stay near the top.
            if chunks and not chunks[-1].endswith("\n\n"):
                if chunks[-1].endswith("\n"):
                    chunks.append("\n")
                else:
                    chunks.append("\n\n")
            chunks.append(bumba_section)

            new_text = "".join(chunks)
            # Reuse the atomic-write mechanics, but the lock is already
            # held — write directly via mkstemp+replace inside the lock.
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix="." + target.name + ".",
                suffix=".tmp",
                dir=str(target.parent),
            )
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(new_text)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, target)
                _fsync_dir(target.parent)
            except BaseException:
                try:
                    tmp_path.unlink()
                except FileNotFoundError:
                    pass
                raise

    # ---------------- session header helper ---------------- #

    @staticmethod
    def format_session_header(session_id: str, when: datetime | None = None) -> str:
        """Render a ``log.md`` session header per the schema doc."""
        if not session_id:
            raise ValueError("session_id must be non-empty")
        ts = when if when is not None else datetime.now()
        return f"## {ts.strftime('%Y-%m-%d %H:%M')} — session {session_id}"

    # ---------------- internals ---------------- #

    def _resolve(self, relpath: str) -> Path:
        """Resolve a relpath inside the vault, refusing escapes."""
        # ``relpath`` here can be a quarantine path or a top-level file
        # like ``index.md`` / ``log.md``. The quarantine prefix check
        # belongs in :meth:`write`, not here.
        if relpath.startswith("/"):
            raise ValueError(f"relpath must be relative: {relpath!r}")
        if "\\" in relpath:
            raise ValueError(f"relpath must use forward slashes: {relpath!r}")
        for part in relpath.split("/"):
            if part in ("", ".", ".."):
                raise ValueError(f"relpath must not contain '.' or '..': {relpath!r}")
        return _resolve_inside_vault(self._vault_root, relpath)

    def _list_under(self, prefix: str) -> list[str]:
        """Return relpaths of every ``.md`` under ``<vault>/<prefix>``."""
        root = self._vault_root / prefix
        if not root.is_dir():
            return []
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fname in sorted(filenames):
                if fname.startswith(".") or not fname.endswith(".md"):
                    continue
                full = Path(dirpath) / fname
                rel = full.relative_to(self._vault_root).as_posix()
                out.append(rel)
        return sorted(out)

    def _is_grandfathered(
        self,
        target: Path,
        frontmatter: dict[str, str | int],
    ) -> bool:
        """Decide whether ``target`` is grandfathered.

        A file is grandfathered when (a) it carries no schema frontmatter
        AND (b) the baseline records this exact path (the baseline
        ingest only walked operator-owned content, so a baseline match
        is a strong signal). Files inside ``bumba-contributions/`` are
        Bumba-authored and therefore never grandfathered, regardless of
        baseline contents.
        """
        try:
            rel = target.resolve().relative_to(self._vault_root.resolve()).as_posix()
        except ValueError:
            return False
        if rel.startswith(STAGING_PREFIX) or rel.startswith(CURATED_PREFIX):
            return False
        if frontmatter:
            return False
        if not self._baseline:
            # No baseline supplied — best we can say about an unknown
            # file is "operator-owned, no schema yet". Treating it as
            # grandfathered keeps lint quiet on operator content the
            # caller did not explicitly opt in to validating.
            return True
        return target.resolve() in {p.resolve() for p in self._baseline}
