#!/usr/bin/env python3
"""PreToolUse helper — check tool risk tier and decide allow/deny.

Called by pre-tool-validation.sh with the tool name as argument.
Outputs JSON: {"decision": "allow"} or {"decision": "deny", "reason": "..."}

Environment:
    BUMBA_EXECUTION_CONTEXT: "interactive" | "autonomous" | "orchestrated"
    Defaults to "interactive" if not set.

    BUMBA_RISK_YAML_OVERRIDE: path to YAML config (for testing only).
    If not set, uses agent/config/tool-risk-classifications.yaml.
"""
import json
import os
import sys
from pathlib import Path

# Add agent dir to path so bridge package is importable
agent_dir = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(agent_dir))

from bridge.tool_risk_registry import ToolRiskRegistry


def main() -> None:
    tool_name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not tool_name:
        print(json.dumps({"decision": "allow"}))
        return

    context = os.environ.get("BUMBA_EXECUTION_CONTEXT", "interactive")

    # Support YAML override for testing
    yaml_override = os.environ.get("BUMBA_RISK_YAML_OVERRIDE", "")
    if yaml_override:
        yaml_path = Path(yaml_override)
    else:
        yaml_path = agent_dir / "config" / "tool-risk-classifications.yaml"

    if not yaml_path.exists():
        # No risk config — fail-open
        print(json.dumps({"decision": "allow"}))
        return

    try:
        registry = ToolRiskRegistry.from_yaml(str(yaml_path))
    except Exception:
        # Config load failure — fail-open
        print(json.dumps({"decision": "allow"}))
        return

    if registry.requires_approval(tool_name, context=context):
        tier = registry.get_tier(tool_name)
        print(json.dumps({
            "decision": "deny",
            "reason": (
                f"Tool '{tool_name}' is {tier.value}-tier and requires "
                f"operator approval in {context} mode"
            ),
        }))
    else:
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
