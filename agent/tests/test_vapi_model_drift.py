"""Drift test: VAPI assistant configs must source DEFAULT_VOICE_MODEL (P0.04)."""
import asyncio
import inspect

from bridge import app as bridge_app
from bridge import model_defaults
from bridge import vapi_client as vapi_client_module
from bridge.vapi_client import VAPIClient


def test_assistant_request_uses_canonical_voice_model():
    client = VAPIClient(api_key="", webhook_url="https://example.test/hook")
    payload = {"call": {"id": "test-call"}}
    resp = asyncio.run(client._handle_assistant_request(payload))
    assert resp["assistant"]["model"]["provider"] == "anthropic"
    assert resp["assistant"]["model"]["model"] == model_defaults.DEFAULT_VOICE_MODEL


def test_voice_model_literal_not_hardcoded_in_sources():
    """Both VAPI assistant configs must redirect to the canonical constant,
    not embed the bare model id literal (the actual drift symptom)."""
    literal = '"claude-sonnet-4-5"'
    vapi_src = inspect.getsource(vapi_client_module)
    app_src = inspect.getsource(bridge_app)
    assert literal not in vapi_src, "vapi_client.py still hardcodes the voice model literal"
    assert literal not in app_src, "app.py still hardcodes the voice model literal"


def test_current_voice_model_value_preserved():
    assert model_defaults.DEFAULT_VOICE_MODEL == "claude-sonnet-4-5"
