"""Promote / reject helpers for staged Bumba contributions.

Sprint 05.10 (issue #1020) of the 2026-04-25 reference-audit bundle.
ADR sign-off: ``agent/docs/architecture/second-brain.md`` Decision 3
(``__AZ__`` 2026-05-01) — hybrid quarantine. Bumba writes to
``bumba-contributions/staging/`` and ``bumba-contributions/curated/``;
the operator promotes a staged note to canonical (vault root) via
``/promote`` or rejects it via ``/reject_wiki``.

Why this exists
---------------
The operator commands in :mod:`bridge.commands` need a small,
test-friendly helper that can:

- Read a staged or curated note from ``bumba-contributions/``.
- Strip the schema-required YAML frontmatter (operator-canonical
  content drops ``source`` per the schema doc).
- Atomically write the body to a destination relpath at vault root.
- Remove the staging copy (so re-promotion is a no-op).
- Append a one-line entry to ``log.md``.
- Reject (delete + log + optional rejection signal).

Both helpers are pure-function-shaped: they take a ``WikiRepo``-shaped
collaborator + the source/destination args and return frozen dataclass
results. The command handlers handle Discord-side formatting and the
operator-tier permission check.

Concept-only port — no source copied (Karpathy gist informs the
markdown-wiki shape; nothing copied verbatim). License: NO LICENSE.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Quarantine prefixes — kept in lock-step with WikiRepo constants. We
# do NOT import them from .wiki_repo because callers may pass any
# object with the WikiRepo public surface; keeping these literals here
# makes the helper independent of the import site for tests.
_STAGING_PREFIX = "bumba-contributions/staging/"
_CURATED_PREFIX = "bumba-contributions/curated/"


@dataclass(frozen=True)
class PromoteResult:
    """Outcome of one ``promote_note`` invocation.

    Attributes:
        source_relpath: The staging/curated relpath that was promoted.
        destination_relpath: The vault-root relpath the body was written to.
        bytes_written: Length (in bytes) of the body actually written. 0
            when the call was a no-op (already promoted).
        already_promoted: True iff the destination already existed with
            byte-identical content; the call was a no-op.
        log_entry: The single log line written to ``log.md`` (or the
            line that *would* have been written when ``already_promoted``
            is True — kept for caller telemetry).
    """

    source_relpath: str
    destination_relpath: str
    bytes_written: int
    already_promoted: bool
    log_entry: str


@dataclass(frozen=True)
class RejectResult:
    """Outcome of one ``reject_note`` invocation.

    Attributes:
        source_relpath: The staging/curated relpath that was targeted.
        reason: The free-form rejection reason supplied by the operator
            (or None if not supplied).
        log_entry: The single log line written to ``log.md``.
        deleted: True iff the file was actually deleted; False iff the
            file was already absent (idempotent no-op).
    """

    source_relpath: str
    reason: Optional[str]
    log_entry: str
    deleted: bool


def strip_frontmatter(body_with_frontmatter: str) -> str:
    """Remove a leading YAML frontmatter block.

    Pure function. If ``body_with_frontmatter`` does not begin with a
    ``---`` fence, the input is returned unchanged. Mirrors the contract
    of :func:`bridge.second_brain.wiki_repo._split_frontmatter` but
    returns only the body — the frontmatter dict is irrelevant for
    promotion (operator-canonical content drops ``source`` per the
    schema doc, so we just throw the block away).
    """
    if not body_with_frontmatter.startswith("---"):
        return body_with_frontmatter
    rest = body_with_frontmatter[3:]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    else:
        # Opening fence not followed by newline — not a real frontmatter
        # block; treat the input as plain body.
        return body_with_frontmatter
    closing = rest.find("\n---")
    if closing == -1:
        # Unterminated frontmatter — treat as plain body so the operator
        # at least sees something on /promote rather than a silent drop.
        return body_with_frontmatter
    after = rest[closing + len("\n---"):]
    if after.startswith("\r\n"):
        after = after[2:]
    elif after.startswith("\n"):
        after = after[1:]
    return after


def _validate_quarantine_relpath(relpath: str) -> None:
    """Refuse anything outside the quarantine subtree."""
    if not relpath:
        raise ValueError("source_relpath must be non-empty")
    if relpath.startswith("/"):
        raise ValueError(
            f"source_relpath must be relative, got absolute: {relpath!r}"
        )
    if not (
        relpath.startswith(_STAGING_PREFIX)
        or relpath.startswith(_CURATED_PREFIX)
    ):
        raise ValueError(
            f"source_relpath must start with {_STAGING_PREFIX!r} or "
            f"{_CURATED_PREFIX!r}, got {relpath!r}"
        )


def _validate_destination_relpath(relpath: str) -> None:
    """Refuse destinations that would re-enter quarantine or escape vault."""
    if not relpath:
        raise ValueError("destination_relpath must be non-empty")
    if relpath.startswith("/"):
        raise ValueError(
            f"destination_relpath must be relative: {relpath!r}"
        )
    if "\\" in relpath:
        raise ValueError(
            f"destination_relpath must use forward slashes: {relpath!r}"
        )
    parts = relpath.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(
            f"destination_relpath must not contain '.' or '..': {relpath!r}"
        )
    if relpath.startswith(_STAGING_PREFIX) or relpath.startswith(
        _CURATED_PREFIX
    ):
        raise ValueError(
            "destination_relpath must be canonical (outside "
            f"bumba-contributions/), got {relpath!r}"
        )


def _derive_destination(source_relpath: str) -> str:
    """Pick a default canonical destination for a quarantine relpath.

    Strategy: take the path *after* the quarantine prefix and use it
    verbatim at vault root. This preserves any subdirectory structure
    Bumba used inside ``staging/`` or ``curated/``, so operator promotion
    of ``bumba-contributions/staging/projects/foo.md`` lands at
    ``projects/foo.md`` rather than at the vault root.
    """
    if source_relpath.startswith(_STAGING_PREFIX):
        return source_relpath[len(_STAGING_PREFIX):]
    if source_relpath.startswith(_CURATED_PREFIX):
        return source_relpath[len(_CURATED_PREFIX):]
    # _validate_quarantine_relpath would have raised; defensive.
    raise ValueError(
        f"cannot derive destination for non-quarantine path: {source_relpath!r}"
    )


def _atomic_write(target: Path, contents: str) -> int:
    """Write ``contents`` to ``target`` atomically (mkstemp + replace).

    Returns the number of bytes written. Caller is responsible for any
    surrounding lock — promote operations are operator-driven and rare,
    so we don't take a fcntl lock here (unlike WikiRepo.write which
    races with contributors).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix="." + target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    encoded = contents.encode("utf-8")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return len(encoded)


def _now_iso_utc() -> str:
    """Single-line ISO8601 UTC timestamp for log entries."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def promote_note(
    wiki_repo,
    *,
    source_relpath: str,
    destination_relpath: Optional[str] = None,
) -> PromoteResult:
    """Promote a staged or curated note to operator-canonical.

    Steps (atomic order — destination is written **before** the source
    is removed so a crash leaves the vault in a valid state with both
    copies present, which the next ``/promote`` re-runs idempotently):

    1. Validate source is inside ``bumba-contributions/`` quarantine.
    2. Derive destination if not supplied.
    3. Read source via ``wiki_repo.read`` (raises if missing).
    4. Strip frontmatter from the body.
    5. If destination already exists with identical content → no-op
       (return ``already_promoted=True``).
    6. If destination exists with different content → ``ValueError``
       (operator must resolve the conflict manually; we do not silently
       overwrite operator-canonical content).
    7. Atomic write to destination.
    8. Remove source file.
    9. Append a single line to ``log.md``.

    Args:
        wiki_repo: Anything with a ``vault_root`` :class:`Path` property,
            ``read(relpath)`` returning ``WikiReadResult``, and
            ``append_log(line)``. In production this is a
            :class:`bridge.second_brain.wiki_repo.WikiRepo` instance; tests
            inject a small fake.
        source_relpath: Quarantine relpath to promote
            (``bumba-contributions/staging/...`` or ``.../curated/...``).
        destination_relpath: Optional canonical relpath. When None, we
            derive it by stripping the quarantine prefix.

    Returns:
        :class:`PromoteResult` describing the outcome.

    Raises:
        ValueError: source/destination invalid, or destination exists
            with different content (conflict).
        FileNotFoundError: source not present.
    """
    _validate_quarantine_relpath(source_relpath)
    if destination_relpath is None:
        destination_relpath = _derive_destination(source_relpath)
    _validate_destination_relpath(destination_relpath)

    # Step 3 — read the staging copy. WikiRepo.read raises
    # FileNotFoundError if missing; let it bubble.
    read_result = wiki_repo.read(source_relpath)
    body_with_frontmatter = read_result.body
    # WikiRepo.read already split frontmatter off — ``body`` is the body.
    # But callers can pass a fake that returns the raw text; strip
    # defensively so the helper is robust to either shape.
    body = strip_frontmatter(body_with_frontmatter)

    vault_root = Path(wiki_repo.vault_root)
    source_path = vault_root / source_relpath
    dest_path = vault_root / destination_relpath

    # Step 5/6 — destination conflict check. Compare bytes so trailing-
    # newline drift between source and destination does not falsely flag
    # a conflict (we re-render the body below; identical body produces
    # identical bytes).
    expected_bytes = body.encode("utf-8")
    if dest_path.exists():
        existing = dest_path.read_bytes()
        if existing == expected_bytes:
            log_entry = (
                f"- {_now_iso_utc()} promoted (no-op, already at destination): "
                f"{source_relpath} -> {destination_relpath}"
            )
            # Still remove the staging copy if it exists, so subsequent
            # /promote calls don't keep finding it. This makes the call
            # truly idempotent rather than "destination exists but
            # staging keeps re-appearing in /wiki list".
            if source_path.exists():
                source_path.unlink()
            try:
                wiki_repo.append_log(log_entry)
            except Exception as e:  # noqa: BLE001 — log append non-fatal
                logger.warning("promote: append_log failed (non-fatal): %s", e)
            return PromoteResult(
                source_relpath=source_relpath,
                destination_relpath=destination_relpath,
                bytes_written=0,
                already_promoted=True,
                log_entry=log_entry,
            )
        # Different content — operator must resolve.
        raise ValueError(
            f"destination {destination_relpath!r} already exists with "
            "different content; operator must resolve manually before promotion"
        )

    # Step 7 — atomic write to destination. We do not go through
    # WikiRepo.write here because that path validates the relpath is
    # inside bumba-contributions/ (the quarantine subtree). Promotion
    # by definition writes outside of it, so we use the local atomic
    # primitive.
    bytes_written = _atomic_write(dest_path, body)

    # Step 8 — remove staging copy.
    try:
        source_path.unlink()
    except FileNotFoundError:
        # WikiRepo.read just succeeded, so this is unexpected — but we
        # have already written the destination, so log and continue.
        logger.warning(
            "promote: source %r vanished after read; destination written",
            source_relpath,
        )

    # Step 9 — log it.
    log_entry = (
        f"- {_now_iso_utc()} promoted: {source_relpath} -> {destination_relpath}"
    )
    try:
        wiki_repo.append_log(log_entry)
    except Exception as e:  # noqa: BLE001 — log append non-fatal
        logger.warning("promote: append_log failed (non-fatal): %s", e)

    return PromoteResult(
        source_relpath=source_relpath,
        destination_relpath=destination_relpath,
        bytes_written=bytes_written,
        already_promoted=False,
        log_entry=log_entry,
    )


def reject_note(
    wiki_repo,
    *,
    source_relpath: str,
    reason: Optional[str] = None,
) -> RejectResult:
    """Reject a staged or curated note.

    Steps:

    1. Validate source is inside the quarantine subtree.
    2. If absent → idempotent no-op (still log).
    3. Otherwise delete the file.
    4. Append one line to ``log.md`` (with reason if supplied).

    Args:
        wiki_repo: Same shape contract as :func:`promote_note`.
        source_relpath: Quarantine relpath to reject.
        reason: Optional free-form rejection reason. Single-line strings
            preferred; embedded newlines are flattened.

    Returns:
        :class:`RejectResult`.
    """
    _validate_quarantine_relpath(source_relpath)

    vault_root = Path(wiki_repo.vault_root)
    source_path = vault_root / source_relpath

    deleted = False
    if source_path.exists():
        source_path.unlink()
        deleted = True

    # Flatten embedded newlines in reason so the log line stays single-
    # line (append_log enforces this).
    flat_reason = (
        reason.replace("\n", " ").strip() if reason else None
    )
    if flat_reason:
        log_entry = (
            f"- {_now_iso_utc()} rejected: {source_relpath} "
            f"(reason: {flat_reason})"
        )
    else:
        log_entry = (
            f"- {_now_iso_utc()} rejected: {source_relpath}"
        )
    try:
        wiki_repo.append_log(log_entry)
    except Exception as e:  # noqa: BLE001 — log append non-fatal
        logger.warning("reject: append_log failed (non-fatal): %s", e)

    return RejectResult(
        source_relpath=source_relpath,
        reason=flat_reason,
        log_entry=log_entry,
        deleted=deleted,
    )


__all__ = [
    "PromoteResult",
    "RejectResult",
    "promote_note",
    "reject_note",
    "strip_frontmatter",
]
