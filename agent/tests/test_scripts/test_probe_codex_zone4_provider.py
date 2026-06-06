"""Tests for the Z4-15 Codex provider spike probe."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import scripts.probe_codex_zone4_provider as mod


def test_classify_zone4_codex_path_prefers_pydantic_openai_provider() -> None:
    assert (
        mod.classify_zone4_codex_path(
            has_codex_cli=True,
            has_openai_api_key=True,
        )
        == "pydantic-openai-provider"
    )


def test_classify_zone4_codex_path_requires_adapter_for_cli_only() -> None:
    assert (
        mod.classify_zone4_codex_path(
            has_codex_cli=True,
            has_openai_api_key=False,
        )
        == "codex-cli-adapter-required"
    )


def test_classify_zone4_codex_path_reports_unavailable_without_credentials() -> None:
    assert (
        mod.classify_zone4_codex_path(
            has_codex_cli=False,
            has_openai_api_key=False,
        )
        == "no-codex-provider-available"
    )


def test_build_codex_exec_probe_argv_uses_json_and_prompt() -> None:
    assert mod.build_codex_exec_probe_argv(
        codex_binary="/opt/homebrew/bin/codex",
        prompt="Return OK.",
    ) == ["/opt/homebrew/bin/codex", "exec", "--json", "Return OK."]


def test_inspect_environment_reports_presence_without_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-openai")
    monkeypatch.delenv("CODEX_API_KEY", raising=False)

    with patch("scripts.probe_codex_zone4_provider.shutil.which", return_value="/bin/codex"):
        probe = mod.inspect_local_codex_environment()

    assert probe.has_codex_cli is True
    assert probe.codex_binary == "/bin/codex"
    assert probe.has_codex_auth_json is True
    assert probe.has_openai_api_key is True
    assert probe.has_codex_api_key is False
    rendered = mod.render_markdown(probe)
    assert "sk-secret-openai" not in rendered
    assert "OPENAI_API_KEY: present" in rendered


def test_run_codex_exec_probe_skips_without_live_flag() -> None:
    result = mod.run_codex_exec_probe(
        codex_binary="codex",
        live=False,
    )

    assert result.skipped is True
    assert result.success is False
    assert result.error_class == "live_probe_disabled"


def test_run_codex_exec_probe_uses_subprocess_without_shell() -> None:
    completed = subprocess.CompletedProcess(
        args=["codex", "exec", "--json", "Return OK."],
        returncode=0,
        stdout=(
            '{"type":"thread.started","thread_id":"t1"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}\n'
            '{"type":"turn.completed"}\n'
        ),
        stderr="",
    )

    with patch(
        "scripts.probe_codex_zone4_provider.subprocess.run",
        return_value=completed,
    ) as run:
        result = mod.run_codex_exec_probe(
            codex_binary="codex",
            live=True,
        )

    assert result.success is True
    assert result.exit_code == 0
    assert result.final_text == "OK"
    run.assert_called_once()
    _, kwargs = run.call_args
    assert kwargs["shell"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
