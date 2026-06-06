"""Tests for the guarded OpenRouter daemon boot preflight."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from scripts import openrouter_daemon_boot_smoke as smoke


def _config(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "backends_enabled": True,
        "backends_main": "openrouter",
        "backends_chiefs_default": "openrouter",
        "backends_specialists_default": "openrouter",
        "openrouter_api_key": "sk-or-secret-test-value",
        "openrouter_default_model": "z-ai/glm-4.6",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_safe_load(monkeypatch, config: object) -> None:
    monkeypatch.setattr(smoke, "load_config", lambda _path: config)
    monkeypatch.setattr(smoke, "_run_startup_validators", lambda _config: None)


def test_main_refuses_when_live_gate_is_set(capsys, tmp_path) -> None:
    config_path = tmp_path / "bridge.toml"

    rc = smoke.main(
        ["--config", str(config_path)],
        environ={"BUMBA_ALLOW_LIVE": "1"},
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "BUMBA_ALLOW_LIVE=1" in captured.err


def test_main_prints_offline_preflight_report(monkeypatch, capsys, tmp_path) -> None:
    config_path = tmp_path / "bridge.toml"
    _patch_safe_load(monkeypatch, _config())
    monkeypatch.setattr(smoke, "_warm_claude_enabled_for_config", lambda _config: False)

    rc = smoke.main(
        ["--config", str(config_path), "--timeout", "7"],
        environ={},
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "preflight_passed"
    assert payload["mode"] == "offline_preflight"
    assert payload["config_path"] == str(config_path)
    assert payload["timeout_seconds"] == 7.0
    assert payload["backends_enabled"] is True
    assert payload["main_backend"] == "openrouter"
    assert payload["openrouter_default_model"] == "z-ai/glm-4.6"
    assert payload["openrouter_key_present"] is True
    assert payload["warm_claude_enabled"] is False
    assert payload["would_start_daemon"] is False
    assert payload["launchd_touched"] is False
    assert payload["live_model_calls"] is False
    assert payload["discord_started"] is False
    assert payload["api_started"] is False
    assert payload["message_processing_started"] is False


def test_report_does_not_print_openrouter_key(monkeypatch, capsys, tmp_path) -> None:
    secret = "sk-or-secret-test-value"
    _patch_safe_load(monkeypatch, _config(openrouter_api_key=secret))
    monkeypatch.setattr(smoke, "_warm_claude_enabled_for_config", lambda _config: False)

    rc = smoke.main(["--config", str(tmp_path / "bridge.toml")], environ={})

    captured = capsys.readouterr()
    assert rc == 0
    assert secret not in captured.out
    assert secret not in captured.err
    assert "openrouter_key_present" in captured.out


def test_main_fails_when_main_backend_is_not_openrouter(
    monkeypatch, capsys, tmp_path
) -> None:
    _patch_safe_load(monkeypatch, _config(backends_main="claude"))
    monkeypatch.setattr(smoke, "_warm_claude_enabled_for_config", lambda _config: True)

    rc = smoke.main(["--config", str(tmp_path / "bridge.toml")], environ={})

    captured = capsys.readouterr()
    assert rc == 1
    assert "[backends].main must be 'openrouter'" in captured.err
    assert "warm Claude must be disabled" in captured.err


def test_main_fails_when_openrouter_key_missing(monkeypatch, capsys, tmp_path) -> None:
    _patch_safe_load(monkeypatch, _config(openrouter_api_key=""))
    monkeypatch.setattr(smoke, "_warm_claude_enabled_for_config", lambda _config: False)

    rc = smoke.main(["--config", str(tmp_path / "bridge.toml")], environ={})

    captured = capsys.readouterr()
    assert rc == 1
    assert "openrouter_api_key must be present" in captured.err


def test_start_daemon_flag_refuses_without_daemon_gate(
    monkeypatch, capsys, tmp_path
) -> None:
    _patch_safe_load(monkeypatch, _config())
    monkeypatch.setattr(smoke, "_warm_claude_enabled_for_config", lambda _config: False)

    rc = smoke.main(
        ["--config", str(tmp_path / "bridge.toml"), "--start-daemon"],
        environ={},
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "BUMBA_ALLOW_DAEMON_SMOKE=1" in captured.err


def test_start_daemon_runs_guarded_lifecycle_when_gate_present(
    monkeypatch, capsys, tmp_path
) -> None:
    config_path = tmp_path / "bridge.toml"
    _patch_safe_load(monkeypatch, _config())
    monkeypatch.setattr(smoke, "_warm_claude_enabled_for_config", lambda _config: False)
    monkeypatch.setattr(
        smoke,
        "_run_daemon_lifecycle_smoke",
        lambda **_kwargs: {
            "status": "lifecycle_passed",
            "mode": "guarded_daemon_lifecycle",
            "daemon_started": True,
            "daemon_stopped": True,
            "launchd_touched": False,
            "live_model_calls": False,
        },
    )

    rc = smoke.main(
        ["--config", str(config_path), "--start-daemon"],
        environ={"BUMBA_ALLOW_DAEMON_SMOKE": "1"},
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "lifecycle_passed"
    assert payload["daemon_started"] is True
    assert payload["daemon_stopped"] is True
    assert payload["launchd_touched"] is False
    assert payload["live_model_calls"] is False


def test_lifecycle_parent_strips_live_and_key_env(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "lifecycle_passed"}),
            stderr="",
        )

    monkeypatch.setenv("BUMBA_ALLOW_LIVE", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-secret")
    monkeypatch.setattr(smoke.subprocess, "run", _fake_run)

    report = smoke._run_daemon_lifecycle_smoke(
        config_path=tmp_path / "bridge.toml",
        timeout_seconds=7.0,
    )

    env = captured["env"]
    assert isinstance(env, dict)
    assert "BUMBA_ALLOW_LIVE" not in env
    assert "OPENROUTER_API_KEY" not in env
    assert env[smoke.CHILD_GATE_ENV] == "1"
    assert "--_child-daemon" in captured["command"]
    assert report["status"] == "lifecycle_passed"
    assert report["child_report"] == {"status": "lifecycle_passed"}
    assert report["daemon_started"] is True
    assert report["daemon_stopped"] is True


def test_lifecycle_parent_redacts_child_failure(monkeypatch, tmp_path) -> None:
    secret = "sk-or-v1-abcdefghijklmnopqrstuvwxyz"

    def _fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"OpenRouter rejected {secret}",
        )

    monkeypatch.setattr(smoke.subprocess, "run", _fake_run)

    try:
        smoke._run_daemon_lifecycle_smoke(
            config_path=tmp_path / "bridge.toml",
            timeout_seconds=7.0,
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected child failure")

    assert secret not in message
    assert "sk-or-REDACTED" in message


def test_child_daemon_entry_refuses_without_child_gate(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.delenv(smoke.CHILD_GATE_ENV, raising=False)

    rc = smoke._run_child_daemon_entry(
        config_path=tmp_path / "bridge.toml",
        timeout_seconds=1.0,
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "child gate" in captured.err


def test_child_daemon_entry_prints_cycle_report(monkeypatch, capsys, tmp_path) -> None:
    async def _fake_cycle(**_kwargs):
        return {
            "status": "lifecycle_passed",
            "mode": "local_no_connect_child",
            "steady_state_reached": True,
        }

    monkeypatch.setenv(smoke.CHILD_GATE_ENV, "1")
    monkeypatch.setattr(smoke, "_run_child_daemon_cycle", _fake_cycle)

    rc = smoke._run_child_daemon_entry(
        config_path=tmp_path / "bridge.toml",
        timeout_seconds=1.0,
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "lifecycle_passed"
    assert payload["steady_state_reached"] is True
