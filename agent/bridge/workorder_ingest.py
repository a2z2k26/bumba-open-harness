"""Devin-style knowledge auto-ingest for completed WorkOrders.

Sprint S13: When a WorkOrder COMPLETEs, its output is automatically ingested
into temporal_knowledge + a secondary persistence target, keyed by
(wo.project, wo.skill). Future WOs with similar (project, skill) retrieve
prior successful results as context at SessionStart.

Sprint S5.1 (#2349): the secondary target is now :class:`WorkOrderStore`.
Previously this branch held a renamed ``memory_index`` handle whose real
interface (``MemoryFile`` — ``update`` / ``read`` / ``get_memory_context``)
never accepted ``.upsert``, so every call silently no-op'd via
``AttributeError``. Completed WO outputs were dropping on the floor of any
deployment that configured the handle.

Wiring contract:
- Pass a real :class:`WorkOrderStore` as ``work_order_store`` to enable the
  secondary write path. The ingestor fetches the existing WO row by ID,
  attaches the completion output via :meth:`WorkOrder.with_output`, and
  persists via :meth:`WorkOrderStore.save`.
- If ``work_order_store`` is configured but the WO row is missing
  (orphan event), the ingestor logs at WARNING — visible wiring degradation
  rather than silent no-op.
- If ``work_order_store`` is configured but the object lacks the expected
  ``get`` / ``save`` surface (incompatible target), the ingestor logs at
  WARNING once per event — visible wiring failure.
- If ``work_order_store`` is ``None``, no secondary write happens; this is
  the deliberate "secondary target is optional" path and is logged at INFO
  once at wire time.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bridge.work_order import WorkOrderOutput

if TYPE_CHECKING:
    from bridge.work_order_store import WorkOrderStore

log = logging.getLogger(__name__)


class WorkOrderIngestor:
    """Subscribes to workorder.completed events and ingests outputs.

    Designed to be dependency-injected at bridge startup with the
    temporal_knowledge and work_order_store objects.

    Both storage targets are optional — if not provided, that target
    is skipped. Sprint S5.1: when ``work_order_store`` is provided but the
    secondary write fails (orphan WO id, incompatible store), the failure
    surfaces at WARNING — silent no-op is no longer a supported state.
    """

    def __init__(
        self,
        *,
        event_bus: object | None = None,
        temporal_knowledge: object | None = None,
        work_order_store: "WorkOrderStore | None" = None,
    ) -> None:
        self._bus = event_bus
        self._tk = temporal_knowledge
        # Sprint S5.1 (#2349) — replaces the old ``memory_store``/``memory_index``
        # handle. The real persistence target is :class:`WorkOrderStore`; its
        # ``get`` + ``save`` surface is duck-typed below (and the parameter is
        # typed in TYPE_CHECKING) so tests can inject lightweight fakes.
        self._wos = work_order_store
        self._wired = False

    def wire(self) -> None:
        """Subscribe to the event bus. Call once at bridge startup."""
        if self._wired or self._bus is None:
            return
        self._bus.subscribe("workorder.completed", self._on_completed)  # type: ignore[attr-defined]
        self._wired = True
        if self._wos is None:
            log.info(
                "WorkOrderIngestor wired to event bus "
                "(secondary persistence: not configured)"
            )
        else:
            log.info(
                "WorkOrderIngestor wired to event bus "
                "(secondary persistence: WorkOrderStore)"
            )

    def _on_completed(self, event_name: object, payload: dict | None = None) -> None:
        """Handle a workorder.completed event.

        Expected payload fields:
            workorder_id: str
            skill: str
            project: str
            output_text: str
        """
        _, payload = self._event_name_and_payload(event_name, payload)
        wo_id = payload.get("workorder_id", "")
        skill = payload.get("skill", "")
        project = payload.get("project", "")
        output = payload.get("output_text", "")

        if not output:
            log.debug("WorkOrderIngestor: skipping WO %s (no output_text)", wo_id[:8])
            return

        key = f"project:{project}:skill:{skill}"
        log.info(
            "WorkOrderIngestor: ingesting WO %s (project=%s skill=%s len=%d)",
            wo_id[:8], project, skill, len(output),
        )

        # Ingest into temporal_knowledge
        if self._tk is not None:
            try:
                self._tk.append(  # type: ignore[attr-defined]
                    key=key,
                    value=output,
                    source=f"workorder:{wo_id}",
                )
            except AttributeError:
                # temporal_knowledge may use a different API
                try:
                    self._tk.store(  # type: ignore[attr-defined]
                        key=key,
                        value=output,
                        reason=f"WorkOrder {wo_id[:8]} completed",
                        changed_by="system",
                    )
                except Exception:
                    log.exception("temporal_knowledge ingest failed for WO %s", wo_id[:8])
            except Exception:
                log.exception("temporal_knowledge.append failed for WO %s", wo_id[:8])

        # Secondary persistence: route the completion output through WorkOrderStore.
        # Sprint S5.1 (#2349) — replaces the old silent no-op against the renamed
        # ``memory_index`` handle, which never had an ``upsert`` method.
        if self._wos is not None:
            self._persist_to_work_order_store(wo_id, output)

    def _event_name_and_payload(
        self,
        event_name: object,
        payload: dict | None,
    ) -> tuple[str, dict]:
        """Accept both legacy direct calls and live EventBus callbacks."""
        if isinstance(event_name, str) and payload is not None:
            return event_name, payload

        raw_event_type = getattr(event_name, "event_type", "")
        raw_payload = getattr(event_name, "payload", {})
        if isinstance(raw_event_type, str) and isinstance(raw_payload, dict):
            return raw_event_type, raw_payload

        return "", {}

    def _persist_to_work_order_store(self, wo_id: str, output_text: str) -> None:
        """Attach completion output to the WO row and persist via WorkOrderStore.

        Surfaces three failure modes at WARNING level (visible wiring status,
        not silent debug):

        - **incompatible target**: the configured object lacks ``get`` / ``save``
          (e.g. operator wired a sketch/fake by mistake)
        - **orphan event**: a ``workorder.completed`` event references a WO id
          that has no row in the store (event-vs-state drift)
        - **save failure**: the store accepted the call but raised at persist
          time (DB locked, schema drift, etc.)
        """
        store = self._wos
        # Duck-typed presence check — keeps the contract narrow (we only need
        # ``get`` + ``save``) and surfaces misconfigured targets explicitly.
        if not (hasattr(store, "get") and hasattr(store, "save")):
            log.warning(
                "WorkOrderIngestor: configured secondary target is incompatible "
                "(expected WorkOrderStore-shaped object with .get + .save, got %s) "
                "— skipping WO %s",
                type(store).__name__, wo_id[:8],
            )
            return

        try:
            wo = store.get(wo_id)  # type: ignore[union-attr]
        except Exception:
            log.exception(
                "WorkOrderIngestor: WorkOrderStore.get failed for WO %s", wo_id[:8]
            )
            return

        if wo is None:
            log.warning(
                "WorkOrderIngestor: WO %s has no row in WorkOrderStore "
                "(orphan workorder.completed event) — secondary write skipped",
                wo_id[:8],
            )
            return

        # Replace the output with one carrying the completion text. WorkOrder is
        # frozen, so ``with_output`` returns a new instance.
        try:
            updated = wo.with_output(WorkOrderOutput(result=output_text))
            store.save(updated)  # type: ignore[union-attr]
        except Exception:
            log.exception(
                "WorkOrderIngestor: WorkOrderStore.save failed for WO %s", wo_id[:8]
            )
            return

        log.debug(
            "WorkOrderIngestor: secondary write OK for WO %s (len=%d)",
            wo_id[:8], len(output_text),
        )

    def ingest_directly(
        self,
        wo_id: str,
        skill: str,
        project: str,
        output: str,
    ) -> None:
        """Directly ingest an output without going through the event bus.

        Useful for testing and for callers that already have the WO data.
        """
        if not output:
            return
        self._on_completed(
            "workorder.completed",
            {
                "workorder_id": wo_id,
                "skill": skill,
                "project": project,
                "output_text": output,
            },
        )
