"""Shared template strings for the new-specialist + new-team skills.

D3.1 ships EXPERTISE_TEMPLATE + WORKER_SYSTEM_PROMPT_TEMPLATE. D3.2 extends
with TEAM_YAML_TEMPLATE + CHIEF_SYSTEM_PROMPT_TEMPLATE. The duplicate
``## Domain Patterns`` header bug from A4 § "Structural problems #1" is fixed
once here; every scaffold inherits the fix.

E4.1 adds three hardened bundle families (single-agent, agent-team,
chief+specialist) via BundleResult + the three *Bundle dataclasses.

E4.7 adds SKILL_TEMPLATE + _SkillBundle + SKILL_BUNDLE for the new-skill
scaffold command.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

DEFAULT_ZONE4_TOOL_CAPABLE_MODEL = "anthropic-oauth:claude-sonnet-4-5"
DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER = "claude"


# ---- Specialist expertise stub (single Domain Patterns header) ----
# Substitution placeholders: {name}, {team}
EXPERTISE_TEMPLATE = """\
---
agent: {name}
zone: 4
department: {team}
type: updatable
max_lines: 500
schema_version: 1
---

# {name} — Expertise

*This file is updated by {name} after each significant session.*

## Domain Patterns
<!-- Patterns and preferences observed across sessions. Operator
     pre-confirmed conventions, aesthetic choices, standing guidelines. -->

## Tool Use
<!-- Which tools to reach for first; which to avoid; what tool failure means. -->

## Operating Constraints
<!-- Cost cues, escalation rules, when to handle solo vs. defer to chief. -->

## Decision Log
<!-- Key decisions made by this specialist and their rationale. -->

## Known Risks

## Cross-Agent Notes
"""


# ---- Worker (specialist) system prompt scaffold ----
# Substitution placeholders: {name}, {team}, {role}
WORKER_SYSTEM_PROMPT_TEMPLATE = """\
# {name}

You are **{name}**, a specialist in the {team} department.

## Role

{role}

## Mission

<!-- 3-5 sentences. What outcomes does this specialist own?
     What does success look like? When should the chief delegate to you? -->

## Operating doctrine

- Execute the task; emit at least one `surface(kind='result')` per task before
  returning. Surface BLOCKER if you cannot proceed. Never delegate further;
  never go silent.
- Stay inside your `domain.write` paths. Surface DOMAIN_VIOLATION if asked to
  write outside scope.
- See `## Expertise` (loaded from `agent/config/expertise/updatable/{name}.md`)
  for accumulated patterns and preferences.

## Examples

<!-- Optional: 2-3 examples of correct task handling. -->
"""


# ---- Chief expertise stub ----
# Substitution placeholders: {name}, {team}
CHIEF_EXPERTISE_TEMPLATE = """\
---
agent: {name}
zone: 4
department: {team}
type: updatable
max_lines: 1000
schema_version: 1
---

# {name} — Expertise

*This file is updated by {name} after each significant orchestration session.*

## Delegation Patterns
<!-- When to delegate vs. handle in-chief. Which specialist owns what. -->

## Synthesis Patterns
<!-- How to merge specialist outputs into a coherent result. -->

## Escalation Triggers
<!-- Patterns that warrant routing to Strategy Board or halting for operator input. -->

## Domain Patterns
<!-- Department-specific conventions and standing operator preferences. -->

## Decision Log
<!-- Key orchestration decisions and their rationale. -->

## Known Risks
"""


# ---- Chief system prompt scaffold ----
# Substitution placeholders: {name}, {team}, {prefix}, {role}, {mission}, {roster}
CHIEF_SYSTEM_PROMPT_TEMPLATE = """\
# {name}

You are **{name}**, chief of the {team} department.

## Role

{role}

## Mission

{mission}

## Department Roster

{{ROSTER}}

## Operating doctrine

- **Delegate, don't execute.** Use the `delegate(specialist, task)` tool for
  specialist work; synthesise results here.
- **One turn of silence = BLOCKER.** If a specialist returns nothing useful,
  surface a BLOCKER immediately.
- **Cost discipline.** Stay within the department cost cap. Prefer one precise
  delegation over two exploratory ones.
- **Synthesise clearly.** Return a single, coherent result that integrates all
  specialist contributions. Never raw-forward a specialist response.

## Escalation

Escalate to the Strategy Board when:
- Operator override or judgment is required
- Two specialists disagree and the answer materially affects outside parties
- Budget cap would be exceeded

## Examples

<!-- Optional: 2-3 examples of correct orchestration patterns for this team. -->
"""


# ---- Full team YAML scaffold ----
# Substitution placeholders: {name}, {prefix}, {description}, {chief_name},
#   {chief_role}, {chief_mission}, {workers_block}
TEAM_YAML_TEMPLATE = """\
team:
  name: {name}
  zone: 4
  description: >
    {description}

  escalation:
    from_zone: 3
    triggers:
      - "<trigger phrase 1>"
      - "<trigger phrase 2>"
      - "<trigger phrase 3>"
    complexity_threshold: 6
    auto_escalate: false

  constraints:
    cost_limit_usd: 1.50
    timeout_seconds: 600
    concurrency_limit: 3
    usage_limits:
      request_limit: 20
      request_token_limit: 250000
      response_token_limit: 250000
    expected_min_specialists: 1

  budget:
    daily_limit_usd: 4.00
    alert_thresholds: [0.50, 0.75, 0.90]

  tools:
    common: [read_file, search_knowledge]
    department: [continue_handoff]
    per_employee: {{}}

  vapi:
    enabled: false
    model: gpt-4o-mini
    voice: onyx
    greeting: "{name} department. How can I help?"
    tools: []

  chief:
    name: {chief_name}
    role: >
      {chief_role}
    model: {default_zone4_model}
    adapter: {default_zone4_adapter}
    skills:
      - zero-micromanagement
      - mental-model
      - active-listener
    expertise: agent/config/expertise/updatable/{chief_name}.md
    expertise_max_lines: 1000
    system_prompt: agent/config/agents/zone4/{name}/{chief_name}.md
    domain:
      read: ["*"]
      write:
        - "agent/config/expertise/{chief_name}.md"
        - "sessions/"
        - "docs/{name}/"
    thinking: extended
    max_turns: 30
    timeout_minutes: 20.0

  workers:
{workers_block}
# S04: MCP server allowlist for DEPARTMENT write jail
# Empty list = inherit bridge default (permissive); expand via operator PR
mcp_servers: []
"""


# ---- Single worker block (appended per specialist in interactive mode) ----
# Substitution placeholders: {name}, {team}, {role}
WORKER_YAML_BLOCK_TEMPLATE = """\
    - name: {name}
      role: "{role}"
      model: {default_zone4_model}
      adapter: {default_zone4_adapter}
      skills: [mental-model]
      expertise: agent/config/expertise/updatable/{name}.md
      system_prompt: agent/config/agents/zone4/{team}/{name}.md
      domain:
        read: ["*"]
        write: ["docs/{team}/", "sessions/"]
"""


# ---------------------------------------------------------------------------
# E4.1 — Hardened bundle families
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BundleResult:
    """Planned scaffold output: (file_path, content) pairs, write-order matters."""

    files: tuple[tuple[str, str], ...]


class TemplateBundle(Protocol):
    """A bundle that renders a self-consistent scaffold from keyword args."""

    def render(self, **kwargs: str) -> BundleResult: ...


@dataclass(frozen=True)
class SingleAgentBundle:
    """Solo agent: chief = worker (same name, same prompt).

    The synthetic YAML uses a ``chief`` entry that points to the same
    agent file as the single worker entry so ``_RootSchema`` validates.
    The ``workers`` list is intentionally empty — the agent handles
    everything; delegation-loop risk is zero.

    Required kwargs: name, team, role
    """

    def render(  # type: ignore[override]
        self,
        name: str,
        team: str,
        role: str = "<one-line role description>",
    ) -> BundleResult:
        expertise_path = f"agent/config/expertise/updatable/{name}.md"
        prompt_path = f"agent/config/agents/zone4/{team}/{name}.md"

        team_yaml = f"""\
team:
  name: {team}
  zone: 4
  description: >
    Single-agent department — {name} handles all tasks directly.

  escalation:
    from_zone: 3
    triggers:
      - "<trigger phrase 1>"
    complexity_threshold: 6
    auto_escalate: false

  constraints:
    cost_limit_usd: 0.50
    timeout_seconds: 300
    concurrency_limit: 1
    usage_limits:
      request_limit: 10
      request_token_limit: 25000
      response_token_limit: 10000

  budget:
    daily_limit_usd: 2.00
    alert_thresholds: [0.50, 0.75, 0.90]

  tools:
    common: [read_file, search_knowledge]
    department: []
    # TODO: add per-agent tool overrides if needed
    per_employee: {{}}

  vapi:
    enabled: false
    model: gpt-4o-mini
    voice: onyx
    greeting: "{team} department. How can I help?"
    tools: []

  chief:
    name: {name}
    role: >
      {role}
    model: {DEFAULT_ZONE4_TOOL_CAPABLE_MODEL}
    adapter: {DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER}
    skills: [mental-model]
    expertise: {expertise_path}
    expertise_max_lines: 1000
    system_prompt: {prompt_path}
    domain:
      read: ["*"]
      write:
        - "agent/config/expertise/{name}.md"
        - "sessions/"
        - "docs/{team}/"
    thinking: ""
    max_turns: 20
    timeout_minutes: 10.0

  workers: []

mcp_servers: []
"""
        return BundleResult(
            files=(
                (expertise_path, expertise_for(name, team)),
                (prompt_path, worker_prompt_for(name, team, role)),
                (f"agent/config/teams/{team}.yaml", team_yaml),
            )
        )


@dataclass(frozen=True)
class AgentTeamBundle:
    """Chief + N workers from a pre-built workers block.

    Required kwargs: name, prefix, description, chief_name, chief_role,
        chief_mission, workers_block
    Additional: pass worker (name, team, role) tuples via worker_specs
        to get per-worker expertise and prompt files in the result.
    """

    worker_specs: tuple[tuple[str, str, str], ...] = ()

    def render(  # type: ignore[override]
        self,
        name: str,
        prefix: str,
        description: str,
        chief_name: str,
        chief_role: str,
        chief_mission: str,
        workers_block: str = "",
    ) -> BundleResult:
        chief_expertise_path = f"agent/config/expertise/updatable/{chief_name}.md"
        chief_prompt_path = f"agent/config/agents/zone4/{name}/{chief_name}.md"

        files: list[tuple[str, str]] = [
            (chief_expertise_path, chief_expertise_for(chief_name, name)),
            (
                chief_prompt_path,
                chief_prompt_for(chief_name, name, prefix, chief_role, chief_mission),
            ),
            (
                f"agent/config/teams/{name}.yaml",
                team_yaml_for(
                    name,
                    prefix,
                    description,
                    chief_name,
                    chief_role,
                    chief_mission,
                    workers_block,
                ),
            ),
        ]

        for w_name, w_team, w_role in self.worker_specs:
            files.append(
                (
                    f"agent/config/expertise/updatable/{w_name}.md",
                    expertise_for(w_name, w_team),
                )
            )
            files.append(
                (
                    f"agent/config/agents/zone4/{w_team}/{w_name}.md",
                    worker_prompt_for(w_name, w_team, w_role),
                )
            )

        return BundleResult(files=tuple(files))


@dataclass(frozen=True)
class ChiefSpecialistBundle:
    """Chief + exactly one named specialist.

    Convenience wrapper over AgentTeamBundle for the common 1-specialist
    pattern: eliminates the caller-side workers_block string assembly.

    Required kwargs: team, prefix, description, chief_name, chief_role,
        chief_mission, specialist_name, specialist_role
    """

    def render(  # type: ignore[override]
        self,
        team: str,
        prefix: str,
        description: str,
        chief_name: str,
        chief_role: str,
        chief_mission: str,
        specialist_name: str,
        specialist_role: str = "<one-line specialist role>",
    ) -> BundleResult:
        workers_block = worker_yaml_block_for(specialist_name, team, specialist_role)
        bundle = AgentTeamBundle(
            worker_specs=((specialist_name, team, specialist_role),)
        )
        return bundle.render(
            name=team,
            prefix=prefix,
            description=description,
            chief_name=chief_name,
            chief_role=chief_role,
            chief_mission=chief_mission,
            workers_block=workers_block,
        )


@dataclass(frozen=True)
class ScaffoldPaths:
    """Resolved on-disk paths for a single specialist scaffold."""

    expertise: str         # agent/config/expertise/updatable/<name>.md
    system_prompt: str     # agent/config/agents/zone4/<team>/<name>.md
    placeholder_test: str  # agent/tests/test_teams/test_specialist_<name>.py
    checklist: str         # agent/data/scaffolding/<name>-checklist.md


@dataclass(frozen=True)
class TeamScaffoldPaths:
    """Resolved on-disk paths for a full team scaffold."""

    team_yaml: str          # agent/config/teams/<name>.yaml
    chief_expertise: str    # agent/config/expertise/updatable/<chief>.md
    chief_prompt: str       # agent/config/agents/zone4/<name>/<chief>.md
    worker_expertises: tuple[str, ...]   # one per specialist
    worker_prompts: tuple[str, ...]      # one per specialist
    checklist: str          # agent/data/scaffolding/<name>-team-checklist.md


def expertise_for(name: str, team: str) -> str:
    """Render EXPERTISE_TEMPLATE for a specialist."""
    return EXPERTISE_TEMPLATE.format(name=name, team=team)


def worker_prompt_for(
    name: str,
    team: str,
    role: str = "<one-line role description>",
) -> str:
    """Render WORKER_SYSTEM_PROMPT_TEMPLATE for a specialist."""
    return WORKER_SYSTEM_PROMPT_TEMPLATE.format(name=name, team=team, role=role)


def chief_expertise_for(name: str, team: str) -> str:
    """Render CHIEF_EXPERTISE_TEMPLATE for a chief agent."""
    return CHIEF_EXPERTISE_TEMPLATE.format(name=name, team=team)


def chief_prompt_for(
    name: str,
    team: str,
    prefix: str,
    role: str = "<one-line chief role>",
    mission: str = "<!-- 3-5 sentences describing department mission -->",
) -> str:
    """Render CHIEF_SYSTEM_PROMPT_TEMPLATE for a chief agent.

    Note: the rendered template preserves the literal ``{ROSTER}`` placeholder
    (double-brace escaped) so DepartmentRegistry.prewarm() can inject the live
    specialist list at runtime.
    """
    return CHIEF_SYSTEM_PROMPT_TEMPLATE.format(
        name=name,
        team=team,
        prefix=prefix,
        role=role,
        mission=mission,
    )


def worker_yaml_block_for(name: str, team: str, role: str) -> str:
    """Render a single YAML worker block for embedding in the team YAML."""
    return WORKER_YAML_BLOCK_TEMPLATE.format(
        name=name,
        team=team,
        role=role,
        default_zone4_model=DEFAULT_ZONE4_TOOL_CAPABLE_MODEL,
        default_zone4_adapter=DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER,
    )


def team_yaml_for(
    name: str,
    prefix: str,
    description: str,
    chief_name: str,
    chief_role: str,
    chief_mission: str,
    workers_block: str,
) -> str:
    """Render TEAM_YAML_TEMPLATE for a new department."""
    return TEAM_YAML_TEMPLATE.format(
        name=name,
        prefix=prefix,
        description=description,
        chief_name=chief_name,
        chief_role=chief_role,
        chief_mission=chief_mission,
        workers_block=workers_block,
        default_zone4_model=DEFAULT_ZONE4_TOOL_CAPABLE_MODEL,
        default_zone4_adapter=DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER,
    )


# ---------------------------------------------------------------------------
# E4.7 — Skill scaffold bundle
# ---------------------------------------------------------------------------

# Frontmatter matches the repo convention at agent/config/skills/ (3 fields).
# Extra fields are allowed so ad-hoc skill variants can add their own without
# breaking validation. The audit_skill_frontmatter.py script enforces the
# ~/.claude/skills/ installed convention separately.
class _SkillFrontmatterSchema(BaseModel):
    name: str
    description: str
    # Stored as a comma-separated string in YAML (e.g. "Bash, Read, Write"),
    # not a YAML list — match what the repo convention actually uses.
    allowed_tools: str = Field(default="", alias="allowed-tools")
    # E4.8 — assignment scope: main | global | <team_name>
    # Default 'main' preserves today's behavior (main agent only).
    assignment: str = "main"

    model_config = {"extra": "allow", "populate_by_name": True}


SKILL_TEMPLATE = """\
---
name: {name}
description: {description}
allowed-tools: Bash, Read, Write
assignment: {assignment}
---

# {name}

<!-- Replace this stub with the actual skill content. -->

## When to use

<!-- 2-3 sentences on the trigger conditions for this skill. -->

## What it does

<!-- Numbered steps describing the skill's behavior. -->

1. Step one
2. Step two
3. Step three

## Examples

<!-- 1-3 usage examples showing typical invocations. -->

## Operator checklist

- [ ] Filled in "When to use" section
- [ ] Described steps accurately
- [ ] Provided at least one example
- [ ] Adjusted allowed-tools to only what this skill needs
"""


@dataclass(frozen=True)
class _SkillBundle:
    """Scaffold a single Claude Code skill manifest.

    Produces one file: either a standalone ``<name>.md`` or a directory-form
    ``<name>/SKILL.md`` depending on the ``directory_form`` flag.

    Required kwargs: name, description
    Optional kwargs: directory_form (bool, default False)
    """

    def render(  # type: ignore[override]
        self,
        name: str,
        description: str,
        directory_form: bool = False,
        assignment: str = "main",
    ) -> BundleResult:
        path = (
            f"agent/config/skills/{name}/SKILL.md"
            if directory_form
            else f"agent/config/skills/{name}.md"
        )
        content = SKILL_TEMPLATE.format(
            name=name, description=description, assignment=assignment
        )
        return BundleResult(files=((path, content),))


SKILL_BUNDLE = _SkillBundle()
