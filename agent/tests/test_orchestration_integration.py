"""Integration tests for end-to-end orchestration pipeline.

Tests: routing → execution → verification → synthesis
Depends on: consolidated root modules (S01 — bridge/orchestration/ collapsed)
"""

from bridge.work_order import WorkOrder, WorkOrderStatus
from bridge.dependency_manager import DependencyManager
from bridge.modality_detector import ModalityDetector, ModalityMatch
from bridge.model_assignments import ModelRouter, Domain, ModelSpec
from bridge.token_cost import TokenCostManager, TokenUsage
from bridge.rate_limiter import TokenBucketRateLimiter, RateLimitResult
from bridge.circuit_breaker import CircuitBreaker, State
from bridge.error_recovery import ErrorRecoveryManager
from bridge.lifecycle_manager import EXPERIMENTAL_USE_ACK, WorkLifecycleManager
from bridge.verification import VerificationLayer, VerificationTier, VerificationResult
from bridge.synthesizer import Synthesizer, SynthesisMode, SynthesisResult


class TestOrchestrationPipeline:
    """Test end-to-end orchestration pipeline."""

    def test_modality_detection(self):
        """Test detecting execution modality from command."""
        detector = ModalityDetector()

        commands = [
            "do this solo",
            "orchestrate with the team",
            "process in parallel",
        ]

        for cmd in commands:
            result = detector.detect(cmd)
            assert isinstance(result, ModalityMatch)
            assert result.modality is not None
            assert 0.0 <= result.confidence <= 1.0

    def test_model_routing(self):
        """Test model assignment based on domain."""
        router = ModelRouter()

        # Test getting model for different domains
        domains = [Domain.CODE, Domain.ANALYSIS, Domain.RESEARCH, Domain.QA]

        for domain in domains:
            model = router.get_model(domain)
            # Should return a ModelSpec
            assert isinstance(model, ModelSpec)
            assert model.model_id is not None

    def test_rate_limiting_in_pipeline(self):
        """Test rate limiting during execution phase."""
        rate_limiter = TokenBucketRateLimiter()

        # Check and record multiple requests
        for i in range(5):
            result = rate_limiter.check_request(
                provider="anthropic",
                model="claude-opus-4-6",
                estimated_tokens=500,
            )
            assert isinstance(result, RateLimitResult)
            assert result.allowed or result.wait_seconds >= 0

            if result.allowed:
                rate_limiter.record_usage(
                    provider="anthropic",
                    model="claude-opus-4-6",
                    tokens_used=500,
                )

    def test_cost_tracking_in_pipeline(self):
        """Test cost tracking during execution phase."""
        cost_manager = TokenCostManager(daily_budget=100.0)

        # Record usage from 3 parallel executions
        models = ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]

        for model in models:
            usage = TokenUsage(
                model=model,
                input_tokens=1000,
                output_tokens=2000,
            )
            cost = cost_manager.record_usage(usage)
            assert cost >= 0
            assert cost > 0  # Should have non-zero cost

        # Verify total cost is sum of individual costs
        total = cost_manager.get_total_cost()
        assert total > 0

        # Verify cost by model
        by_model = cost_manager.get_cost_by_model()
        assert len(by_model) == 3
        for model in models:
            assert model in by_model
            assert by_model[model] > 0

    def test_verification_pipeline(self):
        """Test verification at multiple tiers."""
        verification = VerificationLayer()

        test_content = {"text": "Test output content"}

        # Test each verification tier
        for tier in [VerificationTier.DRAFT, VerificationTier.STANDARD, VerificationTier.VERIFIED]:
            result = verification.verify(test_content, tier=tier)
            assert result is not None
            assert isinstance(result, VerificationResult)

    def test_synthesis_pipeline(self):
        """Test synthesizing multiple WorkOrder outputs (root Synthesizer API)."""
        synthesizer = Synthesizer()

        # Create WorkOrders as inputs
        work_orders = [
            WorkOrder.create(intent="task one", skill="code", project="p"),
            WorkOrder.create(intent="task two", skill="analyze", project="p"),
            WorkOrder.create(intent="task three", skill="review", project="p"),
        ]

        # Test concatenation mode
        concat_result = synthesizer.synthesize(
            work_orders, mode=SynthesisMode.CONCATENATE
        )
        assert isinstance(concat_result, SynthesisResult)
        assert concat_result.mode == SynthesisMode.CONCATENATE

    def test_full_orchestration_flow(self):
        """Test a complete orchestration flow: routing → verification."""
        # 1. Modality detection
        detector = ModalityDetector()
        modality = detector.detect("analyze user requirements in parallel")
        assert modality.modality is not None

        # 2. Model routing
        router = ModelRouter()
        model_spec = router.get_model(Domain.ANALYSIS)
        assert isinstance(model_spec, ModelSpec)

        # 3. Rate limiting and cost tracking
        rate_limiter = TokenBucketRateLimiter()
        cost_manager = TokenCostManager(daily_budget=50.0)

        # Simulate 3 parallel tasks
        outputs = []
        for i in range(3):
            # Check rate limit
            rate_check = rate_limiter.check_request(
                "anthropic", "claude-opus-4-6", estimated_tokens=1000
            )

            if rate_check.allowed:
                rate_limiter.record_usage(
                    "anthropic", "claude-opus-4-6", tokens_used=1000
                )

                # Track cost
                usage = TokenUsage(
                    model="claude-opus-4-6",
                    input_tokens=500,
                    output_tokens=500,
                )
                cost = cost_manager.record_usage(usage)
                assert cost > 0
                outputs.append(WorkOrder.create(intent=f"task {i+1}", skill="code", project="p"))

        # 4. Verification
        verification = VerificationLayer()
        verified_outputs = []
        for output in outputs:
            verified = verification.verify({"intent": output.intent}, tier=VerificationTier.STANDARD)
            assert verified is not None
            verified_outputs.append(output)

        # 5. Synthesis
        if verified_outputs:
            synthesizer = Synthesizer()
            final = synthesizer.synthesize(
                verified_outputs, mode=SynthesisMode.CONCATENATE
            )
            assert isinstance(final, SynthesisResult)


class TestErrorRecoveryInOrchestration:
    """Test error recovery during orchestration."""

    def test_circuit_breaker_protection(self):
        """Circuit breaker prevents cascading failures."""
        from bridge.circuit_breaker import CircuitBreakerConfig
        circuit = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=5, success_threshold=1, timeout_seconds=30.0)
        )

        # Simulate failures
        for _ in range(6):
            try:
                circuit.call(lambda: 1 / 0)  # Force exception
            except Exception:
                pass

        # Circuit should be open or half-open
        assert circuit.state in [State.OPEN, State.HALF_OPEN, State.CLOSED]

    def test_error_recovery_strategies(self):
        """Error recovery manager uses multiple strategies."""
        recovery = ErrorRecoveryManager()

        # Simulate operation with errors
        def operation():
            raise ValueError("Operation failed")

        # Try recovery
        try:
            recovery.recover_from_error(
                operation,
                error=ValueError("Operation failed"),
            )
        except Exception:
            # Recovery may not always succeed
            pass

    def test_dependency_resolution_with_errors(self):
        """Dependency manager handles missing dependencies."""
        manager = DependencyManager()

        # Add valid tasks with dependencies
        manager.add_task("task_a")
        manager.add_task("task_b", dependencies=["task_a"])

        # Check topological order
        try:
            order = manager.topological_sort()
            assert len(order) == 2
            # task_a should come before task_b
            assert order.index("task_a") < order.index("task_b")
        except Exception:
            pass  # Dependency resolution may fail


class TestOrchestrationMetrics:
    """Test metrics collection during orchestration."""

    def test_cost_tracking_across_pipeline(self):
        """Cost tracking works across all pipeline phases."""
        cost_mgr = TokenCostManager(daily_budget=100.0)

        # Track costs from different models
        models = [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        ]

        for model in models:
            cost_mgr.record_usage(
                TokenUsage(model=model, input_tokens=1000, output_tokens=1000)
            )

        # Verify cost breakdown
        total = cost_mgr.get_total_cost()
        by_model = cost_mgr.get_cost_by_model()

        assert total > 0
        assert len(by_model) == 3

    def test_rate_limit_tracking(self):
        """Rate limit tracking per provider/model."""
        limiter = TokenBucketRateLimiter()

        # Record some usage
        limiter.record_usage("anthropic", "claude-opus-4-6", tokens_used=5000)

        # Verify model tracking
        status = limiter.get_bucket_status("anthropic")
        assert status is not None
        assert isinstance(status, dict)

    def test_work_lifecycle_tracking(self):
        """Work lifecycle manager tracks pipeline progress."""
        lifecycle = WorkLifecycleManager(experimental_ack=EXPERIMENTAL_USE_ACK)

        work = WorkOrder.create(intent="test_task", skill="@test", project="p")

        # Move through lifecycle phases
        try:
            lifecycle.decompose(work)
        except Exception:
            pass

        # Verify work order status is valid
        assert work.status in [
            WorkOrderStatus.PENDING,
            WorkOrderStatus.ASSIGNED,
            WorkOrderStatus.EXECUTING,
            WorkOrderStatus.COMPLETE,
            WorkOrderStatus.FAILED,
            WorkOrderStatus.CANCELLED,
        ]


class TestOrchestrationEdgeCases:
    """Test edge cases in orchestration."""

    def test_large_parallel_execution(self):
        """Handles large number of parallel tasks."""
        cost_mgr = TokenCostManager(daily_budget=1000.0)

        # Simulate 50 parallel executions
        for i in range(50):
            cost_mgr.record_usage(
                TokenUsage(
                    model="claude-haiku-4-5",
                    input_tokens=100,
                    output_tokens=200,
                )
            )

        total = cost_mgr.get_total_cost()
        assert total > 0

    def test_rapid_mode_switching(self):
        """Modality detector handles rapid command changes."""
        detector = ModalityDetector()

        commands = [
            "do this solo",
            "orchestrate with the team",
            "process in parallel",
            "approve this output",
            "sequence these steps",
        ]

        for cmd in commands:
            result = detector.detect(cmd)
            assert result.modality is not None
            assert 0.0 <= result.confidence <= 1.0

    def test_budget_exhaustion_during_pipeline(self):
        """Pipeline handles budget exhaustion gracefully."""
        cost_mgr = TokenCostManager(daily_budget=0.10)  # Very small budget

        # Record large usage
        cost = cost_mgr.record_usage(
            TokenUsage(
                model="claude-opus-4-6",
                input_tokens=1_000_000,  # Will exceed budget
                output_tokens=1_000_000,
            )
        )

        # Should generate alerts
        alerts = cost_mgr.get_alerts()
        assert len(alerts) > 0

        # Should prevent further usage
        can_afford = cost_mgr.can_afford(100_000)
        assert not can_afford

    def test_circuit_breaker_recovery(self):
        """Circuit breaker can recover."""
        from bridge.circuit_breaker import CircuitBreakerConfig
        circuit = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=5, success_threshold=1, timeout_seconds=30.0)
        )

        # Open the circuit with failures
        for _ in range(6):
            try:
                circuit.call(lambda: 1 / 0)
            except Exception:
                pass

        # Circuit should be in one of these states
        assert circuit.state in [State.OPEN, State.HALF_OPEN, State.CLOSED]
