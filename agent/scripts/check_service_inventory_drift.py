#!/usr/bin/env python3
"""Service inventory drift checker — Sprint audit-2026-05-16.F.03 (SW-2, issue #2076).

Authoritative source (decided 2026-05-16):
    ``SERVICE_MAP`` in ``agent/bridge/services/runner.py`` is the code-as-registry
    source of truth for the bridge's 18 scheduled services. Every parallel
    surface (narrations, schedules, timeouts, plist files) must be reconcilable
    against it.

Audit reference: docs/audits/2026-05-16-whole-codebase-audit.md SW-2 — recommended
either bless code-as-registry or extract a declarative ``agent/config/services.yaml``.
This sprint blesses the existing code surface because:

    1. ``runner.py`` already owns the runtime contract: ``SERVICE_MAP[name]``
       drives every ``python -m bridge.services.runner <name>`` invocation
       from launchd. A YAML registry would have to round-trip through this
       table anyway.
    2. The 4 secondary surfaces (``SERVICE_NARRATIONS``, ``SERVICE_SCHEDULES``,
       ``SERVICE_TIMEOUTS``, plist filenames) already live next to or one
       module away from ``SERVICE_MAP``. The drift risk is purely "did
       someone add a service and forget one of the other tables?" — exactly
       what this checker catches.
    3. The existing ``agent/config/registry/{events,metrics,actions}/`` YAMLs
       describe REST endpoints and health components. They are NOT a
       declarative service-inventory in the sense SW-2 means. Two registry
       files happen to be called ``services.yaml`` but list (a) Zone 4 REST
       routes and (b) /healthz components — confusingly named. We leave them
       alone for this sprint; F.05 (architecture-docs sweep) is the place to
       rename or re-document.

What this script checks
-----------------------

For each parallel surface, the checker computes the set of service keys and
diffs it against ``SERVICE_MAP``:

* ``SERVICE_NARRATIONS`` (``result.py``) — every ``SERVICE_MAP`` key must have
  a narration entry. Extra keys are flagged.
* ``SERVICE_SCHEDULES`` (``result.py``) — same rule.
* ``SERVICE_TIMEOUTS`` (``runner.py``) — same rule.
* Plist labels (``agent/scripts/*.plist`` ∪ ``agent/config/launchdaemons/*.plist``)
  — every plist label normalised to underscore form must either map to a
  ``SERVICE_MAP`` key or be on the documented ``ON_DEMAND_PLISTS`` exception
  list owned by the existing structural validator (``runner.validate_services``).

Exit codes
----------

* ``0`` — no drift detected.
* ``1`` — drift detected; diff is printed to stderr.

This mirrors the pattern of ``agent/bridge/services/runner.py::validate_services``
(structural Rules 1–4) but factors the inventory drift check into a single-
purpose script suitable for CI invocation alongside ``check_registry_completeness``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Repo root is 2 levels above this file (agent/scripts/ → agent/ → repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_DIR = REPO_ROOT / "agent"

# Plist labels that intentionally have NO SERVICE_MAP entry — kept in sync with
# the structural validator's ON_DEMAND_PLISTS at runner.py.
ON_DEMAND_PLISTS: frozenset[str] = frozenset({
    "bridge",
    "maintenance",
    "cost-rollup",
    "monitor",
    "oauth-refresh",
    "deploy-helper",
    "experiment",
    "consolidation-deep",
    "consolidation-micro",
    "consolidation-standard",
    "weekly-ceo-review",
    "job-execute",
})


def _load_authoritative(agent_dir: Path) -> dict[str, tuple[str, str]]:
    """Import ``SERVICE_MAP`` from the runtime tree.

    We import the live module rather than re-parsing source so the checker
    catches keys added by import-time logic (none today, but the contract
    survives future refactors).
    """
    agent_str = str(agent_dir)
    if agent_str not in sys.path:
        sys.path.insert(0, agent_str)
    from bridge.services.runner import SERVICE_MAP  # noqa: E402

    return dict(SERVICE_MAP)


def _load_secondary_maps(agent_dir: Path) -> dict[str, set[str]]:
    """Load the four parallel-surface keysets keyed off ``SERVICE_MAP``."""
    agent_str = str(agent_dir)
    if agent_str not in sys.path:
        sys.path.insert(0, agent_str)
    from bridge.services.result import SERVICE_NARRATIONS, SERVICE_SCHEDULES  # noqa: E402
    from bridge.services.runner import SERVICE_TIMEOUTS  # noqa: E402

    return {
        "SERVICE_NARRATIONS": set(SERVICE_NARRATIONS.keys()),
        "SERVICE_SCHEDULES": set(SERVICE_SCHEDULES.keys()),
        "SERVICE_TIMEOUTS": set(SERVICE_TIMEOUTS.keys()),
    }


def _scan_plist_labels(repo_root: Path) -> set[str]:
    """Return the set of plist labels found on disk, hyphenated."""
    plist_dirs = (
        repo_root / "agent" / "scripts",
        repo_root / "agent" / "config" / "launchdaemons",
    )
    labels: set[str] = set()
    pattern = re.compile(r"com\.bumba\.agent-([^./]+)\.plist$")
    for d in plist_dirs:
        if not d.exists():
            continue
        for path in d.glob("com.bumba.agent-*.plist"):
            m = pattern.search(path.name)
            if m:
                labels.add(m.group(1))
    return labels


def check_drift(
    authoritative: dict[str, tuple[str, str]],
    secondary: dict[str, set[str]],
    plist_labels: set[str],
    on_demand_plists: frozenset[str] = ON_DEMAND_PLISTS,
) -> list[str]:
    """Return a list of drift error strings; empty list = no drift."""
    errors: list[str] = []
    authoritative_keys = set(authoritative.keys())

    # Surface 1-3: secondary keysets must match authoritative exactly (no missing,
    # no extra). Each surface drives operator-visible behaviour:
    #
    #   - SERVICE_NARRATIONS / SERVICE_SCHEDULES: render_service_detail() falls
    #     back to "(no narration)" when the key is missing — silent UX drift.
    #   - SERVICE_TIMEOUTS: missing keys fall back to DEFAULT_TIMEOUT (300s),
    #     hiding real per-service timing requirements.
    for surface_name, keys in secondary.items():
        missing = authoritative_keys - keys
        extra = keys - authoritative_keys
        if missing:
            errors.append(
                f"{surface_name}: missing entries for SERVICE_MAP keys "
                f"{sorted(missing)}"
            )
        if extra:
            errors.append(
                f"{surface_name}: has extra keys not in SERVICE_MAP "
                f"{sorted(extra)}"
            )

    # Surface 4: plist labels. The mapping is hyphen→underscore (e.g.
    # 'job-search' label → 'job_search' SERVICE_MAP key). A plist with no
    # SERVICE_MAP entry is either on the on-demand allowlist or it's drift.
    unaccounted_labels = {
        label
        for label in plist_labels
        if label not in on_demand_plists
        and label.replace("-", "_") not in authoritative_keys
    }
    if unaccounted_labels:
        errors.append(
            f"plist: labels not in SERVICE_MAP and not on ON_DEMAND_PLISTS allowlist "
            f"{sorted(unaccounted_labels)}"
        )

    # Reverse: every SERVICE_MAP key should be reachable from a plist or be on
    # the on-demand-key allowlist (which is owned by runner.validate_services).
    # We only flag keys with NO matching plist label (hyphen or underscore form)
    # so the checker stays focused on inventory-set drift, not the structural
    # rules that runner.validate_services already covers.
    on_demand_keys: frozenset[str] = frozenset({
        "consolidation",
        "job_search_execute",
        "funnel_post",
        "weekly_ceo_review",
    })
    unreachable_keys = {
        key
        for key in authoritative_keys
        if key not in on_demand_keys
        and key not in plist_labels
        and key.replace("_", "-") not in plist_labels
    }
    if unreachable_keys:
        errors.append(
            f"SERVICE_MAP: keys with no matching plist and not on the "
            f"on-demand-key allowlist {sorted(unreachable_keys)}"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress success summary; only print on drift",
    )
    args = parser.parse_args(argv)

    try:
        authoritative = _load_authoritative(AGENT_DIR)
        secondary = _load_secondary_maps(AGENT_DIR)
        plist_labels = _scan_plist_labels(REPO_ROOT)
    except Exception as exc:  # pragma: no cover — surfaced via test
        print(
            f"service-inventory-drift: ERROR loading inventory: {exc}",
            file=sys.stderr,
        )
        return 2

    errors = check_drift(authoritative, secondary, plist_labels)

    if errors:
        print(
            f"service-inventory-drift: {len(errors)} drift error(s) detected",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  DRIFT: {err}", file=sys.stderr)
        print(
            "\nFix by reconciling secondary surfaces against "
            "agent/bridge/services/runner.py::SERVICE_MAP (the authoritative source).",
            file=sys.stderr,
        )
        return 1

    if not args.quiet:
        print(
            f"service-inventory-drift: OK "
            f"({len(authoritative)} services, {len(plist_labels)} plist labels, "
            f"all 4 parallel surfaces aligned)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
