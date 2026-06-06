"""Tests for modality supplement loading."""

from pathlib import Path

import pytest

from bridge.modality_loader import ModalityLoader, Modality, load_for_intent


@pytest.fixture
def modalities_dir(tmp_path: Path) -> Path:
    """Create test modality supplement files."""
    modalities = tmp_path / "modalities"
    modalities.mkdir()
    (modalities / "engineer.md").write_text("# Engineer\nTest content")
    (modalities / "orchestrator.md").write_text("# Orchestrator\nTest content")
    (modalities / "pa.md").write_text("# PA\nTest content")
    (modalities / "communicator.md").write_text("# Communicator\nTest content")
    return modalities


def test_modality_enum_values() -> None:
    assert Modality.ENGINEER.value == "engineer"
    assert Modality.ORCHESTRATOR.value == "orchestrator"
    assert Modality.PA.value == "pa"
    assert Modality.COMMUNICATOR.value == "communicator"


def test_load_supplement(modalities_dir: Path) -> None:
    loader = ModalityLoader(modalities_dir)
    content = loader.load_supplement(Modality.ENGINEER)
    assert "# Engineer" in content
    assert "Test content" in content


def test_load_supplement_missing_file(tmp_path: Path) -> None:
    loader = ModalityLoader(tmp_path)
    content = loader.load_supplement(Modality.ENGINEER)
    assert content == ""


def test_activate_modality(modalities_dir: Path) -> None:
    loader = ModalityLoader(modalities_dir)
    loader.activate(Modality.ENGINEER)
    assert loader.active_modality == Modality.ENGINEER
    assert "# Engineer" in loader.active_supplement


def test_activate_replaces_previous(modalities_dir: Path) -> None:
    loader = ModalityLoader(modalities_dir)
    loader.activate(Modality.ENGINEER)
    loader.activate(Modality.PA)
    assert loader.active_modality == Modality.PA
    assert "# PA" in loader.active_supplement
    assert "# Engineer" not in loader.active_supplement


def test_deactivate(modalities_dir: Path) -> None:
    loader = ModalityLoader(modalities_dir)
    loader.activate(Modality.ENGINEER)
    loader.deactivate()
    assert loader.active_modality is None
    assert loader.active_supplement == ""


def test_default_modality_is_engineer(modalities_dir: Path) -> None:
    loader = ModalityLoader(modalities_dir, default=Modality.ENGINEER)
    assert loader.active_modality == Modality.ENGINEER
    assert "# Engineer" in loader.active_supplement


def test_orchestrator_extends_engineer(modalities_dir: Path) -> None:
    """Orchestrator modality should include both engineer and orchestrator supplements."""
    loader = ModalityLoader(modalities_dir)
    loader.activate(Modality.ORCHESTRATOR)
    assert "# Engineer" in loader.active_supplement
    assert "# Orchestrator" in loader.active_supplement


# -- D1.3 tests: load_for_intent convenience function --

def test_load_for_intent_returns_preamble(modalities_dir: Path) -> None:
    """load_for_intent returns supplement text for a known modality name."""
    preamble = load_for_intent("engineer", modalities_dir)
    assert preamble != ""
    assert "# Engineer" in preamble


def test_load_for_intent_unknown_returns_empty(modalities_dir: Path) -> None:
    """load_for_intent returns empty string for an unrecognised intent."""
    preamble = load_for_intent("totally_unknown_intent", modalities_dir)
    assert preamble == ""


def test_load_for_intent_none_returns_empty(modalities_dir: Path) -> None:
    """load_for_intent returns empty string when intent is None."""
    preamble = load_for_intent(None, modalities_dir)
    assert preamble == ""


def test_load_for_intent_communicator(modalities_dir: Path) -> None:
    """load_for_intent returns communicator supplement for design-class intent."""
    preamble = load_for_intent("communicator", modalities_dir)
    assert "# Communicator" in preamble


def test_load_for_intent_missing_file(tmp_path: Path) -> None:
    """load_for_intent returns empty string when supplement file does not exist."""
    # tmp_path has no .md files — supplement will be missing
    preamble = load_for_intent("engineer", tmp_path)
    assert preamble == ""


def test_load_for_intent_pa(modalities_dir: Path) -> None:
    """load_for_intent returns pa supplement for strategy-class intent."""
    preamble = load_for_intent("pa", modalities_dir)
    assert "# PA" in preamble
