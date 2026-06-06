"""Tests for ComputerUseDriver — Sprint 5j.04 / #2129.

Covers:
- Sandbox boundary check (SandboxBoundaryError on wrong UID)
- Field-value redaction (sensitive vs non-sensitive)
- Audit log lifecycle (session_start / session_end)
- BrowserDriver protocol conformance
- Idempotent close
"""
from __future__ import annotations

import os

import pytest

from job_search.browser.computer_use import (
    ComputerUseDriver,
    SandboxBoundaryError,
    _redact_field_value,
    _check_sandbox_boundary,
)
from job_search.browser.driver import BrowserDriver


class TestRedactFieldValue:
    def test_password_field_redacts_to_class(self):
        assert _redact_field_value("password", "hunter2") == "<password-redacted>"
        assert _redact_field_value("user_password_input", "secret") == "<password-redacted>"

    def test_mfa_secret_redacts(self):
        assert _redact_field_value("mfa_secret", "AAAA") == "<mfa_secret-redacted>"

    def test_ssn_redacts(self):
        assert _redact_field_value("ssn_field", "123-45-6789") == "<ssn-redacted>"

    def test_email_redacts_local_keeps_domain(self):
        assert _redact_field_value("email", "operator@example.com") == "<email>@example.com"

    def test_non_sensitive_field_passes_through_truncated(self):
        assert _redact_field_value("first_name", "the operator") == "the operator"

    def test_long_value_truncates_at_60(self):
        long = "x" * 100
        result = _redact_field_value("notes", long)
        assert result.endswith("...")
        assert len(result) <= 63  # 60 + "..."


class TestSandboxBoundaryCheck:
    def test_no_env_var_skips_check(self, monkeypatch):
        """When BUMBA_BROWSER_UID is unset, the check is a no-op (test mode)."""
        monkeypatch.delenv("BUMBA_BROWSER_UID", raising=False)
        _check_sandbox_boundary()  # must not raise

    def test_invalid_env_var_raises(self, monkeypatch):
        monkeypatch.setenv("BUMBA_BROWSER_UID", "not-an-int")
        with pytest.raises(SandboxBoundaryError, match="must be int"):
            _check_sandbox_boundary()

    def test_uid_mismatch_raises(self, monkeypatch):
        """When env var is set to a UID different from the current process,
        raise SandboxBoundaryError."""
        current = os.geteuid()
        # Pick a UID guaranteed to differ
        wrong_uid = current + 1000
        monkeypatch.setenv("BUMBA_BROWSER_UID", str(wrong_uid))
        with pytest.raises(SandboxBoundaryError, match="outside sandbox"):
            _check_sandbox_boundary()

    def test_uid_match_passes(self, monkeypatch):
        monkeypatch.setenv("BUMBA_BROWSER_UID", str(os.geteuid()))
        _check_sandbox_boundary()  # must not raise


class TestComputerUseDriverConstruction:
    def test_construct_with_skip_boundary_for_tests(self, tmp_path):
        """Tests pass `skip_boundary_check=True` to avoid the sandbox check."""
        driver = ComputerUseDriver(
            skip_boundary_check=True,
            audit_log_root=tmp_path / "audit",
            profile_root=tmp_path / "profiles",
        )
        assert driver.session_id.startswith("cu-")

    def test_construct_raises_outside_sandbox(self, tmp_path, monkeypatch):
        """Without skip_boundary_check, mismatched UID raises."""
        wrong_uid = os.geteuid() + 1000
        monkeypatch.setenv("BUMBA_BROWSER_UID", str(wrong_uid))
        with pytest.raises(SandboxBoundaryError):
            ComputerUseDriver(
                audit_log_root=tmp_path / "audit",
                profile_root=tmp_path / "profiles",
            )

    def test_constructor_writes_session_start_audit_line(self, tmp_path):
        driver = ComputerUseDriver(
            skip_boundary_check=True,
            audit_log_root=tmp_path / "audit",
            profile_root=tmp_path / "profiles",
        )
        audit_path = tmp_path / "audit" / f"{driver.session_id}.jsonl"
        assert audit_path.exists()
        content = audit_path.read_text()
        assert "session_start" in content
        assert driver.session_id in content


class TestProtocolConformance:
    def test_implements_browser_driver(self, tmp_path):
        """Computer-use driver must satisfy the BrowserDriver protocol."""
        driver = ComputerUseDriver(
            skip_boundary_check=True,
            audit_log_root=tmp_path / "audit",
            profile_root=tmp_path / "profiles",
        )
        assert isinstance(driver, BrowserDriver)


class TestIdempotentClose:
    def test_close_without_session_does_not_raise(self, tmp_path):
        import asyncio
        driver = ComputerUseDriver(
            skip_boundary_check=True,
            audit_log_root=tmp_path / "audit",
            profile_root=tmp_path / "profiles",
        )
        # No browser launched; close() must be idempotent
        asyncio.run(driver.close())
        asyncio.run(driver.close())

    def test_close_writes_session_end_audit_line(self, tmp_path):
        import asyncio
        driver = ComputerUseDriver(
            skip_boundary_check=True,
            audit_log_root=tmp_path / "audit",
            profile_root=tmp_path / "profiles",
        )
        asyncio.run(driver.close())
        content = (tmp_path / "audit" / f"{driver.session_id}.jsonl").read_text()
        assert "session_end" in content


class TestModelDecideStub:
    """The _model_decide method requires API authorization that the runbook
    walks through. Verify the stub raises with a useful message."""

    def test_model_decide_raises_with_runbook_pointer(self, tmp_path):
        import asyncio
        driver = ComputerUseDriver(
            skip_boundary_check=True,
            audit_log_root=tmp_path / "audit",
            profile_root=tmp_path / "profiles",
        )
        async def _call():
            await driver._model_decide("/tmp/x.png", "click submit")
        with pytest.raises(NotImplementedError, match="computer-use-sandbox-setup.md"):
            asyncio.run(_call())
