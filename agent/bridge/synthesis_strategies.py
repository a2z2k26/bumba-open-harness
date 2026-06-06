"""Synthesizer strategy Protocol + 4 concrete implementations.

Sprint S09 sub-bet 1: replaces if/elif dispatch in Synthesizer with
strategy-based dispatch via the SynthesisStrategy Protocol.

Strategies:
  TextConcat       — CONCATENATE mode (lift from Synthesizer._concatenate)
  StructuredMerge  — STRUCTURED_MERGE mode
  LLMSynthesis     — LLM_SYNTHESIS mode (stub; requires runner injection)
  FirstResult      — Return the first completed WO output (useful for fast-path)
"""
from __future__ import annotations

import json
import logging
from typing import Protocol

from bridge.synthesizer import SynthesisMode, SynthesisResult
from bridge.work_order import WorkOrder, WorkOrderStatus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class SynthesisStrategy(Protocol):
    """Protocol for synthesis strategy implementations."""

    mode: SynthesisMode

    def combine(
        self,
        work_orders: list[WorkOrder],
        **opts: object,
    ) -> SynthesisResult:
        """Combine outputs from multiple WorkOrders into a SynthesisResult."""
        ...


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------

class TextConcat:
    """CONCATENATE — join non-empty outputs with a markdown divider."""

    mode = SynthesisMode.CONCATENATE

    def combine(
        self,
        work_orders: list[WorkOrder],
        **opts: object,
    ) -> SynthesisResult:
        warnings: list[str] = []
        parts: list[str] = []
        for wo in work_orders:
            if wo.status != WorkOrderStatus.COMPLETE:
                warnings.append(
                    f"WorkOrder '{wo.intent}' ({wo.id[:8]}) is incomplete "
                    f"(status: {wo.status.value})"
                )
            if wo.output.result:
                parts.append(f"## {wo.intent}\n\n{wo.output.result}")
        return SynthesisResult(
            success=True,
            combined="\n\n---\n\n".join(parts),
            warnings=warnings,
            mode=SynthesisMode.CONCATENATE,
        )


class StructuredMerge:
    """STRUCTURED_MERGE — merge a JSON key across all outputs."""

    mode = SynthesisMode.STRUCTURED_MERGE

    def combine(
        self,
        work_orders: list[WorkOrder],
        merge_key: str = "",
        **opts: object,
    ) -> SynthesisResult:
        warnings: list[str] = []
        merged_values: list[object] = []

        for wo in work_orders:
            if wo.status != WorkOrderStatus.COMPLETE:
                warnings.append(
                    f"WorkOrder '{wo.intent}' ({wo.id[:8]}) is incomplete "
                    f"(status: {wo.status.value})"
                )
            if not wo.output.result:
                continue
            try:
                data = json.loads(wo.output.result)
                if merge_key and merge_key in data:
                    val = data[merge_key]
                    if isinstance(val, list):
                        merged_values.extend(val)
                    else:
                        merged_values.append(val)
                else:
                    merged_values.append(data)
            except (json.JSONDecodeError, TypeError):
                warnings.append(f"WorkOrder {wo.id[:8]} output is not valid JSON")

        try:
            combined = json.dumps({merge_key: merged_values} if merge_key else merged_values)
            return SynthesisResult(
                success=True,
                combined=combined,
                warnings=warnings,
                mode=SynthesisMode.STRUCTURED_MERGE,
            )
        except (TypeError, ValueError) as e:
            return SynthesisResult(
                success=False,
                combined="",
                warnings=warnings + [f"JSON serialisation failed: {e}"],
                mode=SynthesisMode.STRUCTURED_MERGE,
            )


class LLMSynthesis:
    """LLM_SYNTHESIS — stub; returns concatenated output without LLM call.

    Full implementation requires an injected ClaudeRunner at construction.
    For now, falls back to TextConcat behaviour to preserve integration.
    """

    mode = SynthesisMode.LLM_SYNTHESIS

    def combine(
        self,
        work_orders: list[WorkOrder],
        **opts: object,
    ) -> SynthesisResult:
        log.debug("LLMSynthesis.combine: LLM synthesis not wired — falling back to TextConcat")
        return TextConcat().combine(work_orders, **opts)


class FirstResult:
    """Return the first COMPLETE WorkOrder's output (fast-path strategy)."""

    # Use CONCATENATE as the mode (closest existing enum value)
    mode = SynthesisMode.CONCATENATE

    def combine(
        self,
        work_orders: list[WorkOrder],
        **opts: object,
    ) -> SynthesisResult:
        for wo in work_orders:
            if wo.status == WorkOrderStatus.COMPLETE and wo.output.result:
                return SynthesisResult(
                    success=True,
                    combined=wo.output.result,
                    warnings=[],
                    mode=SynthesisMode.CONCATENATE,
                )
        return SynthesisResult(
            success=False,
            combined="",
            warnings=["No completed WorkOrders with output found"],
            mode=SynthesisMode.CONCATENATE,
        )


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[SynthesisMode, SynthesisStrategy] = {
    SynthesisMode.CONCATENATE: TextConcat(),
    SynthesisMode.STRUCTURED_MERGE: StructuredMerge(),
    SynthesisMode.LLM_SYNTHESIS: LLMSynthesis(),
}


def get_strategy(mode: SynthesisMode) -> SynthesisStrategy:
    """Return the registered strategy for the given mode.

    Falls back to TextConcat for unknown modes.
    """
    return _REGISTRY.get(mode, TextConcat())


def register_strategy(strategy: SynthesisStrategy) -> None:
    """Register a custom strategy, overriding the default for its mode."""
    _REGISTRY[strategy.mode] = strategy
