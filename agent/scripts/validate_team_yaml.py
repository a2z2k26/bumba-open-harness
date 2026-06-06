"""Validate a Zone 4 team YAML — schema check + cross-reference check.

D7.13 #1425 — frictionless team setup. The Pydantic schema in
`teams._config._RootSchema` already rejects unknown / mistyped fields
(`extra="forbid"`). This CLI adds the layer the schema can't catch:

1. **Per-employee tool key validity** — every key in `tools.per_employee:`
   matches a literal `name:` of a worker (catches typos like
   `qa-engineer` vs `qa_engineer`). Always an error.
2. **Expertise file existence** — every `expertise:` path resolves to a
   real markdown file on disk. Warning by default, error under `--strict`.
3. **System-prompt file existence** — every `system_prompt:` path resolves
   to a real markdown file on disk. Warning by default, error under
   `--strict`.
4. **VAPI tool subset** — every tool listed under `vapi.tools:` appears
   somewhere in the team's `tools` block. Warning, not error.
5. **Chief roster placeholder** (P3.6) — for delegate-mode teams (workers
   > 0) the chief's ``system_prompt`` file must contain the literal
   ``{{ROSTER}}`` placeholder so the runtime roster injection lands in
   the right place. Warning only — does not block ``--strict``. The
   runtime's `_inject_roster_into_prompt` already degrades gracefully
   (appends with a logged warning), so this is observable drift not
   load-blocking misconfiguration. The placeholder invariant is hard-
   enforced separately by
   ``tests/test_teams/test_roster.py::test_production_chief_prompt_contains_roster_placeholder``.
6. **Delegation floor** (P3.6 → activated #1645) — for delegate-mode
   teams (workers > 0) ``constraints.expected_min_specialists`` must
   be > 0 so verify_team Gate 8 enforces a delegation floor instead of
   silently allowing the chief to direct-answer. **Warning by default,
   ERROR under ``--strict``** (activated 2026-05-12 per operator policy
   call in issue #1645 + classification doc at
   ``docs/architecture/2026-05-12-1645-delegation-floor-classification.md``).
   Default-mode behaviour remains warning-only for back-compat with
   ad-hoc scaffolds; production YAMLs must declare the floor and run
   under ``--strict`` in CI.
7. **Adapter ↔ model-prefix consistency** (S2.4 #2339) — for every
   chief/worker, declared ``adapter`` must agree with the ``model:``
   string prefix: ``adapter: claude`` requires a model WITHOUT the
   ``openrouter:`` prefix; ``adapter: openrouter`` requires a model
   WITH it. Runtime routes by model-prefix (#1961), so a mismatch
   means the declared operator intent contradicts actual routing.
   **Warning by default, ERROR under ``--strict``** (S2.4 promoted
   2026-05-19 after S2.3 #2275 cleaned all production YAMLs). The
   load-time WARNING in ``teams._config._warn_adapter_model_mismatch``
   is preserved for advisory scaffolding runs; this validator check
   adds strict-mode CI enforcement.

Why missing files are warnings by default: existing teams may have stale
path references where the supporting markdown is yet to be authored. The
default-validate path is advisory so the per-team check never fails on
pre-existing drift. The `scaffold_doctor.py` command runs `--strict`
because *its* job is to surface gaps a freshly-scaffolded team must close.

Exit codes:
  0  team YAML is valid (schema + structural cross-references all pass)
  1  validation failure (schema invalid, structural error, OR --strict
     promoted a missing-file warning to an error)
  2  unexpected I/O error

Usage:
    python -m scripts.validate_team_yaml <team-name>          # validate one team (advisory file checks)
    python -m scripts.validate_team_yaml <team-name> --strict # error on missing expertise/system_prompt
    python -m scripts.validate_team_yaml --all                # validate every team in config/teams/
    python -m scripts.validate_team_yaml --check-template     # smoke-check the golden template

Smoke test: `--all` exits 0 against every team in `agent/config/teams/`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from teams._config import InvalidConfigError, load_department_config

# Repo root: agent/scripts/ → agent/ → repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TEAMS_DIR = REPO_ROOT / "agent" / "config" / "teams"
TEMPLATE_PATH = TEAMS_DIR / "_template.yaml"


@dataclass
class ValidationReport:
    """Result of validating one team YAML.

    `errors` block exit-non-zero. `warnings` are advisory and do not
    affect the exit code (e.g. VAPI tools not declared in `tools:`).
    """
    team: str
    yaml_path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _yaml_for_team(team_name: str) -> Path:
    """Resolve a team name (or path) to an absolute YAML path."""
    candidate = Path(team_name)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    direct = TEAMS_DIR / f"{team_name}.yaml"
    if direct.exists():
        return direct
    sys.stderr.write(
        f"[validate-team] ERROR: no team YAML at {direct} "
        f"(also tried {candidate})\n"
    )
    raise SystemExit(1)


def _validate_schema(yaml_path: Path, report: ValidationReport) -> object | None:
    """Parse the YAML through the strict Pydantic schema. Returns the
    `DepartmentConfig` on success, None on failure (with errors recorded).
    """
    try:
        cfg = load_department_config(yaml_path)
        return cfg
    except InvalidConfigError as exc:
        report.errors.append(f"schema: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"schema (unexpected): {exc}")
        return None


def _validate_path_exists(
    field_name: str,
    rel_path: str,
    owner: str,
    report: ValidationReport,
    *,
    strict: bool,
) -> None:
    """Check that `rel_path` resolves to an existing file.

    Resolution mirrors the runtime: paths are tried first against
    ``agent/`` (because the bridge daemon's CWD is ``agent/``, so YAMLs
    using ``config/agents/...`` resolve under ``agent/config/...``),
    then against repo root for YAMLs that already use the
    ``agent/config/...`` prefix. See ``_resolve_chief_prompt_path`` for
    the original of this fallback pattern (P3.6).

    Missing-file diagnostics are warnings unless ``strict`` is set, in
    which case they are promoted to errors (used by `scaffold_doctor.py`
    and by --strict CI gates).
    """
    if not rel_path:
        return  # empty paths are allowed by the schema (defaults to "")
    candidates: list[Path] = []
    if not rel_path.startswith("agent/"):
        candidates.append(REPO_ROOT / "agent" / rel_path)
    candidates.append(REPO_ROOT / rel_path)
    bucket = report.errors if strict else report.warnings
    full: Path | None = None
    for c in candidates:
        if c.exists():
            full = c
            break
    if full is None:
        bucket.append(
            f"{field_name}: {owner!r} references {rel_path!r} "
            f"but file does not exist (tried {', '.join(str(c) for c in candidates)})"
        )
    elif not full.is_file():
        # "Not a file" is always an error — it means the path resolves to
        # a directory or device, which the loader can't read.
        report.errors.append(
            f"{field_name}: {owner!r} references {rel_path!r} "
            f"but it is not a file"
        )


def _validate_cross_references(
    yaml_path: Path,
    cfg: object,
    report: ValidationReport,
    *,
    strict: bool,
) -> None:
    """Check expertise/system_prompt paths and per-employee tool keys."""
    # Re-parse the raw YAML for fields the DepartmentConfig hides
    # (per_employee tools, vapi tools list).
    import yaml as _yaml

    raw = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    team = raw.get("team", {})

    # 1. Chief expertise + system_prompt
    chief = team.get("chief", {})
    chief_name = chief.get("name", "<unknown-chief>")
    _validate_path_exists(
        "expertise", chief.get("expertise", ""), chief_name, report, strict=strict
    )
    _validate_path_exists(
        "system_prompt", chief.get("system_prompt", ""), chief_name, report, strict=strict
    )

    # 2. Worker expertise + system_prompt + name collection
    workers: list[dict] = team.get("workers", []) or []
    worker_names: set[str] = set()
    for w in workers:
        wname = w.get("name", "<unknown-worker>")
        worker_names.add(wname)
        _validate_path_exists(
            "expertise", w.get("expertise", ""), wname, report, strict=strict
        )
        _validate_path_exists(
            "system_prompt", w.get("system_prompt", ""), wname, report, strict=strict
        )

    # 3. Per-employee tool keys must reference real workers
    per_employee = team.get("tools", {}).get("per_employee", {}) or {}
    for emp_key in per_employee.keys():
        if emp_key not in worker_names:
            report.errors.append(
                f"tools.per_employee: key {emp_key!r} does not match any "
                f"worker name. Known workers: {sorted(worker_names) or '<none>'}"
            )

    # 4. VAPI tools — warning only — should appear under tools.common /
    # tools.department / tools.per_employee somewhere (advisory; the runtime
    # provisioning is permissive).
    vapi = team.get("vapi", {}) or {}
    if vapi.get("enabled"):
        vapi_tools = set(vapi.get("tools", []) or [])
        all_tools: set[str] = set()
        tools_block = team.get("tools", {}) or {}
        all_tools.update(tools_block.get("common", []) or [])
        all_tools.update(tools_block.get("department", []) or [])
        for emp_tools in (tools_block.get("per_employee", {}) or {}).values():
            all_tools.update(emp_tools or [])
        unknown = vapi_tools - all_tools
        for t in sorted(unknown):
            report.warnings.append(
                f"vapi.tools: {t!r} is not declared in tools.{{common,department,per_employee}} — "
                f"the VAPI receptionist may receive a tool the team's executors do not provision."
            )

    # 5/6. Delegate-mode checks (P3.6).
    #
    # A team is "delegate-mode" if it declares any workers — the chief has
    # specialists to delegate to. Single-director teams (workers: []) skip
    # both checks because there is no roster to inject and no delegation
    # floor to enforce. Both checks emit WARNINGS only (not errors, even
    # under --strict) — see the module docstring for rationale.
    if workers:
        _validate_roster_placeholder(
            chief_name=chief_name,
            system_prompt_rel=chief.get("system_prompt", ""),
            report=report,
        )
        _validate_delegation_floor(
            team_name=team.get("name", "<unknown-team>"),
            constraints=team.get("constraints", {}) or {},
            worker_count=len(workers),
            report=report,
            strict=strict,
        )

    # 7. Adapter ↔ model-prefix consistency (S2.4 #2339).
    #
    # Warning by default, ERROR under --strict. Mirrors the delegation_floor
    # promotion pattern. The load-time warning in
    # ``teams._config._warn_adapter_model_mismatch`` is preserved for
    # advisory scaffolding; this validator-layer check adds the strict CI
    # gate so future drift cannot slip past `--strict` while runtime
    # prefix-precedence masks the operator-intent contradiction.
    team_name = team.get("name", "<unknown-team>")
    _validate_adapter_model_consistency(
        team_name=team_name,
        role="chief",
        member=chief,
        report=report,
        strict=strict,
    )
    for w in workers:
        _validate_adapter_model_consistency(
            team_name=team_name,
            role="worker",
            member=w,
            report=report,
            strict=strict,
        )


def _resolve_chief_prompt_path(rel_path: str) -> Path | None:
    """Resolve a chief ``system_prompt`` path to the canonical on-disk file.

    Some team YAMLs declare the path as ``config/agents/...`` (which the
    runtime resolves against its `agent/` CWD), and others declare it as
    ``agent/config/agents/...`` (which the validator's repo-root rebase
    resolves directly). Always prefer the canonical ``agent/config/...``
    location — there is a pre-existing shadow at ``<repo>/config/...``
    that contains stale duplicates of chief prompts (a write-territory
    drift the broader cleanup will address; not P3.6's scope), and the
    runtime ALWAYS reads from `agent/config/...` because its CWD is
    `agent/`. Reading the shadow would produce false-negative warnings
    on a chief prompt that is actually well-formed.
    """
    candidates: list[Path] = []
    if not rel_path.startswith("agent/"):
        candidates.append(REPO_ROOT / "agent" / rel_path)
    candidates.append(REPO_ROOT / rel_path)
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def _validate_roster_placeholder(
    *,
    chief_name: str,
    system_prompt_rel: str,
    report: ValidationReport,
) -> None:
    """Sprint P3.6 — chief system prompt must carry ``{{ROSTER}}``.

    Always advisory (warning). The runtime injection in
    ``teams._factory._inject_roster_into_prompt`` appends the roster
    block at end-of-prompt with a logged WARN when the placeholder is
    missing, so behaviour is degraded but not load-blocking. The hard
    invariant ("every production chief prompt contains the placeholder")
    is enforced by
    ``tests/test_teams/test_roster.py::test_production_chief_prompt_contains_roster_placeholder``;
    the validator surfaces drift in third-party / scaffold-stage teams.
    """
    if not system_prompt_rel:
        # No prompt file declared — the chief uses the prompt-file default
        # (empty) and the runtime falls back to appending the roster. We
        # cannot inspect a non-existent file; skip the check.
        return
    full = _resolve_chief_prompt_path(system_prompt_rel)
    if full is None:
        # Path-existence check (#3 above) already records this drift; do
        # not double-report here.
        return
    try:
        body = full.read_text(encoding="utf-8")
    except OSError as exc:
        report.errors.append(
            f"roster_placeholder: could not read {system_prompt_rel} for "
            f"{chief_name!r}: {exc}"
        )
        return
    if "{{ROSTER}}" not in body:
        report.warnings.append(
            f"roster_placeholder: chief {chief_name!r} system_prompt "
            f"{system_prompt_rel!r} does not contain the literal '{{{{ROSTER}}}}' "
            f"placeholder; the runtime will append the roster block at end "
            f"of prompt with a degraded-injection warning (see "
            f"teams._factory._inject_roster_into_prompt)."
        )


def _validate_delegation_floor(
    *,
    team_name: str,
    constraints: dict,
    worker_count: int,
    report: ValidationReport,
    strict: bool = False,
) -> None:
    """Sprint P3.6 / activated #1645 — delegate-mode teams must declare
    a non-zero ``expected_min_specialists`` floor.

    Default mode: warning (advisory) for back-compat with ad-hoc
    scaffolds. Under ``--strict``: ERROR (activated 2026-05-12 per
    operator decision on #1645). Production YAMLs must declare the
    floor; CI runs ``--strict`` to enforce.

    Default ``expected_min_specialists = 0`` disables Gate 8 in
    ``teams._verify``, which lets a chief direct-answer instead of
    delegating. See classification doc at
    ``docs/architecture/2026-05-12-1645-delegation-floor-classification.md``
    for the migration history and per-test impact.
    """
    ems = constraints.get("expected_min_specialists", 0)
    if not isinstance(ems, int):
        report.errors.append(
            f"delegation_floor: team {team_name!r} constraints."
            f"expected_min_specialists must be an int (got {type(ems).__name__})"
        )
        return
    if ems <= 0:
        bucket = report.errors if strict else report.warnings
        bucket.append(
            f"delegation_floor: team {team_name!r} declares {worker_count} "
            f"worker(s) but constraints.expected_min_specialists is 0 — Gate 8 "
            f"in teams._verify is disabled, the chief is allowed to "
            f"direct-answer instead of delegating. Set "
            f"expected_min_specialists to a positive int (commonly 1 or "
            f"len(workers)) to enforce the delegation floor."
        )


_OPENROUTER_MODEL_PREFIX: str = "openrouter:"
_DEFAULT_ADAPTER: str = "claude"


def _validate_adapter_model_consistency(
    *,
    team_name: str,
    role: str,
    member: dict,
    report: ValidationReport,
    strict: bool,
) -> None:
    """Sprint S2.4 (#2339) — adapter ↔ model-prefix must agree.

    Default mode: warning (advisory for scaffolding). Under ``--strict``:
    ERROR (S2.4 strict-mode promotion). Mirrors the ``delegation_floor``
    pattern: same warning-vs-error bucket switching, identical strict
    semantics.

    Two mismatch shapes (matches the load-time warning in
    ``teams._config._warn_adapter_model_mismatch``):

    - ``adapter: "claude"`` (or unset, default) + ``model:`` starting with
      ``openrouter:`` — runtime routes through OpenRouter despite the
      declared ``claude`` intent (#1961).
    - ``adapter: "openrouter"`` + ``model:`` WITHOUT the ``openrouter:``
      prefix — runtime falls through to pydantic-ai's default Anthropic
      provider despite the declared ``openrouter`` intent.

    Why the validator AND ``_config.py`` both check this: the load-time
    warning surfaces in logs whenever any caller loads the YAML;
    --strict here surfaces the same mismatch as a CI gate failure so
    drift can't ship through.
    """
    name = member.get("name", "<unknown-member>")
    model = member.get("model", "")
    if not isinstance(model, str) or not model:
        return  # schema-layer validation handles empty/non-str model
    adapter = member.get("adapter", _DEFAULT_ADAPTER)
    model_has_openrouter_prefix = model.startswith(_OPENROUTER_MODEL_PREFIX)
    bucket = report.errors if strict else report.warnings
    if adapter == "claude" and model_has_openrouter_prefix:
        bucket.append(
            f"adapter_model_mismatch: team {team_name!r} {role} {name!r} "
            f"declares adapter='claude' but model={model!r} starts with "
            f"'openrouter:' — runtime routes through OpenRouter (prefix "
            f"wins, #1961). Update adapter to 'openrouter' or change the "
            f"model string to remove the prefix."
        )
    elif adapter == "openrouter" and not model_has_openrouter_prefix:
        bucket.append(
            f"adapter_model_mismatch: team {team_name!r} {role} {name!r} "
            f"declares adapter='openrouter' but model={model!r} lacks the "
            f"'openrouter:' prefix — runtime falls through to pydantic-ai's "
            f"default Anthropic provider (#1961). Add the 'openrouter:' "
            f"prefix to the model string or change adapter to 'claude'."
        )


def validate_team(yaml_path: Path, *, strict: bool = False) -> ValidationReport:
    """Run full validation (schema + cross-refs) on one YAML path.

    ``strict`` promotes missing expertise/system_prompt files from
    warnings to errors. The doctor command sets this; the per-team
    validate command leaves it false (advisory).
    """
    report = ValidationReport(team=yaml_path.stem, yaml_path=yaml_path)
    cfg = _validate_schema(yaml_path, report)
    if cfg is None:
        # Schema errors are load-blocking; cross-ref check would just add
        # noise on top. Bail with the schema diagnostic only.
        return report
    _validate_cross_references(yaml_path, cfg, report, strict=strict)
    return report


def _format_report(report: ValidationReport) -> str:
    """Render a ValidationReport for stdout."""
    lines: list[str] = []
    status = "OK" if report.ok else "FAIL"
    lines.append(f"[{status}] {report.team}  ({report.yaml_path})")
    for err in report.errors:
        lines.append(f"  ERROR: {err}")
    for warn in report.warnings:
        lines.append(f"  WARN:  {warn}")
    return "\n".join(lines)


def _all_team_yamls() -> list[Path]:
    """Return every non-template team YAML in TEAMS_DIR, sorted."""
    return sorted(p for p in TEAMS_DIR.glob("*.yaml") if not p.name.startswith("_"))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate-team-yaml",
        description=(
            "Validate a Zone 4 team YAML against the Pydantic schema and "
            "cross-reference checks (expertise/system_prompt files exist, "
            "per_employee keys match worker names)."
        ),
    )
    parser.add_argument(
        "team",
        nargs="?",
        help="Team name (e.g. 'qa') or path to a YAML file.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate every non-template team YAML in agent/config/teams/.",
    )
    parser.add_argument(
        "--check-template",
        action="store_true",
        help="Smoke-check the golden-path template at config/teams/_template.yaml.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Promote missing expertise/system_prompt files from warnings "
            "to errors. Used by scaffold_doctor.py."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.check_template:
        if not TEMPLATE_PATH.exists():
            sys.stderr.write(f"[validate-team] ERROR: template not found at {TEMPLATE_PATH}\n")
            return 1
        # The template references placeholder paths that don't exist
        # (`agent/config/expertise/updatable/example-chief.md` etc).
        # That's intentional — the template is a shape contract, not a
        # working team. Run with strict=False so the smoke check
        # validates the schema + structural cross-refs only.
        report = validate_team(TEMPLATE_PATH, strict=False)
        sys.stdout.write(_format_report(report) + "\n")
        return 0 if report.ok else 1

    if args.all:
        reports = [validate_team(p, strict=args.strict) for p in _all_team_yamls()]
        for r in reports:
            sys.stdout.write(_format_report(r) + "\n")
        failed = [r for r in reports if not r.ok]
        sys.stdout.write(
            f"\n[validate-team] {len(reports) - len(failed)}/{len(reports)} OK"
            + (f", {len(failed)} FAILED" if failed else "")
            + "\n"
        )
        return 0 if not failed else 1

    if not args.team:
        parser.error("must pass <team> or --all or --check-template")

    yaml_path = _yaml_for_team(args.team)
    report = validate_team(yaml_path, strict=args.strict)
    sys.stdout.write(_format_report(report) + "\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
