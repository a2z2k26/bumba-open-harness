"""Tests for atomic secrets file writing (T0.1.1)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.token_refresher import TokenRefresher


class TestAtomicSecretsWrite:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.secrets_path = os.path.join(self.tmp_dir, ".secrets")
        Path(self.secrets_path).write_text(
            "discord_token=test123\n"
            "claude_oauth_token=old_access\n"
            "claude_oauth_refresh_token=old_refresh\n"
        )
        self.refresher = TokenRefresher(
            access_token="new_access",
            refresh_token="new_refresh",
            secrets_file=self.secrets_path,
        )

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_atomic_write_creates_no_tmp_after_success(self):
        """After successful write, .secrets.tmp should not exist."""
        self.refresher._update_secrets_file()
        assert not Path(self.secrets_path + ".tmp").exists()
        assert Path(self.secrets_path).exists()

    def test_atomic_write_updates_tokens(self):
        """Tokens should be updated in the file."""
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_token=new_access" in content
        assert "claude_oauth_refresh_token=new_refresh" in content
        assert "discord_token=test123" in content  # preserved

    def test_atomic_write_preserves_original_on_rename_failure(self):
        """If os.rename fails, original file should be intact."""
        with patch("os.rename", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                self.refresher._update_secrets_file()
        # Original file should still be readable with old values
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_token=old_access" in content

    def test_atomic_write_no_duplicate_keys(self):
        """After write, each key should appear exactly once."""
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        lines = [l for l in content.splitlines() if l.startswith("claude_oauth_token=")]
        assert len(lines) == 1
        assert lines[0] == "claude_oauth_token=new_access"

    def test_atomic_write_adds_missing_keys(self):
        """If a key doesn't exist in the file, it should be appended."""
        Path(self.secrets_path).write_text("discord_token=test123\n")
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_token=new_access" in content
        assert "claude_oauth_refresh_token=new_refresh" in content

    def test_atomic_write_nonexistent_file(self):
        """If secrets file doesn't exist, method should return without error."""
        self.refresher._secrets_file = "/nonexistent/path/.secrets"
        # Should not raise
        self.refresher._update_secrets_file()

    def test_atomic_write_preserves_expires_at(self):
        """expires_at field should be preserved if not updated."""
        Path(self.secrets_path).write_text(
            "discord_token=test123\n"
            "claude_oauth_token=old_access\n"
            "claude_oauth_refresh_token=old_refresh\n"
            "claude_oauth_expires_at=1234567890\n"
        )
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_expires_at=1234567890" in content
