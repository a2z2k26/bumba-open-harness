"""Declarative wiring manifest for BridgeApp subsystem assignment.

Sprint 01.01 — scaffold only. Sprint 01.02 will use these primitives to migrate
the 28 scattered ``self._commands.set_*(...)`` calls in ``app.py:477-696`` into a
single declarative manifest. Sprints 01.03/01.04 will declare ``required=False``
entries with ``source_attr`` pointing at attributes that future plans will fill —
giving an operator a single boot-time line that answers "what got wired and what
is waiting on which plan?".

This module is intentionally pure and dependency-free: it imports only stdlib
so it can be tested in isolation and so importing ``bridge.wiring`` cannot
trigger circular imports through ``bridge.app``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger
from typing import Any, Sequence

__all__ = [
    "WiringEntry",
    "WiringMissingError",
    "WiringReport",
    "apply_wiring_manifest",
    "log_wiring_report",
]


class WiringMissingError(RuntimeError):
    """Raised when a subsystem is invoked before its declarative wire fired.

    The contract this exception enforces: subsystems that depend on a
    setter-based wire (e.g. ``ProactiveScheduler.set_dispatch``) MUST raise
    this instead of silently no-op'ing when the setter was never called.
    Silent no-op leaves the runtime in a degraded state that is invisible
    to the operator; this exception surfaces the gap loudly and lets the
    scheduler/dispatcher log a ledger row with a clear cause.

    Sprint #1614 (2026-05-11 runtime audit) introduced this for the
    ``ProactiveScheduler._dispatch`` direct-attribute assignment bypass —
    see the "Wiring discipline" section in ``agent/CLAUDE.md``.
    """


@dataclass(frozen=True)
class WiringEntry:
    """Declarative description of a single setter wire.

    Each entry maps a ``BridgeApp`` source attribute onto a setter on a target
    object (typically ``CommandHandler`` or ``BridgeApp`` itself). At
    ``apply_wiring_manifest`` time, the helper resolves
    ``getattr(app, source_attr, None)`` and — if truthy — invokes
    ``getattr(target, setter_name)(source_value)``.

    Fields
    ------
    target_name:
        Human-readable label for the target, used only in log lines (e.g.
        ``"CommandHandler"``, ``"BridgeApp"``). Not used for resolution.
    target:
        The actual object whose setter will be called.
    setter_name:
        The attribute name on ``target`` to call with the source value.
    source_attr:
        The attribute name on the ``BridgeApp`` instance to read as the source.
    required:
        If ``True``, a ``None`` source value at apply time raises ``RuntimeError``
        rather than being recorded as pending. Use this for invariants — e.g.
        ``set_session_hooks`` MUST fire because operator commands depend on it.
    reason_if_none:
        Free-text explanation of *why* this source might be ``None`` and which
        plan owns its construction. Surfaced in the boot-time wiring report.
    group:
        Coarse grouping for log output: ``"command-handler"``, ``"bridge-app"``,
        ``"session-manager"``, ``"api-server"``. Used only for log organization.
    """

    target_name: str
    target: Any
    setter_name: str
    source_attr: str
    required: bool
    reason_if_none: str
    group: str
    failed_marker_attr: str | None = None
    """Optional attribute on ``app`` whose truthy value escalates a PENDING
    entry to FAILED.

    Sprint #1614 (2026-05-11). When a subsystem's init block catches an
    exception and leaves the source attribute None, the WiringReport's
    pending list looks identical to a "deferred, owned by a future plan"
    case. Setting ``failed_marker_attr="_proactive_scheduler_init_failed"``
    on the entry lets the manifest distinguish the two: if
    ``getattr(app, failed_marker_attr)`` is truthy, the entry is recorded
    in ``report.failed`` instead of ``report.pending``.

    ``None`` (the default) preserves the original PENDING-vs-active-only
    semantics for every existing entry.
    """


@dataclass
class WiringReport:
    """Outcome of applying a wiring manifest.

    Attributes
    ----------
    active:
        Number of entries whose source was truthy and whose setter ran without
        raising.
    pending:
        ``(setter_name, reason_if_none)`` tuples for entries where the source
        attribute resolved to ``None`` (or was missing) and ``required=False``.
    errors:
        ``(setter_name, exception)`` tuples for entries whose setter raised at
        invocation time. The helper does not re-raise — failures are surfaced
        through ``log_wiring_report`` so a partial-wire boot still progresses.
    """

    active: int = 0
    pending: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, Exception]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    """Entries whose source is None AND whose ``failed_marker_attr`` is
    truthy on the app — i.e. the init block ran but the construction
    raised, leaving the subsystem in a degraded state. Reported separately
    from PENDING so the operator can distinguish "deferred by plan" from
    "tried and failed" in the boot log.
    """


def apply_wiring_manifest(
    app: Any,
    manifest: Sequence[WiringEntry],
    logger: Logger,
) -> WiringReport:
    """Walk ``manifest`` in order and apply each entry against ``app``.

    The helper is pure with respect to ``manifest``: it never mutates the
    sequence or its entries. ``app`` is touched only via ``getattr`` reads.
    Setter invocation is via ``getattr(target, setter_name)(source_value)``.

    A ``required=True`` entry whose resolved source is falsy raises
    ``RuntimeError`` immediately — silent skipping of an invariant wire is the
    anti-pattern this manifest exists to eliminate.

    Setter exceptions are caught and recorded in ``report.errors`` so a single
    misbehaving subsystem cannot bring down the whole wiring pass; the operator
    still sees the boot-time wiring summary.
    """
    report = WiringReport()

    for entry in manifest:
        source_value = getattr(app, entry.source_attr, None)

        if not source_value:
            if entry.required:
                raise RuntimeError(
                    f"Required wiring entry {entry.setter_name!r} on {entry.target_name} "
                    f"has no source ({entry.source_attr!r} is missing or falsy on app). "
                    f"Reason recorded: {entry.reason_if_none}"
                )
            # Sprint #1614 — when an init-failure marker is set, escalate
            # PENDING → FAILED so the operator sees "this subsystem tried
            # and crashed" rather than "this is deferred by a future plan".
            if (
                entry.failed_marker_attr is not None
                and getattr(app, entry.failed_marker_attr, False)
            ):
                report.failed.append((entry.setter_name, entry.reason_if_none))
                logger.warning(
                    "wiring.failed group=%s target=%s setter=%s marker=%s reason=%s",
                    entry.group,
                    entry.target_name,
                    entry.setter_name,
                    entry.failed_marker_attr,
                    entry.reason_if_none,
                )
                continue
            report.pending.append((entry.setter_name, entry.reason_if_none))
            logger.debug(
                "wiring.pending group=%s target=%s setter=%s reason=%s",
                entry.group,
                entry.target_name,
                entry.setter_name,
                entry.reason_if_none,
            )
            continue

        setter = getattr(entry.target, entry.setter_name)
        try:
            setter(source_value)
        except Exception as exc:  # noqa: BLE001 — capture-and-record is the contract
            report.errors.append((entry.setter_name, exc))
            logger.exception(
                "wiring.error group=%s target=%s setter=%s",
                entry.group,
                entry.target_name,
                entry.setter_name,
            )
            continue

        report.active += 1
        logger.debug(
            "wiring.active group=%s target=%s setter=%s source=%s",
            entry.group,
            entry.target_name,
            entry.setter_name,
            entry.source_attr,
        )

    return report


def log_wiring_report(report: WiringReport, logger: Logger) -> None:
    """Emit a single INFO summary line plus DEBUG/ERROR detail lines.

    The summary line shape — ``"Wiring complete: N active, M pending, K errors"`` —
    is the canonical signal Sprint 01.02's operator-side deploy verification
    looks for in stderr.log to confirm the manifest fired as expected.
    """
    logger.info(
        "Wiring complete: %d active, %d pending, %d errors, %d failed",
        report.active,
        len(report.pending),
        len(report.errors),
        len(report.failed),
    )

    for setter_name, reason in report.pending:
        logger.debug("wiring.pending setter=%s reason=%s", setter_name, reason)

    for setter_name, exc in report.errors:
        logger.error("wiring.error setter=%s exc=%r", setter_name, exc)

    # Sprint #1614 — surface FAILED entries at WARNING so they don't blend
    # into the silent-pending pile.
    for setter_name, reason in report.failed:
        logger.warning(
            "wiring.failed setter=%s reason=%s (init block raised; subsystem degraded)",
            setter_name,
            reason,
        )
