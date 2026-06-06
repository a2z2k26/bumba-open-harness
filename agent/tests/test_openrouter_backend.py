"""P5.01 — OpenRouterBackend (subclass of HttpBackend). httpx fully mocked.

Design reconciliation (operator-approved): OpenRouterBackend extends the P3.02
HttpBackend rather than re-implementing the HTTP surface standalone (as the
original issue specced, which predated P3.02). It inherits transport='http',
request(), parse_event(), the capability methods, and usage-cost machinery,
overriding only OpenRouter specifics: auth_env injects OPENROUTER_API_KEY, the
model defaults from config.fallback_openrouter_model, and parse_cost prefers
OpenRouter's reported usage.cost (USD, measured) over token×price.

Premise correction: the real BridgeConfig field is `fallback_openrouter_model`
(= DEFAULT_OPENROUTER_MODEL from P0.04), NOT the `openrouter_default_model` the
issue's _FakeConfig invented.
"""
from __future__ import annotations

from decimal import Decimal

from bridge.backends._protocol import BackendProtocol, StreamEvent
from bridge.backends.http_base import HttpBackend
from bridge.backends.openrouter import OpenRouterBackend


class _FakeConfig:
    openrouter_api_key = "sk-or-test-123"
    fallback_openrouter_model = "deepseek/deepseek-chat"


def _make_backend() -> OpenRouterBackend:
    return OpenRouterBackend(_FakeConfig())


def test_is_httpbackend_subclass():
    assert isinstance(_make_backend(), HttpBackend)


def test_satisfies_backend_protocol():
    assert isinstance(_make_backend(), BackendProtocol)


def test_reports_http_transport():
    assert _make_backend().transport == "http"


def test_model_defaults_from_config():
    backend = _make_backend()
    # request() (inherited) uses the configured default model in the payload.
    from unittest import mock

    fake_resp = mock.Mock()
    fake_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    fake_resp.raise_for_status.return_value = None
    fake_client = mock.MagicMock()
    fake_client.post.return_value = fake_resp
    fake_client.__enter__.return_value = fake_client
    with mock.patch("bridge.backends.http_base.httpx.Client", return_value=fake_client), \
         mock.patch.dict("os.environ", {"BUMBA_ALLOW_LIVE": "1"}):
        backend.request(message="hi")
    _, kwargs = fake_client.post.call_args
    assert kwargs["json"]["model"] == "deepseek/deepseek-chat"


def test_parse_event_assistant_text():
    raw = (
        '{"choices":[{"message":{"role":"assistant","content":"the answer"}}],'
        '"model":"deepseek/deepseek-chat","id":"gen-1"}'
    )
    ev = _make_backend().parse_event(raw)
    assert isinstance(ev, StreamEvent)
    assert ev.text == "the answer"


def test_auth_env_injects_openrouter_api_key():
    assert _make_backend().auth_env() == {"OPENROUTER_API_KEY": "sk-or-test-123"}


def test_auth_env_empty_when_no_key():
    cfg = _FakeConfig()
    cfg.openrouter_api_key = ""
    assert OpenRouterBackend(cfg).auth_env() == {}


def test_parse_cost_measured_from_usage_cost():
    # OpenRouter credit accounts return usage.cost (USD) directly — measured.
    event = {"id": "gen-xyz", "usage": {"cost": 0.000123}}
    cm = _make_backend().parse_cost(event)
    assert cm.source == "measured"
    assert cm.amount_usd == Decimal("0.000123")
    assert cm.backend == "openrouter"
    assert cm.raw_usage_id == "gen-xyz"


def test_parse_cost_unknown_when_no_cost_and_no_pricing():
    # Tokens present but no dollar amount + no configured price → unknown,
    # NOT a measured zero.
    event = {"id": "gen-1", "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    cm = _make_backend().parse_cost(event)
    assert cm.source == "unknown"
    assert cm.amount_usd is None
    assert cm.backend == "openrouter"


def test_capability_honesty_inherited_all_false():
    backend = _make_backend()
    assert backend.supports_tool_calling() is False
    assert backend.supports_mcp_config() is False


def test_shutdown_is_noop():
    assert _make_backend().shutdown() is None
