"""Strict parser for the Zone 3 engineering team config."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINEERING_CONFIG_PATH = REPO_ROOT / "agent" / "config" / "zone3" / "engineering.yaml"

ExecutionMode = Literal["claude-p"]


class EngineeringConfigError(ValueError):
    """Raised when the Zone 3 engineering config is invalid."""


@dataclass(frozen=True)
class EngineeringChief:
    name: str
    model: str
    prompt: Path
    max_parallel_specialists: int


@dataclass(frozen=True)
class EngineeringSpecialist:
    name: str
    model: str
    prompt: Path
    when_to_call: str
    write_scopes: tuple[str, ...]
    allowed_mcp_servers: tuple[str, ...]


@dataclass(frozen=True)
class EngineeringEscalationThresholds:
    delegate_at_complexity: int
    chief_at_complexity: int
    zone4_at_complexity: int


@dataclass(frozen=True)
class EngineeringConstraints:
    timeout_seconds: int
    max_parallel_specialists: int
    require_worktree: bool
    require_local_ci: bool
    escalation_thresholds: EngineeringEscalationThresholds


@dataclass(frozen=True)
class EngineeringTools:
    common: tuple[str, ...]
    mcp_allowed_servers: tuple[str, ...]


@dataclass(frozen=True)
class EngineeringTeamConfig:
    name: str
    zone: int
    execution: ExecutionMode
    description: str
    chief: EngineeringChief
    constraints: EngineeringConstraints
    tools: EngineeringTools
    specialists: tuple[EngineeringSpecialist, ...]

    @property
    def chief_name(self) -> str:
        return self.chief.name

    @property
    def timeout_seconds(self) -> int:
        return self.constraints.timeout_seconds

    @property
    def require_worktree(self) -> bool:
        return self.constraints.require_worktree

    @property
    def require_local_ci(self) -> bool:
        return self.constraints.require_local_ci


def _repo_root_for_config(config_path: Path) -> Path:
    resolved = config_path.resolve()
    try:
        return resolved.parents[3]
    except IndexError as exc:
        raise EngineeringConfigError(
            f"config path is too shallow to infer repo root: {config_path}"
        ) from exc


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise EngineeringConfigError(f"{context} must be a mapping")
    out: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise EngineeringConfigError(f"{context} contains non-string key {key!r}")
        out[key] = item
    return out


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: set[str],
    context: str,
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        joined = ", ".join(f"{context}.{key}" for key in unknown)
        raise EngineeringConfigError(f"unknown field(s): {joined}")


def _required(mapping: Mapping[str, object], key: str, context: str) -> object:
    if key not in mapping:
        raise EngineeringConfigError(f"{context}.{key} is required")
    return mapping[key]


def _string(mapping: Mapping[str, object], key: str, context: str) -> str:
    value = _required(mapping, key, context)
    if not isinstance(value, str) or not value.strip():
        raise EngineeringConfigError(f"{context}.{key} must be a non-empty string")
    return value


def _int(mapping: Mapping[str, object], key: str, context: str) -> int:
    value = _required(mapping, key, context)
    if not isinstance(value, int) or isinstance(value, bool):
        raise EngineeringConfigError(f"{context}.{key} must be an integer")
    return value


def _positive_int(mapping: Mapping[str, object], key: str, context: str) -> int:
    value = _int(mapping, key, context)
    if value <= 0:
        raise EngineeringConfigError(f"{context}.{key} must be > 0")
    return value


def _bool(mapping: Mapping[str, object], key: str, context: str) -> bool:
    value = _required(mapping, key, context)
    if not isinstance(value, bool):
        raise EngineeringConfigError(f"{context}.{key} must be a boolean")
    return value


def _string_tuple(mapping: Mapping[str, object], key: str, context: str) -> tuple[str, ...]:
    value = _required(mapping, key, context)
    if not isinstance(value, list) or not value:
        raise EngineeringConfigError(f"{context}.{key} must be a non-empty list")
    strings: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise EngineeringConfigError(
                f"{context}.{key}[{index}] must be a non-empty string"
            )
        strings.append(item)
    return tuple(strings)


def _prompt_path(
    mapping: Mapping[str, object],
    *,
    owner: str,
    repo_root: Path,
    context: str,
) -> Path:
    raw = _string(mapping, "prompt", context)
    prompt = Path(raw)
    resolved = prompt if prompt.is_absolute() else repo_root / prompt
    if not resolved.is_file():
        raise EngineeringConfigError(
            f"{owner}.prompt references missing file: {raw}"
        )
    return prompt


def _parse_thresholds(raw: object) -> EngineeringEscalationThresholds:
    context = "team.constraints.escalation_thresholds"
    thresholds = _mapping(raw, context)
    _reject_unknown(
        thresholds,
        {"delegate_at_complexity", "chief_at_complexity", "zone4_at_complexity"},
        context,
    )
    delegate_at = _positive_int(thresholds, "delegate_at_complexity", context)
    chief_at = _positive_int(thresholds, "chief_at_complexity", context)
    zone4_at = _positive_int(thresholds, "zone4_at_complexity", context)
    if not delegate_at <= chief_at <= zone4_at:
        raise EngineeringConfigError(
            "team.constraints.escalation_thresholds must satisfy "
            "delegate_at_complexity <= chief_at_complexity <= zone4_at_complexity"
        )
    return EngineeringEscalationThresholds(
        delegate_at_complexity=delegate_at,
        chief_at_complexity=chief_at,
        zone4_at_complexity=zone4_at,
    )


def _parse_chief(raw: object, *, repo_root: Path) -> EngineeringChief:
    context = "team.chief"
    chief = _mapping(raw, context)
    _reject_unknown(
        chief,
        {"name", "model", "prompt", "max_parallel_specialists"},
        context,
    )
    name = _string(chief, "name", context)
    return EngineeringChief(
        name=name,
        model=_string(chief, "model", context),
        prompt=_prompt_path(chief, owner=name, repo_root=repo_root, context=context),
        max_parallel_specialists=_positive_int(
            chief,
            "max_parallel_specialists",
            context,
        ),
    )


def _parse_constraints(raw: object) -> EngineeringConstraints:
    context = "team.constraints"
    constraints = _mapping(raw, context)
    _reject_unknown(
        constraints,
        {
            "timeout_seconds",
            "max_parallel_specialists",
            "require_worktree",
            "require_local_ci",
            "escalation_thresholds",
        },
        context,
    )
    return EngineeringConstraints(
        timeout_seconds=_positive_int(constraints, "timeout_seconds", context),
        max_parallel_specialists=_positive_int(
            constraints,
            "max_parallel_specialists",
            context,
        ),
        require_worktree=_bool(constraints, "require_worktree", context),
        require_local_ci=_bool(constraints, "require_local_ci", context),
        escalation_thresholds=_parse_thresholds(
            _required(constraints, "escalation_thresholds", context)
        ),
    )


def _parse_tools(raw: object) -> EngineeringTools:
    context = "team.tools"
    tools = _mapping(raw, context)
    _reject_unknown(tools, {"common", "mcp_allowed_servers"}, context)
    return EngineeringTools(
        common=_string_tuple(tools, "common", context),
        mcp_allowed_servers=_string_tuple(tools, "mcp_allowed_servers", context),
    )


def _parse_specialists(raw: object, *, repo_root: Path) -> tuple[EngineeringSpecialist, ...]:
    if not isinstance(raw, list) or not raw:
        raise EngineeringConfigError("team.specialists must be a non-empty list")

    specialists: list[EngineeringSpecialist] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        context = f"specialists[{index}]"
        specialist = _mapping(item, context)
        _reject_unknown(
            specialist,
            {
                "name",
                "model",
                "prompt",
                "when_to_call",
                "write_scopes",
                "allowed_mcp_servers",
            },
            context,
        )
        name = _string(specialist, "name", context)
        if name in seen:
            raise EngineeringConfigError(f"duplicate specialist name: {name}")
        seen.add(name)
        specialists.append(
            EngineeringSpecialist(
                name=name,
                model=_string(specialist, "model", context),
                prompt=_prompt_path(
                    specialist,
                    owner=name,
                    repo_root=repo_root,
                    context=context,
                ),
                when_to_call=_string(specialist, "when_to_call", context),
                write_scopes=_string_tuple(specialist, "write_scopes", context),
                allowed_mcp_servers=_string_tuple(
                    specialist,
                    "allowed_mcp_servers",
                    context,
                ),
            )
        )
    return tuple(specialists)


def load_engineering_team_config(
    config_path: Path = DEFAULT_ENGINEERING_CONFIG_PATH,
) -> EngineeringTeamConfig:
    """Load and validate a Zone 3 engineering team config."""
    config_path = config_path.resolve()
    repo_root = _repo_root_for_config(config_path)
    try:
        raw: object = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EngineeringConfigError(f"could not read config: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise EngineeringConfigError(f"could not parse YAML: {config_path}") from exc

    root = _mapping(raw, "root")
    _reject_unknown(root, {"team"}, "root")
    team = _mapping(_required(root, "team", "root"), "team")
    _reject_unknown(
        team,
        {
            "name",
            "zone",
            "execution",
            "description",
            "chief",
            "constraints",
            "tools",
            "specialists",
        },
        "team",
    )

    name = _string(team, "name", "team")
    if name != "engineering":
        raise EngineeringConfigError("team.name must be engineering")

    zone = _int(team, "zone", "team")
    if zone != 3:
        raise EngineeringConfigError("team.zone must be 3")

    execution = _string(team, "execution", "team")
    if execution != "claude-p":
        raise EngineeringConfigError("team.execution must be claude-p")

    return EngineeringTeamConfig(
        name=name,
        zone=zone,
        execution="claude-p",
        description=_string(team, "description", "team"),
        chief=_parse_chief(_required(team, "chief", "team"), repo_root=repo_root),
        constraints=_parse_constraints(_required(team, "constraints", "team")),
        tools=_parse_tools(_required(team, "tools", "team")),
        specialists=_parse_specialists(
            _required(team, "specialists", "team"),
            repo_root=repo_root,
        ),
    )
