"""Tests for TeamOutput pydantic model (sprint B2.2)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from teams._types import TeamOutput


def test_team_output_minimal() -> None:
    output = TeamOutput(answer="The answer.")
    assert output.answer == "The answer."
    assert output.handoff_id is None
    assert output.confidence == 1.0
    assert output.specialist_outputs == []


def test_team_output_full() -> None:
    output = TeamOutput(
        answer="Synthesis of board decision.",
        handoff_id="abc123def456",
        confidence=0.82,
        specialist_outputs=["revenue: X", "contrarian: Y"],
    )
    assert output.handoff_id == "abc123def456"
    assert output.confidence == 0.82
    assert len(output.specialist_outputs) == 2


def test_team_output_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        TeamOutput(answer="x", confidence=1.5)
    with pytest.raises(ValidationError):
        TeamOutput(answer="x", confidence=-0.1)


def test_team_output_public_import() -> None:
    """Verify TeamOutput is exported from the teams package."""
    from teams import TeamOutput as public_TeamOutput
    assert public_TeamOutput is TeamOutput


def test_team_output_extra_fields_forbidden() -> None:
    """Extra fields must be rejected to surface YAML typos early."""
    with pytest.raises(ValidationError):
        TeamOutput(answer="x", unknown_field="bad")


def test_team_output_confidence_boundary_values() -> None:
    """0.0 and 1.0 must be valid boundaries."""
    out_zero = TeamOutput(answer="x", confidence=0.0)
    assert out_zero.confidence == 0.0
    out_one = TeamOutput(answer="x", confidence=1.0)
    assert out_one.confidence == 1.0
