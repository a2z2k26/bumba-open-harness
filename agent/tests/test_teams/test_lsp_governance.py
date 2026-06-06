"""Governance + capability alignment for the LSP track (Z4-21, #2447).

Asserts:
- QA and Ops governance bundles instruct LSP-first code inspection, naming the
  exact `lsp_*` tools so specialists are not sent to a dead tool.
- The QA/Ops capability manifests grant LSP tools only to code-oriented roles.
- Strategy and Design manifests do NOT receive LSP grants by default.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import yaml

AGENT_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_ROOT = AGENT_ROOT / "config" / "governance" / "zone4"
CAPABILITY_ROOT = AGENT_ROOT / "config" / "capabilities" / "zone4"

LSP_TOOLS = ("lsp_find_definition", "lsp_find_references", "lsp_diagnostics")

QA_CHIEF_GOVERNANCE = GOVERNANCE_ROOT / "qa" / "qa-chief" / "CLAUDE.md"
OPS_CHIEF_GOVERNANCE = GOVERNANCE_ROOT / "ops" / "ops-chief" / "CLAUDE.md"

# Code-oriented roles that SHOULD have LSP grants.
EXPECTED_LSP_ROLES = {
    "qa.yaml": {"qa-engineer", "code-reviewer", "automation-engineer"},
    "ops.yaml": {"ops-devops-specialist", "ops-sre-engineer"},
}


def test_qa_governance_names_lsp_tools() -> None:
    body = QA_CHIEF_GOVERNANCE.read_text(encoding="utf-8")
    assert "When inspecting code" in body
    for tool in LSP_TOOLS:
        assert tool in body, f"qa governance missing {tool}"


def test_ops_governance_names_lsp_tools() -> None:
    body = OPS_CHIEF_GOVERNANCE.read_text(encoding="utf-8")
    assert "When inspecting code" in body
    for tool in LSP_TOOLS:
        assert tool in body, f"ops governance missing {tool}"


def test_lsp_grants_only_to_code_oriented_qa_ops_roles() -> None:
    for manifest_name, expected_roles in EXPECTED_LSP_ROLES.items():
        granted = _roles_with_lsp(CAPABILITY_ROOT / manifest_name)
        assert granted == expected_roles, (
            f"{manifest_name}: LSP-granted roles {granted} != expected "
            f"{expected_roles}"
        )


def test_strategy_and_design_have_no_lsp_grants() -> None:
    for manifest_name in ("strategy.yaml", "design.yaml"):
        granted = _roles_with_lsp(CAPABILITY_ROOT / manifest_name)
        assert granted == set(), (
            f"{manifest_name} must not grant LSP tools by default; got {granted}"
        )


def test_lsp_not_in_department_defaults() -> None:
    """LSP must be a per-role grant, never a department-wide default."""
    for path in sorted(CAPABILITY_ROOT.glob("*.yaml")):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        defaults = manifest.get("defaults", {}) if isinstance(manifest, dict) else {}
        default_tools = set(_string_items(defaults.get("tools")))
        assert default_tools.isdisjoint(LSP_TOOLS), (
            f"{path.name}: LSP tools must not be in department defaults"
        )


def _roles_with_lsp(manifest_path: Path) -> set[str]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        return set()
    roles: set[str] = set()
    for section in ("chief", "specialists"):
        block = manifest.get(section) or {}
        if not isinstance(block, Mapping):
            continue
        for role, grant in block.items():
            if not isinstance(grant, Mapping):
                continue
            tools = set(_string_items(grant.get("tools")))
            if tools & set(LSP_TOOLS):
                roles.add(str(role))
    return roles


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    seq = cast(Sequence[object], value)
    return tuple(item for item in seq if isinstance(item, str))
