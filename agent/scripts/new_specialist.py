"""bumba new-specialist <team> <name> — scaffold a Z4 specialist in <3s.

Reads no LLM. Writes 5 files atomically (or aborts before the first write
if any target exists). Reuses templates from _scaffolding_templates.

Exit codes:
  0  scaffold succeeded
  1  validation failure (unknown team, duplicate name, write-target collision)
  2  unexpected I/O error (caller should retry)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable

import yaml

from scripts._scaffolding_templates import (
    DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER,
    DEFAULT_ZONE4_TOOL_CAPABLE_MODEL,
    ScaffoldPaths,
    expertise_for,
    worker_prompt_for,
)


# Repo root: agent/scripts/ → agent/ → repo root
REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_paths(team: str, name: str) -> ScaffoldPaths:
    """Build the four on-disk targets for one specialist scaffold."""
    safe = name.replace("-", "_")
    return ScaffoldPaths(
        expertise=str(REPO_ROOT / f"agent/config/expertise/updatable/{name}.md"),
        system_prompt=str(REPO_ROOT / f"agent/config/agents/zone4/{team}/{name}.md"),
        placeholder_test=str(
            REPO_ROOT / f"agent/tests/test_teams/test_specialist_{safe}.py"
        ),
        checklist=str(REPO_ROOT / f"agent/data/scaffolding/{name}-checklist.md"),
    )


def _team_yaml_path(team: str) -> Path:
    return REPO_ROOT / f"agent/config/teams/{team}.yaml"


def _verify_team_exists(team: str) -> None:
    """Abort with exit 1 if the team YAML does not exist."""
    p = _team_yaml_path(team)
    if not p.exists():
        existing = sorted(
            x.stem for x in (REPO_ROOT / "agent/config/teams").glob("*.yaml")
        )
        sys.stderr.write(
            f"[bumba] ERROR: team {team!r} not found.\n"
            f"        Existing teams: {', '.join(existing)}\n"
            f"        Use `bumba new-team {team}` to create it first.\n"
        )
        raise SystemExit(1)


def _verify_no_collisions(paths: ScaffoldPaths, team: str, name: str) -> None:
    """Abort with exit 1 if any target file or YAML worker entry already exists."""
    for target in (
        paths.expertise,
        paths.system_prompt,
        paths.placeholder_test,
        paths.checklist,
    ):
        if Path(target).exists():
            sys.stderr.write(
                f"[bumba] ERROR: {target} already exists.\n"
                f"        Refusing to overwrite operator-authored content.\n"
            )
            raise SystemExit(1)

    raw = yaml.safe_load(_team_yaml_path(team).read_text(encoding="utf-8"))
    workers = (raw.get("team") or {}).get("workers") or []
    for w in workers:
        if w.get("name") == name:
            sys.stderr.write(
                f"[bumba] ERROR: specialist {name!r} already exists in team {team!r}.\n"
                f"        agent/config/teams/{team}.yaml already declares this name.\n"
                f"        To update an existing specialist, edit the files directly.\n"
            )
            raise SystemExit(1)


def _write_file(path: str, content: str) -> None:
    """Atomic write: mkdir -p, write to .tmp, rename."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(p)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _insert_worker_block(team: str, name: str) -> int:
    """Append a worker block to the team YAML; return the approx line number inserted.

    Prefers ruamel.yaml round-trip if available (preserves comments). Falls
    back to a line-marker insert before the ``# END_WORKERS`` sentinel comment,
    or plain append if sentinel is absent. See issue #1191 architectural
    decision §3 for rationale.
    """
    yaml_path = _team_yaml_path(team)
    block = (
        f"    - name: {name}\n"
        f"      role: \"<one-line description — REQUIRED>\"\n"
        f"      model: {DEFAULT_ZONE4_TOOL_CAPABLE_MODEL}\n"
        f"      adapter: \"{DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER}\"\n"
        f"      expertise: agent/config/expertise/updatable/{name}.md\n"
        f"      system_prompt: agent/config/agents/zone4/{team}/{name}.md\n"
        f"      domain:\n"
        f"        read: [\"*\"]\n"
        f"        write: [\"<paths — REQUIRED, narrow!>\"]\n"
    )

    text = yaml_path.read_text(encoding="utf-8")

    # Try ruamel.yaml first (preserves comments + key ordering).
    try:
        from ruamel.yaml import YAML  # type: ignore[import-untyped]
        from io import StringIO

        ruyaml = YAML()
        ruyaml.preserve_quotes = True
        data = ruyaml.load(text)
        team_data = data.get("team") or {}
        workers = team_data.get("workers")
        if workers is None:
            team_data["workers"] = ruyaml.seq([])
            workers = team_data["workers"]
        workers.append(
            ruyaml.load(
                f"- name: {name}\n"
                f"  role: \"<one-line description — REQUIRED>\"\n"
                f"  model: {DEFAULT_ZONE4_TOOL_CAPABLE_MODEL}\n"
                f"  adapter: \"{DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER}\"\n"
                f"  expertise: agent/config/expertise/updatable/{name}.md\n"
                f"  system_prompt: agent/config/agents/zone4/{team}/{name}.md\n"
                f"  domain:\n"
                f"    read: ['*']\n"
                f"    write: ['<paths — REQUIRED, narrow!>']\n"
            )[0]
        )
        buf = StringIO()
        ruyaml.dump(data, buf)
        new_text = buf.getvalue()
        _write_file(str(yaml_path), new_text)
        return new_text.count("\n") - block.count("\n")  # approx
    except ImportError:
        pass  # fall through to line-marker / append strategy

    # Fallback: sentinel insert, inline-list replace, or plain append.
    sentinel = "# END_WORKERS"
    if sentinel in text:
        new_text = text.replace(sentinel, block + "\n  " + sentinel, 1)
    elif "workers: []" in text:
        # Replace inline empty-list form with block form + new worker.
        new_text = text.replace("workers: []", "workers:\n" + block, 1)
    elif "workers: []\n" in text:
        new_text = text.replace("workers: []\n", "workers:\n" + block + "\n", 1)
    else:
        # Append after the last existing worker block (heuristic: end of file).
        new_text = text.rstrip("\n") + "\n" + block + "\n"

    _write_file(str(yaml_path), new_text)
    # Return approximate line of insertion.
    return new_text[: new_text.find(block)].count("\n") + 1


def _placeholder_test_source(team: str, name: str) -> str:
    safe = name.replace("-", "_")
    return f'''\
"""Placeholder construction smoke test for {name}.

Generated by `bumba new-specialist`. Asserts the specialist is discoverable via
load_department_config and its AgentSpec has the expected name. Replace with
substantive behaviour tests once the specialist is fleshed out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teams._config import load_department_config


TEAMS_DIR = Path(__file__).resolve().parents[3] / "agent" / "config" / "teams"


@pytest.mark.offline
def test_{safe}_present_in_team_yaml() -> None:
    config = load_department_config(TEAMS_DIR / "{team}.yaml")
    names = {{e.name for e in config.employees}}
    assert "{name}" in names, (
        f"Specialist '{name}' not found in {team} team config. "
        f"Employees present: {{sorted(names)}}"
    )
'''


def _checklist_source(team: str, name: str, yaml_line: int) -> str:
    return f"""\
# {name} — operator fill-in checklist

Generated by `bumba new-specialist {team} {name}`.

---

## Required actions (the skill wrote stubs; you own the substance)

1. **agent/config/teams/{team}.yaml** (worker block near line {yaml_line})
   - `role:` — replace placeholder with a one-line description  [REQUIRED]
   - `domain.write:` — replace placeholder with actual write paths  [REQUIRED, narrow!]
   - `model:` — override from the default Claude tool-capable model if this specialist warrants another provider
   - `per_employee_tools:` — add a subset of `tools.common + tools.department` once you know what this specialist needs

2. **agent/config/agents/zone4/{team}/{name}.md** (system prompt)
   - Replace the `<!-- Mission -->` placeholder with 3-5 sentences describing what outcomes this specialist owns
   - Add 2-3 `## Examples` of correct task handling (optional but recommended)

3. **agent/config/expertise/updatable/{name}.md** (expertise)
   - `## Domain Patterns` — add 3+ patterns this specialist should know  [REQUIRED]
   - `## Tool Use` — which tools to reach for first; which to avoid (recommended)
   - `## Operating Constraints` — cost cues, escalation rules (recommended)

---

## Optional / follow-up

- Add routing keywords for this specialist to `bridge/departments.py` once usage patterns emerge
- Narrow `per_employee_tools:` after observing which tools the specialist actually calls
- Run `make live-smoke` after filling in the required fields to confirm construction succeeds

---

## Verification

```bash
# Offline construction test (no API key needed)
python -m pytest agent/tests/test_teams/test_specialist_{name.replace("-", "_")}.py -m offline -v

# Live smoke (requires ANTHROPIC_API_KEY)
make live-smoke
```
"""


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bumba new-specialist",
        description="Scaffold a Zone 4 specialist in < 3 seconds.",
    )
    parser.add_argument("team", help="existing team name (e.g. design, qa)")
    parser.add_argument("name", help="new specialist name (e.g. rust-specialist)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    started = time.monotonic()
    sys.stdout.write(f"[bumba] new-specialist: {args.team} / {args.name}\n")

    _verify_team_exists(args.team)
    paths = _resolve_paths(args.team, args.name)
    _verify_no_collisions(paths, args.team, args.name)

    # All collision checks passed — write atomically.
    _write_file(paths.expertise, expertise_for(args.name, args.team))
    _write_file(paths.system_prompt, worker_prompt_for(args.name, args.team))
    yaml_line = _insert_worker_block(args.team, args.name)
    _write_file(paths.placeholder_test, _placeholder_test_source(args.team, args.name))
    _write_file(paths.checklist, _checklist_source(args.team, args.name, yaml_line))

    elapsed = time.monotonic() - started
    sys.stdout.write(
        f"[bumba] done in {elapsed:.1f}s — 5 files written\n"
        f"[bumba] expertise:      {paths.expertise}\n"
        f"[bumba] system prompt:  {paths.system_prompt}\n"
        f"[bumba] team YAML:      agent/config/teams/{args.team}.yaml (line ~{yaml_line})\n"
        f"[bumba] test:           {paths.placeholder_test}\n"
        f"[bumba] checklist:      {paths.checklist}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
