"""Probe whether Codex can power Zone 4 PydanticAI agents.

The default path is non-secret and offline-safe: inspect local binaries,
credential presence, repo backend support, and PydanticAI import support
without printing credential values. A live `codex exec --json` smoke is
available only behind an explicit flag.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_PATH = (
    REPO_ROOT / "docs" / "audits" / "2026-05-21-codex-zone4-provider-spike.md"
)
DEFAULT_CODEX_PROMPT = "Return exactly OK and nothing else."

Zone4CodexPath = Literal[
    "pydantic-openai-provider",
    "codex-cli-adapter-required",
    "no-codex-provider-available",
]


@dataclass(frozen=True)
class CodexExecProbeResult:
    skipped: bool
    success: bool
    exit_code: int | None
    stdout: str
    stderr: str
    final_text: str
    duration_seconds: float
    error_class: str | None


@dataclass(frozen=True)
class CodexZone4ProviderProbe:
    codex_binary: str | None
    codex_version: str | None
    has_codex_cli: bool
    has_codex_auth_json: bool
    has_codex_api_key: bool
    has_openai_api_key: bool
    pydantic_openai_import_ok: bool
    repo_codex_backend_present: bool
    recommended_path: Zone4CodexPath
    codex_exec_probe: CodexExecProbeResult | None = None


def classify_zone4_codex_path(
    *,
    has_codex_cli: bool,
    has_openai_api_key: bool,
) -> Zone4CodexPath:
    """Classify the safe Zone 4 provider path from credential presence."""
    if has_openai_api_key:
        return "pydantic-openai-provider"
    if has_codex_cli:
        return "codex-cli-adapter-required"
    return "no-codex-provider-available"


def build_codex_exec_probe_argv(
    *,
    codex_binary: str,
    prompt: str = DEFAULT_CODEX_PROMPT,
) -> list[str]:
    """Build the opt-in deterministic Codex CLI probe argv."""
    return [codex_binary, "exec", "--json", prompt]


def _has_env(name: str) -> bool:
    return bool(os.environ.get(name))


def _codex_auth_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "auth.json"
    return Path.home() / ".codex" / "auth.json"


def _codex_version(codex_binary: str) -> str | None:
    try:
        completed = subprocess.run(
            [codex_binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (completed.stdout or completed.stderr).strip()
    if not text:
        return None
    return text.splitlines()[-1]


def _pydantic_openai_import_ok() -> bool:
    try:
        import pydantic_ai.models.openai  # noqa: F401
        import pydantic_ai.providers.openai  # noqa: F401
    except Exception:  # noqa: BLE001 - import probe only
        return False
    return True


def inspect_local_codex_environment(
    *,
    codex_binary_name: str = "codex",
) -> CodexZone4ProviderProbe:
    """Inspect local Codex/OpenAI provider surfaces without exposing secrets."""
    codex_binary = shutil.which(codex_binary_name)
    has_codex_cli = codex_binary is not None
    has_openai_api_key = _has_env("OPENAI_API_KEY")
    return CodexZone4ProviderProbe(
        codex_binary=codex_binary,
        codex_version=_codex_version(codex_binary) if codex_binary else None,
        has_codex_cli=has_codex_cli,
        has_codex_auth_json=_codex_auth_path().is_file(),
        has_codex_api_key=_has_env("CODEX_API_KEY"),
        has_openai_api_key=has_openai_api_key,
        pydantic_openai_import_ok=_pydantic_openai_import_ok(),
        repo_codex_backend_present=(
            REPO_ROOT / "agent" / "bridge" / "backends" / "codex.py"
        ).is_file(),
        recommended_path=classify_zone4_codex_path(
            has_codex_cli=has_codex_cli,
            has_openai_api_key=has_openai_api_key,
        ),
    )


def _string_from_timeout_payload(payload: str | bytes | None) -> str:
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return payload


def _extract_final_text(stdout: str) -> str:
    final_text = ""
    for line in stdout.splitlines():
        try:
            event: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                final_text = text
    return final_text


def run_codex_exec_probe(
    *,
    codex_binary: str,
    live: bool,
    prompt: str = DEFAULT_CODEX_PROMPT,
    timeout_seconds: int = 60,
) -> CodexExecProbeResult:
    """Run the deterministic Codex CLI probe only when `live` is true."""
    if not live:
        return CodexExecProbeResult(
            skipped=True,
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            final_text="",
            duration_seconds=0.0,
            error_class="live_probe_disabled",
        )

    argv = build_codex_exec_probe_argv(codex_binary=codex_binary, prompt=prompt)
    start = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            shell=False,
        )
    except FileNotFoundError:
        return CodexExecProbeResult(
            skipped=False,
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            final_text="",
            duration_seconds=time.monotonic() - start,
            error_class="codex_cli_missing",
        )
    except subprocess.TimeoutExpired as exc:
        return CodexExecProbeResult(
            skipped=False,
            success=False,
            exit_code=None,
            stdout=_string_from_timeout_payload(exc.stdout),
            stderr=_string_from_timeout_payload(exc.stderr),
            final_text="",
            duration_seconds=time.monotonic() - start,
            error_class="timeout",
        )

    final_text = _extract_final_text(completed.stdout)
    success = completed.returncode == 0 and bool(final_text.strip())
    return CodexExecProbeResult(
        skipped=False,
        success=success,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        final_text=final_text,
        duration_seconds=time.monotonic() - start,
        error_class=None if success else "codex_exec_failed",
    )


_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|sk-or-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def _present(value: bool) -> str:
    return "present" if value else "absent"


def _directness_label(path: Zone4CodexPath) -> str:
    if path == "pydantic-openai-provider":
        return "direct via OpenAI API provider, not via paid Codex account"
    if path == "codex-cli-adapter-required":
        return "indirect via Codex CLI adapter"
    return "unavailable"


def render_markdown(probe: CodexZone4ProviderProbe) -> str:
    """Render the Z4-15 audit document without secret values."""
    lines = [
        "# Codex Zone 4 Provider Spike",
        "",
        "Date: 2026-05-21",
        "Issue: Z4-15",
        "",
        "## Answer",
        "",
        (
            "- Codex for PydanticAI Zone 4 is "
            f"**{_directness_label(probe.recommended_path)}**."
        ),
        (
            "- Recommendation: "
            f"`{probe.recommended_path}`."
        ),
        (
            "- A paid Codex account and an OpenAI API key are separate runtime "
            "surfaces. PydanticAI can use OpenAI-compatible APIs when an "
            "OpenAI API credential exists; Codex CLI uses `codex exec` and "
            "its own Codex auth file."
        ),
        "",
        "## Local Probe",
        "",
        f"- Codex CLI: {_present(probe.has_codex_cli)}",
        f"- Codex binary: `{probe.codex_binary or '<not found>'}`",
        f"- Codex version: `{_redact(probe.codex_version or '<unknown>')}`",
        f"- Codex auth.json: {_present(probe.has_codex_auth_json)}",
        f"- CODEX_API_KEY: {_present(probe.has_codex_api_key)}",
        f"- OPENAI_API_KEY: {_present(probe.has_openai_api_key)}",
        (
            "- PydanticAI OpenAI provider import: "
            f"{'ok' if probe.pydantic_openai_import_ok else 'failed'}"
        ),
        (
            "- Repo Codex CLI backend: "
            f"{_present(probe.repo_codex_backend_present)}"
        ),
        "",
        "## PydanticAI Provider Finding",
        "",
        (
            "- Current PydanticAI docs show `OpenAIChatModel` with "
            "`OpenAIProvider`, using `OPENAI_API_KEY` by default or an "
            "explicit provider API key."
        ),
        (
            "- Current PydanticAI docs also describe OpenAI-compatible "
            "providers through `OPENAI_BASE_URL` plus `OPENAI_API_KEY`."
        ),
        (
            "- The docs did not establish a direct paid-Codex-account "
            "PydanticAI provider for Zone 4 agents. Codex appears as a CLI "
            "surface, not as a direct PydanticAI billing surface."
        ),
        "",
        "## Paths",
        "",
        (
            "- Path A: PydanticAI OpenAI provider. Direct for Zone 4 when "
            "`OPENAI_API_KEY` is configured, with OpenAI API billing and "
            "standard provider security controls."
        ),
        (
            "- Path B: Custom `codex-exec:` adapter. Indirect path that "
            "would shell out to Codex CLI and rely on `~/.codex/auth.json`; "
            "requires explicit adapter, logging, cost, and timeout work."
        ),
        (
            "- Path C: Keep OpenRouter for specialists while reducing scope "
            "and cost. This preserves the current Zone 4 PydanticAI shape "
            "but leaves OpenRouter cost exposure in place."
        ),
        "",
        "## Security And Cost Implications",
        "",
        (
            "- Do not copy Codex auth tokens into Zone 4 YAML or logs. This "
            "probe records only presence or absence."
        ),
        (
            "- Path A spends through the OpenAI API key, not through a paid "
            "Codex account. It needs normal API-budget tracking."
        ),
        (
            "- Path B may use Codex subscription/auth state, but Zone 4 would "
            "need a subprocess adapter before PydanticAI agents could use it."
        ),
        (
            "- Path C avoids new provider work but does not address the "
            "OpenRouter exposure that motivated this spike."
        ),
    ]

    if probe.codex_exec_probe is not None:
        result = probe.codex_exec_probe
        lines.extend(
            [
                "",
                "## Codex Exec Probe",
                "",
                f"- Skipped: {result.skipped}",
                f"- Success: {result.success}",
                f"- Exit code: {result.exit_code}",
                f"- Error class: `{result.error_class or '<none>'}`",
                f"- Final text: `{_redact(result.final_text or '<none>')}`",
            ]
        )
        if result.stderr:
            lines.append(f"- Stderr snippet: `{_redact(result.stderr[:300])}`")

    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--live-codex-exec", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    args = parser.parse_args(argv)

    probe = inspect_local_codex_environment(codex_binary_name=args.codex_binary)
    live_binary = probe.codex_binary or args.codex_binary
    codex_exec_probe = run_codex_exec_probe(
        codex_binary=live_binary,
        live=args.live_codex_exec,
        timeout_seconds=args.timeout_seconds,
    )
    probe = CodexZone4ProviderProbe(
        codex_binary=probe.codex_binary,
        codex_version=probe.codex_version,
        has_codex_cli=probe.has_codex_cli,
        has_codex_auth_json=probe.has_codex_auth_json,
        has_codex_api_key=probe.has_codex_api_key,
        has_openai_api_key=probe.has_openai_api_key,
        pydantic_openai_import_ok=probe.pydantic_openai_import_ok,
        repo_codex_backend_present=probe.repo_codex_backend_present,
        recommended_path=probe.recommended_path,
        codex_exec_probe=codex_exec_probe,
    )

    markdown = render_markdown(probe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    sys.stdout.write(f"wrote {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
