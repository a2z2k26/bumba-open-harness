"""
LIVITY Agent Lifecycle State Machine.

Manages the lifecycle of agents from spawn to completion with event-driven
state transitions, configurable timeouts, and state history tracking.

States: IDLE → SPAWNING → ACTIVE → VALIDATING → COMPLETING → COMPLETED
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Callable


class AgentState(str, Enum):
    """Agent lifecycle states."""
    IDLE = "idle"
    SPAWNING = "spawning"
    ACTIVE = "active"
    VALIDATING = "validating"
    COMPLETING = "completing"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class StateTransition:
    """Record of a state transition event."""
    fromState: AgentState
    toState: AgentState
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentLifecycleConfig:
    """Configuration for agent lifecycle timeouts and behavior."""
    spawnTimeoutSeconds: float = 30.0
    activeTimeoutSeconds: float = 300.0
    validatingTimeoutSeconds: float = 60.0
    completingTimeoutSeconds: float = 30.0
    enableHistoryTracking: bool = True


class AgentLifecycleFSM:
    """
    Finite state machine for agent lifecycle management.

    Manages state transitions, enforces timeout constraints, and tracks history.
    """

    def __init__(
        self,
        agent_id: str,
        config: Optional[AgentLifecycleConfig] = None,
    ):
        """
        Initialize the FSM.

        Args:
            agent_id: Unique identifier for the agent
            config: Lifecycle configuration (uses defaults if not provided)
        """
        self.agent_id = agent_id
        self.config = config or AgentLifecycleConfig()
        self.current_state = AgentState.IDLE
        self.state_entered_at = datetime.now(timezone.utc)
        self.history: List[StateTransition] = []
        self._transition_callbacks: Dict[str, List[Callable]] = {}

    def register_transition_callback(
        self, from_state: AgentState, to_state: AgentState, callback: Callable
    ) -> None:
        """Register a callback to be invoked on specific state transitions."""
        key = f"{from_state.value}->{to_state.value}"
        if key not in self._transition_callbacks:
            self._transition_callbacks[key] = []
        self._transition_callbacks[key].append(callback)

    def _invoke_callbacks(self, from_state: AgentState, to_state: AgentState) -> None:
        """Invoke any registered callbacks for this transition."""
        key = f"{from_state.value}->{to_state.value}"
        if key in self._transition_callbacks:
            for callback in self._transition_callbacks[key]:
                try:
                    callback(self)
                except Exception:
                    # Log but don't fail on callback errors
                    pass

    def spawn(self) -> bool:
        """Transition from IDLE to SPAWNING. Returns True if successful."""
        if self.current_state != AgentState.IDLE:
            return False
        return self._transition_to(AgentState.SPAWNING, event="spawn")

    def activate(self) -> bool:
        """Transition from SPAWNING to ACTIVE. Returns True if successful."""
        if self.current_state != AgentState.SPAWNING:
            return False
        return self._transition_to(AgentState.ACTIVE, event="activate")

    def begin_validation(self) -> bool:
        """Transition from ACTIVE to VALIDATING. Returns True if successful."""
        if self.current_state != AgentState.ACTIVE:
            return False
        return self._transition_to(AgentState.VALIDATING, event="begin_validation")

    def begin_completion(self) -> bool:
        """Transition from VALIDATING to COMPLETING. Returns True if successful."""
        if self.current_state != AgentState.VALIDATING:
            return False
        return self._transition_to(AgentState.COMPLETING, event="begin_completion")

    def complete(self) -> bool:
        """Transition from COMPLETING to COMPLETED. Returns True if successful."""
        if self.current_state != AgentState.COMPLETING:
            return False
        return self._transition_to(AgentState.COMPLETED, event="complete")

    def error(self, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Transition to ERROR state from any state. Returns True if successful."""
        if self.current_state == AgentState.ERROR or self.current_state == AgentState.COMPLETED:
            return False
        return self._transition_to(AgentState.ERROR, event="error", metadata=metadata or {})

    def cancel(self) -> bool:
        """Transition to CANCELLED state from any non-terminal state."""
        if self.current_state in (AgentState.COMPLETED, AgentState.CANCELLED):
            return False
        return self._transition_to(AgentState.CANCELLED, event="cancel")

    def _transition_to(
        self,
        new_state: AgentState,
        event: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Internal method to perform a state transition.

        Returns True if successful, False if transition is invalid.
        """
        old_state = self.current_state

        # Record the transition
        transition = StateTransition(
            fromState=old_state,
            toState=new_state,
            event=event,
            metadata=metadata or {},
        )

        if self.config.enableHistoryTracking:
            self.history.append(transition)

        self.current_state = new_state
        self.state_entered_at = datetime.now(timezone.utc)

        # Invoke callbacks
        self._invoke_callbacks(old_state, new_state)

        return True

    def is_in_timeout(self) -> bool:
        """Check if the current state has exceeded its timeout."""
        if self.current_state == AgentState.IDLE:
            return False
        if self.current_state == AgentState.COMPLETED:
            return False
        if self.current_state == AgentState.CANCELLED:
            return False

        timeout_map = {
            AgentState.SPAWNING: self.config.spawnTimeoutSeconds,
            AgentState.ACTIVE: self.config.activeTimeoutSeconds,
            AgentState.VALIDATING: self.config.validatingTimeoutSeconds,
            AgentState.COMPLETING: self.config.completingTimeoutSeconds,
        }

        if self.current_state not in timeout_map:
            return False

        timeout = timeout_map[self.current_state]
        elapsed = (datetime.now(timezone.utc) - self.state_entered_at).total_seconds()
        return elapsed > timeout

    def time_in_current_state(self) -> float:
        """Return seconds elapsed in the current state."""
        return (datetime.now(timezone.utc) - self.state_entered_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize FSM state to a dictionary."""
        return {
            "agentId": self.agent_id,
            "currentState": self.current_state.value,
            "stateEnteredAt": self.state_entered_at.isoformat(),
            "timeInCurrentState": self.time_in_current_state(),
            "isInTimeout": self.is_in_timeout(),
            "historyCount": len(self.history),
            "history": [
                {
                    "fromState": t.fromState.value,
                    "toState": t.toState.value,
                    "timestamp": t.timestamp,
                    "event": t.event,
                    "metadata": t.metadata,
                }
                for t in self.history
            ] if self.config.enableHistoryTracking else [],
        }

    def get_history(self) -> List[StateTransition]:
        """Return the state transition history."""
        return self.history.copy()

    def reset(self) -> None:
        """Reset FSM to IDLE state."""
        self._transition_to(AgentState.IDLE, event="reset")
