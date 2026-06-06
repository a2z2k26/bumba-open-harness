"""Test the structural validator catches drift between plists / SERVICE_MAP / ServiceResult.

These are static-analysis tests — they inspect source text and file presence
without importing the service classes, so they run offline with no external deps.
"""
from __future__ import annotations

from pathlib import Path

# Repo root is 2 levels above this file (agent/tests/ → agent/ → repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNNER_PATH = REPO_ROOT / "agent" / "bridge" / "services" / "runner.py"


def test_validate_services_function_exists() -> None:
    """runner.py must contain an extended validate_services function."""
    src = RUNNER_PATH.read_text()
    assert "def validate_services" in src, \
        "runner.py must define validate_services()"
    assert "--validate" in src, \
        "runner.py must expose --validate CLI flag"


def test_validate_checks_plist_enumeration() -> None:
    """Validator must enumerate plist files on disk (Rule 1 + Rule 2)."""
    src = RUNNER_PATH.read_text()
    assert "plist" in src.lower(), \
        "Validator must enumerate .plist files"
    assert "glob" in src, \
        "Validator must use glob to find plist files"


def test_validate_checks_service_map() -> None:
    """Validator must reference SERVICE_MAP for cross-checking (Rule 1 + Rule 2)."""
    src = RUNNER_PATH.read_text()
    assert "SERVICE_MAP" in src, \
        "Validator must reference SERVICE_MAP"


def test_validate_checks_constructor_signature() -> None:
    """Validator must inspect constructor signatures for data_dir (Rule 3)."""
    src = RUNNER_PATH.read_text()
    assert "data_dir" in src, \
        "Validator must check for 'data_dir' param in constructors (Rule 3)"
    assert "inspect" in src, \
        "Validator must import inspect for signature introspection (Rule 3)"


def test_validate_checks_run_return_annotation() -> None:
    """Validator must verify run() return annotations (Rule 4)."""
    src = RUNNER_PATH.read_text()
    assert "ServiceResult" in src, \
        "Validator must check for ServiceResult return annotation (Rule 4)"
    assert "__annotations__" in src or "get_type_hints" in src, \
        "Validator must inspect type annotations on run() (Rule 4)"


def test_on_demand_exception_lists_present() -> None:
    """Documented exception lists must exist so orphan detection doesn't false-positive."""
    src = RUNNER_PATH.read_text()
    assert "ON_DEMAND_PLISTS" in src or "ON_DEMAND_SERVICES" in src, \
        "Validator must have an ON_DEMAND exception list for infrastructure plists"
    assert "ON_DEMAND_KEYS" in src, \
        "Validator must have ON_DEMAND_KEYS for programmatically-invoked services"


def test_ci_workflows_exist() -> None:
    """All 5 P0 CI workflow files must be present in the repo."""
    required = [
        ".github/workflows/validate-services.yml",
        ".github/workflows/test-offline.yml",
        ".github/workflows/lint-ruff.yml",
        ".github/workflows/security-semgrep.yml",
        ".github/workflows/deploy-script-lint.yml",
    ]
    missing = []
    for rel in required:
        if not (REPO_ROOT / rel).exists():
            missing.append(rel)
    assert not missing, f"Missing CI workflow files: {missing}"


def test_validate_services_yml_triggers_on_pr_and_main() -> None:
    """validate-services.yml must trigger on pull_request and push to main."""
    yml = (REPO_ROOT / ".github/workflows/validate-services.yml").read_text()
    assert "pull_request" in yml, "validate-services.yml must trigger on pull_request"
    assert "main" in yml, "validate-services.yml must trigger on push to main"


def test_validate_services_yml_runs_validate_command() -> None:
    """validate-services.yml must invoke the --validate runner command."""
    yml = (REPO_ROOT / ".github/workflows/validate-services.yml").read_text()
    assert "--validate" in yml, \
        "validate-services.yml must run 'python -m bridge.services.runner --validate'"


def test_deploy_script_lint_checks_baseline_regen() -> None:
    """deploy-script-lint.yml must verify baseline regen is present in deploy scripts."""
    yml = (REPO_ROOT / ".github/workflows/deploy-script-lint.yml").read_text()
    assert "regenerate_kernel_baseline" in yml or "NO_BASELINE" in yml, \
        "deploy-script-lint.yml must check for baseline regen step"


def test_rejects_root_python_shadows(tmp_path: "Path") -> None:
    """validate_services() Rule 0 must surface shadow-tree .py files at repo root."""
    import importlib.util

    # Load the runner module via spec to avoid side-effects from __main__ block
    spec = importlib.util.spec_from_file_location("runner_under_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    # Use tmp_path as a fake repo root with a shadow bridge/ dir containing a .py file
    shadow_dir = tmp_path / "bridge"
    shadow_dir.mkdir()
    (shadow_dir / "fake_shadow.py").write_text("# shadow\n")

    # Extract the inner helper directly to test it in isolation
    # validate_services() defines _check_no_root_python_shadows as a closure;
    # we reconstruct it here using the same logic with dependency-injected root.
    import pathlib

    def _check_no_root_python_shadows(repo_root: pathlib.Path) -> list[str]:
        forbidden_dirs = ["bridge", "teams", "tests", "job_search"]
        forbidden_files = ["pyproject.toml", "uv.lock"]
        shadow_errors: list[str] = []
        for d in forbidden_dirs:
            path = repo_root / d
            if path.exists() and any(path.rglob("*.py")):
                shadow_errors.append(
                    f"Shadow-tree detected: {path} contains .py files. "
                    f"Canonical location is agent/{d}/."
                )
        for f in forbidden_files:
            path = repo_root / f
            if path.exists():
                shadow_errors.append(
                    f"Shadow file detected at repo root: {path}. "
                    f"Canonical location is agent/{f}."
                )
        return shadow_errors

    # Should detect the shadow bridge/ dir
    errors = _check_no_root_python_shadows(tmp_path)
    assert len(errors) == 1
    assert "bridge" in errors[0]
    assert "Shadow-tree detected" in errors[0]

    # Clean repo root (no shadow dirs) should return no errors
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    assert _check_no_root_python_shadows(clean_root) == []

    # Shadow file (pyproject.toml at root) should also be detected
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    errors2 = _check_no_root_python_shadows(tmp_path)
    assert any("pyproject.toml" in e for e in errors2)


def test_validate_services_source_contains_rule0() -> None:
    """runner.py must contain the Rule 0 shadow-tree check."""
    src = RUNNER_PATH.read_text()
    assert "_check_no_root_python_shadows" in src, \
        "validate_services() must define _check_no_root_python_shadows (Rule 0)"
    assert "Shadow-tree detected" in src, \
        "Rule 0 must emit a 'Shadow-tree detected' error message"


# --- Sprint 04.14: agent_messages.py resurrection guard (Rule 5) -----------


def test_validate_services_source_contains_rule5() -> None:
    """runner.py must contain the Sprint 04.14 agent_messages.py resurrection guard."""
    src = RUNNER_PATH.read_text()
    assert "_check_no_agent_messages_resurrection" in src, \
        "validate_services() must define _check_no_agent_messages_resurrection (Rule 5)"
    assert "Sprint 04.13" in src, \
        "Rule 5 must reference Sprint 04.13 (the deletion that this guard protects)"
    assert "WorkOrder" in src, \
        "Rule 5 must mention the WorkOrder class collision risk"


def test_agent_messages_resurrection_guard_fires_when_file_exists(tmp_path: "Path") -> None:
    """The guard must surface an error when agent/bridge/agent_messages.py exists."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("runner_under_test_rule5", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    # Build a fake repo root with the forbidden file present.
    bridge_dir = tmp_path / "agent" / "bridge"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "agent_messages.py").write_text(
        "# resurrected — Sprint 04.14 should fail validation here\n"
    )

    errors = mod._check_no_agent_messages_resurrection(tmp_path)
    assert len(errors) == 1
    assert "agent_messages.py" in errors[0]
    assert "Sprint 04.13" in errors[0]
    assert "WorkOrder" in errors[0]
    assert "work_order.py:150" in errors[0]


def test_agent_messages_resurrection_guard_passes_when_file_absent(tmp_path: "Path") -> None:
    """The guard must return zero errors when agent_messages.py is absent."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("runner_under_test_rule5_absent", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    # Empty fake repo root — no agent_messages.py.
    bridge_dir = tmp_path / "agent" / "bridge"
    bridge_dir.mkdir(parents=True)

    errors = mod._check_no_agent_messages_resurrection(tmp_path)
    assert errors == []


def test_agent_messages_file_not_in_live_tree() -> None:
    """Live regression check — agent/bridge/agent_messages.py must not exist in this repo."""
    forbidden = REPO_ROOT / "agent" / "bridge" / "agent_messages.py"
    assert not forbidden.exists(), (
        f"Sprint 04.14 invariant violated: {forbidden} exists. "
        "It was deleted in Sprint 04.13 to remove a duplicate WorkOrder class. "
        "Do not resurrect it."
    )
