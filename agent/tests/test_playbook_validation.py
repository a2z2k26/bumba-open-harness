"""End-to-end validation of the team-playbook recipe (Z4-S50 #1397).

This test walks the entire ``docs/zone4/team-playbook.md`` recipe from
scaffold through to verifier gates, against a TestModel chief. It is the
canonical proof that an engineer following the playbook end-to-end can
produce a working department team without writing any production team
artefacts.

Recipe walked:

    Step 1  scripts/scaffold_zone4.py chief-specialist <slug>
    Step 2  assert 5 expected files written
    Step 3  scripts/validate_team_yaml.py <slug> --strict   exit 0
    Step 4  scripts/scaffold_doctor.py <slug>               exit 0
    Step 5  load via teams._registry.DepartmentRegistry, build via
            teams._factory.build_manager_agent, override chief with
            pydantic_ai.models.test.TestModel, run end-to-end
    Step 6  teams._verify.verify_team_result — assert all 8 gates pass

The scaffold tooling writes to ``REPO_ROOT/agent/config/...``. We
``monkeypatch`` the module-level ``REPO_ROOT`` / ``TEAMS_DIR`` /
``TEMPLATE_PATH`` constants so every byte lands in ``tmp_path`` —
production team YAMLs are never touched.

No live API calls. The chief is overridden with a deterministic
``FunctionModel`` that invokes the scaffolded specialist once, and the
specialist is overridden with a deterministic text model, so the run
completes in milliseconds while still satisfying the delegation floor.

Authority note (Z4-S50 spec): if the scaffold tooling does not compose
cleanly with the verifier under TestModel, that is a finding, not a
test failure to suppress. Surface it in the PR body.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

# Source repo root, used to copy the golden _template.yaml into tmp_path so
# scaffold_doctor's template-field-set diff has something to compare against.
_SOURCE_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_TEMPLATE = (
    _SOURCE_REPO_ROOT / "agent" / "config" / "teams" / "_template.yaml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patched_repo_root(fake_root: Path):
    """Return a context-manager stack that redirects every scaffold/validate/
    doctor module-level path constant at ``fake_root``.

    The three scripts each cache their own ``REPO_ROOT`` / ``TEAMS_DIR`` /
    ``TEMPLATE_PATH`` at import time. ``validate_team_yaml`` is the source
    of truth — ``scaffold_doctor`` imports the same names — but
    ``patch.object`` only updates the binding on the named module, so all
    three must be patched explicitly.
    """
    import scripts.scaffold_zone4 as scaffold_mod
    import scripts.scaffold_doctor as doctor_mod
    import scripts.validate_team_yaml as validate_mod

    teams_dir = fake_root / "agent" / "config" / "teams"
    template_path = teams_dir / "_template.yaml"

    return [
        patch.object(scaffold_mod, "REPO_ROOT", fake_root),
        patch.object(scaffold_mod, "TEAMS_DIR", teams_dir),
        patch.object(validate_mod, "REPO_ROOT", fake_root),
        patch.object(validate_mod, "TEAMS_DIR", teams_dir),
        patch.object(validate_mod, "TEMPLATE_PATH", template_path),
        patch.object(doctor_mod, "REPO_ROOT", fake_root),
        patch.object(doctor_mod, "TEAMS_DIR", teams_dir),
        patch.object(doctor_mod, "TEMPLATE_PATH", template_path),
    ]


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """Build a tmp REPO_ROOT skeleton with the golden template copied in.

    scaffold_zone4 will create the team YAML + expertise + system_prompt
    files inside this tree; nothing escapes ``tmp_path``.
    """
    teams_dir = tmp_path / "agent" / "config" / "teams"
    expertise_dir = tmp_path / "agent" / "config" / "expertise" / "updatable"
    agents_dir = tmp_path / "agent" / "config" / "agents" / "zone4"
    teams_dir.mkdir(parents=True)
    expertise_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)

    # Copy the golden _template.yaml so scaffold_doctor's field-set diff has
    # a real template to read. (Without it, the doctor logs a WARN and skips
    # the diff — still passes — but copying matches the production posture.)
    if _SOURCE_TEMPLATE.exists():
        shutil.copy2(_SOURCE_TEMPLATE, teams_dir / "_template.yaml")

    return tmp_path


# ---------------------------------------------------------------------------
# The single end-to-end test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_playbook_recipe_end_to_end(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walk the full team-playbook recipe and assert every step succeeds.

    This is the contract test for Z4-S00 (#1384) — the playbook promises
    that a chief-specialist team can be authored, validated, doctored, and
    run against a deterministic chief in one pass. If any step regresses,
    this test fails before the regression escapes to a real new department.
    """
    slug = "playbook-test"

    # The factory's _load_system_prompt and _load_expertise resolve the
    # YAML's repo-relative paths from the current working directory. Move
    # the test's CWD into the tmp_path so 'agent/config/...' paths in the
    # scaffolded YAML resolve against fake_repo, not the real repo. The
    # alternative — rewriting the scaffolded YAML to absolute paths — would
    # be a stronger test of YAML mutation, but the playbook-level guarantee
    # is "scaffold + run from repo root works", and chdir matches that
    # working assumption exactly.
    monkeypatch.chdir(fake_repo)

    import scripts.scaffold_zone4 as scaffold_mod
    import scripts.scaffold_doctor as doctor_mod
    import scripts.validate_team_yaml as validate_mod

    # ----- Step 1: scaffold ------------------------------------------------
    with _stack_patches(_patched_repo_root(fake_repo)):
        rc = scaffold_mod.main(["chief-specialist", slug])
    assert rc == 0, f"scaffold_zone4 chief-specialist exit code was {rc}"

    # ----- Step 2: assert 5 expected files were created -------------------
    expected_files = [
        fake_repo / f"agent/config/teams/{slug}.yaml",
        fake_repo / f"agent/config/expertise/updatable/{slug}-chief.md",
        fake_repo / f"agent/config/agents/zone4/{slug}/{slug}-chief.md",
        fake_repo / f"agent/config/expertise/updatable/{slug}-specialist.md",
        fake_repo / f"agent/config/agents/zone4/{slug}/{slug}-specialist.md",
    ]
    missing = [str(p) for p in expected_files if not p.exists()]
    assert not missing, f"scaffold did not produce: {missing}"

    # ----- Step 3: validate_team_yaml --strict -----------------------------
    with _stack_patches(_patched_repo_root(fake_repo)):
        rc = validate_mod.main([slug, "--strict"])
    assert rc == 0, (
        "validate_team_yaml --strict failed for the freshly-scaffolded team. "
        "The playbook step 3 must exit 0; if it doesn't, the scaffold "
        "tooling produced a YAML that the strict validator rejects."
    )

    # ----- Step 4: scaffold_doctor (first-run readiness) -------------------
    with _stack_patches(_patched_repo_root(fake_repo)):
        rc = doctor_mod.main([slug])
    assert rc == 0, (
        "scaffold_doctor failed for the freshly-scaffolded team. The "
        "playbook step 4 must exit 0; the scaffold should produce a team "
        "that is first-run ready out of the box."
    )

    # ----- Step 5: registry load → factory build → run via TestModel ------
    from teams._registry import DepartmentRegistry
    from teams._team import DepartmentTeam

    teams_dir = fake_repo / "agent/config/teams"
    registry = DepartmentRegistry.from_directory(teams_dir)
    assert slug in registry.department_names(), (
        f"DepartmentRegistry did not discover {slug!r} from {teams_dir}; "
        f"discovered: {registry.department_names()}"
    )
    config = registry.get_config(slug)

    # Build a fresh DepartmentTeam (lazy_build=False so the manager agent is
    # constructed before we attach the override). load_department_config has
    # already validated the YAML; this exercises build_manager_agent +
    # build_employee_agents end-to-end.
    team = DepartmentTeam(config=config, lazy_build=False)

    expected_answer = "playbook validation: synthesis"

    # Local import to avoid coupling test fixtures to other test modules at
    # module-import time.
    from tests.test_teams.conftest import (
        make_chief_delegating_model,
        make_deps,
        make_specialist_text_model,
    )

    deps = make_deps(session_id="playbook-test", department=slug)

    specialist_name = f"{slug}-specialist"
    chief_model = make_chief_delegating_model(
        [(specialist_name, "Validate the playbook specialist path.")],
        final_answer=expected_answer,
    )
    specialist_model = make_specialist_text_model("playbook specialist: ok")

    with team.employees[specialist_name].override(model=specialist_model):
        with team.manager.override(model=chief_model):
            result = await team.run(
                "Validate the playbook recipe end-to-end.", deps=deps
            )

    # ----- Step 6: verify_team_result — all 8 gates must pass -------------
    from teams._verify import verify_team_result

    violations = verify_team_result(result, config)
    assert not violations, (
        "verify_team_result returned non-empty violations for a "
        "playbook-scaffolded team. This means the scaffold produces a "
        "YAML or runtime shape that the gates reject. Violations:\n  - "
        + "\n  - ".join(violations)
    )

    # Sanity: the deterministic chief model's structured output flowed through.
    assert expected_answer in result.manager_output, (
        f"manager_output did not contain TestModel synthesis text. Got: "
        f"{result.manager_output!r}"
    )
    assert result.success is True, (
        f"team.run reported success=False; error: {result.error!r}"
    )


# ---------------------------------------------------------------------------
# Patch-stack helper (small, local — not worth a fixture)
# ---------------------------------------------------------------------------


class _stack_patches:
    """Apply a list of ``unittest.mock.patch`` objects as a single context.

    ``contextlib.ExitStack`` would also work, but a tiny purpose-built
    helper keeps the test surface free of stdlib indirection — every reader
    can see exactly what's being patched.
    """

    def __init__(self, patches: list) -> None:
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for p in reversed(self._patches):
            p.stop()
        return False
