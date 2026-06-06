"""Tests for job_search.credentials (Sprint 5j.05 / #2160).

Coverage:
- CredentialRef shape + parsing + validation
- read_credentials happy path + missing-key error + allowlist enforcement
- list_accounts / list_families
- Schema strictness: undeclared fields skipped
- Operator CLI: add, list, remove flows (via main() programmatic invocation)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from job_search.credentials import (
    CredentialRef,
    FAMILY_FIELD_SETS,
    list_accounts,
    list_families,
    main,
    read_credentials,
)


def _write_secrets(path: Path, entries: dict[str, str]) -> None:
    """Write a flat key=value secrets file."""
    path.write_text("\n".join(f"{k}={v}" for k, v in entries.items()) + "\n")


class TestCredentialRef:
    def test_construct_with_valid_family_and_account(self):
        r = CredentialRef(family="greenhouse", account="main")
        assert r.family == "greenhouse"
        assert r.account == "main"

    def test_construct_rejects_empty_family(self):
        with pytest.raises(ValueError):
            CredentialRef(family="", account="main")

    def test_construct_rejects_empty_account(self):
        with pytest.raises(ValueError):
            CredentialRef(family="greenhouse", account="")

    def test_construct_rejects_uppercase_family(self):
        with pytest.raises(ValueError):
            CredentialRef(family="Greenhouse", account="main")

    def test_construct_rejects_uppercase_account(self):
        with pytest.raises(ValueError):
            CredentialRef(family="greenhouse", account="MAIN")

    def test_parse_valid_reference(self):
        r = CredentialRef.parse("ats_greenhouse_main")
        assert r.family == "greenhouse"
        assert r.account == "main"

    def test_parse_rejects_missing_prefix(self):
        with pytest.raises(ValueError):
            CredentialRef.parse("greenhouse_main")

    def test_parse_rejects_extra_segments(self):
        with pytest.raises(ValueError):
            CredentialRef.parse("ats_greenhouse_main_email")  # field included

    def test_key_prefix(self):
        r = CredentialRef(family="lever", account="test")
        assert r.key_prefix() == "ats_lever_test_"


class TestReadCredentials:
    def test_happy_path_resolves_all_declared_fields(self, tmp_path):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "operator@example.com",
            "ats_greenhouse_main_password": "hunter2",
            "ats_greenhouse_main_mfa_secret": "MFASEED",
        })
        cs = read_credentials(
            CredentialRef(family="greenhouse", account="main"),
            secrets_path=secrets,
        )
        assert cs.family == "greenhouse"
        assert cs.account == "main"
        assert cs.get("email") == "operator@example.com"
        assert cs.get("password") == "hunter2"
        assert cs.get("mfa_secret") == "MFASEED"

    def test_partial_seeding_returns_only_present_fields(self, tmp_path):
        """Operator may seed only email+password, skipping mfa_secret. That's OK."""
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "operator@example.com",
            "ats_greenhouse_main_password": "hunter2",
        })
        cs = read_credentials("ats_greenhouse_main", secrets_path=secrets)
        assert cs.get("email") == "operator@example.com"
        assert cs.get("password") == "hunter2"
        assert cs.get("mfa_secret") is None

    def test_no_matching_keys_raises_keyerror(self, tmp_path):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {"unrelated_key": "value"})
        with pytest.raises(KeyError, match="No credentials found"):
            read_credentials("ats_greenhouse_main", secrets_path=secrets)

    def test_missing_secrets_file_raises_keyerror(self, tmp_path):
        secrets = tmp_path / "does-not-exist"
        with pytest.raises(KeyError):
            read_credentials("ats_greenhouse_main", secrets_path=secrets)

    def test_string_ref_accepted_alongside_credentialref(self, tmp_path):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_lever_test_email": "test@example.com",
        })
        cs1 = read_credentials("ats_lever_test", secrets_path=secrets)
        cs2 = read_credentials(
            CredentialRef(family="lever", account="test"),
            secrets_path=secrets,
        )
        assert cs1.fields == cs2.fields

    def test_undeclared_field_is_skipped(self, tmp_path):
        """A field not in FAMILY_FIELD_SETS[family] is silently filtered."""
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "x@example.com",
            "ats_greenhouse_main_unknown_field": "leaked",
        })
        cs = read_credentials("ats_greenhouse_main", secrets_path=secrets)
        # email landed; unknown_field did NOT
        assert "email" in cs.fields
        assert "unknown_field" not in cs.fields

    def test_keys_for_other_accounts_do_not_leak(self, tmp_path):
        """Reading ats_greenhouse_main must NOT pick up ats_greenhouse_test_*."""
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "operator@example.com",
            "ats_greenhouse_test_email": "test@example.com",
            "ats_greenhouse_test_password": "different",
        })
        cs = read_credentials("ats_greenhouse_main", secrets_path=secrets)
        assert cs.get("email") == "operator@example.com"
        assert "password" not in cs.fields  # test account's password did NOT leak

    def test_non_ats_keys_are_ignored_even_when_prefix_collides(self, tmp_path):
        """`atsadjacent_greenhouse_main_email` must NOT be matched (regex anchors on `ats_`)."""
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "real@example.com",
            "atsadjacent_greenhouse_main_email": "fake@example.com",
            "discord_token": "should-not-leak",
        })
        cs = read_credentials("ats_greenhouse_main", secrets_path=secrets)
        assert cs.get("email") == "real@example.com"
        assert len(cs.fields) == 1


class TestListAccounts:
    def test_returns_empty_when_no_credentials(self, tmp_path):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {"unrelated": "value"})
        assert list_accounts(secrets_path=secrets) == []

    def test_lists_all_families_and_accounts(self, tmp_path):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "x",
            "ats_lever_main_email": "x",
            "ats_lever_test_email": "x",
        })
        accounts = list_accounts(secrets_path=secrets)
        assert len(accounts) == 3
        assert CredentialRef(family="greenhouse", account="main") in accounts
        assert CredentialRef(family="lever", account="main") in accounts
        assert CredentialRef(family="lever", account="test") in accounts

    def test_family_filter_restricts_results(self, tmp_path):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "x",
            "ats_lever_main_email": "x",
            "ats_workday_main_email": "x",
        })
        accounts = list_accounts(family="lever", secrets_path=secrets)
        assert len(accounts) == 1
        assert accounts[0].family == "lever"

    def test_results_are_sorted(self, tmp_path):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_workday_main_email": "x",
            "ats_greenhouse_main_email": "x",
            "ats_lever_main_email": "x",
        })
        accounts = list_accounts(secrets_path=secrets)
        families = [r.family for r in accounts]
        assert families == sorted(families)


class TestListFamilies:
    def test_returns_unique_sorted_families(self, tmp_path):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_workday_main_email": "x",
            "ats_greenhouse_main_email": "x",
            "ats_greenhouse_test_email": "x",
        })
        assert list_families(secrets_path=secrets) == ["greenhouse", "workday"]


class TestFamilyFieldSets:
    """Schema sanity — declared families have the expected field set."""

    def test_all_five_ats_families_declared(self):
        expected = {"greenhouse", "lever", "workday", "ashby", "bamboohr"}
        assert set(FAMILY_FIELD_SETS) == expected

    def test_all_families_share_baseline_email_password_mfa(self):
        baseline = {"email", "password", "mfa_secret"}
        for family, fields in FAMILY_FIELD_SETS.items():
            assert baseline.issubset(fields), (
                f"family {family} missing baseline fields: {baseline - fields}"
            )


class TestCLIList:
    def test_list_subcommand_empty_vault_prints_no_credentials(self, tmp_path, capsys):
        secrets = tmp_path / ".secrets"
        secrets.write_text("")
        exit_code = main(["--secrets-path", str(secrets), "list"])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "No credentials found" in out

    def test_list_subcommand_populated_vault_prints_each_account(self, tmp_path, capsys):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "x",
            "ats_lever_main_email": "y",
        })
        exit_code = main(["--secrets-path", str(secrets), "list"])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "greenhouse/main" in out
        assert "lever/main" in out

    def test_list_with_family_filter(self, tmp_path, capsys):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "x",
            "ats_lever_main_email": "y",
        })
        exit_code = main(["--secrets-path", str(secrets), "list", "--family", "lever"])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "lever/main" in out
        assert "greenhouse/main" not in out


class TestCLIRemove:
    def test_remove_without_confirm_refuses(self, tmp_path, capsys):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {"ats_greenhouse_main_email": "x"})
        exit_code = main([
            "--secrets-path", str(secrets), "remove", "greenhouse", "main",
        ])
        assert exit_code == 2
        out = capsys.readouterr().out
        assert "Refusing to remove without --confirm" in out
        # Key still present
        assert "ats_greenhouse_main_email=x" in secrets.read_text()

    def test_remove_with_confirm_strips_all_family_account_keys(self, tmp_path, capsys):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {
            "ats_greenhouse_main_email": "x",
            "ats_greenhouse_main_password": "y",
            "ats_greenhouse_test_email": "z",   # different account — should survive
            "discord_token": "preserve",         # unrelated — should survive
        })
        exit_code = main([
            "--secrets-path", str(secrets),
            "remove", "greenhouse", "main", "--confirm",
        ])
        assert exit_code == 0
        text = secrets.read_text()
        assert "ats_greenhouse_main_email" not in text
        assert "ats_greenhouse_main_password" not in text
        # Other accounts + unrelated keys preserved
        assert "ats_greenhouse_test_email" in text
        assert "discord_token" in text

    def test_remove_nonexistent_account_reports_no_match(self, tmp_path, capsys):
        secrets = tmp_path / ".secrets"
        _write_secrets(secrets, {"discord_token": "preserve"})
        exit_code = main([
            "--secrets-path", str(secrets),
            "remove", "greenhouse", "main", "--confirm",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "No keys matched prefix" in out
