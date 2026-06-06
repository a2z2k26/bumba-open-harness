"""Report-only Zone 4 capability manifest parser and comparator."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

CapabilityMode = Literal["report_only", "strict"]
CapabilityRole = Literal["chief", "specialist"]
_MODES = {"report_only", "strict"}
_TOP_LEVEL_FIELDS = {"department", "mode", "defaults", "chief", "specialists"}
_GRANT_FIELDS = {"tools", "skills", "mcp_servers"}


class CapabilityManifestError(ValueError):
    """Raised when a capability manifest is malformed."""


@dataclass(frozen=True)
class CapabilityGrant:
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityManifest:
    department: str
    mode: CapabilityMode
    defaults: CapabilityGrant
    chief: dict[str, CapabilityGrant]
    specialists: dict[str, CapabilityGrant]
    path: Path


@dataclass(frozen=True)
class CapabilityReport:
    department: str
    agent: str
    role: CapabilityRole
    mode: CapabilityMode
    extra_tools: tuple[str, ...] = ()
    missing_tools: tuple[str, ...] = ()
    extra_skills: tuple[str, ...] = ()
    missing_skills: tuple[str, ...] = ()
    extra_mcp_servers: tuple[str, ...] = ()
    missing_mcp_servers: tuple[str, ...] = ()

    @property
    def has_violation(self) -> bool:
        return any(
            (
                self.extra_tools,
                self.missing_tools,
                self.extra_skills,
                self.missing_skills,
                self.extra_mcp_servers,
                self.missing_mcp_servers,
            )
        )

    def telemetry_fields(self) -> tuple[tuple[str, str], ...]:
        prefix = f"capability.{self.agent}"
        fields: list[tuple[str, str]] = [
            (f"{prefix}.mode", self.mode),
            (f"{prefix}.role", self.role),
            (f"{prefix}.violation", str(self.has_violation).lower()),
        ]
        for field_name in (
            "extra_tools",
            "missing_tools",
            "extra_skills",
            "missing_skills",
            "extra_mcp_servers",
            "missing_mcp_servers",
        ):
            values = getattr(self, field_name)
            if values:
                fields.append((f"{prefix}.{field_name}", ",".join(values)))
        return tuple(fields)


def load_capability_manifest(path: Path | str) -> CapabilityManifest:
    manifest_path = Path(path)
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise CapabilityManifestError(f"{manifest_path}: expected mapping")
    _reject_unknown(data, _TOP_LEVEL_FIELDS, f"{manifest_path}: top level")

    department = _required_str(data, "department", manifest_path)
    mode_raw = _required_str(data, "mode", manifest_path)
    if mode_raw not in _MODES:
        raise CapabilityManifestError(
            f"{manifest_path}: mode must be one of {sorted(_MODES)}"
        )

    return CapabilityManifest(
        department=department,
        mode=mode_raw,  # type: ignore[arg-type]
        defaults=_parse_grant(data.get("defaults") or {}, manifest_path, "defaults"),
        chief=_parse_grant_map(data.get("chief") or {}, manifest_path, "chief"),
        specialists=_parse_grant_map(
            data.get("specialists") or {},
            manifest_path,
            "specialists",
        ),
        path=manifest_path,
    )


def load_capability_manifests(root: Path | str) -> dict[str, CapabilityManifest]:
    root_path = Path(root)
    manifests: dict[str, CapabilityManifest] = {}
    for path in sorted(root_path.glob("*.yaml")):
        manifest = load_capability_manifest(path)
        if manifest.department in manifests:
            raise CapabilityManifestError(
                f"duplicate department {manifest.department!r}: {path}"
            )
        manifests[manifest.department] = manifest
    return manifests


def capability_grant_for_agent(
    manifest: CapabilityManifest,
    *,
    agent_name: str,
    role: CapabilityRole,
) -> CapabilityGrant:
    if role == "chief":
        specific = manifest.chief.get(agent_name)
    else:
        specific = manifest.specialists.get(agent_name)
    return _merge_grants(manifest.defaults, specific or CapabilityGrant())


def compare_capabilities(
    *,
    department: str,
    agent_name: str,
    role: CapabilityRole,
    actual_tools: Iterable[str],
    actual_skills: Iterable[str],
    actual_mcp_servers: Iterable[str],
    manifest: CapabilityManifest,
) -> CapabilityReport:
    grant = capability_grant_for_agent(
        manifest,
        agent_name=agent_name,
        role=role,
    )
    tools = _dedupe(actual_tools)
    skills = _dedupe(actual_skills)
    mcp_servers = _dedupe(actual_mcp_servers)
    return CapabilityReport(
        department=department,
        agent=agent_name,
        role=role,
        mode=manifest.mode,
        extra_tools=_extras(tools, grant.tools),
        missing_tools=_missing(grant.tools, tools),
        extra_skills=_extras(skills, grant.skills),
        missing_skills=_missing(grant.skills, skills),
        extra_mcp_servers=_extras(mcp_servers, grant.mcp_servers),
        missing_mcp_servers=_missing(grant.mcp_servers, mcp_servers),
    )


def filter_tools_for_manifest(
    *,
    actual_tools: Iterable[str],
    grant: CapabilityGrant,
    mode: CapabilityMode,
) -> tuple[str, ...]:
    """Return the tool names that may be registered under a manifest mode."""
    tools = _dedupe(actual_tools)
    if mode == "report_only":
        return tools
    allowed = set(grant.tools)
    return tuple(tool for tool in tools if tool in allowed)


def _parse_grant_map(
    raw: object,
    path: Path,
    label: str,
) -> dict[str, CapabilityGrant]:
    if not isinstance(raw, dict):
        raise CapabilityManifestError(f"{path}: {label} must be a mapping")
    grants: dict[str, CapabilityGrant] = {}
    for agent_name, grant_raw in raw.items():
        if not isinstance(agent_name, str) or not agent_name:
            raise CapabilityManifestError(f"{path}: {label} has invalid agent name")
        grants[agent_name] = _parse_grant(
            grant_raw or {},
            path,
            f"{label}.{agent_name}",
        )
    return grants


def _parse_grant(raw: object, path: Path, label: str) -> CapabilityGrant:
    if not isinstance(raw, dict):
        raise CapabilityManifestError(f"{path}: {label} must be a mapping")
    _reject_unknown(raw, _GRANT_FIELDS, f"{path}: {label}")
    return CapabilityGrant(
        tools=_string_tuple(raw.get("tools", []), path, f"{label}.tools"),
        skills=_string_tuple(raw.get("skills", []), path, f"{label}.skills"),
        mcp_servers=_string_tuple(
            raw.get("mcp_servers", []),
            path,
            f"{label}.mcp_servers",
        ),
    )


def _merge_grants(
    defaults: CapabilityGrant,
    specific: CapabilityGrant,
) -> CapabilityGrant:
    return CapabilityGrant(
        tools=_dedupe((*defaults.tools, *specific.tools)),
        skills=_dedupe((*defaults.skills, *specific.skills)),
        mcp_servers=_dedupe((*defaults.mcp_servers, *specific.mcp_servers)),
    )


def _extras(actual: tuple[str, ...], allowed: tuple[str, ...]) -> tuple[str, ...]:
    allowed_set = set(allowed)
    return tuple(value for value in actual if value not in allowed_set)


def _missing(allowed: tuple[str, ...], actual: tuple[str, ...]) -> tuple[str, ...]:
    actual_set = set(actual)
    return tuple(value for value in allowed if value not in actual_set)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _string_tuple(raw: object, path: Path, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise CapabilityManifestError(f"{path}: {label} must be a list")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise CapabilityManifestError(f"{path}: {label} must contain strings")
        values.append(item)
    return tuple(values)


def _required_str(data: dict[object, object], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise CapabilityManifestError(f"{path}: {key} must be a non-empty string")
    return value


def _reject_unknown(
    data: dict[object, object],
    allowed: set[str],
    label: str,
) -> None:
    unknown = sorted(str(key) for key in data if key not in allowed)
    if unknown:
        raise CapabilityManifestError(f"{label}: unknown fields {unknown}")
