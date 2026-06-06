"""Issue #79 -- Self-registration manager for cross-machine coordination.

Handles automatic registration of this agent instance into the PeerRegistry,
periodic heartbeat emission, and graceful deregistration on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass

from . import model_defaults  # P0.01 canonical default-model constants
from .peer_registry import PeerMetadata, PeerRecord, PeerRegistry, PeerStatus

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistrationConfig:
    """Identity of this agent instance."""

    machine: str
    branch: str
    model: str
    version: str
    capabilities: list[str]

    @classmethod
    def from_environment(cls) -> RegistrationConfig:
        """Build config from env vars and git metadata."""
        machine = os.environ.get("BUMBA_MACHINE_NAME", os.uname().nodename)
        model = os.environ.get("BUMBA_MODEL", model_defaults.DEFAULT_REGISTRATION_MODEL)
        version = os.environ.get("BUMBA_VERSION", "0.0.0")

        # Try to read current git branch
        branch = os.environ.get("BUMBA_BRANCH", "")
        if not branch:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                branch = result.stdout.strip() or "unknown"
            except Exception:
                branch = "unknown"

        caps_raw = os.environ.get("BUMBA_CAPABILITIES", "")
        capabilities = [c.strip() for c in caps_raw.split(",") if c.strip()] if caps_raw else []

        return cls(
            machine=machine,
            branch=branch,
            model=model,
            version=version,
            capabilities=capabilities,
        )


class PeerRegistrationManager:
    """Manages this agent's lifecycle in the peer registry.

    Call ``start()`` after the event loop is running and ``stop()`` during
    shutdown.  The manager registers itself, emits periodic heartbeats,
    and deregisters on stop.
    """

    def __init__(
        self,
        registry: PeerRegistry,
        config: RegistrationConfig,
    ) -> None:
        self._registry = registry
        self._config = config
        self._peer_id = uuid.uuid4().hex[:16]
        self._heartbeat_task: asyncio.Task | None = None

    # -- public API --------------------------------------------------

    @property
    def self_peer_id(self) -> str:
        return self._peer_id

    async def start(self) -> None:
        """Register self and begin heartbeat loop."""
        now = time.time()
        record = PeerRecord(
            peer_id=self._peer_id,
            name=f"{self._config.machine}/{self._config.branch}",
            status=PeerStatus.ONLINE,
            metadata=PeerMetadata(
                machine=self._config.machine,
                branch=self._config.branch,
                model=self._config.model,
                version=self._config.version,
                capabilities=list(self._config.capabilities),
            ),
            last_heartbeat=now,
            registered_at=now,
        )
        self._registry.register(record)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        log.info("PeerRegistrationManager started (peer_id=%s)", self._peer_id)

    async def stop(self) -> None:
        """Cancel heartbeat and deregister self."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        self._registry.deregister(self._peer_id)
        log.info("PeerRegistrationManager stopped (peer_id=%s)", self._peer_id)

    # -- internal ----------------------------------------------------

    async def _heartbeat_loop(self, interval: float = 60.0) -> None:
        """Periodically update heartbeat timestamp."""
        try:
            while True:
                await asyncio.sleep(interval)
                self._registry.update_heartbeat(self._peer_id)
                log.debug("Heartbeat sent for peer %s", self._peer_id)
        except asyncio.CancelledError:
            return
