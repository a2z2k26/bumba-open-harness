"""Z4-09 tests for loading compact governance bundles into prompts."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from teams._factory import _load_system_prompt
from teams._governance import (
    GOVERNANCE_LINE_CAP,
    load_governance_bundle,
    resolve_governance_bundle_path,
)
from teams._types import AgentSpec


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _spec(name: str = "strategy-product-chief", system_prompt: Path | None = None):
    return AgentSpec(
        name=name,
        model="anthropic:claude-sonnet-4-6",
        role="chief",
        system_prompt_path=str(system_prompt or ""),
    )


def test_load_governance_bundle_orders_files(tmp_path: Path) -> None:
    root = tmp_path / "governance"
    agent_dir = root / "zone4" / "strategy" / "strategy-product-chief"
    _write(agent_dir / "CLAUDE.md", "claude rules")
    _write(agent_dir / "SOUL.md", "soul rules")
    _write(agent_dir / "ARTIFACTS.md", "artifact rules")

    text = load_governance_bundle(
        root,
        department="strategy",
        agent_name="strategy-product-chief",
        zone=4,
    )

    assert text.index("claude rules") < text.index("soul rules")
    assert text.index("soul rules") < text.index("artifact rules")


def test_load_governance_bundle_caps_total_lines(tmp_path: Path) -> None:
    root = tmp_path / "governance"
    agent_dir = root / "zone4" / "strategy" / "strategy-product-chief"
    _write(
        agent_dir / "CLAUDE.md",
        "\n".join(f"line {i}" for i in range(GOVERNANCE_LINE_CAP + 20)),
    )

    text = load_governance_bundle(
        root,
        department="strategy",
        agent_name="strategy-product-chief",
        zone=4,
    )

    assert len(text.splitlines()) == GOVERNANCE_LINE_CAP


def test_missing_governance_bundle_logs_info(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="teams._governance"):
        text = load_governance_bundle(
            tmp_path / "governance",
            department="design",
            agent_name="design-chief",
            zone=4,
        )

    assert text == ""
    assert any("governance.bundle_missing" in r.message for r in caplog.records)


def test_resolve_governance_bundle_path_includes_zone_department_and_agent(
    tmp_path: Path,
) -> None:
    path = resolve_governance_bundle_path(
        tmp_path / "governance",
        department="strategy",
        agent_name="strategy-product-chief",
        zone=4,
    )

    assert path == (
        tmp_path
        / "governance"
        / "zone4"
        / "strategy"
        / "strategy-product-chief"
    )


def test_load_system_prompt_inserts_governance_after_doctrine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "governance"
    agent_dir = root / "zone4" / "strategy" / "strategy-product-chief"
    _write(agent_dir / "CLAUDE.md", "governance claude")
    _write(agent_dir / "SOUL.md", "governance soul")
    prompt = _write(tmp_path / "prompt.md", "You are the strategy chief.")
    monkeypatch.setattr("teams._factory._GOVERNANCE_ROOT", root)

    text = _load_system_prompt(
        _spec(system_prompt=prompt),
        tier="chief",
        department="strategy",
        zone=4,
    )

    assert text.index("# Chief Doctrine") < text.index("governance claude")
    assert text.index("governance soul") < text.index("You are the strategy chief.")


def test_load_system_prompt_without_bundle_keeps_base_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = _write(tmp_path / "prompt.md", "You are the design chief.")
    monkeypatch.setattr("teams._factory._GOVERNANCE_ROOT", tmp_path / "governance")

    text = _load_system_prompt(
        _spec(name="design-chief", system_prompt=prompt),
        tier="chief",
        department="design",
        zone=4,
    )

    assert text.startswith("# Chief Doctrine")
    assert text.endswith("You are the design chief.")
