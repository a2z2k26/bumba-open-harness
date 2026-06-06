"""Tests for multi-provider API key loading."""

from __future__ import annotations

import os
from pathlib import Path


from teams._providers import (
    PROVIDER_ENV_MAP,
    list_available_providers,
    load_provider_keys,
    parse_secrets_file,
)


class TestParseSecretsFile:
    def test_extracts_provider_keys(self, tmp_path: Path):
        secrets = tmp_path / ".secrets"
        secrets.write_text(
            "discord_token=abc123\n"
            "openai_api_key=sk-test-openai\n"
            "google_api_key=key-test-google\n"
            "notion_api_token=secret\n"
            "groq_api_key=gsk-test\n"
        )
        parsed = parse_secrets_file(secrets)
        assert parsed["openai_api_key"] == "sk-test-openai"
        assert parsed["google_api_key"] == "key-test-google"
        assert parsed["groq_api_key"] == "gsk-test"

    def test_handles_missing_file(self, tmp_path: Path):
        result = parse_secrets_file(tmp_path / "nonexistent")
        assert result == {}

    def test_ignores_comments_and_blanks(self, tmp_path: Path):
        secrets = tmp_path / ".secrets"
        secrets.write_text(
            "# This is a comment\n"
            "\n"
            "openai_api_key=sk-test\n"
            "# another comment\n"
            "google_api_key=key-test\n"
        )
        parsed = parse_secrets_file(secrets)
        assert parsed == {
            "openai_api_key": "sk-test",
            "google_api_key": "key-test",
        }


class TestLoadProviderKeys:
    def test_sets_env_vars_for_known_providers(self, tmp_path: Path, monkeypatch):
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)

        secrets = tmp_path / ".secrets"
        secrets.write_text(
            "openai_api_key=sk-openai-value\n"
            "google_api_key=key-google-value\n"
            "groq_api_key=gsk-groq-value\n"
        )

        loaded = load_provider_keys(secrets_path=secrets)

        assert "openai" in loaded
        assert "google" in loaded
        assert "groq" in loaded
        assert os.environ["OPENAI_API_KEY"] == "sk-openai-value"
        assert os.environ["GOOGLE_API_KEY"] == "key-google-value"
        assert os.environ["GROQ_API_KEY"] == "gsk-groq-value"

    def test_no_op_when_no_provider_keys(self, tmp_path: Path, monkeypatch):
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)

        secrets = tmp_path / ".secrets"
        secrets.write_text(
            "discord_token=abc\n"
            "notion_api_token=xyz\n"
        )

        loaded = load_provider_keys(secrets_path=secrets)
        assert loaded == {}

    def test_missing_secrets_file_is_safe(self, tmp_path: Path):
        loaded = load_provider_keys(secrets_path=tmp_path / "missing")
        assert loaded == {}


class TestListAvailableProviders:
    def test_returns_empty_when_no_keys(self, tmp_path: Path, monkeypatch):
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text("discord_token=abc\n")
        load_provider_keys(secrets_path=secrets)
        providers = list_available_providers()
        assert providers == []

    def test_returns_provider_names_when_keys_set(self, tmp_path: Path, monkeypatch):
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text("openai_api_key=sk-test\n")
        load_provider_keys(secrets_path=secrets)
        providers = list_available_providers()
        assert "openai" in providers


class TestOpenRouterProvider:
    """Issue #1072 — OpenRouter is the operator's chosen backplane for
    every Z4 chief and specialist. The Main Agent stays on the free
    Claude OAuth path; everything below it pays through OpenRouter.

    These tests pin the plumbing: the secrets-file key is recognised,
    parses out, and the env var pydantic-ai's OpenRouterProvider reads
    (`OPENROUTER_API_KEY`) is set after ``load_provider_keys``.
    """

    def test_openrouter_key_in_provider_env_map(self) -> None:
        assert PROVIDER_ENV_MAP["openrouter_api_key"] == "OPENROUTER_API_KEY"

    def test_parse_extracts_openrouter_key(self, tmp_path: Path) -> None:
        secrets = tmp_path / ".secrets"
        secrets.write_text(
            "discord_token=abc\n"
            "openrouter_api_key=sk-or-v1-test-value\n"
            "notion_api_token=xyz\n"
        )
        parsed = parse_secrets_file(secrets)
        assert parsed["openrouter_api_key"] == "sk-or-v1-test-value"

    def test_load_sets_openrouter_env_var(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text("openrouter_api_key=sk-or-v1-load-test\n")

        loaded = load_provider_keys(secrets_path=secrets)
        assert "openrouter" in loaded
        assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-load-test"

    def test_openrouter_listed_in_available_providers(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text("openrouter_api_key=sk-or-v1-list-test\n")
        load_provider_keys(secrets_path=secrets)
        providers = list_available_providers()
        assert "openrouter" in providers

    def test_openrouter_absent_when_only_other_keys_set(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text("openai_api_key=sk-openai-only\n")
        load_provider_keys(secrets_path=secrets)
        providers = list_available_providers()
        assert "openrouter" not in providers
        assert "OPENROUTER_API_KEY" not in os.environ


class TestUppercaseEnvVarFormatAccepted:
    """The operator's runtime ``.secrets`` file uses uppercase env-var
    names for provider keys (``OPENAI_API_KEY=...``,
    ``OPENROUTER_API_KEY=...``) while reserving lowercase forms for
    bridge-internal keys (``discord_bot_token``, ``claude_oauth_token``).
    Both forms must be accepted by the loader so the operator never has
    to renumber an existing file.
    """

    def test_uppercase_openrouter_key_loaded(
        self, tmp_path, monkeypatch
    ):
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text("OPENROUTER_API_KEY=sk-or-v1-uppercase\n")
        loaded = load_provider_keys(secrets_path=secrets)
        assert "openrouter" in loaded
        assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-uppercase"

    def test_uppercase_openai_key_loaded(self, tmp_path, monkeypatch):
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text("OPENAI_API_KEY=sk-uppercase-openai\n")
        loaded = load_provider_keys(secrets_path=secrets)
        assert "openai" in loaded
        assert os.environ["OPENAI_API_KEY"] == "sk-uppercase-openai"

    def test_mixed_case_secrets_file_loads_all_known_providers(
        self, tmp_path, monkeypatch
    ):
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text(
            "# Discord credentials\n"
            "discord_bot_token=ignored\n"
            "\n"
            "# Claude OAuth\n"
            "claude_oauth_token=ignored\n"
            "\n"
            "# Provider API keys (uppercase env-var form)\n"
            "OPENAI_API_KEY=sk-openai-mixed\n"
            "GOOGLE_API_KEY=key-google-mixed\n"
            "OPENROUTER_API_KEY=sk-or-v1-mixed\n"
            "\n"
            "# Other operator secrets\n"
            "notion_api_token=ignored\n"
        )
        loaded = load_provider_keys(secrets_path=secrets)
        assert "openai" in loaded
        assert "google" in loaded
        assert "openrouter" in loaded
        assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-mixed"

    def test_lowercase_form_still_works(self, tmp_path, monkeypatch):
        for env_var in PROVIDER_ENV_MAP.values():
            monkeypatch.delenv(env_var, raising=False)
        secrets = tmp_path / ".secrets"
        secrets.write_text("openrouter_api_key=sk-or-v1-lowercase\n")
        loaded = load_provider_keys(secrets_path=secrets)
        assert "openrouter" in loaded
        assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-lowercase"

    def test_last_write_wins_when_both_forms_present(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text(
            "openrouter_api_key=lowercase-value\n"
            "OPENROUTER_API_KEY=uppercase-value\n"
        )
        parsed = parse_secrets_file(secrets)
        assert parsed["openrouter_api_key"] == "uppercase-value"


class TestZ4AnthropicOnlyOnChiefs:
    """#2566 hybrid-fleet contract: Anthropic appears ONLY on chiefs.

    The OLD doctrine (2026-04-30) forbade Anthropic anywhere in Z4 and
    routed everything through OpenRouter. That is OBSOLETE. As of #2566
    (ops chief flipped in #2596; board/design/job_search/qa flipped on
    the fix/2566 branch), the architecture is:

      - All 6 department chiefs run on ``anthropic-oauth:claude-sonnet-4-5``.
        Chiefs REQUIRE tool-calling (delegate / final_result), which
        codex-exec cannot do (it returns prose). Anthropic OAuth gives
        native tool support, subscription-billed, no API key.
      - All workers/specialists run on ``codex-exec:`` (prose only),
        with two surviving canaries (strategy openai:gpt-4o-mini metrics
        analyst). OpenRouter is dead — zero ``openrouter:`` strings remain.

    The true invariant this test now pins: any ``anthropic`` /
    ``claude`` model string in a Z4 YAML must be a CHIEF, never a worker.
    A worker re-introducing Anthropic (cost regression) is the violation
    we catch.
    """

    def test_anthropic_only_appears_on_chiefs(self):
        """Anthropic model strings may live only on the ``chief:`` spec.

        Walk each team YAML, track whether the current ``model:`` line is
        under the ``chief:`` mapping or a ``workers:`` entry, and flag any
        Anthropic/claude model string that lands on a worker.
        """
        from pathlib import Path
        teams_dir = Path(__file__).parent.parent.parent / "config" / "teams"

        offenders = []
        for yaml_path in sorted(teams_dir.glob("*.yaml")):
            in_chief = False
            in_workers = False
            for line_no, line in enumerate(
                yaml_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = line.strip()
                # Section tracking — top-level keys under ``team:`` are
                # indented two spaces; we only need to know whether the
                # nearest preceding section header is chief or workers.
                if stripped.startswith("chief:"):
                    in_chief, in_workers = True, False
                    continue
                if stripped.startswith("workers:"):
                    in_chief, in_workers = False, True
                    continue
                # ``vapi:`` (and any other top-level section) closes both.
                if stripped.endswith(":") and not line.startswith(" " * 4):
                    if not stripped.startswith(("chief:", "workers:")):
                        in_chief = in_workers = False

                if not stripped.startswith("model:"):
                    continue
                lower = stripped.lower()
                if not any(
                    token in lower
                    for token in ("anthropic", "claude-", "/claude")
                ):
                    continue
                # An Anthropic model string under a worker is the violation.
                if in_workers:
                    offenders.append(
                        f"{yaml_path.name}:{line_no}: {stripped} "
                        "(Anthropic on a worker — only chiefs may use it)"
                    )

        assert not offenders, (
            "Z4 workers must not use Anthropic models (#2566: Anthropic is "
            "the chief-only tool-calling tier; workers run codex-exec):\n  "
            + "\n  ".join(offenders)
        )

    def test_all_six_chiefs_are_anthropic_oauth(self):
        """All 6 dept chiefs run anthropic-oauth (#2566 hybrid fleet)."""
        from teams import DepartmentRegistry

        teams_dir = (
            Path(__file__).parent.parent.parent / "config" / "teams"
        )
        registry = DepartmentRegistry.from_directory(teams_dir)
        for department in ("board", "design", "job_search", "ops", "qa", "strategy"):
            manager = registry.get_config(department).manager
            assert manager.model == "anthropic-oauth:claude-sonnet-4-5", (
                f"{department} chief must be anthropic-oauth, got {manager.model}"
            )
            assert manager.adapter == "claude"
