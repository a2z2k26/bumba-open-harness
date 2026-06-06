"""Dark Factory state-machine helpers (concept-only-no-license port).

This subpackage implements the "GitHub labels as the only state machine"
pattern from coleam00/dark-factory-experiment. The repo has no LICENSE,
so this is a concept port only — no source was copied.

Bumba uses SQLite (`bridge.work_order_store.WorkOrderStore`) for the
WorkOrder dispatcher. The factory pipeline (Plan 14 phases 2-5) needs
cross-process coordination that survives total crash and is visible in
the GitHub UI; SQLite cannot provide either. Labels can.

This module COMPLEMENTS — does not replace — the SQLite path.

Sprint 14.02 adds `governance.py` for poison-immune governance fetch from
`origin/main`; Sprint 14.04 adds `triage.py`; Sprint 14.05 adds
`implement.py`. Each module is independently importable.
"""
from __future__ import annotations

from bridge.factory.labels import (
    FACTORY_LABELS,
    FACTORY_OPT_IN_LABEL,
    FactoryState,
    LabelStateError,
    ensure_labels_exist,
    get_state,
    transition_state,
)
from bridge.factory.triage import (
    COST_CAP_USD,
    TriageVerdict,
    classify_issue,
    triage_workflow,
)

__all__ = [
    "COST_CAP_USD",
    "FACTORY_LABELS",
    "FACTORY_OPT_IN_LABEL",
    "FactoryState",
    "LabelStateError",
    "TriageVerdict",
    "classify_issue",
    "ensure_labels_exist",
    "get_state",
    "transition_state",
    "triage_workflow",
]
