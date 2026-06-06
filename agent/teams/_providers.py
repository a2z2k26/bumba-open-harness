"""Multi-provider API key loader for Zone 4 Pydantic AI teams.

Reads non-Anthropic API keys from the bridge .secrets file and sets
the corresponding environment variables that Pydantic AI provider
clients expect. Called once at bridge startup — no-op if no keys found.

Anthropic is handled by the existing bridge secrets loading path.
This module is strictly additive.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Map from secrets file key suffix → provider name → env var name
# Format: secrets file has e.g. "openai_api_key=sk-..." → sets OPENAI_API_KEY
PROVIDER_ENV_MAP: dict[str, str] = {
    "openai_api_key": "OPENAI_API_KEY",
    "google_api_key": "GOOGLE_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
    "mistral_api_key": "MISTRAL_API_KEY",
    "cohere_api_key": "CO_API_KEY",
    "bedrock_access_key": "AWS_ACCESS_KEY_ID",
    "bedrock_secret_key": "AWS_SECRET_ACCESS_KEY",
    "ollama_base_url": "OLLAMA_HOST",
    # Issue #1072 (2026-04-30): OpenRouter is the operator's chosen
    # backplane for every Z4 chief and specialist. The Main Agent stays
    # on the free Claude OAuth path; everything below it pays through
    # OpenRouter so per-agent model selection (claude / gpt / llama /
    # qwen / mixtral / etc.) is one YAML edit and one billing surface.
    # pydantic-ai's OpenRouterProvider auto-discovers OPENROUTER_API_KEY
    # from the env, so this loader entry is the only Python change
    # needed to enable openrouter: model strings in YAML.
    "openrouter_api_key": "OPENROUTER_API_KEY",
}

# Reverse map: secrets key → provider name
_SECRETS_KEY_TO_PROVIDER: dict[str, str] = {
    "openai_api_key": "openai",
    "google_api_key": "google",
    "groq_api_key": "groq",
    "mistral_api_key": "mistral",
    "cohere_api_key": "cohere",
    "bedrock_access_key": "bedrock",
    "bedrock_secret_key": "bedrock",
    "ollama_base_url": "ollama",
    "openrouter_api_key": "openrouter",
}

_DEFAULT_SECRETS_PATH = Path("/opt/bumba-harness/data/.secrets")


# Reverse map populated at module load: env-var name → canonical secrets-key.
# Lets the parser accept the env-var form (e.g. ``OPENROUTER_API_KEY=...``)
# as well as the original lowercase secrets-key form (``openrouter_api_key=...``).
# Required because the operator's ``.secrets`` file uses uppercase env-var
# names for provider keys (``OPENAI_API_KEY``, ``OPENROUTER_API_KEY``, etc.)
# while early sections use lowercase (``discord_bot_token``,
# ``claude_oauth_token``). Both forms are now accepted; the canonical
# secrets-key form is what gets returned for downstream lookups.
_ENV_VAR_TO_SECRETS_KEY: dict[str, str] = {
    env_var: secrets_key for secrets_key, env_var in PROVIDER_ENV_MAP.items()
}


def parse_secrets_file(secrets_path: Path) -> dict[str, str]:
    """Parse a .secrets file and return only provider API key entries.

    Accepts both naming conventions found in the operator's secrets file:

    - Canonical lowercase secrets-key form: ``openrouter_api_key=sk-...``
    - Env-var form (uppercase): ``OPENROUTER_API_KEY=sk-...``

    Returns a dict of {canonical_secrets_key: value}. Env-var-form keys
    are normalised to their canonical secrets-key form before being
    returned, so downstream callers see exactly one shape regardless of
    how the file was written. Non-provider keys (discord_token,
    notion_api_token, etc.) are excluded.
    """
    if not secrets_path.exists():
        return {}

    result: dict[str, str] = {}
    try:
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key in PROVIDER_ENV_MAP:
                # Canonical lowercase form
                result[key] = value
            elif key in _ENV_VAR_TO_SECRETS_KEY:
                # Uppercase env-var form — normalise to canonical
                canonical = _ENV_VAR_TO_SECRETS_KEY[key]
                result[canonical] = value
    except OSError as e:
        log.warning("Failed to read secrets file %s: %s", secrets_path, e)

    return result


def load_provider_keys(
    secrets_path: Path | None = None,
) -> dict[str, str]:
    """Load non-Anthropic provider API keys and set environment variables.

    Returns a dict of {provider_name: env_var_name} for each key loaded.
    Returns empty dict if no provider keys found or secrets file missing.
    """
    path = secrets_path or _DEFAULT_SECRETS_PATH
    parsed = parse_secrets_file(path)

    loaded: dict[str, str] = {}
    for secrets_key, value in parsed.items():
        env_var = PROVIDER_ENV_MAP.get(secrets_key)
        provider = _SECRETS_KEY_TO_PROVIDER.get(secrets_key)
        if env_var and provider:
            os.environ[env_var] = value
            loaded[provider] = env_var
            log.info("provider_key.loaded provider=%s env_var=%s", provider, env_var)

    if loaded:
        log.info("providers.available count=%d providers=%s", len(loaded), sorted(set(loaded)))
    else:
        log.debug("providers.none_configured (Anthropic-only mode)")

    return loaded


def list_available_providers() -> list[str]:
    """Return list of provider names whose env vars are currently set."""
    available = []
    seen: set[str] = set()
    for secrets_key, env_var in PROVIDER_ENV_MAP.items():
        provider = _SECRETS_KEY_TO_PROVIDER.get(secrets_key)
        if provider and provider not in seen and os.environ.get(env_var):
            available.append(provider)
            seen.add(provider)
    return sorted(available)
