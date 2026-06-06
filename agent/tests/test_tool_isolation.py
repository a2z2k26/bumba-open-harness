"""Tests for MS5.6: Isolated Tool Registries."""

from __future__ import annotations

import json
import os


from bridge.tool_isolation import (
    DAILY_TOKEN_BUDGET,
    BoundaryViolation,
    BudgetTracker,
    InvocationAudit,
    IsolatedToolRegistry,
    IsolationConfig,
    check_bash_command,
    check_recursion,
    filter_mcp_config,
    scan_output_for_violations,
)


# ── MCP Config Filtering ──


class TestMCPFiltering:
    def test_filter_allowed_servers(self):
        master = {
            "mcpServers": {
                "brave-search": {"command": "brave"},
                "exa": {"command": "exa"},
                "notion": {"command": "notion"},
            }
        }
        filtered = filter_mcp_config(master, ["brave-search", "exa"])
        assert "brave-search" in filtered["mcpServers"]
        assert "exa" in filtered["mcpServers"]
        assert "notion" not in filtered["mcpServers"]

    def test_filter_empty_allowlist(self):
        master = {"mcpServers": {"brave": {"command": "brave"}}}
        filtered = filter_mcp_config(master, [])
        # No servers leak through, but the top-level `mcpServers` key MUST
        # still be present — a bare `{}` is rejected by `claude -p
        # --mcp-config` as an invalid MCP config schema (#2345).
        assert filtered == {"mcpServers": {}}

    def test_filter_nonexistent_server(self):
        master = {"mcpServers": {"brave": {"command": "brave"}}}
        filtered = filter_mcp_config(master, ["nonexistent"])
        # Zero matches still produces a schema-valid file (mcpServers present).
        assert filtered == {"mcpServers": {}}

    def test_filter_from_disabled(self):
        master = {"_mcpServers_disabled": {"brave": {"command": "brave"}}}
        filtered = filter_mcp_config(master, ["brave"])
        assert "brave" in filtered.get("mcpServers", {})


# ── Sprint P2.4 — MCP server allowlist composes with tool-name allowlist ──


class TestP24LayerSeparation:
    """The split required by Sprint P2.4 (issue #1582):

    `filter_mcp_config` is the SERVER-level filter (controls which MCP
    servers a department's subprocess sees in its filtered `.mcp.json`).
    The TOOL-NAME allowlist lives in `teams._config._ToolsSchema.allowed_tools`
    and applies at agent.tool() registration time. The two layers are
    deliberately separate so a misconfigured `allowed_tools` allowlist
    cannot grant unintended access to a server that the team is not
    supposed to reach.
    """

    def test_server_filter_does_not_inspect_tool_names(self):
        """`filter_mcp_config` filters by SERVER key, not by tool name.

        Regression guard for the audit finding: even if the master MCP
        config has a server with rich tool surface, only the allowlisted
        SERVER keys leak through. Tool-level enforcement is a separate
        layer (see `teams._factory` + `teams._config._ToolsSchema`).
        """
        master = {
            "mcpServers": {
                "github": {"command": "gh", "tools": ["read", "write_pr", "delete"]},
                "notion": {"command": "no", "tools": ["read", "create"]},
            }
        }
        # Allow ONLY notion. The github server's `write_pr` / `delete`
        # tools must not appear anywhere in the filtered config — they
        # belong to a server that wasn't allowed.
        filtered = filter_mcp_config(master, ["notion"])
        assert "github" not in filtered.get("mcpServers", {})
        assert "notion" in filtered.get("mcpServers", {})
        # Cross-server tool names like "write_pr" do not leak via the
        # SERVER filter — the only way `write_pr` could be invoked is if
        # `github` were also allowlisted.
        flat = str(filtered)
        assert "write_pr" not in flat
        assert "delete" not in flat

    def test_empty_allowlist_means_no_servers(self):
        """`filter_mcp_config([])` returns `{"mcpServers": {}}` — deny-by-default.

        The registry path under `mcp_mode="deny_by_default"` relies on
        this: empty allowed_servers must NOT silently fall through to the
        master config. The `mcpServers` key stays present but empty so the
        written file is still schema-valid for `claude -p --mcp-config`
        (#2345) — the previous bare `{}` crashed the subprocess at boot.
        """
        master = {"mcpServers": {"github": {"command": "gh"}}}
        filtered = filter_mcp_config(master, [])
        assert filtered == {"mcpServers": {}}
        assert filtered["mcpServers"] == {}


# ── Bash Command Validation ──


class TestBashValidation:
    def test_denied_rm_rf(self):
        ok, reason = check_bash_command("rm -rf /tmp/data")
        assert ok is False
        assert "denied" in reason

    def test_denied_sudo(self):
        ok, _ = check_bash_command("sudo ls /root")
        assert ok is False

    def test_denied_eval(self):
        ok, _ = check_bash_command("eval(user_input)")
        assert ok is False

    def test_allowed_ls(self):
        ok, _ = check_bash_command("ls -la /tmp")
        assert ok is True

    def test_allowlist_match(self):
        ok, _ = check_bash_command(
            "cat file.txt",
            allowed_patterns=[r"^cat ", r"^ls "],
        )
        assert ok is True

    def test_allowlist_no_match(self):
        ok, reason = check_bash_command(
            "wget http://example.com",
            allowed_patterns=[r"^cat ", r"^ls "],
        )
        assert ok is False

    def test_denied_force_push(self):
        ok, _ = check_bash_command("git push --force")
        assert ok is False


# ── Recursion Prevention ──


class TestRecursion:
    def test_depth_0_allowed(self):
        ok, _ = check_recursion({"BUMBA_AGENT_DEPTH": "0"})
        assert ok is True

    def test_depth_1_blocked(self):
        ok, reason = check_recursion({"BUMBA_AGENT_DEPTH": "1"})
        assert ok is False
        assert "recursion" in reason.lower()

    def test_no_depth_var_allowed(self):
        ok, _ = check_recursion({})
        assert ok is True

    def test_depth_2_blocked(self):
        ok, _ = check_recursion({"BUMBA_AGENT_DEPTH": "2"})
        assert ok is False


# ── Budget Tracker ──


class TestBudgetTracker:
    def test_initial_zero(self):
        bt = BudgetTracker()
        assert bt.get_daily_usage() == 0
        assert bt.is_over_budget() is False

    def test_record_usage(self):
        bt = BudgetTracker()
        bt.record_usage("research", 10000)
        assert bt.get_daily_usage() == 10000
        assert bt.get_tool_usage("research") == 10000

    def test_over_budget(self):
        bt = BudgetTracker()
        bt.record_usage("research", DAILY_TOKEN_BUDGET + 1)
        assert bt.is_over_budget() is True

    def test_alert_threshold(self):
        bt = BudgetTracker()
        bt.record_usage("research", int(DAILY_TOKEN_BUDGET * 0.81))
        assert bt.should_alert() is True

    def test_remaining(self):
        bt = BudgetTracker()
        bt.record_usage("research", 100000)
        assert bt.get_remaining() == DAILY_TOKEN_BUDGET - 100000


# ── Output Scanning ──


class TestOutputScanning:
    def test_clean_output(self):
        violations = scan_output_for_violations("Here is the analysis result.")
        assert len(violations) == 0

    def test_api_key_detected(self):
        # Synthetic test sentinel — not a real GitHub token. The whole point of
        # this test is to confirm `scan_output_for_violations` flags such strings.
        # Sprint 08.03 (#781). Revisit 2026-09-01.
        violations = scan_output_for_violations("Found key: ghp_abcdefghijklmnopqrstuvwxyz1234567890")  # nosemgrep: generic.secrets.security.detected-github-token.detected-github-token
        assert len(violations) >= 1
        assert any(v.violation_type == "sensitive_data" for v in violations)

    def test_aws_key_detected(self):
        violations = scan_output_for_violations("Key: AKIAIOSFODNN7EXAMPLE")
        assert len(violations) >= 1

    def test_denied_op_in_output(self):
        violations = scan_output_for_violations("I ran: sudo rm -rf /tmp")
        assert len(violations) >= 1
        assert any(v.violation_type == "bash_denied" for v in violations)


# ── Isolated Environment Creation ──


class TestIsolatedEnv:
    def test_create_env(self, tmp_path):
        master = {"mcpServers": {"brave": {"command": "brave"}, "notion": {"command": "notion"}}}
        registry = IsolatedToolRegistry(master_config=master)
        config = IsolationConfig(
            tool_name="research",
            allowed_mcp_servers=["brave"],
        )
        env = registry.create_isolated_env(config)

        # Filtered config file should exist
        assert os.path.exists(env.filtered_config_path)

        # Env vars should include depth and tool name
        assert env.env_vars["BUMBA_AGENT_DEPTH"] == "1"
        assert env.env_vars["BUMBA_AGENT_TOOL"] == "research"

        # Filtered config should only contain brave
        with open(env.filtered_config_path) as f:
            filtered = json.loads(f.read())
        assert "brave" in filtered.get("mcpServers", {})
        assert "notion" not in filtered.get("mcpServers", {})

        # Cleanup
        env.cleanup()
        assert not os.path.exists(env.filtered_config_path)

    def test_cleanup_idempotent(self):
        registry = IsolatedToolRegistry()
        config = IsolationConfig(tool_name="test", allowed_mcp_servers=[])
        env = registry.create_isolated_env(config)
        env.cleanup()
        env.cleanup()  # Should not raise
        assert env.cleanup_done is True


# ── Invocation Validation ──


class TestInvocationValidation:
    def test_allowed_at_depth_0(self):
        registry = IsolatedToolRegistry()
        ok, _ = registry.validate_invocation(
            IsolationConfig(tool_name="test"),
            env_vars={"BUMBA_AGENT_DEPTH": "0"},
        )
        assert ok is True

    def test_blocked_at_depth_1(self):
        registry = IsolatedToolRegistry()
        ok, reason = registry.validate_invocation(
            IsolationConfig(tool_name="test"),
            env_vars={"BUMBA_AGENT_DEPTH": "1"},
        )
        assert ok is False

    def test_blocked_over_budget(self):
        registry = IsolatedToolRegistry()
        registry._budget.record_usage("x", DAILY_TOKEN_BUDGET + 1)
        ok, reason = registry.validate_invocation(
            IsolationConfig(tool_name="test"),
        )
        assert ok is False
        assert "budget" in reason.lower()


# ── Audit ──


class TestAudit:
    def test_record_and_get(self):
        registry = IsolatedToolRegistry()
        audit = InvocationAudit(
            invocation_id="inv-1",
            agent_tool="research",
            tokens_used=5000,
            duration_seconds=3.5,
        )
        registry.record_invocation(audit)
        audits = registry.get_audits()
        assert len(audits) == 1
        assert audits[0].agent_tool == "research"

    def test_filter_by_tool(self):
        registry = IsolatedToolRegistry()
        registry.record_invocation(InvocationAudit(agent_tool="a", tokens_used=100))
        registry.record_invocation(InvocationAudit(agent_tool="b", tokens_used=200))
        assert len(registry.get_audits("a")) == 1

    def test_violation_count(self):
        registry = IsolatedToolRegistry()
        registry.record_invocation(InvocationAudit(
            agent_tool="test",
            boundary_violations=[
                BoundaryViolation(violation_type="bash_denied"),
                BoundaryViolation(violation_type="sensitive_data"),
            ],
        ))
        assert registry.count_violations() == 2
