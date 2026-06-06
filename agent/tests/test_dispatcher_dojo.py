"""Test Dojo-gate returns handled=False (not handled=True with no result).

Regression test for issue #628: dispatcher returned
DispatchResult(valid=True, handled=True) with **no result field** when the
dojo trust floor was not met.  The caller contract in app.py is:

    if dispatch_result.handled and dispatch_result.result is not None:

With handled=True and result=None the condition was False, so the caller
fell through to direct invoke — but the event bus and metrics had already
fired, causing double-invocation when trust wiring activates.

Fix: return handled=False so the caller falls through cleanly.
Event bus publish and metrics counter still fire for observability.
"""
from pathlib import Path


def test_dojo_gate_returns_handled_false():
    """Dojo-gate block must return handled=False, not handled=True."""
    src = Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    assert src.exists(), f"dispatcher.py not found at {src}"

    content = src.read_text()
    lines = content.splitlines()

    # Locate every line that mentions 'dojo floor' — the reason string
    dojo_lines = [
        i for i, line in enumerate(lines)
        if "dojo floor" in line
    ]
    assert dojo_lines, (
        "No 'dojo floor' reason string found in dispatcher.py — "
        "dojo gate may have been removed"
    )

    for dojo_line_num in dojo_lines:
        # Gather context: 5 lines before through 10 lines after the reason string
        start = max(0, dojo_line_num - 5)
        end = min(len(lines), dojo_line_num + 10)
        context = "\n".join(lines[start:end])

        # The contract: handled=True is forbidden near the dojo-floor reason
        assert "handled=True" not in context, (
            f"Dojo-gate at line {dojo_line_num + 1} still returns handled=True "
            f"(violates caller contract — will cause double-invocation):\n\n{context}"
        )

        # Confirm the correct value is present
        assert "handled=False" in context, (
            f"Dojo-gate at line {dojo_line_num + 1} does not return handled=False:\n\n{context}"
        )


def test_dojo_gate_preserves_event_bus_publish():
    """Dojo-gate must still publish to the event bus even when handled=False."""
    src = Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    content = src.read_text()
    lines = content.splitlines()

    dojo_lines = [i for i, l in enumerate(lines) if "dojo floor" in l]
    assert dojo_lines, "No dojo floor block found"

    for dojo_line_num in dojo_lines:
        # Event bus publish should appear in the surrounding block
        start = max(0, dojo_line_num - 20)
        context = "\n".join(lines[start : dojo_line_num + 5])
        assert "dojo.gated" in context, (
            f"Dojo-gate block near line {dojo_line_num + 1} no longer publishes "
            f"'dojo.gated' to the event bus — observability was lost"
        )


def test_successful_dispatch_still_returns_handled_true():
    """The normal (successful) dispatch path must still return handled=True with a result."""
    src = Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    content = src.read_text()

    # The executor success path should still set handled=True with a result
    assert "handled=True, result=result" in content or (
        "handled=True" in content and "result=result" in content
    ), (
        "Successful dispatch path no longer returns handled=True with result "
        "— may have been accidentally removed"
    )
