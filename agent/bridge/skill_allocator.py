"""Centralized skill allocator for #1112 Phase 4.

Default-deny: a skill is available to an agent ONLY when explicitly allocated
via the manifest. New skills are dormant until allocated.

Taxonomy axes (hierarchical):
- zone: 3 (engineering) | 4 (autonomous departments)
- department: "engineering" (zone 3 only)
              | "board" | "design" | "qa" | "ops" | "job_search" | "strategy"
              (zone 4). None ⇒ universal across departments.
- role: "chief" | "specialist" | None (None ⇒ universal across roles)
- agent: specific named agent | None (None ⇒ universal across agents within role)

Allocations cascade: a department-only rule flows to every role + agent
inside that department. A role-narrowed rule only surfaces for that role.
An agent-narrowed rule only surfaces for those specific named agents.

The manifest file format (proposed-allocations.yaml) is intentionally
NOT strict YAML — each group node mixes a list-of-skills with an
`allocation:` mapping at the same level. We therefore use a custom
line-based pre-parser that emits a strict YAML intermediate before
handing off to yaml.safe_load.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Zone = Literal[3, 4]
Role = Literal["chief", "specialist"]

# Marker key the pre-parser uses to bucket the skill list inside each group.
_SKILLS_KEY = "_skills"


@dataclass(frozen=True)
class AllocationRule:
    """A single allocation row: one skill, one (zone, dept, role, agents) target.

    Frozen — rules are immutable once constructed. The allocator builds
    rules at load time and never mutates them.

    Override rules (``override=True``) are agent-scoped grants that bypass
    the (zone, dept, role) matching dimensions. The operator uses overrides
    to issue a specific skill to a specific named agent post-team allocation
    — see Sprint 4.05 (#2152). On an override rule, ``zone``/``department``/
    ``role`` are populated with sentinels for provenance display but are
    NOT consulted during matching.
    """

    skill: str
    zone: Zone
    department: str | None = None
    role: Role | None = None
    agents: tuple[str, ...] = ()
    note: str | None = None
    override: bool = False


@dataclass(frozen=True)
class AgentSkillReport:
    """Per-agent discovery report — Sprint 4.04 / #2151.

    Returned by ``SkillAllocator.describe_agent``. Frozen for the same
    reason as ``AllocationRule`` — once the allocator computes the
    report, callers must not mutate it.

    Attributes:
        agent_name: The agent the report describes. ``None`` when the
            caller asked for a department- or role-wide view rather than
            a specific named agent.
        zone: ``3`` (engineering) or ``4`` (autonomous departments).
        department: Department the agent belongs to, or ``None`` for a
            zone-wide / cross-department query.
        role: ``"chief"`` / ``"specialist"`` / ``None`` for a
            role-universal query.
        allowed_skills: Skills the agent is allowed to use, sorted
            alphabetically. Empty tuple when default-deny applies (no
            rule matched).
        source_rules: Per-skill provenance. Each entry is
            ``(skill, rule_summary)`` where ``rule_summary`` is a
            short, human-readable description of the most-specific
            allocation rule that granted the skill. Sorted by skill
            name so the table aligns with ``allowed_skills``.

    Provenance policy: when more than one rule grants the same skill
    we surface the **most-specific** rule (agents > role > department >
    universal). This is the most useful row for an operator answering
    "why does this agent have this skill?".
    """

    agent_name: str | None
    zone: Zone
    department: str | None
    role: Role | None
    allowed_skills: tuple[str, ...]
    source_rules: tuple[tuple[str, str], ...]


def _rule_summary(rule: AllocationRule) -> str:
    """Build a short, human-readable provenance string for a rule.

    Examples:
        zone=3, dept=engineering, agents=[engineering-backend-architect]
        zone=4, dept=design, role=chief
        zone=3, dept=engineering (universal)
        zone=4 (universal across departments)
        OVERRIDE agents=[engineering-backend-architect]

    Override rules render with an explicit ``OVERRIDE`` prefix so the operator
    answering "why does this agent have this skill?" sees immediately that the
    grant is a per-agent post-team allocation, not a categorical rule.
    """
    if rule.override:
        return f"OVERRIDE agents=[{','.join(rule.agents)}]"
    parts: list[str] = [f"zone={rule.zone}"]
    if rule.department is not None:
        parts.append(f"dept={rule.department}")
    if rule.role is not None:
        parts.append(f"role={rule.role}")
    if rule.agents:
        parts.append(f"agents=[{','.join(rule.agents)}]")
    # Mark universal scopes explicitly so operators can spot them.
    if rule.department is None:
        return ", ".join(parts) + " (universal across departments)"
    if rule.role is None and not rule.agents:
        return ", ".join(parts) + " (universal)"
    return ", ".join(parts)


def _rule_specificity(rule: AllocationRule) -> int:
    """Higher = more specific. Used to pick provenance per skill.

    Ordering (override > agents > role > department > universal) matches how
    a human operator reasons about "which rule actually grants this":

      5 — override (operator's explicit per-agent post-team allocation, #2152)
      4 — agent-narrowed rule (most specific categorical)
      3 — role-narrowed (chief or specialist) but no agent list
      2 — department-only
      1 — fully universal (no dept, no role, no agents)
    """
    if rule.override:
        return 5
    if rule.agents:
        return 4
    if rule.role is not None:
        return 3
    if rule.department is not None:
        return 2
    return 1


@dataclass
class SkillAllocator:
    """Default-deny skill allocator. Manifest-driven.

    A SkillAllocator with `rules=[]` returns an empty set for every query.
    This is the security posture — explicit allocation is required for
    any skill to be available to any agent.
    """

    rules: list[AllocationRule] = field(default_factory=list)

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> "SkillAllocator":
        """Load + parse the proposed-allocations.yaml format.

        See module docstring for why we don't use yaml.safe_load directly.
        """
        text = Path(manifest_path).read_text()
        normalized = _normalize_manifest_text(text)
        data = yaml.safe_load(normalized) or {}

        rules: list[AllocationRule] = []
        for category in data.get("categories", []) or []:
            skills_dict = category.get("skills") or {}
            if not isinstance(skills_dict, dict):
                continue
            for _group_name, group in skills_dict.items():
                if not isinstance(group, dict):
                    continue
                skill_names = _extract_skills_from_group(group)
                allocation_list = group.get("allocation") or []
                if not isinstance(allocation_list, list):
                    continue
                for alloc in allocation_list:
                    if not isinstance(alloc, dict):
                        continue
                    zone = alloc.get("zone")
                    if zone not in (3, 4):
                        continue
                    department = alloc.get("department")
                    role = alloc.get("role")
                    agents_raw = alloc.get("agents") or ()
                    agents = tuple(str(a) for a in agents_raw)
                    note = alloc.get("note")
                    for skill in skill_names:
                        rules.append(
                            AllocationRule(
                                skill=skill,
                                zone=zone,  # type: ignore[arg-type]
                                department=department,
                                role=role,  # type: ignore[arg-type]
                                agents=agents,
                                note=note,
                            )
                        )

        # Sprint 4.05 (#2152) — overrides: per-agent skill grants that bypass
        # (zone, dept, role) matching. Each override entry names ONE agent +
        # a list of skills to grant. Overrides are applied AFTER categorical
        # rules so an override-granted skill simply joins the agent's allowed
        # set (cannot remove; removal stays an edit to the main rules).
        for override in data.get("overrides") or ():
            if not isinstance(override, dict):
                continue
            agent_name = override.get("agent")
            if not isinstance(agent_name, str) or not agent_name:
                continue
            skills_raw = override.get("skills") or ()
            note = override.get("note")
            for skill in skills_raw:
                if not isinstance(skill, str):
                    continue
                rules.append(
                    AllocationRule(
                        skill=skill,
                        zone=3,  # sentinel — not consulted on override rules
                        department=None,
                        role=None,
                        agents=(agent_name,),
                        note=note,
                        override=True,
                    )
                )

        return cls(rules=rules)

    def allowed_skills(
        self,
        *,
        zone: Zone,
        department: str | None = None,
        role: Role | None = None,
        agent_name: str | None = None,
    ) -> set[str]:
        """Return the set of skills allowed for an agent on (zone, dept, role, agent).

        Default-deny: returns an empty set if no rule matches.

        Matching semantics:
        - rule.zone must equal `zone` (no cross-zone leak)
        - rule.department=None ⇒ universal across departments
          rule.department set ⇒ must equal `department`
        - rule.role=None ⇒ universal across roles
          rule.role set ⇒ must equal `role`
        - rule.agents=() ⇒ universal across agents within the role
          rule.agents set ⇒ `agent_name` must be in the tuple
            (None agent_name ⇒ does NOT match an agent-narrowed rule)
        """
        out: set[str] = set()
        for rule in self.rules:
            # Sprint 4.05 (#2152) — overrides bypass (zone, dept, role)
            # matching entirely. Match by agent_name only.
            if rule.override:
                if agent_name is not None and agent_name in rule.agents:
                    out.add(rule.skill)
                continue
            if rule.zone != zone:
                continue
            if rule.department is not None and rule.department != department:
                continue
            if rule.role is not None and rule.role != role:
                continue
            if rule.agents:
                if agent_name is None or agent_name not in rule.agents:
                    continue
            out.add(rule.skill)
        return out

    def describe_agent(
        self,
        *,
        zone: Zone,
        department: str | None = None,
        role: Role | None = None,
        agent_name: str | None = None,
    ) -> AgentSkillReport:
        """Programmatic discovery surface (Sprint 4.04 / #2151).

        Returns an :class:`AgentSkillReport` describing the skills
        allowed for ``(zone, department, role, agent_name)`` plus the
        most-specific allocation rule that granted each skill.

        Default-deny: when no rule matches, ``allowed_skills`` and
        ``source_rules`` are both empty tuples. The report is still
        returned (rather than ``None``) so the operator command can
        render a "0 skills" view without special-casing.

        Provenance policy: per-skill, the rule with the highest
        :func:`_rule_specificity` score wins. Ties are broken by the
        rule's position in ``self.rules`` (earlier wins), which gives
        a deterministic answer when the manifest ships duplicates.
        """
        # Walk rules once; for each match, update a per-skill
        # (rule, specificity) cache so the final report carries one
        # provenance row per skill. Overrides (Sprint 4.05 / #2152) bypass
        # (zone, dept, role) matching and beat any categorical rule on
        # specificity (operator's explicit grant wins for provenance).
        best_by_skill: dict[str, tuple[int, AllocationRule]] = {}
        for rule in self.rules:
            if rule.override:
                if agent_name is None or agent_name not in rule.agents:
                    continue
            else:
                if rule.zone != zone:
                    continue
                if rule.department is not None and rule.department != department:
                    continue
                if rule.role is not None and rule.role != role:
                    continue
                if rule.agents:
                    if agent_name is None or agent_name not in rule.agents:
                        continue
            score = _rule_specificity(rule)
            current = best_by_skill.get(rule.skill)
            if current is None or score > current[0]:
                best_by_skill[rule.skill] = (score, rule)

        skills_sorted = tuple(sorted(best_by_skill))
        source_rules = tuple(
            (skill, _rule_summary(best_by_skill[skill][1])) for skill in skills_sorted
        )
        return AgentSkillReport(
            agent_name=agent_name,
            zone=zone,
            department=department,
            role=role,
            allowed_skills=skills_sorted,
            source_rules=source_rules,
        )


def _extract_skills_from_group(group: dict[str, Any]) -> list[str]:
    """Walk a group dict and return the list of skill names.

    The pre-parser stores the bullet-list of skills under the key
    `_SKILLS_KEY` ("_skills"). Anything else (notably "allocation") is
    ignored. For defensive robustness this also accepts the legacy
    layout where skill names appear as list values under arbitrary keys.
    """
    skills: list[str] = []
    skill_list = group.get(_SKILLS_KEY)
    if isinstance(skill_list, list):
        skills.extend(str(s) for s in skill_list)
        return skills
    # Defensive fallback for any group that wasn't pre-parsed:
    for key, value in group.items():
        if key in {"allocation", _SKILLS_KEY}:
            continue
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            skills.extend(value)
        elif isinstance(value, str):
            skills.append(value)
    return skills


# ----------------------------------------------------------------------
# Custom pre-parser: convert the proposed-allocations.yaml shape into
# strict YAML by rewriting each group's leading bullet list into a
# `_skills:` mapping value before the `allocation:` line.
# ----------------------------------------------------------------------

_GROUP_HEADER_RE = re.compile(r"^( {6})([A-Za-z0-9_]+):\s*$")
_SKILL_BULLET_RE = re.compile(r"^( {8})- (.+?)\s*$")
_ALLOCATION_LINE_RE = re.compile(r"^( {8})allocation:\s*$")


def _normalize_manifest_text(text: str) -> str:
    """Rewrite the custom format into strict YAML.

    Within a group at 6-space indent (`      group_name:`), the file places
    skill bullets at 8-space indent (`        - skill-foo`) followed by
    `        allocation:` at the same indent — invalid YAML.

    We rewrite each such group into:
        group_name:
          _skills:
            - skill-foo
            - skill-bar
          allocation:
            - zone: 3
              ...

    Indentation choice: we use 4-space increments inside groups so the
    resulting YAML is unambiguous.
    """
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        group_header = _GROUP_HEADER_RE.match(line)
        if group_header:
            indent = group_header.group(1)
            name = group_header.group(2)
            # Look ahead: collect skill bullets (8-space `- skill`) until
            # we either hit `allocation:` at 8-space indent or leave the group.
            skills: list[str] = []
            j = i + 1
            saw_allocation = False
            while j < n:
                la = lines[j]
                if not la.strip():
                    # Blank lines inside a group — keep walking
                    j += 1
                    continue
                if _ALLOCATION_LINE_RE.match(la):
                    saw_allocation = True
                    break
                m = _SKILL_BULLET_RE.match(la)
                if m:
                    skills.append(m.group(2))
                    j += 1
                    continue
                # Not a skill bullet, not allocation — could be a comment,
                # nested key, or end of group. If it's at 8-space indent
                # starting with `#`, treat as in-group comment and skip.
                stripped_indent = len(la) - len(la.lstrip(" "))
                if stripped_indent >= 8 and la.lstrip().startswith("#"):
                    j += 1
                    continue
                # Otherwise the group has ended without an allocation block
                # (shouldn't happen in the real fixture, but be defensive).
                break

            if skills and saw_allocation:
                # Emit the rewritten group header
                out.append(f"{indent}{name}:")
                out.append(f"{indent}  {_SKILLS_KEY}:")
                for s in skills:
                    out.append(f"{indent}    - {s}")
                # Emit allocation: line with consistent indent (under group)
                out.append(f"{indent}  allocation:")
                # Continue from j+1; the rest of the allocation block follows.
                # We need to keep the allocation entries but reindent them
                # so they're under `  allocation:` at indent+2.
                # Original allocation entries are at indent+10 ("          - zone: ...");
                # they were correct under the original 8-space `allocation:`.
                # Now `allocation:` is at indent+2 (i.e. 8 spaces total when
                # `indent` is 6 spaces). The entries should be at indent+4 = 10.
                # That matches the original indentation, so we can copy
                # the lines verbatim until the next group/category boundary.
                k = j + 1
                while k < n:
                    la = lines[k]
                    if not la.strip():
                        out.append(la)
                        k += 1
                        continue
                    # Stop when we encounter the next group header
                    # (6-space `name:`) or category boundary (2-space `- id:`).
                    stripped_indent = len(la) - len(la.lstrip(" "))
                    if stripped_indent <= 6 and la.lstrip().startswith(("-", "skills:")):
                        # Reached next category item or new top-level key
                        break
                    if _GROUP_HEADER_RE.match(la):
                        # Reached the next sibling group
                        break
                    if stripped_indent <= 4 and la.lstrip():
                        # Reached category/top-level
                        break
                    out.append(la)
                    k += 1
                i = k
                continue
            # No allocation block found — fall through and emit verbatim
        out.append(line)
        i += 1
    return "\n".join(out) + "\n"
