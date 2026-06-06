"""Tests for scripts/deploy_lib.py — consolidation library for deploy primitives.

Sprint 5.00b (issue #2154): the four primitives that every deploy script
today inlines — kernel baseline regen, daemon bounce, post-deploy smoke,
and version stamping — are now in one importable library so future deploy
scripts can call helpers instead of pasting inline heredocs.

Tests use mocked subprocess + filesystem so they run in any environment,
NOT just on the Mac mini runtime. CRITICAL: the library is opt-in only;
no existing deploy script behavior changes, and these tests therefore
only exercise the new lib.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_lib():
    """Import scripts/deploy_lib.py as a module.

    Same path-resolution trick as test_regenerate_kernel_baseline.py:
    /scripts/ is a repo-root exception to the everything-under-/agent/ rule.
    """
    spec = importlib.util.spec_from_file_location(
        "deploy_lib",
        Path(__file__).resolve().parent.parent.parent / "scripts" / "deploy_lib.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Module shape
# ---------------------------------------------------------------------------


class TestModuleShape:
    """The library must expose the four primitive functions named in the spec."""

    def test_exposes_regenerate_baseline(self):
        mod = _load_lib()
        assert hasattr(mod, "regenerate_baseline")
        assert callable(mod.regenerate_baseline)

    def test_exposes_bounce_daemon(self):
        mod = _load_lib()
        assert hasattr(mod, "bounce_daemon")
        assert callable(mod.bounce_daemon)

    def test_exposes_smoke_test(self):
        mod = _load_lib()
        assert hasattr(mod, "smoke_test")
        assert callable(mod.smoke_test)

    def test_exposes_version_stamp(self):
        mod = _load_lib()
        assert hasattr(mod, "version_stamp")
        assert callable(mod.version_stamp)


# ---------------------------------------------------------------------------
# regenerate_baseline — delegates to the standalone script
# ---------------------------------------------------------------------------


class TestRegenerateBaseline:
    """regenerate_baseline() must shell out to scripts/regenerate_kernel_baseline.py.

    Rationale: that script is the existing kernel-integrity source of truth,
    is already called by every deploy script, and runs as root. The lib
    helper wraps it so deploy scripts don't have to know the exact path.
    Never re-implement the hashing — that creates a drift surface.
    """

    def test_invokes_regenerate_kernel_baseline_script(self):
        mod = _load_lib()
        with patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mod.regenerate_baseline()
            assert mock_run.called
            args, _ = mock_run.call_args
            cmd = args[0]
            # Must call the regenerate_kernel_baseline.py helper, not inline.
            joined = " ".join(cmd) if isinstance(cmd, list) else cmd
            assert "regenerate_kernel_baseline.py" in joined

    def test_passes_target_root_when_provided(self):
        mod = _load_lib()
        with patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mod.regenerate_baseline(target_root="/opt/bumba-harness/agent-flat/agent")
            args, _ = mock_run.call_args
            cmd = args[0]
            joined = " ".join(cmd) if isinstance(cmd, list) else cmd
            assert "--target-root" in joined
            assert "/opt/bumba-harness/agent-flat/agent" in joined

    def test_raises_on_nonzero_exit(self):
        mod = _load_lib()
        with patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="boom"
            )
            try:
                mod.regenerate_baseline()
            except RuntimeError as exc:
                assert "regenerate" in str(exc).lower() or "baseline" in str(exc).lower()
            else:
                raise AssertionError("expected RuntimeError on non-zero exit")


# ---------------------------------------------------------------------------
# bounce_daemon — launchctl kickstart for the bridge
# ---------------------------------------------------------------------------


class TestBounceDaemon:
    """bounce_daemon() must restart a launchd-managed service.

    Default label is the bridge daemon. Caller can override for other
    services (deploy-helper, briefing, check-in, maintenance).
    """

    def test_default_label_is_bridge(self):
        mod = _load_lib()
        assert mod.DEFAULT_DAEMON_LABEL == "com.bumba.agent-bridge"

    def test_invokes_launchctl_kickstart_with_default_label(self):
        mod = _load_lib()
        with patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mod.bounce_daemon()
            args, _ = mock_run.call_args
            cmd = args[0]
            joined = " ".join(cmd) if isinstance(cmd, list) else cmd
            assert "launchctl" in joined
            assert "kickstart" in joined
            assert mod.DEFAULT_DAEMON_LABEL in joined

    def test_respects_explicit_label(self):
        mod = _load_lib()
        with patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mod.bounce_daemon(label="com.bumba.agent-deploy-helper")
            args, _ = mock_run.call_args
            cmd = args[0]
            joined = " ".join(cmd) if isinstance(cmd, list) else cmd
            assert "com.bumba.agent-deploy-helper" in joined
            assert mod.DEFAULT_DAEMON_LABEL not in joined.replace(
                "com.bumba.agent-deploy-helper", ""
            )

    def test_raises_on_nonzero_exit(self):
        mod = _load_lib()
        with patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=2, stdout="", stderr="not loaded"
            )
            try:
                mod.bounce_daemon()
            except RuntimeError as exc:
                assert "launchctl" in str(exc).lower() or "bounce" in str(exc).lower()
            else:
                raise AssertionError("expected RuntimeError on non-zero exit")


# ---------------------------------------------------------------------------
# smoke_test — post-deploy /healthz probe
# ---------------------------------------------------------------------------


class TestSmokeTest:
    """smoke_test() must hit a HTTP endpoint and return a clean PASS/FAIL.

    Default host is localhost:8200 (the bridge daemon's REST port; see
    agent/config/bridge.toml). Returns True on 2xx, False otherwise. Never
    raises on HTTP errors — the deploy script decides whether a failed
    smoke aborts the deploy.
    """

    def test_default_host_is_localhost_bridge_port(self):
        mod = _load_lib()
        assert mod.DEFAULT_SMOKE_URL.startswith("http://localhost:8200")

    def test_returns_true_on_2xx(self):
        mod = _load_lib()
        fake_response = MagicMock()
        fake_response.status = 200
        fake_response.read.return_value = b'{"status":"ok"}'
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)
        with patch.object(mod.urllib.request, "urlopen", return_value=fake_response):
            ok, _detail = mod.smoke_test()
            assert ok is True

    def test_returns_false_on_non_2xx(self):
        mod = _load_lib()
        fake_response = MagicMock()
        fake_response.status = 503
        fake_response.read.return_value = b"unavailable"
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)
        with patch.object(mod.urllib.request, "urlopen", return_value=fake_response):
            ok, _detail = mod.smoke_test()
            assert ok is False

    def test_returns_false_on_connection_error(self):
        mod = _load_lib()
        with patch.object(
            mod.urllib.request,
            "urlopen",
            side_effect=OSError("connection refused"),
        ):
            ok, detail = mod.smoke_test()
            assert ok is False
            assert "connection refused" in detail.lower() or "error" in detail.lower()

    def test_honors_custom_url(self):
        mod = _load_lib()
        captured = {}

        def fake_urlopen(req, timeout=None):
            # urllib.request.urlopen accepts either a URL string or a Request
            url = req if isinstance(req, str) else req.full_url
            captured["url"] = url
            resp = MagicMock()
            resp.status = 200
            resp.read.return_value = b"ok"
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch.object(mod.urllib.request, "urlopen", side_effect=fake_urlopen):
            mod.smoke_test(url="http://localhost:9999/healthz")
        assert captured["url"] == "http://localhost:9999/healthz"


# ---------------------------------------------------------------------------
# version_stamp — write data/version.json via bridge.version.write_version
# ---------------------------------------------------------------------------


class TestVersionStamp:
    """version_stamp() must write a version.json under the runtime data dir.

    The shape must match what bridge.version.get_current_version() reads
    so /healthz reports the deployed version. Never re-implement the
    schema — call bridge.version.write_version when importable; fall back
    to writing the same dict shape when the source tree's bridge module
    isn't on the import path (which is true for most deploy scripts).
    """

    def test_writes_version_json_with_expected_shape(self, tmp_path):
        mod = _load_lib()
        info = mod.version_stamp(
            data_dir=tmp_path,
            version="phase5-abc1234",
            git_commit="abc1234deadbeef",
            deployed_by="test-deploy",
        )
        version_file = tmp_path / "version.json"
        assert version_file.exists()
        data = json.loads(version_file.read_text())
        assert data["version"] == "phase5-abc1234"
        assert data["git_commit"] == "abc1234deadbeef"
        assert data["deployed_by"] == "test-deploy"
        assert "deployed_at" in data
        # And the returned dataclass-ish must match
        assert info["version"] == "phase5-abc1234"

    def test_creates_data_dir_if_missing(self, tmp_path):
        mod = _load_lib()
        target = tmp_path / "fresh" / "data"
        # target does NOT exist yet
        mod.version_stamp(
            data_dir=target,
            version="phase6-deadbee",
            git_commit="deadbee",
            deployed_by="test-deploy",
        )
        assert (target / "version.json").exists()

    def test_default_deployed_by_is_manual(self, tmp_path):
        mod = _load_lib()
        mod.version_stamp(
            data_dir=tmp_path,
            version="phase7-1234567",
            git_commit="1234567",
        )
        data = json.loads((tmp_path / "version.json").read_text())
        # Match bridge.version.write_version's default
        assert data["deployed_by"] == "manual"
