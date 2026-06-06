"""Z3-04 — governance bundle loading + prompt assembly for Zone 3 engineering.

Each engineering agent (chief + specialists) has a governance bundle under
``agent/config/governance/zone3/engineering/<agent-name>/`` containing
``CLAUDE.md``, ``SOUL.md``, and ``ARTIFACTS.md``. The loader concatenates the
bundle, then the specialist's base prompt, then the task — in that deterministic
order — so governance always precedes the task and no Zone 4 governance path is
ever consulted.

Governance files are line-capped (:data:`GOVERNANCE_LINE_CAP`) to keep the
subprocess context tight; the test suite fails if a file exceeds the cap.
"""

from __future__ import annotations

from pathlib import Path

from zone3.engineering_config import EngineeringSpecialist, EngineeringTeamConfig

_AGENT_ROOT = Path(__file__).resolve().parents[1]  # .../agent
ZONE3_GOVERNANCE_ROOT = _AGENT_ROOT / "config" / "governance" / "zone3" / "engineering"

GOVERNANCE_FILE_NAMES: tuple[str, ...] = ("CLAUDE.md", "SOUL.md", "ARTIFACTS.md")
GOVERNANCE_LINE_CAP = 120


def governance_bundle_dir(agent_name: str) -> Path:
    """Return the governance bundle directory for an engineering agent."""
    return ZONE3_GOVERNANCE_ROOT / agent_name


def load_zone3_governance(*, agent_name: str) -> str:
    """Load and concatenate an agent's governance bundle in fixed order.

    Raises:
        FileNotFoundError: when the agent has no governance bundle.
    """
    bundle = governance_bundle_dir(agent_name)
    if not bundle.is_dir():
        raise FileNotFoundError(f"no Zone 3 governance bundle for agent: {agent_name}")
    parts: list[str] = []
    for filename in GOVERNANCE_FILE_NAMES:
        path = bundle / filename
        if not path.is_file():
            raise FileNotFoundError(f"missing {filename} in governance bundle: {bundle}")
        parts.append(path.read_text(encoding="utf-8").rstrip())
    return "\n\n".join(part for part in parts if part.strip())


def build_engineering_prompt(
    config: EngineeringTeamConfig,
    specialist: EngineeringSpecialist,
    task: str,
) -> str:
    """Assemble governance + base prompt + task in deterministic order.

    ``config`` is accepted for signature parity with the dispatcher's
    ``PromptBuilder`` seam; governance resolution is by agent name.
    """
    governance = load_zone3_governance(agent_name=specialist.name)
    base_prompt = (
        specialist.prompt.read_text(encoding="utf-8")
        if specialist.prompt.is_file()
        else ""
    )
    parts = [
        part
        for part in (governance, base_prompt, f"Task:\n{task}")
        if part.strip()
    ]
    return "\n\n---\n\n".join(parts)


__all__ = [
    "GOVERNANCE_FILE_NAMES",
    "GOVERNANCE_LINE_CAP",
    "ZONE3_GOVERNANCE_ROOT",
    "build_engineering_prompt",
    "governance_bundle_dir",
    "load_zone3_governance",
]
