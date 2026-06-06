"""Sprint P3.3 / issue #1724 — wire `board_cross_vendor_enabled` into roster.

The flag at ``BridgeConfig.board_cross_vendor_enabled`` (default False) gates
the cross-vendor seats in ``agent/config/teams/board.yaml``. The factory's
``_filter_cross_vendor_employees`` strips any board worker whose
``adapter == "openrouter"`` when the flag is OFF, and materialises every
worker when it is ON. The filter is board-specific and keyed on the adapter
field (not worker name), so it self-adjusts as the YAML evolves.

2026-06-04 #2566 hybrid-fleet reality: OpenRouter is DEAD (the API key
died) and codex `exec` cannot tool-call, so EVERY board worker now runs on
``model: "codex-exec:"`` + ``adapter: "codex-exec"``. There are ZERO
``adapter: "openrouter"`` board workers left. Consequence for THIS module:

- The cross-vendor filter is now a NO-OP for the board department —
  flag-OFF and flag-ON both materialise all 9 workers, because none match
  ``adapter == "openrouter"``.
- The filter mechanism itself is unchanged in code (``_filter_cross_vendor
  _employees`` still exists and still keys on the openrouter adapter), so
  the wiring is verified against a non-board synthetic fixture that DOES
  carry an ``adapter: openrouter`` worker (see ``_make_non_board_config``).

The structural intent — "the flag gates the openrouter cohort, scoped to
board, keyed on adapter" — is preserved; only the board-side expected sets
flip from claude/openrouter to codex-exec because the YAML moved off both.

Source finding: Lane B H2 / HI-4 in the 2026-05-12 comprehensive audit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teams._config import load_department_config
from teams._factory import build_employee_agents, roster_from_department_config


# Repo-relative path to the real board.yaml. The test suite runs with
# cwd == agent/ — mirrors the anchor convention in
# test_board_adapter_field.py.
_BOARD_YAML = (
    Path(__file__).resolve().parent.parent.parent / "config" / "teams" / "board.yaml"
)


@pytest.fixture(scope="module")
def board_config():
    """The real board.yaml as a DepartmentConfig.

    Module-scoped because load_department_config is read-only and the
    config is frozen — sharing across tests saves a YAML parse per test.
    """
    if not _BOARD_YAML.exists():
        pytest.skip("board.yaml not present in this checkout")
    return load_department_config(_BOARD_YAML)


@pytest.fixture(scope="module")
def expected_codex_names(board_config) -> set[str]:
    """Names of every board worker whose adapter is `codex-exec`.

    Post-#2566 hybrid-fleet this is every board worker. Derived at runtime
    so the test stays correct if the YAML evolves.
    """
    return {e.name for e in board_config.employees if e.adapter == "codex-exec"}


@pytest.fixture(scope="module")
def expected_openrouter_names(board_config) -> set[str]:
    """Names of every board worker whose adapter is `openrouter`.

    Post-#2566 hybrid-fleet this is the empty set — the cross-vendor filter
    keys on this adapter, so an empty set means the filter is a no-op for
    board (all workers survive both flag states). Kept as a fixture so the
    disjointness/no-op assertions read against the live YAML, not a literal.
    """
    return {e.name for e in board_config.employees if e.adapter == "openrouter"}


@pytest.fixture(scope="module")
def expected_filtered_names(board_config) -> set[str]:
    """Board workers that survive the flag-OFF cross-vendor filter.

    The filter strips ``adapter == "openrouter"`` workers when the flag is
    OFF. Derived at runtime: post-#2566 (no openrouter workers) this equals
    every worker; if a future change re-adds an openrouter seat, this set
    shrinks automatically and the gating assertions stay honest.
    """
    return {e.name for e in board_config.employees if e.adapter != "openrouter"}


# ---------------------------------------------------------------------------
# Ground-truth shape check — guards against board.yaml drifting away from
# the audit assumption (6 claude + 3 openrouter at finding-time).
# ---------------------------------------------------------------------------


class TestBoardYamlShape:
    def test_board_yaml_workers_are_all_codex_exec(
        self, board_config, expected_codex_names, expected_openrouter_names
    ) -> None:
        """Post-#2566 hybrid-fleet: every board WORKER runs on codex-exec.

        Pre-#2566 the cross-vendor-flag filter relied on board carrying a
        mix of claude- and openrouter-adapter workers. OpenRouter is now
        dead and codex `exec` cannot tool-call, so all board workers are
        prose-only `adapter: "codex-exec"`. The two consequences this guards:

        1. Every worker is codex-exec (the worker default of the hybrid fleet).
        2. Zero workers carry `adapter: "openrouter"`, which is the key the
           cross-vendor filter strips on — so the filter is a no-op for board.

        If a future change re-introduces an openrouter board seat (e.g. the
        key is restored), the openrouter assertion flips and the flag's
        gating tests below regain teeth automatically.
        """
        all_worker_names = {e.name for e in board_config.employees}
        assert len(all_worker_names) >= 1, "board.yaml must declare workers"
        assert expected_codex_names == all_worker_names, (
            "every board worker should be adapter=codex-exec post-#2566"
        )
        assert len(expected_openrouter_names) == 0, (
            "post-#2566 board.yaml should have zero openrouter-adapter workers "
            "(OpenRouter is dead) — the cross-vendor filter is a no-op for board"
        )


# ---------------------------------------------------------------------------
# roster_from_department_config — chief's prompt-side seam
# ---------------------------------------------------------------------------


class TestRosterFromConfig:
    def test_default_flag_off_excludes_openrouter_workers(
        self, board_config, expected_filtered_names, expected_openrouter_names
    ) -> None:
        """Default call (flag OFF) → openrouter workers absent from roster.

        Post-#2566 there are zero openrouter board workers, so the filter
        strips nothing and the flag-OFF roster equals every worker. The
        disjointness assertion is the durable guardrail: whatever the
        openrouter cohort is (empty today), it must NOT appear under flag-OFF.
        """
        roster = roster_from_department_config(
            board_config, cross_vendor_enabled=False
        )
        roster_names = set(roster.names())

        assert roster_names == expected_filtered_names
        assert roster_names.isdisjoint(expected_openrouter_names), (
            f"openrouter workers leaked into roster: "
            f"{roster_names & expected_openrouter_names}"
        )

    def test_flag_on_includes_all_workers(
        self, board_config, expected_filtered_names, expected_openrouter_names
    ) -> None:
        """Flag ON → every YAML worker present in the roster."""
        roster = roster_from_department_config(
            board_config, cross_vendor_enabled=True
        )
        roster_names = set(roster.names())

        assert roster_names == expected_filtered_names | expected_openrouter_names

    def test_non_board_department_unaffected_by_flag(self, tmp_path) -> None:
        """The cross-vendor filter is a board-specific policy; other
        departments are passed through unchanged even with the flag OFF.
        """
        cfg = _make_non_board_config(tmp_path)
        roster_off = roster_from_department_config(cfg, cross_vendor_enabled=False)
        roster_on = roster_from_department_config(cfg, cross_vendor_enabled=True)

        assert set(roster_off.names()) == set(roster_on.names())
        assert len(roster_off.specialists) == len(cfg.employees)


# ---------------------------------------------------------------------------
# build_employee_agents — agent-construction seam
# ---------------------------------------------------------------------------


class TestBuildEmployeeAgents:
    def test_default_flag_off_excludes_openrouter_workers(
        self, board_config, expected_filtered_names, expected_openrouter_names
    ) -> None:
        """Default call (flag OFF) → openrouter workers absent from agent map.

        Post-#2566 the openrouter cohort is empty, so flag-OFF materialises
        every worker. The disjointness assertion stays the durable guardrail.
        """
        agents = build_employee_agents(
            board_config, cross_vendor_enabled=False
        )

        assert set(agents.keys()) == expected_filtered_names
        assert set(agents.keys()).isdisjoint(expected_openrouter_names)

    def test_flag_on_includes_all_workers(
        self, board_config, expected_filtered_names, expected_openrouter_names
    ) -> None:
        """Flag ON → every YAML worker reaches the agent map."""
        agents = build_employee_agents(
            board_config, cross_vendor_enabled=True
        )

        assert set(agents.keys()) == expected_filtered_names | expected_openrouter_names

    def test_non_board_department_unaffected_by_flag(self, tmp_path) -> None:
        """Filter is board-specific — qa/eng/ops pass through regardless."""
        cfg = _make_non_board_config(tmp_path)
        agents_off = build_employee_agents(cfg, cross_vendor_enabled=False)
        agents_on = build_employee_agents(cfg, cross_vendor_enabled=True)

        assert set(agents_off.keys()) == set(agents_on.keys())
        assert len(agents_off) == len(cfg.employees)


# ---------------------------------------------------------------------------
# Back-compat — default-argument behaviour preserves pre-#1724 semantics.
# ---------------------------------------------------------------------------


class TestBackCompatDefault:
    def test_roster_factory_default_arg_preserves_pre_1724_behaviour(
        self, board_config, expected_filtered_names, expected_openrouter_names
    ) -> None:
        """Calling without the flag arg must include all 9 workers.

        Existing call sites (tests, ad-hoc loaders) don't pass the flag.
        The default arg MUST resolve to the pre-#1724 behaviour
        (cross_vendor_enabled=True i.e. include everything) so legacy
        callers see no regression. Production wiring in
        ``teams/_team.py::_build`` is the place where the BridgeConfig
        flag is consulted and the default flips to off.
        """
        roster = roster_from_department_config(board_config)
        roster_names = set(roster.names())

        assert roster_names == expected_filtered_names | expected_openrouter_names

    def test_employee_factory_default_arg_preserves_pre_1724_behaviour(
        self, board_config, expected_filtered_names, expected_openrouter_names
    ) -> None:
        agents = build_employee_agents(board_config)
        assert set(agents.keys()) == expected_filtered_names | expected_openrouter_names


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_non_board_config(tmp_path: Path):
    """Build a minimal non-board DepartmentConfig with one openrouter worker.

    Used to prove the filter only fires for the `board` department — other
    departments with cross-vendor adapters (if any ever ship) are passed
    through unchanged.
    """
    import textwrap

    yaml_path = tmp_path / "engineering.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """\
            team:
              name: engineering
              zone: 3
              chief:
                name: eng-chief
                model: opus-4.6
              workers:
                - name: eng-architect
                  model: sonnet-4.6
                  adapter: claude
                - name: eng-cross
                  model: openrouter:anthropic/claude-3.5-sonnet
                  adapter: openrouter
            """
        )
    )
    return load_department_config(yaml_path)
