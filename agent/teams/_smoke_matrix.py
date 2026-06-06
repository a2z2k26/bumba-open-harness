"""Zone 4 end-to-end smoke matrix (Z4-22 #2448).

Exercises, for each Zone 4 department, two legs:

- **readiness** — ``registry.route(dept, "ready to work?", deps)``. Hits the
  deterministic ``render_readiness`` path (Z4-01); spends zero provider
  requests. This is the cheap proof-of-life every department must pass.
- **substantive** — one real ``DepartmentTeam.run`` driven by deterministic
  models against a tmp ``artifact_root``, so the run writes a real
  ``manifest.json`` + telemetry (Z4-02 / Z4-05) with no live API call.

Failures are classified into the six issue classes: ``provider``,
``usage_policy``, ``timeout``, ``schema_validation``, ``artifact``,
``memory``.

Why offline-only (2026-05-21 provider context): 46/52 Zone 4 seats are
configured against an OpenRouter key that 401s at invocation. A *live*
smoke matrix would mostly fail until the provider cutover, so the gate runs
fully offline (deterministic models, mocked providers). Live-smoke
instructions are operator-gated and live in
``docs/operator/zone4-smoke-matrix.md``; they are NOT part of the release
gate.

Design constraints (acceptance criteria, #2448):

- Runs without Discord.
- Readiness path uses zero provider requests.
- Substantive path records telemetry and a manifest.
- Failures classify into the six classes.
- Missing dependencies are recorded as expected-fail, never hidden.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Mapping

from teams._readiness import is_readiness_prompt
from teams._run_telemetry import normalize_failure_class
from teams._types import BridgeDeps, DepartmentConfig, TeamResult


# ---------------------------------------------------------------------------
# Default smoke matrix (issue table)
# ---------------------------------------------------------------------------

# Each entry: (readiness_prompt, substantive_prompt). Mirrors the issue's
# smoke-matrix table. ``ops`` and ``job_search`` use a readiness-only
# substantive prompt because their substantive paths have side effects that
# the offline gate intentionally does not drive (health-check workflow /
# browser submission). They run the readiness leg twice — harmless and keeps
# the matrix shape uniform.
DEFAULT_SMOKES: dict[str, tuple[str, str]] = {
    "board": (
        "ready to work?",
        "give me one practical next enhancement for team reliability",
    ),
    "design": (
        "ready to work?",
        "Give me one small UX improvement for Bumba's team output visibility.",
    ),
    "qa": (
        "ready to work?",
        "What's one small testing improvement we should make next to bumba-open-harness?",
    ),
    "strategy": (
        "ready to work?",
        "What product decision should we make next week?",
    ),
    "ops": (
        "ready to work?",
        "ready to work?",
    ),
    "job_search": (
        "ready to work?",
        "ready to work?",
    ),
}


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

_PROVIDER_TOKENS = (
    "provider", "openrouter", "anthropic", "openai", "401", "403", "429",
    "unauthorized", "rate limit", "model_http", "http_error", "api key",
    "connection", "network",
)
_USAGE_TOKENS = ("usage_limit", "usage policy", "usage_policy", "quota", "cap")
_TIMEOUT_TOKENS = ("timeout", "timed out", "deadline")
_SCHEMA_TOKENS = (
    "schema", "validation", "validationerror", "unexpected", "unknown department",
    "invalid", "verify", "gate",
)
_ARTIFACT_TOKENS = ("artifact", "manifest", "workspace")
_MEMORY_TOKENS = ("memory", "checkpoint", "second_brain", "second brain")


def classify_smoke_failure(exc: BaseException | str | None) -> str | None:
    """Map a failure into one of the six smoke classes.

    Precedence is deliberate: type-based matches (usage / timeout / provider
    HTTP) win over keyword matches, then keyword matches run most-specific
    first. The dead-OpenRouter 401 is a *provider* problem, not a code bug —
    so a bare "401 Unauthorized" string classifies as ``provider``.
    """
    if exc is None:
        return None

    # Type-based matches first — these are unambiguous.
    try:
        from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

        if isinstance(exc, UsageLimitExceeded):
            return "usage_policy"
        if isinstance(exc, ModelHTTPError):
            return "provider"
    except Exception:  # noqa: BLE001 — pydantic-ai may be absent in unit env
        pass
    if isinstance(exc, TimeoutError):
        return "timeout"

    text = (str(exc) if not isinstance(exc, str) else exc).lower()

    # Keyword precedence: usage > timeout > artifact > memory > schema >
    # provider. Provider is the catch-all for anything that smells like a
    # remote-service problem (incl. bare 401).
    if _any(text, _USAGE_TOKENS):
        return "usage_policy"
    if _any(text, _TIMEOUT_TOKENS):
        return "timeout"
    if _any(text, _ARTIFACT_TOKENS):
        return "artifact"
    if _any(text, _MEMORY_TOKENS):
        return "memory"
    if _any(text, _PROVIDER_TOKENS):
        return "provider"
    if _any(text, _SCHEMA_TOKENS):
        return "schema_validation"

    # Unknown — fall back to the telemetry normalizer's snake-case label so
    # the operator at least sees the exception class, then treat it as a
    # schema_validation bucket (a code-side surprise, not a provider issue).
    normalized = normalize_failure_class(exc)
    return "schema_validation" if normalized else None


def _any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


# ---------------------------------------------------------------------------
# Result data classes (immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SmokeCaseResult:
    """Outcome of one (department, leg) smoke case."""

    department: str
    leg: str  # "readiness" | "substantive"
    ok: bool
    provider_requests: int
    manifest_path: str | None
    telemetry_captured: bool
    failure_class: str | None
    error: str | None
    expected_fail: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "department": self.department,
            "leg": self.leg,
            "ok": self.ok,
            "provider_requests": self.provider_requests,
            "manifest_path": self.manifest_path,
            "telemetry_captured": self.telemetry_captured,
            "failure_class": self.failure_class,
            "error": self.error,
            "expected_fail": self.expected_fail,
        }


@dataclass(frozen=True)
class SmokeMatrixResult:
    """Aggregate of every smoke case + the release-gate verdict."""

    cases: tuple[SmokeCaseResult, ...]

    @property
    def gate_ok(self) -> bool:
        """True when every non-expected-fail case passed.

        Expected-fail cases (a declared dependency not yet landed, or a
        known-dead provider seat) do not break the gate — they are surfaced
        in the report but do not block a release that does not depend on
        them.
        """
        return all(c.ok or c.expected_fail for c in self.cases)

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_ok": self.gate_ok,
            "case_count": len(self.cases),
            "pass_count": sum(1 for c in self.cases if c.ok),
            "fail_count": sum(1 for c in self.cases if not c.ok),
            "cases": [c.to_dict() for c in self.cases],
        }


# ---------------------------------------------------------------------------
# Substantive runner — offline by default, injectable for tests
# ---------------------------------------------------------------------------

# A substantive runner takes (config, deps, prompt) and returns a TeamResult.
# The default builds a real DepartmentTeam and drives it with deterministic
# models so no live API call happens. Tests can inject a runner that raises
# to exercise failure classification.
SubstantiveRunner = Callable[
    [DepartmentConfig, BridgeDeps, str], Awaitable[TeamResult]
]


async def _default_substantive_runner(
    config: DepartmentConfig,
    deps: BridgeDeps,
    prompt: str,
) -> TeamResult:
    """Drive one offline substantive run via deterministic models.

    Mirrors the production ``DepartmentTeam.run`` path (so the manifest +
    telemetry pipeline executes for real) but overrides the chief and first
    specialist with ``FunctionModel`` instances that emit a fixed delegation
    + synthesis. No model provider is contacted.
    """
    import contextlib

    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
    )
    from pydantic_ai.models.function import FunctionModel

    from teams._team import DepartmentTeam

    team = DepartmentTeam(config, lazy_build=False)

    # Delegate to EVERY roster specialist on the first chief turn. This
    # satisfies any ``expected_min_specialists`` delegation floor —
    # including peer-deliberation teams like the Strategy Board whose floor
    # is ``len(workers)`` (a single delegation would trip Gate 8 in
    # ``teams._verify`` and surface as a schema_validation failure). A
    # standard chief+single-specialist team simply gets one delegation.
    specialist_names = tuple(emp.name for emp in config.employees)

    call_state = {"n": 0}

    async def _chief_fn(messages, info):  # noqa: ANN001
        call_state["n"] += 1
        if call_state["n"] == 1 and specialist_names:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="delegate",
                        args={
                            "specialist": name,
                            "task": "Smoke matrix substantive check.",
                        },
                    )
                    for name in specialist_names
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={
                        "answer": "smoke matrix: synthesised offline",
                        "specialist_outputs": [],
                    },
                )
            ]
        )

    async def _specialist_fn(messages, info):  # noqa: ANN001
        return ModelResponse(parts=[TextPart(content="smoke specialist ok")])

    chief_model = FunctionModel(_chief_fn, model_name="smoke-chief")
    specialist_model = FunctionModel(_specialist_fn, model_name="smoke-specialist")

    with contextlib.ExitStack() as stack:
        for name in specialist_names:
            stack.enter_context(
                team.employees[name].override(model=specialist_model)
            )
        stack.enter_context(team.manager.override(model=chief_model))
        return await team.run(prompt, deps=deps)


# ---------------------------------------------------------------------------
# Matrix driver
# ---------------------------------------------------------------------------


async def run_smoke_matrix(
    registry,
    *,
    smokes: Mapping[str, tuple[str, str]] | None = None,
    artifact_root: Path | str | None = None,
    substantive_runner: SubstantiveRunner | None = None,
    expected_fail_departments: frozenset[str] = frozenset(),
) -> SmokeMatrixResult:
    """Run the offline smoke matrix and return per-case results + a gate verdict.

    Args:
        registry: a ``DepartmentRegistry`` (or anything exposing
            ``route``, ``department_names``, ``get_config``).
        smokes: department → (readiness_prompt, substantive_prompt). Defaults
            to :data:`DEFAULT_SMOKES`.
        artifact_root: where substantive runs write their run workspace +
            manifest. When None, substantive runs skip manifest capture.
        substantive_runner: override the offline runner (tests inject one
            that raises to exercise failure classification).
        expected_fail_departments: departments whose failures should be
            marked ``expected_fail`` (declared dependency not landed) rather
            than break the gate.
    """
    matrix = dict(smokes) if smokes is not None else dict(DEFAULT_SMOKES)
    runner = substantive_runner or _default_substantive_runner
    root = Path(artifact_root).expanduser() if artifact_root is not None else None

    known = set(registry.department_names())
    cases: list[SmokeCaseResult] = []

    for department, prompts in matrix.items():
        readiness_prompt, substantive_prompt = prompts
        is_expected_fail = department in expected_fail_departments
        registered = department in known

        cases.append(
            await _run_readiness_case(
                registry, department, readiness_prompt,
                expected_fail=is_expected_fail or not registered,
            )
        )
        cases.append(
            await _run_substantive_case(
                registry, department, substantive_prompt,
                root=root, runner=runner,
                expected_fail=is_expected_fail or not registered,
                registered=registered,
            )
        )

    return SmokeMatrixResult(cases=tuple(cases))


async def _run_readiness_case(
    registry,
    department: str,
    prompt: str,
    *,
    expected_fail: bool,
) -> SmokeCaseResult:
    """Run the zero-provider readiness leg via ``registry.route``."""
    deps = _build_smoke_deps(department, artifact_root=None)
    try:
        result = await registry.route(department, prompt, deps)
    except Exception as exc:  # noqa: BLE001
        return SmokeCaseResult(
            department=department, leg="readiness", ok=False,
            provider_requests=0, manifest_path=None,
            telemetry_captured=False,
            failure_class=classify_smoke_failure(exc),
            error=f"{type(exc).__name__}: {exc}",
            expected_fail=expected_fail,
        )

    # A genuine readiness response is deterministic (Z4-01) — it never
    # invokes a model, so provider_requests is structurally 0. We also
    # guard the prompt actually matched the readiness path; if not, the
    # case is a misconfiguration the operator should see.
    matched = is_readiness_prompt(prompt)
    ok = bool(result.success and matched)
    error = None
    if not result.success:
        error = result.error
    elif not matched:
        error = f"prompt {prompt!r} did not match the readiness path"

    return SmokeCaseResult(
        department=department, leg="readiness", ok=ok,
        provider_requests=0, manifest_path=None,
        telemetry_captured=False,
        failure_class=classify_smoke_failure(error) if not ok else None,
        error=error,
        expected_fail=expected_fail,
    )


async def _run_substantive_case(
    registry,
    department: str,
    prompt: str,
    *,
    root: Path | None,
    runner: SubstantiveRunner,
    expected_fail: bool,
    registered: bool,
) -> SmokeCaseResult:
    """Run the substantive leg (real run path, deterministic models)."""
    if not registered:
        return SmokeCaseResult(
            department=department, leg="substantive", ok=False,
            provider_requests=0, manifest_path=None,
            telemetry_captured=False,
            failure_class="schema_validation",
            error=f"Unknown department: {department}",
            expected_fail=expected_fail,
        )

    # Readiness-only substantive prompt (ops/job_search) — route it through
    # the deterministic readiness path and skip the run machinery, since the
    # issue table calls for "no side effect" on those legs.
    if is_readiness_prompt(prompt):
        deps = _build_smoke_deps(department, artifact_root=None)
        try:
            result = await registry.route(department, prompt, deps)
        except Exception as exc:  # noqa: BLE001
            return SmokeCaseResult(
                department=department, leg="substantive", ok=False,
                provider_requests=0, manifest_path=None,
                telemetry_captured=False,
                failure_class=classify_smoke_failure(exc),
                error=f"{type(exc).__name__}: {exc}",
                expected_fail=expected_fail,
            )
        return SmokeCaseResult(
            department=department, leg="substantive",
            ok=bool(result.success),
            provider_requests=0, manifest_path=None,
            telemetry_captured=False,
            failure_class=(
                None if result.success
                else classify_smoke_failure(result.error)
            ),
            error=None if result.success else result.error,
            expected_fail=expected_fail,
        )

    config = registry.get_config(department)
    deps = _build_smoke_deps(department, artifact_root=root)

    try:
        result = await runner(config, deps, prompt)
    except Exception as exc:  # noqa: BLE001
        return SmokeCaseResult(
            department=department, leg="substantive", ok=False,
            provider_requests=0, manifest_path=None,
            telemetry_captured=False,
            failure_class=classify_smoke_failure(exc),
            error=f"{type(exc).__name__}: {exc}",
            expected_fail=expected_fail,
        )

    manifest_path = result.manifest_path
    telemetry_captured = result.telemetry is not None
    ok = bool(result.success)

    return SmokeCaseResult(
        department=department, leg="substantive", ok=ok,
        provider_requests=0,
        manifest_path=manifest_path,
        telemetry_captured=telemetry_captured,
        failure_class=(
            None if ok else classify_smoke_failure(result.error)
        ),
        error=None if ok else result.error,
        expected_fail=expected_fail,
    )


def _build_smoke_deps(
    department: str,
    *,
    artifact_root: Path | None,
) -> BridgeDeps:
    """Construct an offline BridgeDeps with all-mock collaborators.

    Mirrors ``z4_smoke_probe._make_probe_deps`` — production code must not
    import from ``tests/``, so the mock deps are built inline.
    """
    from unittest.mock import AsyncMock, MagicMock

    memory_store = AsyncMock()
    memory_store.get = AsyncMock(return_value=None)
    memory_store.set = AsyncMock(return_value=None)

    return BridgeDeps(
        session_id=f"z4-smoke-{department}",
        department=department,
        operator_id="z4-smoke-matrix",
        memory_store=memory_store,
        event_bus=MagicMock(),
        trust_manager=MagicMock(),
        cost_tracker=MagicMock(),
        knowledge_search=AsyncMock(return_value=[]),
        cost_limit_usd=2.0,
        artifact_root=artifact_root,
    )
