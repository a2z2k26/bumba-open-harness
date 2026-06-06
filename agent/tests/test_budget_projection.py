"""Tests for token budget pre-turn projection."""
from __future__ import annotations

from bridge.budget import project_turn_cost


class TestProjectTurnCost:
    def test_haiku_projection(self):
        cost = project_turn_cost("haiku", estimated_input_tokens=1000)
        # haiku: $0.25/1M in, $1.25/1M out
        # Assume 1.5x output ratio: 1000 in + 1500 out
        # = (1000 * 0.25 + 1500 * 1.25) / 1_000_000
        # = (250 + 1875) / 1_000_000 = 0.002125
        assert 0.001 < cost < 0.01

    def test_sonnet_projection(self):
        cost = project_turn_cost("sonnet", estimated_input_tokens=5000)
        # sonnet: $3/1M in, $15/1M out, 2x ratio
        # = (5000 * 3 + 10000 * 15) / 1_000_000
        # = (15000 + 150000) / 1_000_000 = 0.165
        assert 0.10 < cost < 0.25

    def test_opus_projection(self):
        cost = project_turn_cost("opus", estimated_input_tokens=5000)
        # opus: $15/1M in, $75/1M out, 3x ratio
        # Much more expensive
        assert cost > 0.30

    def test_unknown_model_defaults_to_sonnet(self):
        cost = project_turn_cost("unknown-model", estimated_input_tokens=1000)
        sonnet_cost = project_turn_cost("sonnet", estimated_input_tokens=1000)
        assert cost == sonnet_cost

    def test_zero_tokens_returns_zero(self):
        assert project_turn_cost("haiku", estimated_input_tokens=0) == 0.0
