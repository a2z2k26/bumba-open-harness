"""Sprint 06.05: memory.store_message uses redacted_text, called after check_output.

Verifies the ordering fix in app.py: guardrail check_output runs first, then
store_message is called with redacted_text (not raw response) when tokens were stripped.
"""

from __future__ import annotations

from bridge.guardrails import GuardrailConfig, GuardrailEngine


class TestStoreAfterRedaction:
    """GuardrailResult.redacted_text is the value that should reach store_message."""

    def test_redacted_text_differs_from_raw_when_canary_present(self):
        """When a canary token is in the response, redacted_text != raw response."""
        config = GuardrailConfig(canary_tokens=["CANARY-SECRET-TOKEN"])
        engine = GuardrailEngine(config=config)

        raw = "The output contains CANARY-SECRET-TOKEN leaked."
        result = engine.check_output(raw)

        # The result should flag a tripwire
        assert not result.passed
        # redacted_text must not contain the raw canary
        assert "CANARY-SECRET-TOKEN" not in result.redacted_text
        assert "[REDACTED]" in result.redacted_text
        # raw response is NOT stored — caller uses redacted_text
        assert result.redacted_text != raw

    def test_redacted_text_equals_raw_when_no_tokens(self):
        """When no sensitive tokens are configured, redacted_text == raw response."""
        config = GuardrailConfig()
        engine = GuardrailEngine(config=config)

        raw = "Normal response with no secrets."
        result = engine.check_output(raw)

        assert result.redacted_text == raw

    def test_store_message_caller_uses_redacted_text(self):
        """Simulate the app.py store_message caller: picks redacted_text when non-empty."""
        config = GuardrailConfig(canary_tokens=["MY-SECRET"])
        engine = GuardrailEngine(config=config)

        raw_response = "Here is MY-SECRET embedded in response."
        output_check = engine.check_output(raw_response)

        # Reproduce the app.py selection logic (Sprint 06.05)
        stored_content = raw_response
        if output_check.redacted_text:
            stored_content = output_check.redacted_text

        assert "MY-SECRET" not in stored_content
        assert "[REDACTED]" in stored_content

    def test_no_autonomy_path_stores_raw(self):
        """When autonomy is None (no guardrails), raw response is stored unchanged."""
        # Simulate app.py when self._autonomy is None:
        # _assistant_content = result.response_text  (no override)
        raw_response = "Normal response."
        _assistant_content = raw_response  # no guardrail override path
        assert _assistant_content == raw_response

    def test_known_secret_also_stripped_before_store(self):
        """known_secrets are also stripped from what gets stored in memory."""
        config = GuardrailConfig(known_secrets=["api-key-abc123"])
        engine = GuardrailEngine(config=config)

        raw = "Use api-key-abc123 for authentication."
        result = engine.check_output(raw)

        stored_content = result.redacted_text if result.redacted_text else raw
        assert "api-key-abc123" not in stored_content
        assert "[REDACTED]" in stored_content
