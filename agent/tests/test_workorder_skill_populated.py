"""Test that WorkOrders are constructed with non-empty skill values.

Sprint 9 — issue #629: Wire EnvironmentSelector with real skill classification.
"""
from pathlib import Path
import re

import pytest

# Absolute paths — tests must pass regardless of CWD
_THIS_DIR = Path(__file__).parent          # agent/tests/
_BRIDGE_DIR = _THIS_DIR.parent / "bridge"  # agent/bridge/
_APP_PY = _BRIDGE_DIR / "app.py"
_ENV_SEL_PY = _BRIDGE_DIR / "environment_selector.py"


def test_workorder_skill_not_hardcoded_empty():
    """WorkOrder construction in app.py must not use skill='' (hardcoded empty)."""
    src = _APP_PY.read_text()

    lines = src.splitlines()
    in_workorder = False
    for i, line in enumerate(lines):
        if "WorkOrder(" in line or "WorkOrder.create(" in line:
            in_workorder = True
        if in_workorder:
            if 'skill=""' in line or "skill=''," in line or "skill=''" in line:
                context = "\n".join(lines[max(0, i - 3):i + 4])
                pytest.fail(
                    f"WorkOrder constructed with hardcoded skill='' at line {i + 1}:\n{context}"
                )
            if line.strip() == ")" and in_workorder:
                in_workorder = False


def test_classify_intent_used_in_app():
    """app.py must use a skill classifier when constructing WorkOrders."""
    src = _APP_PY.read_text()

    classifiers = [
        "classify_intent",
        "classified_skill",
        "_classify_skill",
        "_classify_message_intent",
        "_intent_to_skill",
    ]
    found = any(c in src for c in classifiers)
    assert found, (
        f"app.py must use a skill classifier (one of {classifiers}) "
        "when constructing WorkOrders"
    )


def test_intent_to_skill_helper_present():
    """_intent_to_skill helper function must be defined in app.py."""
    src = _APP_PY.read_text()
    assert "def _intent_to_skill(" in src, (
        "app.py must define _intent_to_skill() to map intent values to skill strings"
    )


def test_intent_to_skill_logic():
    """_intent_to_skill must return non-empty strings and map filesystem intents correctly."""
    src = _APP_PY.read_text()

    # Extract _INTENT_SKILL_MAP dict literal
    map_match = re.search(
        r"_INTENT_SKILL_MAP(?:\s*:\s*dict\[str,\s*str\])?\s*=\s*(\{[^}]+\})",
        src,
        re.DOTALL,
    )
    assert map_match, "_INTENT_SKILL_MAP not found in app.py"

    ns: dict = {}
    exec(f"_INTENT_SKILL_MAP = {map_match.group(1)}", ns)
    skill_map: dict = ns["_INTENT_SKILL_MAP"]

    # Build the helper function without a docstring to avoid exec issues
    fn_body = (
        "def _intent_to_skill(intent_value):\n"
        "    return _INTENT_SKILL_MAP.get(intent_value, 'chat')\n"
    )
    exec(fn_body, ns)
    _intent_to_skill = ns["_intent_to_skill"]

    # All mapped intents return non-empty strings
    for intent_val, skill in skill_map.items():
        assert skill, f"Empty skill for intent '{intent_val}'"

    # Filesystem-bound intents must NOT produce readonly-only skills
    fs_intents = {"build", "fix", "optimize", "deploy", "migrate"}
    readonly_only_skills = {"chat", "query", "search", "summarize", "explain"}

    for intent_val in fs_intents:
        skill = _intent_to_skill(intent_val)
        assert skill not in readonly_only_skills, (
            f"Intent '{intent_val}' mapped to readonly-only skill '{skill}'; "
            f"expected a filesystem-class skill"
        )

    # Unknown/fallback intents fall through to 'chat'
    assert _intent_to_skill("unknown") == "chat"
    assert _intent_to_skill("totally-unknown-xyz") == "chat"

    # All known intents produce non-empty strings
    for intent in ["build", "fix", "analyze", "optimize", "test", "deploy", "document", "unknown"]:
        result = _intent_to_skill(intent)
        assert result, f"_intent_to_skill('{intent}') returned empty string"


def test_environment_selector_routes_correctly():
    """EnvironmentSelector must route filesystem intents to WORKTREE, not SUBAGENT."""
    src = _ENV_SEL_PY.read_text()

    rules_match = re.search(
        r"_SKILL_CLASS_RULES:\s*list\[tuple\[str,\s*str\]\]\s*=\s*(\[.*?\])",
        src,
        re.DOTALL,
    )
    assert rules_match, "_SKILL_CLASS_RULES not found in environment_selector.py"

    ns: dict = {}
    exec(f"_SKILL_CLASS_RULES = {rules_match.group(1)}", ns)

    # Build _classify_skill without docstring to avoid exec triple-quote issues
    fn_body = (
        "def _classify_skill(skill):\n"
        "    s = skill.lower()\n"
        "    for prefix, klass in _SKILL_CLASS_RULES:\n"
        "        if s.startswith(prefix) or prefix in s:\n"
        "            return klass\n"
        '    return "readonly"\n'
    )
    exec(fn_body, ns)
    _classify_skill = ns["_classify_skill"]

    # Skills produced by _intent_to_skill for filesystem intents
    filesystem_skills = ["implement", "fix-task", "refactor", "migrate"]
    for skill in filesystem_skills:
        klass = _classify_skill(skill)
        assert klass == "filesystem", (
            f"Skill '{skill}' classified as '{klass}', expected 'filesystem'"
        )

    # Skills for readonly intents
    readonly_skills = ["chat", "analyze", "explain"]
    for skill in readonly_skills:
        klass = _classify_skill(skill)
        assert klass == "readonly", (
            f"Skill '{skill}' classified as '{klass}', expected 'readonly'"
        )
