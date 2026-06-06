"""Comprehensive tests for bridge.token_refresher.

Covers: construction, access_token property, start/stop lifecycle,
refresh delay calculation, OAuth HTTP call, atomic secrets write,
do_refresh end-to-end, alert callback on failure, on_refresh callback.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.token_refresher import (
    OAUTH_TOKEN_URL,
    REFRESH_INTERVAL_SECONDS,
    TokenRefresher,
    _CLIENT_ID,
)


# ---------------------------------------------------------------------------
# Construction & properties
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_stores_access_token(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        assert tr.access_token == "at"

    def test_defaults_secrets_file(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        assert tr._secrets_file.endswith(".secrets")

    def test_custom_secrets_file(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="rt", secrets_file="/tmp/s")
        assert tr._secrets_file == "/tmp/s"

    def test_converts_expires_at_ms_to_seconds(self) -> None:
        tr = TokenRefresher(
            access_token="at", refresh_token="rt", expires_at_ms=1_700_000_000_000
        )
        assert tr._expires_at == 1_700_000_000.0

    def test_accepts_expires_at_seconds_from_runtime_secrets(self) -> None:
        future = int(time.time() + 7200)
        tr = TokenRefresher(
            access_token="at", refresh_token="rt", expires_at_ms=future,
        )
        assert tr._expires_at == float(future)

    def test_zero_expires_at_when_omitted(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        assert tr._expires_at == 0.0

    def test_alert_callback_stored(self) -> None:
        cb = AsyncMock()
        tr = TokenRefresher(access_token="at", refresh_token="rt", alert_callback=cb)
        assert tr._alert_callback is cb

    def test_set_on_refresh_callback(self) -> None:
        cb = AsyncMock()
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        tr.set_on_refresh(cb)
        assert tr._on_refresh_callback is cb


# ---------------------------------------------------------------------------
# Start / stop lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_without_refresh_token_does_not_create_task(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="")
        tr.start()
        assert tr._task is None

    async def test_start_creates_task(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        with patch.object(tr, "_refresh_loop", new_callable=AsyncMock):
            tr.start()
            assert tr._task is not None
            tr._task.cancel()
            try:
                await tr._task
            except asyncio.CancelledError:
                pass

    async def test_stop_cancels_running_task(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        with patch.object(tr, "_refresh_loop", new_callable=AsyncMock) as mock_loop:
            # Make the loop hang so task stays alive
            mock_loop.side_effect = asyncio.CancelledError
            tr.start()
            await tr.stop()
            assert tr._task.done()

    async def test_stop_when_no_task_is_noop(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        await tr.stop()  # Should not raise
        # No task was started, so the refresher remains in its initial
        # state — no task handle, no started flag.
        assert tr._task is None


# ---------------------------------------------------------------------------
# _next_refresh_delay
# ---------------------------------------------------------------------------


class TestNextRefreshDelay:
    def test_no_expiry_returns_default_interval(self) -> None:
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        assert tr._next_refresh_delay() == REFRESH_INTERVAL_SECONDS

    def test_expiry_far_in_future_caps_at_interval(self) -> None:
        tr = TokenRefresher(
            access_token="at", refresh_token="rt",
            expires_at_ms=int((time.time() + 100_000) * 1000),
        )
        delay = tr._next_refresh_delay()
        assert delay == REFRESH_INTERVAL_SECONDS

    def test_expiry_soon_gives_shorter_delay(self) -> None:
        # Expires in 2 hours => remaining - margin = 2h - 1h = 1h
        future = time.time() + 7200
        tr = TokenRefresher(
            access_token="at", refresh_token="rt",
            expires_at_ms=int(future * 1000),
        )
        delay = tr._next_refresh_delay()
        # Should be ~3600 (7200 - 3600 margin)
        assert 3500 < delay < 3700

    def test_seconds_expiry_does_not_clamp_to_startup_retry(self) -> None:
        future = time.time() + 7200
        tr = TokenRefresher(
            access_token="at", refresh_token="rt",
            expires_at_ms=int(future),
        )
        delay = tr._next_refresh_delay()
        assert 3500 < delay < 3700

    def test_expiry_very_soon_clamps_to_minimum(self) -> None:
        # Expires in 30 seconds => remaining - margin = negative => clamped to 60
        future = time.time() + 30
        tr = TokenRefresher(
            access_token="at", refresh_token="rt",
            expires_at_ms=int(future * 1000),
        )
        delay = tr._next_refresh_delay()
        assert delay == 60

    def test_already_expired_clamps_to_minimum(self) -> None:
        past = time.time() - 600
        tr = TokenRefresher(
            access_token="at", refresh_token="rt",
            expires_at_ms=int(past * 1000),
        )
        delay = tr._next_refresh_delay()
        assert delay == 60


# ---------------------------------------------------------------------------
# _call_refresh_endpoint (sync HTTP)
# ---------------------------------------------------------------------------


class TestCallRefreshEndpoint:
    def test_successful_refresh(self) -> None:
        response_body = json.dumps({
            "access_token": "new_at",
            "refresh_token": "new_rt",
            "expires_in": 28800,
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        tr = TokenRefresher(access_token="old_at", refresh_token="old_rt")

        with patch("bridge.token_refresher.urllib.request.urlopen", return_value=mock_resp):
            result = tr._call_refresh_endpoint()

        assert result["access_token"] == "new_at"
        assert result["refresh_token"] == "new_rt"
        assert result["expires_in"] == 28800

    def test_http_error_raises_runtime_error(self) -> None:
        import urllib.error

        http_err = urllib.error.HTTPError(
            url=OAUTH_TOKEN_URL, code=401, msg="Unauthorized",
            hdrs=MagicMock(), fp=MagicMock(),
        )
        http_err.read = MagicMock(return_value=b"bad credentials")

        tr = TokenRefresher(access_token="at", refresh_token="rt")

        with patch("bridge.token_refresher.urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(RuntimeError, match="HTTP 401"):
                tr._call_refresh_endpoint()

    def test_url_error_raises_runtime_error(self) -> None:
        import urllib.error

        url_err = urllib.error.URLError("Connection refused")

        tr = TokenRefresher(access_token="at", refresh_token="rt")

        with patch("bridge.token_refresher.urllib.request.urlopen", side_effect=url_err):
            with pytest.raises(RuntimeError, match="network error"):
                tr._call_refresh_endpoint()

    def test_sends_correct_request_body(self) -> None:
        """Verify the POST body contains grant_type, client_id, refresh_token."""
        import urllib.parse

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"access_token": "x"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        tr = TokenRefresher(access_token="at", refresh_token="my_rt")

        with patch("bridge.token_refresher.urllib.request.urlopen", return_value=mock_resp) as mock_open:
            tr._call_refresh_endpoint()

        req = mock_open.call_args[0][0]
        body = urllib.parse.parse_qs(req.data.decode())
        assert body["grant_type"] == ["refresh_token"]
        assert body["client_id"] == [_CLIENT_ID]
        assert body["refresh_token"] == ["my_rt"]
        assert req.get_full_url() == OAUTH_TOKEN_URL


# ---------------------------------------------------------------------------
# _do_refresh (async orchestrator)
# ---------------------------------------------------------------------------


class TestDoRefresh:
    async def test_successful_refresh_updates_token(self) -> None:
        tr = TokenRefresher(
            access_token="old", refresh_token="rt",
            secrets_file="/nonexistent/.secrets",
        )

        fake_response = {
            "access_token": "brand_new_token",
            "refresh_token": "new_rt",
            "expires_in": 28800,
        }

        with patch.object(tr, "_call_refresh_endpoint", return_value=fake_response):
            with patch.object(tr, "_update_secrets_file"):
                await tr._do_refresh()

        assert tr.access_token == "brand_new_token"
        assert tr._refresh_token == "new_rt"
        assert tr._expires_at > 0

    async def test_refresh_without_new_refresh_token(self) -> None:
        tr = TokenRefresher(access_token="old", refresh_token="original_rt")

        fake_response = {
            "access_token": "new_at",
            # No refresh_token in response
            "expires_in": 3600,
        }

        with patch.object(tr, "_call_refresh_endpoint", return_value=fake_response):
            with patch.object(tr, "_update_secrets_file"):
                await tr._do_refresh()

        assert tr.access_token == "new_at"
        assert tr._refresh_token == "original_rt"  # unchanged

    async def test_refresh_without_expires_in_sets_zero(self) -> None:
        tr = TokenRefresher(access_token="old", refresh_token="rt")

        fake_response = {"access_token": "new"}

        with patch.object(tr, "_call_refresh_endpoint", return_value=fake_response):
            with patch.object(tr, "_update_secrets_file"):
                await tr._do_refresh()

        assert tr._expires_at == 0.0

    async def test_refresh_none_result_raises(self) -> None:
        tr = TokenRefresher(access_token="old", refresh_token="rt")

        with patch.object(tr, "_call_refresh_endpoint", return_value=None):
            with pytest.raises(RuntimeError, match="returned no data"):
                await tr._do_refresh()

    async def test_refresh_empty_access_token_raises(self) -> None:
        tr = TokenRefresher(access_token="old", refresh_token="rt")

        with patch.object(tr, "_call_refresh_endpoint", return_value={"error": "bad"}):
            with pytest.raises(RuntimeError, match="No access_token"):
                await tr._do_refresh()

    async def test_on_refresh_callback_fires(self) -> None:
        cb = AsyncMock()
        tr = TokenRefresher(access_token="old", refresh_token="rt")
        tr.set_on_refresh(cb)

        fake_response = {"access_token": "new", "expires_in": 100}

        with patch.object(tr, "_call_refresh_endpoint", return_value=fake_response):
            with patch.object(tr, "_update_secrets_file"):
                await tr._do_refresh()

        cb.assert_awaited_once()

    async def test_on_refresh_callback_failure_does_not_raise(self) -> None:
        cb = AsyncMock(side_effect=ValueError("callback boom"))
        tr = TokenRefresher(access_token="old", refresh_token="rt")
        tr.set_on_refresh(cb)

        fake_response = {"access_token": "new", "expires_in": 100}

        with patch.object(tr, "_call_refresh_endpoint", return_value=fake_response):
            with patch.object(tr, "_update_secrets_file"):
                # Should NOT raise despite callback failure
                await tr._do_refresh()

        assert tr.access_token == "new"


# ---------------------------------------------------------------------------
# _refresh_loop behavior
# ---------------------------------------------------------------------------


class TestRefreshLoop:
    async def test_loop_retries_on_failure_with_5min_wait(self) -> None:
        """On refresh failure, loop should sleep 300s then retry."""
        tr = TokenRefresher(access_token="at", refresh_token="rt")
        call_count = 0

        async def fake_do_refresh() -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise RuntimeError("simulated failure")
            # Second call succeeds but we cancel after
            raise asyncio.CancelledError

        with patch.object(tr, "_do_refresh", side_effect=fake_do_refresh):
            with patch.object(tr, "_next_refresh_delay", return_value=0):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    with pytest.raises(asyncio.CancelledError):
                        await tr._refresh_loop()

        # First sleep(0) for initial delay, then sleep(300) for retry
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert 300 in sleep_calls

    async def test_loop_calls_alert_callback_on_failure(self) -> None:
        alert_cb = AsyncMock()
        tr = TokenRefresher(
            access_token="at", refresh_token="rt", alert_callback=alert_cb,
        )

        async def fail_then_cancel() -> None:
            raise RuntimeError("token expired")

        call_count = 0

        async def controlled_do_refresh() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("token expired")
            raise asyncio.CancelledError

        with patch.object(tr, "_do_refresh", side_effect=controlled_do_refresh):
            with patch.object(tr, "_next_refresh_delay", return_value=0):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(asyncio.CancelledError):
                        await tr._refresh_loop()

        alert_cb.assert_awaited_once()
        alert_msg = alert_cb.call_args[0][0]
        assert "Token refresh failed" in alert_msg
        assert "5 minutes" in alert_msg

    async def test_loop_alert_callback_failure_swallowed(self) -> None:
        """If alert callback itself fails, loop should continue."""
        alert_cb = AsyncMock(side_effect=Exception("discord down"))
        tr = TokenRefresher(
            access_token="at", refresh_token="rt", alert_callback=alert_cb,
        )

        call_count = 0

        async def controlled_do_refresh() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("refresh fail")
            raise asyncio.CancelledError

        with patch.object(tr, "_do_refresh", side_effect=controlled_do_refresh):
            with patch.object(tr, "_next_refresh_delay", return_value=0):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(asyncio.CancelledError):
                        await tr._refresh_loop()

        # Loop survived alert callback failure and continued to second iteration
        assert call_count == 2


# ---------------------------------------------------------------------------
# Atomic secrets file writing (expanded from test_token_refresher_atomic.py)
# ---------------------------------------------------------------------------


class TestAtomicSecretsWrite:
    def setup_method(self) -> None:
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

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_atomic_write_creates_no_tmp_after_success(self) -> None:
        self.refresher._update_secrets_file()
        assert not Path(self.secrets_path + ".tmp").exists()
        assert Path(self.secrets_path).exists()

    def test_atomic_write_updates_tokens(self) -> None:
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_token=new_access" in content
        assert "claude_oauth_refresh_token=new_refresh" in content
        assert "discord_token=test123" in content

    def test_atomic_write_preserves_original_on_rename_failure(self) -> None:
        with patch("os.rename", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_token=old_access" in content

    def test_atomic_write_no_duplicate_keys(self) -> None:
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        lines = [l for l in content.splitlines() if l.startswith("claude_oauth_token=")]
        assert len(lines) == 1
        assert lines[0] == "claude_oauth_token=new_access"

    def test_atomic_write_adds_missing_keys(self) -> None:
        Path(self.secrets_path).write_text("discord_token=test123\n")
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_token=new_access" in content
        assert "claude_oauth_refresh_token=new_refresh" in content

    def test_atomic_write_nonexistent_file(self) -> None:
        self.refresher._secrets_file = "/nonexistent/path/.secrets"
        self.refresher._update_secrets_file()  # Should not raise

    def test_atomic_write_preserves_other_keys(self) -> None:
        Path(self.secrets_path).write_text(
            "discord_token=test123\n"
            "claude_oauth_token=old_access\n"
            "claude_oauth_refresh_token=old_refresh\n"
            "claude_oauth_expires_at=1234567890\n"
            "notion_api_token=secret_notion\n"
        )
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_expires_at=1234567890" in content
        assert "notion_api_token=secret_notion" in content
        assert "claude_oauth_token=new_access" in content

    def test_atomic_write_ends_with_newline(self) -> None:
        self.refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert content.endswith("\n")

    def test_atomic_write_empty_refresh_token_not_appended(self) -> None:
        """If refresh_token is empty, it should not be appended to the file."""
        Path(self.secrets_path).write_text("discord_token=test123\n")
        refresher = TokenRefresher(
            access_token="at",
            refresh_token="",
            secrets_file=self.secrets_path,
        )
        refresher._update_secrets_file()
        content = Path(self.secrets_path).read_text()
        assert "claude_oauth_refresh_token" not in content


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-15.D.01 (#2003) — file-sync contract for refresh.
# ---------------------------------------------------------------------------


class TestRefreshFileSyncContract:
    """Lock down the file-sync invariants ``_update_secrets_file`` must
    honor on every refresh (audit §M-2):

    1. The final ``.secrets`` file is mode 0o600 — readable only by the
       owner. Without this, a token refresh could quietly widen
       permissions and expose the OAuth token to other local users.
    2. The legacy ``.claude-token`` cache file is NEVER touched. A.01
       (#1991) demoted ``.claude-token`` to a deprecated read-only
       fallback; the refresher must not resurrect it as a write target.
    3. Writes are atomic: the helper writes to a sibling temp path FIRST,
       chmods 0o600 on the temp path, and only then renames over the
       final path. Without this, a crash mid-write could leave a
       half-written ``.secrets`` and lock the bridge out of OAuth.
    """

    def setup_method(self) -> None:
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

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_secrets_file_written_with_mode_0600(self) -> None:
        """After a refresh, ``.secrets`` MUST be mode 0o600.

        ``_update_secrets_file`` chmods the temp path 0o600 BEFORE the
        atomic rename, so the final file inherits that mode. Verify the
        mode on the path the bridge actually reads from.
        """
        self.refresher._update_secrets_file()
        mode = os.stat(self.secrets_path).st_mode & 0o777
        assert mode == 0o600, (
            f"expected .secrets mode 0o600, got {oct(mode)} — refresh "
            "must not widen permissions on the OAuth secret"
        )

    def test_legacy_claude_token_file_not_written_by_refresh(self) -> None:
        """A.01 (#1991) demoted ``agent/data/.claude-token`` to a
        deprecated read-only fallback. The refresher must not write to
        it under any circumstance — even if it happens to exist before
        the call. Verify both the in-tmp location next to ``.secrets``
        and that the refresher's write path does not include any
        ``.claude-token`` artifact.
        """
        legacy_path = Path(self.tmp_dir) / ".claude-token"
        # Pre-populate the legacy file with a sentinel so we can detect
        # any silent overwrite.
        legacy_path.write_text("DEPRECATED-DO-NOT-TOUCH")

        self.refresher._update_secrets_file()

        # The legacy file content is byte-for-byte unchanged.
        assert legacy_path.read_text() == "DEPRECATED-DO-NOT-TOUCH", (
            "refresh wrote to legacy .claude-token — A.01 demoted this "
            "path; refresher must only touch .secrets"
        )
        # No new claude-token sibling was created adjacent to .secrets.
        siblings = {p.name for p in Path(self.tmp_dir).iterdir()}
        # The legacy file exists because WE created it; no NEW token
        # cache files should appear beyond .secrets + .claude-token.
        allowed = {".secrets", ".claude-token"}
        unexpected = siblings - allowed
        assert not unexpected, (
            f"refresh created unexpected files: {unexpected}"
        )

    def test_refresh_atomicity_writes_to_temp_then_rename(self) -> None:
        """The helper MUST write to a sibling ``.tmp`` path first, then
        rename. Verify by patching ``os.rename`` and capturing the
        (src, dst) pair: src must differ from dst, and src must exist as
        a real file at the moment of rename (i.e. write happened before
        rename, not after).
        """
        captured: dict[str, object] = {}
        real_rename = os.rename

        def _capturing_rename(src: str, dst: str) -> None:
            # Snapshot both paths AND assert the src file exists right
            # now — that proves the write completed before rename.
            captured["src"] = src
            captured["dst"] = dst
            captured["src_exists_at_rename"] = Path(src).is_file()
            real_rename(src, dst)

        with patch("os.rename", side_effect=_capturing_rename):
            self.refresher._update_secrets_file()

        assert captured, "os.rename was never called by _update_secrets_file"
        assert captured["src"] != captured["dst"], (
            f"rename src and dst are identical ({captured['src']!r}) — "
            "atomicity contract requires a distinct temp path"
        )
        assert captured["src_exists_at_rename"] is True, (
            "temp path did not exist at the moment of rename — write "
            "must complete BEFORE rename, not after"
        )
        # Belt-and-suspenders: the src path should be a sibling of the
        # final path (same parent directory), not an unrelated tmpfile.
        assert Path(captured["src"]).parent == Path(captured["dst"]).parent, (
            "temp path must be a sibling of the final path so the rename "
            "is a same-filesystem atomic operation on POSIX"
        )
