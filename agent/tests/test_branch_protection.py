"""Tests for agent.bridge.branch_protection.

Sprint 4.1 — Phase 4A (Agent Harness Hardening).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from bridge.branch_protection import (
    ProtectionResult,
    ProtectionStatus,
    _standard_ruleset_is_satisfied,
    verify_branch_protection,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _strict_ok_payload() -> dict:
    """A protection JSON response that satisfies the standard ruleset."""
    return {
        "url": "https://api.github.com/repos/your-org/test-repo/branches/main/protection",
        "required_status_checks": {"strict": True, "contexts": []},
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
        },
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
        "enforce_admins": {"enabled": False},
    }


def _mock_run_gh(branch_result: tuple[int, str, str], protection_result: tuple[int, str, str]):
    """Build an AsyncMock for `_run_gh` that returns branch lookup, then protection."""
    mock = AsyncMock()
    mock.side_effect = [branch_result, protection_result]
    return mock


# ---------------------------------------------------------------------------
# Ruleset verification (pure unit, no async)
# ---------------------------------------------------------------------------


def test_standard_ruleset_accepts_strict_ok_payload():
    ok, reason = _standard_ruleset_is_satisfied(_strict_ok_payload())
    assert ok is True
    assert reason == ""


def test_standard_ruleset_rejects_missing_pr_reviews():
    payload = _strict_ok_payload()
    payload["required_pull_request_reviews"] = None
    ok, reason = _standard_ruleset_is_satisfied(payload)
    assert ok is False
    assert "required_pull_request_reviews" in reason


def test_standard_ruleset_rejects_zero_required_approvers():
    payload = _strict_ok_payload()
    payload["required_pull_request_reviews"]["required_approving_review_count"] = 0
    ok, reason = _standard_ruleset_is_satisfied(payload)
    assert ok is False
    assert "required_approving_review_count" in reason


def test_standard_ruleset_rejects_stale_review_pass_through():
    payload = _strict_ok_payload()
    payload["required_pull_request_reviews"]["dismiss_stale_reviews"] = False
    ok, reason = _standard_ruleset_is_satisfied(payload)
    assert ok is False
    assert "dismiss_stale_reviews" in reason


def test_standard_ruleset_rejects_non_linear_history():
    payload = _strict_ok_payload()
    payload["required_linear_history"] = {"enabled": False}
    ok, reason = _standard_ruleset_is_satisfied(payload)
    assert ok is False
    assert "required_linear_history" in reason


def test_standard_ruleset_rejects_force_pushes_enabled():
    payload = _strict_ok_payload()
    payload["allow_force_pushes"] = {"enabled": True}
    ok, reason = _standard_ruleset_is_satisfied(payload)
    assert ok is False
    assert "allow_force_pushes" in reason


def test_standard_ruleset_rejects_deletions_enabled():
    payload = _strict_ok_payload()
    payload["allow_deletions"] = {"enabled": True}
    ok, reason = _standard_ruleset_is_satisfied(payload)
    assert ok is False
    assert "allow_deletions" in reason


def test_standard_ruleset_rejects_missing_conversation_resolution():
    payload = _strict_ok_payload()
    payload["required_conversation_resolution"] = {"enabled": False}
    ok, reason = _standard_ruleset_is_satisfied(payload)
    assert ok is False
    assert "required_conversation_resolution" in reason


# ---------------------------------------------------------------------------
# verify_branch_protection (end-to-end with mocked _run_gh)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_returns_strict_ok_for_protected_repo():
    payload = _strict_ok_payload()
    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(0, json.dumps(payload), ""),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        result = await verify_branch_protection("your-org/test-repo")

    assert isinstance(result, ProtectionResult)
    assert result.status == ProtectionStatus.STRICT_OK
    assert result.ok is True
    assert result.degraded is False
    assert result.branch == "main"
    assert "protected" in result.reason.lower()


@pytest.mark.asyncio
async def test_verify_returns_degraded_paid_feature_for_private_free_tier():
    # GitHub responds 403 with "Upgrade to GitHub Pro" for private repos on free tier
    upgrade_message = (
        '{"message":"Upgrade to GitHub Pro or make this repository public to '
        'enable this feature.","status":"403"}'
    )
    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(1, "", upgrade_message),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        result = await verify_branch_protection("your-org/private-free-repo")

    assert result.status == ProtectionStatus.DEGRADED_PAID_FEATURE
    assert result.ok is True
    assert result.degraded is True
    assert "github pro" in result.reason.lower()


@pytest.mark.asyncio
async def test_verify_returns_degraded_unprotected_for_public_without_protection():
    # GitHub responds 404 with "Branch not protected" for public repos without protection
    not_protected_message = '{"message":"Branch not protected","status":"404"}'
    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(1, "", not_protected_message),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        result = await verify_branch_protection("your-org/public-unprotected")

    assert result.status == ProtectionStatus.DEGRADED_UNPROTECTED
    assert result.ok is True
    assert result.degraded is True
    assert "degraded" in result.reason.lower()


@pytest.mark.asyncio
async def test_verify_returns_error_not_found_when_default_branch_lookup_fails():
    mock_run = AsyncMock()
    mock_run.return_value = (1, "", "HTTP 404: Not Found")
    with patch("bridge.branch_protection._run_gh", mock_run):
        result = await verify_branch_protection("your-org/nonexistent")

    assert result.status == ProtectionStatus.ERROR_NOT_FOUND
    assert result.ok is False
    assert result.degraded is False


@pytest.mark.asyncio
async def test_verify_returns_error_missing_rules_when_protection_is_weak():
    weak_payload = _strict_ok_payload()
    weak_payload["allow_force_pushes"] = {"enabled": True}  # violates ruleset
    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(0, json.dumps(weak_payload), ""),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        result = await verify_branch_protection("your-org/weakly-protected")

    assert result.status == ProtectionStatus.ERROR_MISSING_RULES
    assert result.ok is False
    assert result.degraded is False
    assert "allow_force_pushes" in result.reason


@pytest.mark.asyncio
async def test_verify_returns_error_unknown_on_malformed_json():
    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(0, "not valid json {", ""),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        result = await verify_branch_protection("your-org/malformed")

    assert result.status == ProtectionStatus.ERROR_UNKNOWN
    assert result.ok is False


@pytest.mark.asyncio
async def test_verify_handles_non_main_default_branch():
    # bumba-voice uses master, not main — the check must handle this
    payload = _strict_ok_payload()
    mock_run = _mock_run_gh(
        branch_result=(0, "master\n", ""),
        protection_result=(0, json.dumps(payload), ""),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        result = await verify_branch_protection("your-org/bumba-voice")

    assert result.status == ProtectionStatus.STRICT_OK
    assert result.branch == "master"


# ---------------------------------------------------------------------------
# CLI entry (Sprint 06.15b rework — #841)
# ---------------------------------------------------------------------------


def test_cli_returns_zero_for_protected_repo(capsys):
    """CLI exits 0 when the repo is STRICT_OK."""
    from bridge.branch_protection import _cli_main

    payload = _strict_ok_payload()
    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(0, json.dumps(payload), ""),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        rc = _cli_main(["--repo", "your-org/protected-repo"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "OK:" in captured.out
    assert "protected per the standard ruleset" in captured.out


def test_cli_returns_nonzero_for_unprotected_repo(capsys):
    """CLI exits non-zero when the repo has no protection rules (ERROR_*)."""
    from bridge.branch_protection import _cli_main

    # Default branch lookup fails -> ERROR_NOT_FOUND
    mock_run = _mock_run_gh(
        branch_result=(1, "", "repo not found"),
        protection_result=(0, "", ""),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        rc = _cli_main(["--repo", "your-org/missing-repo"])

    assert rc == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err


def test_cli_returns_zero_with_warning_for_degraded_paid_feature(capsys):
    """Default mode: DEGRADED_PAID_FEATURE allows operation with a stderr warning."""
    from bridge.branch_protection import _cli_main

    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(1, "", "Upgrade to GitHub Pro"),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        rc = _cli_main(["--repo", "your-org/private-free-tier"])

    assert rc == 0  # default mode allows degraded
    captured = capsys.readouterr()
    assert "WARN:" in captured.err
    assert "free-tier" in captured.err.lower() or "github pro" in captured.err.lower()


def test_cli_strict_mode_rejects_degraded(capsys):
    """--strict mode exits 2 on any DEGRADED_* result."""
    from bridge.branch_protection import _cli_main

    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(1, "", "Branch not protected"),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        rc = _cli_main(["--repo", "your-org/unprotected", "--strict"])

    assert rc == 2  # strict mode rejects degraded
    captured = capsys.readouterr()
    assert "WARN:" in captured.err


def test_cli_quiet_suppresses_ok_output(capsys):
    """--quiet suppresses stdout on success but still emits stderr on failure."""
    from bridge.branch_protection import _cli_main

    payload = _strict_ok_payload()
    mock_run = _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(0, json.dumps(payload), ""),
    )
    with patch("bridge.branch_protection._run_gh", mock_run):
        rc = _cli_main(["--repo", "your-org/protected", "--quiet"])

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""  # quiet suppresses OK output


def test_cli_requires_repo_argument():
    """argparse rejects invocation without --repo."""
    from bridge.branch_protection import _cli_main

    with pytest.raises(SystemExit) as exc_info:
        _cli_main([])  # no --repo

    # argparse exits with code 2 on missing required arg
    assert exc_info.value.code == 2


def test_cli_module_has_main_block_and_argparse():
    """`__main__` block + argparse are wired so `python -m bridge.branch_protection`
    routes through _cli_main. Verified by source inspection rather than a
    subprocess call — subprocess invocations leak event-loop state that
    can affect later async tests in the suite.
    """
    import inspect
    from bridge import branch_protection

    src = inspect.getsource(branch_protection)
    assert 'if __name__ == "__main__":' in src, (
        "branch_protection.py must have a __main__ block to be invokable "
        "as `python -m bridge.branch_protection`"
    )
    assert "argparse" in src, "_cli_main must use argparse for --repo flag"
    assert hasattr(branch_protection, "_cli_main"), (
        "_cli_main must be importable as a module attribute"
    )


# ---------------------------------------------------------------------------
# D1.5 — check_branch_protection gate wired into factory quality phase
# ---------------------------------------------------------------------------


def _strict_ok_mock() -> object:
    """AsyncMock for verify_branch_protection that returns STRICT_OK."""
    from bridge.branch_protection import ProtectionResult, ProtectionStatus
    from unittest.mock import AsyncMock

    m = AsyncMock(
        return_value=ProtectionResult(
            repo="your-org/bumba-open-harness",
            branch="main",
            status=ProtectionStatus.STRICT_OK,
            ok=True,
            degraded=False,
            reason="your-org/bumba-open-harness/main is protected per the standard ruleset.",
        )
    )
    return m


def _unprotected_mock(repo: str = "your-org/bumba-open-harness") -> object:
    """AsyncMock for verify_branch_protection that returns DEGRADED_UNPROTECTED."""
    from bridge.branch_protection import ProtectionResult, ProtectionStatus
    from unittest.mock import AsyncMock

    m = AsyncMock(
        return_value=ProtectionResult(
            repo=repo,
            branch="main",
            status=ProtectionStatus.DEGRADED_UNPROTECTED,
            ok=True,
            degraded=True,
            reason=f"{repo}/main is protectable but has no branch protection enabled.",
        )
    )
    return m


def test_check_branch_protection_passes_strict_ok():
    """Gate passes when verify_branch_protection returns STRICT_OK."""
    from bridge.factory.quality import check_branch_protection

    with patch("bridge.branch_protection._run_gh", _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(0, json.dumps(_strict_ok_payload()), ""),
    )):
        result = check_branch_protection("your-org/bumba-open-harness", posture="warn")

    assert result.passed is True
    assert result.category == "branch_protection"


def test_check_branch_protection_warn_posture_allows_unprotected():
    """In warn posture, unprotected branch returns passed=True (PR allowed)."""
    from bridge.factory.quality import check_branch_protection

    with patch("bridge.branch_protection._run_gh", _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(1, "", "Branch not protected"),
    )):
        result = check_branch_protection("your-org/bumba-open-harness", posture="warn")

    assert result.passed is True
    assert result.category == "branch_protection"


def test_check_branch_protection_block_posture_rejects_unprotected():
    """In block posture, unprotected branch returns passed=False."""
    from bridge.factory.quality import check_branch_protection

    with patch("bridge.branch_protection._run_gh", _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(1, "", "Branch not protected"),
    )):
        result = check_branch_protection("your-org/bumba-open-harness", posture="block")

    assert result.passed is False
    assert result.category == "branch_protection"
    assert "FAILED" in result.reason
    assert "your-org/bumba-open-harness" in result.reason



def test_check_branch_protection_emits_event_bus_event_on_degraded():
    """EventBus receives security.branch_protection.failed on degraded result.

    EventBus is imported inside check_branch_protection (deferred to avoid
    circular imports), so we patch get_instance on the live class via
    patch.object rather than a module-attribute monkeypatch.
    """
    from bridge.factory.quality import check_branch_protection
    from bridge.event_bus import EventBus

    published_events = []

    class _FakeInstance:
        def publish(self, event_type, payload=None, **_kwargs):
            published_events.append({"event_type": event_type, "payload": payload})

    with patch.object(EventBus, "get_instance", return_value=_FakeInstance()):
        with patch("bridge.branch_protection._run_gh", _mock_run_gh(
            branch_result=(0, "main\n", ""),
            protection_result=(1, "", "Branch not protected"),
        )):
            check_branch_protection("your-org/bumba-open-harness", posture="warn")

    assert len(published_events) == 1
    evt = published_events[0]
    assert evt["event_type"] == "security.branch_protection.failed"
    assert evt["payload"]["repo"] == "your-org/bumba-open-harness"
    assert evt["payload"]["posture"] == "warn"


def test_check_branch_protection_skips_when_repo_empty():
    """Empty repo string skips the gate entirely (passed=True, no API call)."""
    from bridge.factory.quality import check_branch_protection

    # No mock needed — should return immediately without calling _run_gh
    result = check_branch_protection("", posture="block")

    assert result.passed is True
    assert result.category == "branch_protection"


def test_run_all_quality_checks_includes_branch_protection_gate():
    """run_all_quality_checks fires the branch_protection gate as the 4th check."""
    from bridge.factory.quality import run_all_quality_checks

    with patch("bridge.branch_protection._run_gh", _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(0, json.dumps(_strict_ok_payload()), ""),
    )):
        results = run_all_quality_checks(
            diff_stat={"additions": 10, "deletions": 5, "files_changed": 2},
            changed_files=["agent/bridge/foo.py"],
            diff_text="",
            issue_body="",
            repo="your-org/bumba-open-harness",
            branch_protection_posture="warn",
        )

    categories = [r.category for r in results]
    assert "branch_protection" in categories
    bp_result = next(r for r in results if r.category == "branch_protection")
    assert bp_result.passed is True


def test_run_all_quality_checks_gate_order():
    """Branch protection is the 4th gate (index 3) in run_all_quality_checks."""
    from bridge.factory.quality import run_all_quality_checks

    with patch("bridge.branch_protection._run_gh", _mock_run_gh(
        branch_result=(0, "main\n", ""),
        protection_result=(0, json.dumps(_strict_ok_payload()), ""),
    )):
        results = run_all_quality_checks(
            diff_stat={"additions": 0, "deletions": 0, "files_changed": 0},
            changed_files=[],
            diff_text="",
            issue_body="",
            repo="your-org/bumba-open-harness",
        )

    assert len(results) == 4
    assert results[0].category == "pr_size"
    assert results[1].category == "protected_files"
    assert results[2].category == "new_deps"
    assert results[3].category == "branch_protection"


def test_run_all_quality_checks_backward_compat_no_repo():
    """run_all_quality_checks with no repo= kwarg still works (gate skipped)."""
    from bridge.factory.quality import run_all_quality_checks

    # No mock needed — empty repo skips the branch_protection gate
    results = run_all_quality_checks(
        diff_stat={"additions": 0, "deletions": 0, "files_changed": 0},
        changed_files=[],
        diff_text="",
        issue_body="",
    )

    assert len(results) == 4
    bp_result = results[3]
    assert bp_result.category == "branch_protection"
    assert bp_result.passed is True  # gate skipped = pass
