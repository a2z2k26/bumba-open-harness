"""Tests for LIVITY agent lifecycle state machine."""

import time

from bridge.agent_lifecycle import (
    AgentLifecycleFSM,
    AgentState,
    AgentLifecycleConfig,
)


class TestAgentStateEnum:
    """Test the AgentState enum."""

    def test_all_states_defined(self):
        """Verify all required states are defined."""
        states = [s.value for s in AgentState]
        expected = ["idle", "spawning", "active", "validating", "completing", "completed", "error", "cancelled"]
        for state in expected:
            assert state in states

    def test_state_values(self):
        """Verify state values are lowercase strings."""
        assert AgentState.IDLE.value == "idle"
        assert AgentState.SPAWNING.value == "spawning"
        assert AgentState.ACTIVE.value == "active"
        assert AgentState.COMPLETED.value == "completed"


class TestAgentLifecycleConfig:
    """Test configuration."""

    def test_default_config(self):
        """Default config has reasonable timeout values."""
        config = AgentLifecycleConfig()
        assert config.spawnTimeoutSeconds == 30.0
        assert config.activeTimeoutSeconds == 300.0
        assert config.validatingTimeoutSeconds == 60.0
        assert config.completingTimeoutSeconds == 30.0
        assert config.enableHistoryTracking is True

    def test_custom_config(self):
        """Can customize configuration."""
        config = AgentLifecycleConfig(
            spawnTimeoutSeconds=60.0,
            activeTimeoutSeconds=600.0,
            enableHistoryTracking=False,
        )
        assert config.spawnTimeoutSeconds == 60.0
        assert config.activeTimeoutSeconds == 600.0
        assert config.enableHistoryTracking is False


class TestAgentLifecycleFSMInitialization:
    """Test FSM initialization."""

    def test_create_fsm(self):
        """Can create an FSM instance."""
        fsm = AgentLifecycleFSM(agent_id="test-agent-1")
        assert fsm.agent_id == "test-agent-1"
        assert fsm.current_state == AgentState.IDLE

    def test_fsm_with_custom_config(self):
        """Can create FSM with custom configuration."""
        config = AgentLifecycleConfig(spawnTimeoutSeconds=20.0)
        fsm = AgentLifecycleFSM(agent_id="test-agent-2", config=config)
        assert fsm.config.spawnTimeoutSeconds == 20.0


class TestAgentLifecycleTransitions:
    """Test state transitions following the main lifecycle."""

    def test_spawn_from_idle(self):
        """Can transition from IDLE to SPAWNING."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        assert fsm.spawn() is True
        assert fsm.current_state == AgentState.SPAWNING

    def test_activate_from_spawning(self):
        """Can transition from SPAWNING to ACTIVE."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        assert fsm.activate() is True
        assert fsm.current_state == AgentState.ACTIVE

    def test_begin_validation_from_active(self):
        """Can transition from ACTIVE to VALIDATING."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        assert fsm.begin_validation() is True
        assert fsm.current_state == AgentState.VALIDATING

    def test_begin_completion_from_validating(self):
        """Can transition from VALIDATING to COMPLETING."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        fsm.begin_validation()
        assert fsm.begin_completion() is True
        assert fsm.current_state == AgentState.COMPLETING

    def test_complete_from_completing(self):
        """Can transition from COMPLETING to COMPLETED."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        fsm.begin_validation()
        fsm.begin_completion()
        assert fsm.complete() is True
        assert fsm.current_state == AgentState.COMPLETED

    def test_full_happy_path(self):
        """Happy path: IDLE → SPAWNING → ACTIVE → VALIDATING → COMPLETING → COMPLETED."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        assert fsm.current_state == AgentState.IDLE

        assert fsm.spawn() is True
        assert fsm.current_state == AgentState.SPAWNING

        assert fsm.activate() is True
        assert fsm.current_state == AgentState.ACTIVE

        assert fsm.begin_validation() is True
        assert fsm.current_state == AgentState.VALIDATING

        assert fsm.begin_completion() is True
        assert fsm.current_state == AgentState.COMPLETING

        assert fsm.complete() is True
        assert fsm.current_state == AgentState.COMPLETED


class TestAgentLifecycleInvalidTransitions:
    """Test that invalid transitions are rejected."""

    def test_cannot_spawn_twice(self):
        """Cannot transition from SPAWNING to SPAWNING."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        assert fsm.spawn() is False

    def test_cannot_activate_from_idle(self):
        """Cannot transition from IDLE directly to ACTIVE."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        assert fsm.activate() is False

    def test_cannot_validate_from_spawning(self):
        """Cannot skip ACTIVE state."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        assert fsm.begin_validation() is False

    def test_cannot_complete_from_active(self):
        """Cannot skip intermediate states."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        assert fsm.complete() is False


class TestAgentLifecycleErrorHandling:
    """Test error state transitions."""

    def test_error_from_any_non_terminal_state(self):
        """Can transition to ERROR from any non-terminal state."""
        fsm1 = AgentLifecycleFSM(agent_id="test1")
        assert fsm1.error() is True
        assert fsm1.current_state == AgentState.ERROR

        fsm2 = AgentLifecycleFSM(agent_id="test2")
        fsm2.spawn()
        assert fsm2.error() is True
        assert fsm2.current_state == AgentState.ERROR

    def test_cannot_error_from_completed(self):
        """Cannot transition to ERROR from COMPLETED."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        fsm.begin_validation()
        fsm.begin_completion()
        fsm.complete()
        assert fsm.error() is False
        assert fsm.current_state == AgentState.COMPLETED

    def test_error_with_metadata(self):
        """Can attach metadata to error transition."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.error(metadata={"reason": "timeout", "duration": 30})
        assert fsm.current_state == AgentState.ERROR


class TestAgentLifecycleCancellation:
    """Test cancellation."""

    def test_cancel_from_idle(self):
        """Can cancel from IDLE."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        assert fsm.cancel() is True
        assert fsm.current_state == AgentState.CANCELLED

    def test_cancel_from_active(self):
        """Can cancel from ACTIVE."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        assert fsm.cancel() is True
        assert fsm.current_state == AgentState.CANCELLED

    def test_cannot_cancel_completed(self):
        """Cannot cancel a completed agent."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        fsm.begin_validation()
        fsm.begin_completion()
        fsm.complete()
        assert fsm.cancel() is False


class TestAgentLifecycleTimeouts:
    """Test timeout detection."""

    def test_idle_has_no_timeout(self):
        """IDLE state has no timeout."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        assert fsm.is_in_timeout() is False

    def test_completed_has_no_timeout(self):
        """COMPLETED state has no timeout."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        fsm.begin_validation()
        fsm.begin_completion()
        fsm.complete()
        assert fsm.is_in_timeout() is False

    def test_spawning_timeout_detection(self):
        """Detects when SPAWNING exceeds timeout."""
        config = AgentLifecycleConfig(spawnTimeoutSeconds=0.1)
        fsm = AgentLifecycleFSM(agent_id="test-agent", config=config)
        fsm.spawn()
        time.sleep(0.15)
        assert fsm.is_in_timeout() is True

    def test_active_timeout_detection(self):
        """Detects when ACTIVE exceeds timeout."""
        config = AgentLifecycleConfig(activeTimeoutSeconds=0.1)
        fsm = AgentLifecycleFSM(agent_id="test-agent", config=config)
        fsm.spawn()
        fsm.activate()
        time.sleep(0.15)
        assert fsm.is_in_timeout() is True

    def test_time_in_current_state(self):
        """Can measure time spent in current state."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        time.sleep(0.1)
        elapsed = fsm.time_in_current_state()
        assert elapsed >= 0.1


class TestAgentLifecycleHistoryTracking:
    """Test state transition history."""

    def test_history_tracking_enabled(self):
        """History is tracked when enabled."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        fsm.begin_validation()

        history = fsm.get_history()
        assert len(history) == 3
        assert history[0].toState == AgentState.SPAWNING
        assert history[1].toState == AgentState.ACTIVE
        assert history[2].toState == AgentState.VALIDATING

    def test_history_tracking_disabled(self):
        """History can be disabled via config."""
        config = AgentLifecycleConfig(enableHistoryTracking=False)
        fsm = AgentLifecycleFSM(agent_id="test-agent", config=config)
        fsm.spawn()
        fsm.activate()

        history = fsm.get_history()
        assert len(history) == 0

    def test_transition_metadata_in_history(self):
        """Transition metadata is recorded in history."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.error(metadata={"reason": "spawn failed"})

        history = fsm.get_history()
        assert len(history) == 1
        assert history[0].metadata["reason"] == "spawn failed"


class TestAgentLifecycleCallbacks:
    """Test transition callbacks."""

    def test_register_callback(self):
        """Can register a callback for a state transition."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        called = []

        def on_spawn(_):
            called.append("spawned")

        fsm.register_transition_callback(AgentState.IDLE, AgentState.SPAWNING, on_spawn)
        fsm.spawn()

        assert "spawned" in called

    def test_multiple_callbacks(self):
        """Multiple callbacks for same transition all get called."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        calls = []

        def callback1(_):
            calls.append(1)

        def callback2(_):
            calls.append(2)

        fsm.register_transition_callback(AgentState.IDLE, AgentState.SPAWNING, callback1)
        fsm.register_transition_callback(AgentState.IDLE, AgentState.SPAWNING, callback2)
        fsm.spawn()

        assert calls == [1, 2]


class TestAgentLifecycleSerialization:
    """Test FSM serialization."""

    def test_to_dict(self):
        """FSM can be serialized to dict."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()

        data = fsm.to_dict()
        assert data["agentId"] == "test-agent"
        assert data["currentState"] == "active"
        assert "stateEnteredAt" in data
        assert "timeInCurrentState" in data
        assert data["isInTimeout"] is False

    def test_to_dict_with_history(self):
        """Serialization includes history."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()

        data = fsm.to_dict()
        assert data["historyCount"] == 2
        assert len(data["history"]) == 2


class TestAgentLifecycleReset:
    """Test FSM reset."""

    def test_reset_to_idle(self):
        """Can reset FSM to IDLE state."""
        fsm = AgentLifecycleFSM(agent_id="test-agent")
        fsm.spawn()
        fsm.activate()
        fsm.reset()

        assert fsm.current_state == AgentState.IDLE
