"""Result synthesis for multi-agent WorkOrder outputs."""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bridge.work_order import WorkOrder, WorkOrderStatus

log = logging.getLogger(__name__)


class SynthesisMode(enum.Enum):
    CONCATENATE = "concatenate"
    STRUCTURED_MERGE = "structured_merge"
    LLM_SYNTHESIS = "llm_synthesis"


@dataclass(frozen=True)
class RunMetrics:
    """Per-run cost + token + duration counters for an autonomous surface.

    Board Phase 1 metering (issue #2390). Carried on ``SynthesisResult`` so
    the factory/board path emits uniform metering without any department
    YAML schema change. Immutable — combine two runs with :meth:`add`, which
    returns a new instance rather than mutating either operand.

    Token/cost figures are whatever the producing surface measured; the
    canonical system of record for the dollar figure is the per-call cost
    parser in ``bridge.cost_tracker`` / ``bridge.observability.cost``. This
    value object is the transport, not the ledger.
    """

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0

    def add(self, other: "RunMetrics") -> "RunMetrics":
        """Return a new RunMetrics summing this and *other* field-by-field."""
        return RunMetrics(
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            cost_usd=self.cost_usd + other.cost_usd,
            duration_ms=self.duration_ms + other.duration_ms,
        )


@dataclass(frozen=True)
class SynthesisResult:
    success: bool = False
    combined: str = ""
    warnings: tuple[str, ...] = ()
    mode: SynthesisMode = SynthesisMode.CONCATENATE
    # Board Phase 1 metering (#2390) — optional per-run metering. ``None``
    # means the producing path did not measure (back-compat default); a
    # populated RunMetrics carries tokens_in/tokens_out/cost_usd/duration_ms.
    metrics: "RunMetrics | None" = None

    def __init__(
        self,
        success: bool = False,
        combined: str = "",
        warnings: list[str] | tuple[str, ...] = (),
        mode: SynthesisMode = SynthesisMode.CONCATENATE,
        metrics: "RunMetrics | None" = None,
    ) -> None:
        object.__setattr__(self, "success", success)
        object.__setattr__(self, "combined", combined)
        object.__setattr__(self, "warnings", tuple(warnings))
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "metrics", metrics)


class Synthesizer:
    def synthesize(
        self,
        work_orders: list[WorkOrder],
        *,
        mode: SynthesisMode = SynthesisMode.CONCATENATE,
        merge_key: str = "",
        context_complete_flags: dict[str, list[str]] | None = None,
    ) -> SynthesisResult:
        warnings: list[str] = []

        for wo in work_orders:
            if wo.status != WorkOrderStatus.COMPLETE:
                warnings.append(
                    f"WorkOrder '{wo.intent}' ({wo.id[:8]}) is incomplete "
                    f"(status: {wo.status.value})"
                )

        if context_complete_flags:
            for flag_name, wo_ids in context_complete_flags.items():
                for wo_id in wo_ids:
                    warnings.append(
                        f"WorkOrder {wo_id[:8]} flagged as {flag_name} — "
                        f"agent may not have written context to shared memory"
                    )

        if mode == SynthesisMode.CONCATENATE:
            return self._concatenate(work_orders, warnings)
        elif mode == SynthesisMode.STRUCTURED_MERGE:
            return self._structured_merge(work_orders, merge_key, warnings)
        elif mode == SynthesisMode.LLM_SYNTHESIS:
            return self._llm_synthesis(work_orders, warnings)
        else:
            return SynthesisResult(success=False, combined="", warnings=[f"Unknown mode: {mode}"])

    def _concatenate(self, work_orders: list[WorkOrder], warnings: list[str]) -> SynthesisResult:
        parts: list[str] = []
        for wo in work_orders:
            if wo.output.result:
                parts.append(f"## {wo.intent}\n\n{wo.output.result}")
        return SynthesisResult(
            success=True,
            combined="\n\n---\n\n".join(parts),
            warnings=warnings,
            mode=SynthesisMode.CONCATENATE,
        )

    def _structured_merge(
        self, work_orders: list[WorkOrder], merge_key: str, warnings: list[str]
    ) -> SynthesisResult:
        merged_values: list[object] = []
        for wo in work_orders:
            if not wo.output.result:
                continue
            try:
                data = json.loads(wo.output.result)
                if merge_key in data:
                    val = data[merge_key]
                    if isinstance(val, list):
                        merged_values.extend(val)
                    else:
                        merged_values.append(val)
            except json.JSONDecodeError:
                warnings.append(f"WorkOrder {wo.id[:8]} output is not valid JSON")

        result = json.dumps({merge_key: merged_values}, indent=2)
        return SynthesisResult(
            success=True, combined=result, warnings=warnings, mode=SynthesisMode.STRUCTURED_MERGE,
        )

    def _llm_synthesis(self, work_orders: list[WorkOrder], warnings: list[str]) -> SynthesisResult:
        warnings.append(
            "LLM synthesis mode is not yet implemented. Falling back to concatenation."
        )
        return self._concatenate(work_orders, warnings)

    def synthesize_for_skill(
        self,
        work_orders: list[WorkOrder],
        skill_name: str,
        *,
        config: SynthesizerConfig | None = None,
    ) -> SynthesisResult:
        """Synthesize using skill-specific config overrides.

        Bridge-independent API — looks up the skill in config to determine
        the correct synthesis mode and merge key.
        """
        if config is None:
            return self.synthesize(work_orders)

        override = config.skill_overrides.get(skill_name)
        if override is None:
            mode = SynthesisMode(config.default_mode)
            return self.synthesize(work_orders, mode=mode)

        mode = SynthesisMode(override.get("mode", config.default_mode))
        merge_key = override.get("merge_key", config.default_merge_key)
        return self.synthesize(work_orders, mode=mode, merge_key=merge_key)


# ---------------------------------------------------------------------------
# Config loader — bridge-independent
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SynthesizerConfig:
    """Loaded synthesizer configuration."""
    default_mode: str = "concatenate"
    default_merge_key: str = "findings"
    skill_overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    warn_on_incomplete: bool = True

    def __init__(
        self,
        default_mode: str = "concatenate",
        default_merge_key: str = "findings",
        skill_overrides: dict[str, dict[str, str]] | None = None,
        warn_on_incomplete: bool = True,
    ) -> None:
        object.__setattr__(self, "default_mode", default_mode)
        object.__setattr__(self, "default_merge_key", default_merge_key)
        object.__setattr__(self, "skill_overrides", skill_overrides or {})
        object.__setattr__(self, "warn_on_incomplete", warn_on_incomplete)

    @classmethod
    def from_config(cls, config_path: str | Path) -> SynthesizerConfig:
        """Load synthesizer config from YAML.

        Bridge-independent — usable by any Python consumer.
        """
        path = Path(config_path)
        if not path.exists():
            log.warning("Synthesizer config not found: %s", path)
            return cls()

        try:
            import yaml
        except ImportError:
            log.warning("PyYAML not available, using defaults")
            return cls()

        try:
            data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed to parse synthesizer config: %s", path)
            return cls()

        synthesis = data.get("synthesis", {})
        merge_cfg = synthesis.get("structured_merge", {})

        return cls(
            default_mode=synthesis.get("default_mode", "concatenate"),
            default_merge_key=merge_cfg.get("default_merge_key", "findings"),
            skill_overrides=synthesis.get("skill_overrides", {}),
            warn_on_incomplete=synthesis.get("warn_on_incomplete", True),
        )
