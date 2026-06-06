"""Tests for the quality gate chain."""

from __future__ import annotations


from bridge.quality_chain import QualityChain, GateLevel, GateCheckResult


def test_gate_level_ordering() -> None:
    assert GateLevel.LINT.value == 1
    assert GateLevel.TYPECHECK.value == 2
    assert GateLevel.TEST.value == 3
    assert GateLevel.SECURITY.value == 4
    assert GateLevel.ARCHITECTURE.value == 5
    assert GateLevel.CODE_REVIEW.value == 6
    assert GateLevel.HUMAN_APPROVAL.value == 7


def test_chain_runs_gates_in_order() -> None:
    results: list[int] = []

    def gate_1(project: str, files: list[str]) -> GateCheckResult:
        results.append(1)
        return GateCheckResult(passed=True, gate_level=GateLevel.LINT)

    def gate_2(project: str, files: list[str]) -> GateCheckResult:
        results.append(2)
        return GateCheckResult(passed=True, gate_level=GateLevel.TYPECHECK)

    chain = QualityChain()
    chain.register(GateLevel.LINT, gate_1)
    chain.register(GateLevel.TYPECHECK, gate_2)
    result = chain.run("project", ["file.py"])
    assert result.passed is True
    assert results == [1, 2]


def test_chain_stops_on_failure() -> None:
    def passing_gate(project: str, files: list[str]) -> GateCheckResult:
        return GateCheckResult(passed=True, gate_level=GateLevel.LINT)

    def failing_gate(project: str, files: list[str]) -> GateCheckResult:
        return GateCheckResult(passed=False, gate_level=GateLevel.TYPECHECK, reason="Type errors found")

    def should_not_run(project: str, files: list[str]) -> GateCheckResult:
        raise AssertionError("This gate should not have run")

    chain = QualityChain()
    chain.register(GateLevel.LINT, passing_gate)
    chain.register(GateLevel.TYPECHECK, failing_gate)
    chain.register(GateLevel.TEST, should_not_run)
    result = chain.run("project", ["file.py"])
    assert result.passed is False
    assert result.failed_at == GateLevel.TYPECHECK
    assert "Type errors" in result.reason


def test_chain_collects_all_results() -> None:
    def gate_1(project: str, files: list[str]) -> GateCheckResult:
        return GateCheckResult(passed=True, gate_level=GateLevel.LINT)

    def gate_2(project: str, files: list[str]) -> GateCheckResult:
        return GateCheckResult(passed=True, gate_level=GateLevel.TYPECHECK)

    chain = QualityChain()
    chain.register(GateLevel.LINT, gate_1)
    chain.register(GateLevel.TYPECHECK, gate_2)
    result = chain.run("project", ["file.py"])
    assert len(result.gate_results) == 2


def test_warning_mode_continues_on_failure() -> None:
    def failing_gate(project: str, files: list[str]) -> GateCheckResult:
        return GateCheckResult(passed=False, gate_level=GateLevel.ARCHITECTURE, reason="Boundary violation")

    chain = QualityChain()
    chain.register(GateLevel.ARCHITECTURE, failing_gate, strict=False)
    result = chain.run("project", ["file.py"])
    assert result.passed is True
    assert len(result.warnings) > 0


def test_empty_chain_passes() -> None:
    chain = QualityChain()
    result = chain.run("project", ["file.py"])
    assert result.passed is True


def test_escalation_detection() -> None:
    def review_gate(project: str, files: list[str]) -> GateCheckResult:
        return GateCheckResult(
            passed=True,
            gate_level=GateLevel.CODE_REVIEW,
            requires_human=True,
            escalation_reason="Architecture changes detected",
        )

    chain = QualityChain()
    chain.register(GateLevel.CODE_REVIEW, review_gate)
    result = chain.run("project", ["file.py"])
    assert result.passed is True
    assert result.requires_human is True
    assert "Architecture changes" in result.escalation_reasons[0]


# ---------------------------------------------------------------------------
# D1.4 tests: chain ordering, short-circuit, soft failure warnings
# ---------------------------------------------------------------------------

def test_run_passes_all_checkers() -> None:
    """All gates pass -> chain result is passed=True."""
    def make_passing(level: GateLevel):
        def gate(project: str, files: list[str]) -> GateCheckResult:
            return GateCheckResult(passed=True, gate_level=level)
        return gate

    chain = QualityChain()
    chain.register(GateLevel.LINT, make_passing(GateLevel.LINT), strict=True)
    chain.register(GateLevel.TYPECHECK, make_passing(GateLevel.TYPECHECK), strict=True)
    chain.register(GateLevel.TEST, make_passing(GateLevel.TEST), strict=True)
    chain.register(GateLevel.SECURITY, make_passing(GateLevel.SECURITY), strict=True)
    chain.register(GateLevel.CODE_REVIEW, make_passing(GateLevel.CODE_REVIEW), strict=False)
    chain.register(GateLevel.HUMAN_APPROVAL, make_passing(GateLevel.HUMAN_APPROVAL), strict=False)
    result = chain.run("my_project", ["main.py"])
    assert result.passed is True
    assert result.failed_at is None
    assert len(result.gate_results) == 6


def test_run_short_circuits_on_hard_failure() -> None:
    """First strict failure stops the chain; subsequent gates do not run."""
    ran: list[str] = []

    def lint_fail(project: str, files: list[str]) -> GateCheckResult:
        ran.append("lint")
        return GateCheckResult(passed=False, gate_level=GateLevel.LINT, reason="lint error")

    def typecheck_pass(project: str, files: list[str]) -> GateCheckResult:
        ran.append("typecheck")
        return GateCheckResult(passed=True, gate_level=GateLevel.TYPECHECK)

    chain = QualityChain()
    chain.register(GateLevel.LINT, lint_fail, strict=True)
    chain.register(GateLevel.TYPECHECK, typecheck_pass, strict=True)
    result = chain.run("proj", [])
    assert result.passed is False
    assert result.failed_at == GateLevel.LINT
    assert "lint" in ran
    assert "typecheck" not in ran


def test_run_warns_on_soft_failure() -> None:
    """Non-strict gate failure produces a warning, not a hard stop."""
    def soft_fail(project: str, files: list[str]) -> GateCheckResult:
        return GateCheckResult(
            passed=False, gate_level=GateLevel.CODE_REVIEW, reason="review pending"
        )

    def hard_pass(project: str, files: list[str]) -> GateCheckResult:
        return GateCheckResult(passed=True, gate_level=GateLevel.SECURITY)

    chain = QualityChain()
    chain.register(GateLevel.SECURITY, hard_pass, strict=True)
    chain.register(GateLevel.CODE_REVIEW, soft_fail, strict=False)
    result = chain.run("proj", ["app.py"])
    assert result.passed is True
    assert any("CODE_REVIEW" in w for w in result.warnings)
    assert result.failed_at is None
