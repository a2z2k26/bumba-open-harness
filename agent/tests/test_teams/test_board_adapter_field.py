"""Sprint 04.05 — extend board.yaml schema with `adapter` field.

Tests the optional cross-vendor `adapter` knob added to each Board member
in `agent/config/teams/board.yaml` and the loader extension in
`agent/teams/_config.py`.

Acceptance criteria from spec-04-05:
- `test_team_config_loads_4_member_cross_vendor_board`
  → loads a small fixture mixing claude + openrouter members.
- `test_team_config_defaults_adapter_to_claude_when_omitted`
  → omitted `adapter:` keys round-trip to the default value.
- `test_team_config_existing_6_members_unchanged_after_extension`
  → loading the real board.yaml preserves all five existing fields per
    member (model, expertise, system_prompt, domain, role) and surfaces
    the new adapter field.
- Plus: invalid adapter values fail fast, default board.yaml has 9
  members (6 existing + 3 new cross-vendor seats).

Wiring tests for `test_convening_board_contacts_all_members_in_parallel`
and `test_single_member_failure_doesnt_abort_board` are out of scope
for this sprint — they belong with the agent_router.py wiring (Sprint
04.07). See spec line 60: "No new behavior wired into agent_router.py
— that's a downstream sprint."
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from teams._config import (
    ALLOWED_ADAPTERS,
    DEFAULT_ADAPTER,
    InvalidConfigError,
    load_department_config,
)


# Repo-root-relative path to the real board.yaml. The test_teams suite
# already runs with cwd == agent/ (per repo conventions in test_config.py)
# so we anchor here against the package import path.
_BOARD_YAML = Path(__file__).resolve().parent.parent.parent / "config" / "teams" / "board.yaml"


# ---------------------------------------------------------------------------
# Module-level constants surface
# ---------------------------------------------------------------------------


class TestAdapterConstants:
    def test_default_adapter_is_claude(self) -> None:
        assert DEFAULT_ADAPTER == "claude"

    def test_allowed_adapters_includes_claude_and_openrouter(self) -> None:
        assert "claude" in ALLOWED_ADAPTERS
        assert "openrouter" in ALLOWED_ADAPTERS


# ---------------------------------------------------------------------------
# Loader behaviour with the new field
# ---------------------------------------------------------------------------


class TestLoaderRecognisesAdapterField:
    def _write_yaml(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "board.yaml"
        path.write_text(textwrap.dedent(body))
        return path

    def test_team_config_defaults_adapter_to_claude_when_omitted(
        self, tmp_path: Path
    ) -> None:
        """A YAML with no `adapter:` keys round-trips to the default."""
        path = self._write_yaml(
            tmp_path,
            """\
            team:
              name: board
              zone: 4
              chief:
                name: board-ceo
                model: opus-4.6
              workers:
                - name: board-revenue
                  model: sonnet-4.6
            """,
        )

        cfg = load_department_config(path)

        assert cfg.manager.adapter == DEFAULT_ADAPTER == "claude"
        assert all(e.adapter == "claude" for e in cfg.employees)

    def test_team_config_loads_claude_adapter_round_trip(
        self, tmp_path: Path
    ) -> None:
        """Explicit `adapter: claude` round-trips."""
        path = self._write_yaml(
            tmp_path,
            """\
            team:
              name: board
              zone: 4
              chief:
                name: board-ceo
                model: opus-4.6
                adapter: claude
              workers:
                - name: board-revenue
                  model: sonnet-4.6
                  adapter: claude
            """,
        )

        cfg = load_department_config(path)

        assert cfg.manager.adapter == "claude"
        assert cfg.employees[0].adapter == "claude"

    def test_team_config_loads_4_member_cross_vendor_board(
        self, tmp_path: Path
    ) -> None:
        """A 4-worker fixture with mixed adapters loads cleanly.

        Verifies the exact spec scenario: a small board with one
        Anthropic-routed member, two openrouter-routed members, and one
        member that omits the field (default-claude path).
        """
        path = self._write_yaml(
            tmp_path,
            """\
            team:
              name: board
              zone: 4
              chief:
                name: board-ceo
                model: opus-4.6
                adapter: claude
              workers:
                - name: board-revenue
                  model: sonnet-4.6
                  adapter: claude
                - name: board-cross-vendor-strategist
                  model: openrouter:anthropic/claude-3.5-sonnet
                  adapter: openrouter
                - name: board-openrouter-generalist
                  model: openrouter:anthropic/claude-3.5-sonnet
                  adapter: openrouter
                - name: board-default
                  model: sonnet-4.6
            """,
        )

        cfg = load_department_config(path)

        adapters_by_name = {e.name: e.adapter for e in cfg.employees}
        assert adapters_by_name == {
            "board-revenue": "claude",
            "board-cross-vendor-strategist": "openrouter",
            "board-openrouter-generalist": "openrouter",
            "board-default": "claude",
        }

    def test_invalid_adapter_value_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        """Unknown adapter values fail fast at load time."""
        path = self._write_yaml(
            tmp_path,
            """\
            team:
              name: board
              zone: 4
              chief:
                name: board-ceo
                model: opus-4.6
              workers:
                - name: board-revenue
                  model: sonnet-4.6
                  adapter: vertex-ai
            """,
        )

        with pytest.raises(InvalidConfigError) as excinfo:
            load_department_config(path)

        assert "vertex-ai" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Backward-compat: the real shipped board.yaml still loads, all existing
# fields are preserved, and the file now has 9 workers.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _BOARD_YAML.exists(),
    reason="real board.yaml not present in this checkout",
)
class TestRealBoardYaml:
    def test_real_board_yaml_loads_with_nine_workers(self) -> None:
        """Default board.yaml ships with 6 existing + 3 new = 9 workers."""
        cfg = load_department_config(_BOARD_YAML)
        assert cfg.name == "board"
        assert cfg.zone == 4
        assert len(cfg.employees) == 9

    def test_team_config_existing_6_members_unchanged_after_extension(
        self,
    ) -> None:
        """The 6 pre-existing workers retain their full schema (DoD line 75)."""
        cfg = load_department_config(_BOARD_YAML)
        existing_six = {
            "board-revenue",
            "board-compounder",
            "board-product-strategist",
            "board-technical-architect",
            "board-contrarian",
            "board-moonshot",
        }
        by_name = {e.name: e for e in cfg.employees}

        assert existing_six.issubset(by_name.keys())

        for name in existing_six:
            spec = by_name[name]
            # All five existing fields still populated and adapter set to
            # the worker default for the hybrid fleet.
            assert spec.model, f"{name}: model field missing"
            assert spec.expertise_path, f"{name}: expertise field missing"
            assert spec.system_prompt_path, f"{name}: system_prompt missing"
            assert spec.role, f"{name}: role field missing"
            # `domain.write` lives on AgentSpec.deny_write_paths via the
            # _DomainSchema → AgentSpec conversion; presence of any
            # write-jail config is sufficient evidence the domain block
            # round-tripped, since the existing YAML configures `write:`
            # not `deny_write:`. The full domain dict is exercised by
            # tests/test_teams/test_domain_lock_enforcement.py.
            #
            # 2026-06-04 #2566 hybrid-fleet: OpenRouter is dead (key died)
            # and codex `exec` cannot tool-call. Workers/board-members are
            # prose-only, so every board member now runs on
            # `model: "codex-exec:"` + `adapter: "codex-exec"`. Chiefs
            # (board-ceo) stay on anthropic-oauth because they REQUIRE
            # tool-calling (delegate/final_result). See board.yaml chief
            # comment + the hybrid-fleet rationale.
            assert spec.model == "codex-exec:"
            assert spec.adapter == "codex-exec"

    def test_real_board_yaml_three_new_members_use_codex_adapter(
        self,
    ) -> None:
        """The 3 (formerly cross-vendor) seats now run on codex-exec.

        2026-06-04 #2566 hybrid-fleet: these names —
        `board-cross-vendor-strategist`, `board-openrouter-generalist`,
        `board-systems-thinker` — are HISTORICAL LABELS from the Sprint
        04.05 cross-vendor experiment. OpenRouter is dead, so they no
        longer route to a non-Anthropic vendor; they run on `codex-exec:`
        like every other board worker (prose-only). The names persist for
        roster continuity, but the routing is the worker default.
        """
        cfg = load_department_config(_BOARD_YAML)
        new_three = {
            "board-cross-vendor-strategist",
            "board-openrouter-generalist",
            "board-systems-thinker",
        }
        by_name = {e.name: e for e in cfg.employees}

        for name in new_three:
            assert name in by_name, f"{name} missing from board.yaml"
            assert by_name[name].model == "codex-exec:"
            assert by_name[name].adapter == "codex-exec"

    def test_real_board_yaml_chief_preserves_all_fields(self) -> None:
        """The board-ceo chief retains its full schema after extension.

        2026-06-04 #2566 hybrid-fleet: the chief flipped to
        `anthropic-oauth:claude-sonnet-4-5` + `adapter: "claude"`. Chiefs
        REQUIRE tool-calling (delegate/final_result) which codex `exec`
        cannot do — codex is an autonomous agent that returns prose. So
        chiefs run on anthropic-oauth (native tool support, subscription-
        billed) while workers run codex-exec. Mirrors the canonical
        strategy-chief pattern.
        """
        cfg = load_department_config(_BOARD_YAML)
        assert cfg.manager.name == "board-ceo"
        assert cfg.manager.model == "anthropic-oauth:claude-sonnet-4-5"
        assert cfg.manager.expertise_path
        assert cfg.manager.system_prompt_path
        assert cfg.manager.role
        assert cfg.manager.adapter == "claude"
