"""VAPI voice assistant client — real HTTP implementation.

Provides aiohttp-backed HTTP calls to the VAPI REST API.
Lazy session creation follows the same pattern as tts_engine.py / stt_engine.py.

See docs/vapi-operator-handoff.md for operator setup instructions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, AsyncGenerator

import aiohttp

from bridge import model_defaults  # P0.04 canonical default-model constants

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

VAPI_BASE_URL = "https://api.vapi.ai"


class VAPIClient:
    """Client for VAPI voice assistant API.

    Uses a lazy aiohttp.ClientSession (created on first request, reused
    across calls, closed via close()). All methods that hit the network
    require is_configured == True (i.e. a non-empty api_key).
    """

    def __init__(
        self,
        api_key: str = "",
        webhook_url: str = "",
        vapi_assistant_id_receptionist: str = "",
    ) -> None:
        """Initialize the VAPI client.

        Args:
            api_key: VAPI API key (from VAPI dashboard).
            webhook_url: URL where VAPI sends call events.
            vapi_assistant_id_receptionist: VAPI assistant ID for the
                receptionist, used when triggering outbound calls.
        """
        self._api_key = api_key
        self._webhook_url = webhook_url
        self._vapi_assistant_id_receptionist = vapi_assistant_id_receptionist
        self._session: aiohttp.ClientSession | None = None

    @property
    def is_configured(self) -> bool:
        """Return True if the client has valid credentials."""
        return bool(self._api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return (or lazily create) the shared aiohttp session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=5, keepalive_timeout=30, ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=30.0),
            )
        return self._session

    async def close(self) -> None:
        """Close the shared HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def set_tool_handler(self, handler: object) -> None:
        """Wire the department tool handler used to dispatch function-call events.

        Sprint P8.3 / audit M-4 (#1749): replaces the prior direct write
        to the VAPIClient ``_tool_handler`` private attribute from
        ``BridgeApp._initialize``. Wiring through this setter keeps the
        contract operator-visible via ``WIRING_MANIFEST`` rather than
        invisibly assigning a private attribute from another module.

        ``_handle_function_call`` continues to read the wire via
        ``getattr(self, "_tool_handler", None)`` so the function-call path
        works whether the setter has been called yet or not.
        """
        self._tool_handler = handler

    async def create_assistant(self, config: dict) -> str:
        """Create a VAPI assistant and return its ID.

        Args:
            config: Assistant configuration dict sent as the POST body.

        Returns:
            The VAPI assistant ID string.

        Raises:
            ValueError: If api_key is empty.
            aiohttp.ClientError: On HTTP-level failure.
        """
        if not self.is_configured:
            raise ValueError(
                "VAPI api_key is not configured. "
                "Add vapi_api_key to .secrets before calling create_assistant()."
            )

        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{VAPI_BASE_URL}/assistant"

        async with session.post(url, json=config, headers=headers) as resp:
            if resp.status not in (200, 201):
                body = await resp.text()
                logger.error(
                    "VAPI create_assistant failed status=%d body=%s",
                    resp.status,
                    body[:500],
                )
                resp.raise_for_status()

            data: dict = await resp.json()

        assistant_id: str = data.get("id", "")
        logger.info("VAPI assistant created: id=%s name=%s", assistant_id, config.get("name"))
        return assistant_id

    async def handle_webhook(self, event_type: str, payload: dict) -> dict:
        """Route an inbound VAPI webhook event to the appropriate handler.

        Args:
            event_type: The VAPI event type string (e.g. "status-update").
            payload: The full webhook payload dict.

        Returns:
            Response dict to send back to VAPI (may be empty).
        """
        handlers = {
            "assistant-request": self._handle_assistant_request,
            "function-call": self._handle_function_call,
            "status-update": self._handle_status_update,
            "end-of-call-report": self._handle_end_of_call_report,
            "hang": self._handle_hang,
            "transcript": self._handle_transcript,
        }

        handler = handlers.get(event_type)
        if handler is None:
            logger.warning("VAPI webhook: unknown event_type=%s", event_type)
            return {}

        return await handler(payload)

    # ------------------------------------------------------------------
    # Webhook sub-handlers
    # ------------------------------------------------------------------

    async def _handle_assistant_request(self, payload: dict) -> dict:
        """Respond to VAPI assistant-request with a minimal assistant config."""
        logger.info("VAPI assistant-request received: %s", payload.get("call", {}).get("id"))
        return {
            "assistant": {
                "name": "Bumba Receptionist",
                "model": {
                    "provider": "anthropic",
                    # Default sourced from canonical constant (P0.04);
                    # see model_defaults.DEFAULT_VOICE_MODEL for the value.
                    "model": model_defaults.DEFAULT_VOICE_MODEL,
                },
                "firstMessage": "Hi, Bumba here, how can I help?",
                "serverUrl": self._webhook_url,
            }
        }

    async def _handle_function_call(self, payload: dict) -> dict:
        """Dispatch a VAPI function-call event to DepartmentToolHandler."""
        function_call = payload.get("functionCall", {})
        tool_name: str = function_call.get("name", "")
        parameters: dict = function_call.get("parameters", {})

        # DepartmentToolHandler is wired at runtime via app.py when voice is
        # enabled. If it is not present, log and return an error result.
        tool_handler = getattr(self, "_tool_handler", None)
        if tool_handler is None:
            logger.warning("VAPI function-call: no tool handler wired for tool=%s", tool_name)
            return {"result": {"error": "Tool handler not available"}}

        # Department is inferred from context when available; fall back to "receptionist".
        department = payload.get("call", {}).get("assistantId", "receptionist")
        result = await tool_handler.handle_tool_call(department, tool_name, parameters)
        return {"result": result}

    async def _handle_status_update(self, payload: dict) -> dict:
        status = payload.get("status", "unknown")
        call_id = payload.get("call", {}).get("id", "unknown")
        logger.info("VAPI status-update: call_id=%s status=%s", call_id, status)
        return {}

    async def _handle_end_of_call_report(self, payload: dict) -> dict:
        call_id = payload.get("call", {}).get("id", "unknown")
        summary = payload.get("summary", "")
        logger.info(
            "VAPI end-of-call-report: call_id=%s summary=%s",
            call_id,
            summary[:200] if summary else "(none)",
        )
        return {}

    async def _handle_hang(self, payload: dict) -> dict:
        call_id = payload.get("call", {}).get("id", "unknown")
        logger.info("VAPI hang: call_id=%s", call_id)
        return {}

    async def _handle_transcript(self, payload: dict) -> dict:
        # Real-time transcription chunks — ignored for now (D1.7c territory).
        return {}

    # ------------------------------------------------------------------
    # Streaming LLM (D1.7c territory — stub)
    # ------------------------------------------------------------------

    async def stream_llm_response(
        self, conversation: list, context: str
    ) -> AsyncGenerator[str, None]:
        """Stream LLM responses for VAPI's custom LLM endpoint.

        Full implementation is D1.7c territory. Yields a single placeholder
        chunk so callers can iterate without errors.

        Yields:
            Text chunks of the LLM response.
        """
        yield "Voice LLM streaming not yet implemented"

    # ------------------------------------------------------------------
    # Outbound calls
    # ------------------------------------------------------------------

    async def trigger_outbound_call(self, phone: str, context: str) -> str:
        """Initiate an outbound call via VAPI.

        Args:
            phone: Target phone number in E.164 format (e.g. "+15551234567").
            context: Context string describing the purpose of the call.

        Returns:
            The VAPI call ID string.

        Raises:
            ValueError: If api_key or vapi_assistant_id_receptionist is empty.
            aiohttp.ClientError: On HTTP-level failure.
        """
        if not self.is_configured:
            raise ValueError(
                "VAPI api_key is not configured. "
                "Add vapi_api_key to .secrets before triggering outbound calls."
            )
        if not self._vapi_assistant_id_receptionist:
            raise ValueError(
                "vapi_assistant_id_receptionist is not configured. "
                "Run squad provisioning before triggering outbound calls."
            )

        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "assistantId": self._vapi_assistant_id_receptionist,
            "customer": {"number": phone},
        }
        if context:
            body["assistantOverrides"] = {
                "variableValues": {"context": context}
            }

        url = f"{VAPI_BASE_URL}/call"
        async with session.post(url, json=body, headers=headers) as resp:
            if resp.status not in (200, 201):
                err_body = await resp.text()
                logger.error(
                    "VAPI trigger_outbound_call failed status=%d body=%s",
                    resp.status,
                    err_body[:500],
                )
                resp.raise_for_status()

            data: dict = await resp.json()

        call_id: str = data.get("id", "")
        logger.info("VAPI outbound call triggered: call_id=%s phone=%s", call_id, phone)
        return call_id
