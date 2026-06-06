"""Feature-flag registry drift audit (Sprint P6.3, issue #1595).

Audits drift between four sources of truth for boolean feature flags:

  1. BridgeConfig dataclass fields (``agent/bridge/config.py``)
  2. ``_TOML_MAP`` entries in the same module
  3. ``agent/config/feature_flags.yaml`` (this registry)
  4. (informational) keys present in ``agent/config/bridge.toml``

Exits 0 when the registry, the dataclass, and the TOML map agree.
Exits 1 when:

  - A bool field on ``BridgeConfig`` has no registry entry
  - A registry entry references a non-existent dataclass field
  - A registry entry's declared ``default`` disagrees with the dataclass default
  - A registry entry's declared ``toml_key`` is not present in ``_TOML_MAP``
    (when non-empty) OR the mapped field disagrees with the registry field
  - A ``_TOML_MAP`` entry points at a bool dataclass field but no registry
    entry covers that field

Stdlib + PyYAML only. Run from anywhere — the script resolves the repo root
relative to its own location.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


# Repo layout: <repo>/agent/scripts/check_feature_flags.py
SCRIPT_PATH = Path(__file__).resolve()
AGENT_ROOT = SCRIPT_PATH.parent.parent
CONFIG_PY = AGENT_ROOT / "bridge" / "config.py"
FEATURE_FLAGS_YAML = AGENT_ROOT / "config" / "feature_flags.yaml"
BRIDGE_TOML = AGENT_ROOT / "config" / "bridge.toml"

VALID_STATUSES = frozenset({"active", "dormant", "scaffold", "deprecated"})
REQUIRED_REGISTRY_KEYS = frozenset(
    {"toml_key", "owner", "default", "runtime_reader", "docs", "status"}
)


@dataclass(frozen=True)
class BoolField:
    """A bool field discovered on the BridgeConfig dataclass."""

    name: str
    default: bool


def _parse_config_module(config_py: Path) -> tuple[dict[str, BoolField], dict[str, str]]:
    """Return (bool_fields_by_name, toml_map) from ``bridge/config.py``.

    Uses AST so we don't have to import bridge.config (which needs secrets
    + runtime paths). Only top-level class ``BridgeConfig`` and the module-level
    ``_TOML_MAP`` constant are inspected.
    """
    source = config_py.read_text(encoding="utf-8")
    tree = ast.parse(source)

    bool_fields: dict[str, BoolField] = {}
    toml_map: dict[str, str] = {}

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "BridgeConfig":
            for item in node.body:
                if not isinstance(item, ast.AnnAssign):
                    continue
                target = item.target
                if not isinstance(target, ast.Name):
                    continue
                # Type annotation must be the bare name `bool`. We do not
                # include `bool | None` or other unions — only plain bool flags.
                annotation = item.annotation
                if not (isinstance(annotation, ast.Name) and annotation.id == "bool"):
                    continue
                if item.value is None:
                    continue
                # Default must be a literal True/False (ast.Constant).
                if not (isinstance(item.value, ast.Constant) and isinstance(item.value.value, bool)):
                    continue
                bool_fields[target.id] = BoolField(name=target.id, default=item.value.value)
        elif isinstance(node, ast.Assign):
            # Find `_TOML_MAP: dict[str, str] = {...}`
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_TOML_MAP":
                    if isinstance(node.value, ast.Dict):
                        toml_map.update(_dict_from_ast(node.value))
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == "_TOML_MAP":
                if isinstance(node.value, ast.Dict):
                    toml_map.update(_dict_from_ast(node.value))

    return bool_fields, toml_map


def _dict_from_ast(node: ast.Dict) -> dict[str, str]:
    """Convert an ast.Dict of str -> str literals into a Python dict."""
    out: dict[str, str] = {}
    for key_node, val_node in zip(node.keys, node.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        # Right-hand side may be a string literal OR a parenthesized
        # implicit-concat string (modeled as ast.Constant in Python's AST
        # after constant-folding). Skip anything we can't resolve.
        val = _resolve_str(val_node)
        if val is None:
            continue
        out[key_node.value] = val
    return out


def _resolve_str(node: ast.AST) -> str | None:
    """Resolve a string-literal AST node, including parenthesized concats."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # Tuple of strings — bridge/config.py uses `("a" "b")` for line wrapping
    # which the parser flattens to a single Constant, but defensive code:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_str(node.left)
        right = _resolve_str(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _load_registry(path: Path) -> dict[str, dict[str, Any]]:
    """Load the YAML registry. Returns {field_name: entry_dict}."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _load_toml_keys(path: Path) -> set[str]:
    """Return the set of ``section.key`` paths declared in bridge.toml.

    Used informationally — drift between bridge.toml and the registry is
    surfaced as warnings, not errors, because bridge.toml is the runtime
    operator-facing config and may legitimately omit dormant defaults.
    """
    if not path.exists():
        return set()
    try:
        import tomllib
    except ImportError:  # pragma: no cover — Python 3.11+
        return set()
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    keys: set[str] = set()
    for section, values in data.items():
        if isinstance(values, dict):
            for key in values.keys():
                if isinstance(key, str):
                    keys.add(f"{section}.{key}")
        else:
            keys.add(section)
    return keys


def audit(
    bool_fields: dict[str, BoolField],
    toml_map: dict[str, str],
    registry: dict[str, dict[str, Any]],
    toml_keys: set[str],
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) describing drift between sources."""
    errors: list[str] = []
    warnings: list[str] = []

    # Reverse TOML map: field_name -> list of toml_keys that target it
    field_to_toml: dict[str, list[str]] = {}
    for toml_key, field_name in toml_map.items():
        field_to_toml.setdefault(field_name, []).append(toml_key)

    # 1. Every bool dataclass field must have a registry entry
    for field_name, field in bool_fields.items():
        if field_name not in registry:
            errors.append(
                f"BridgeConfig.{field_name} (bool, default={field.default}) "
                f"has no entry in feature_flags.yaml"
            )

    # 2. Every registry entry must reference a real dataclass bool field
    for field_name, entry in registry.items():
        if not isinstance(entry, dict):
            errors.append(f"feature_flags.yaml entry {field_name!r} is not a mapping")
            continue
        missing = REQUIRED_REGISTRY_KEYS - entry.keys()
        if missing:
            errors.append(
                f"feature_flags.yaml entry {field_name!r} missing required keys: "
                f"{sorted(missing)}"
            )
        if field_name not in bool_fields:
            errors.append(
                f"feature_flags.yaml entry {field_name!r} references a "
                f"non-existent BridgeConfig bool field"
            )
            continue

        # 3. Default must match
        registry_default = entry.get("default")
        if not isinstance(registry_default, bool):
            errors.append(
                f"feature_flags.yaml entry {field_name!r} default must be "
                f"a YAML bool, got {type(registry_default).__name__}"
            )
        elif registry_default != bool_fields[field_name].default:
            errors.append(
                f"feature_flags.yaml entry {field_name!r} default "
                f"({registry_default}) disagrees with BridgeConfig default "
                f"({bool_fields[field_name].default})"
            )

        # 4. Status must be a known value
        status = entry.get("status")
        if status not in VALID_STATUSES:
            errors.append(
                f"feature_flags.yaml entry {field_name!r} status {status!r} "
                f"not in {sorted(VALID_STATUSES)}"
            )

        # 5. toml_key consistency
        registry_toml_key = entry.get("toml_key", "")
        if not isinstance(registry_toml_key, str):
            errors.append(
                f"feature_flags.yaml entry {field_name!r} toml_key must be "
                f"a string, got {type(registry_toml_key).__name__}"
            )
            continue
        if registry_toml_key:
            mapped_field = toml_map.get(registry_toml_key)
            if mapped_field is None:
                errors.append(
                    f"feature_flags.yaml entry {field_name!r} declares "
                    f"toml_key={registry_toml_key!r} but no such key exists "
                    f"in _TOML_MAP"
                )
            elif mapped_field != field_name:
                errors.append(
                    f"feature_flags.yaml entry {field_name!r} declares "
                    f"toml_key={registry_toml_key!r} but _TOML_MAP routes "
                    f"that key to BridgeConfig.{mapped_field}"
                )
            elif registry_toml_key not in toml_keys:
                # Informational only — bridge.toml may legitimately omit a
                # dormant default. Warn rather than fail.
                warnings.append(
                    f"feature_flags.yaml entry {field_name!r} declares "
                    f"toml_key={registry_toml_key!r} but bridge.toml does not "
                    f"contain that key (likely dormant default — OK)"
                )

    # 6. Every _TOML_MAP entry pointing at a bool field must have a registry entry
    for toml_key, mapped_field in toml_map.items():
        if mapped_field in bool_fields and mapped_field not in registry:
            errors.append(
                f"_TOML_MAP {toml_key!r} routes to bool field "
                f"BridgeConfig.{mapped_field} but no registry entry exists"
            )

    # 7. Informational: bool fields with no TOML mapping
    for field_name in bool_fields:
        if field_name not in field_to_toml and field_name in registry:
            registry_toml_key = registry[field_name].get("toml_key", "")
            if registry_toml_key:
                # Registry says it has a toml_key but reverse map doesn't list
                # this field — covered by check 5 above. Skip.
                continue
            warnings.append(
                f"BridgeConfig.{field_name} has no entry in _TOML_MAP "
                f"(registry confirms env-only / no TOML key)"
            )

    return errors, warnings


def render_summary(
    bool_fields: dict[str, BoolField],
    registry: dict[str, dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> str:
    lines: list[str] = []
    lines.append(
        f"Bumba feature flag drift audit (Sprint P6.3, issue #1595)\n"
        f"  config_py:         {CONFIG_PY}\n"
        f"  feature_flags.yaml: {FEATURE_FLAGS_YAML}\n"
        f"  bridge.toml:        {BRIDGE_TOML}\n"
    )
    lines.append(
        f"BridgeConfig bool fields: {len(bool_fields)}\n"
        f"Registry entries:         {len(registry)}\n"
        f"Errors (orphan / drift):  {len(errors)}\n"
        f"Warnings (informational): {len(warnings)}\n"
    )

    if errors:
        lines.append("\n== ERRORS ==")
        lines.extend(f"  - {msg}" for msg in errors)

    if warnings:
        lines.append("\n== WARNINGS ==")
        lines.extend(f"  - {msg}" for msg in warnings)

    if not errors:
        lines.append("\nNo orphan flags. Registry, dataclass, and TOML map agree.")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational warnings (still print errors)",
    )
    args = parser.parse_args(argv)

    if not CONFIG_PY.exists():
        print(f"ERROR: {CONFIG_PY} not found", file=sys.stderr)
        return 2
    if not FEATURE_FLAGS_YAML.exists():
        print(f"ERROR: {FEATURE_FLAGS_YAML} not found", file=sys.stderr)
        return 2

    bool_fields, toml_map = _parse_config_module(CONFIG_PY)
    registry = _load_registry(FEATURE_FLAGS_YAML)
    toml_keys = _load_toml_keys(BRIDGE_TOML)

    errors, warnings = audit(bool_fields, toml_map, registry, toml_keys)

    if args.quiet:
        warnings = []

    print(render_summary(bool_fields, registry, errors, warnings))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
