"""Tests for E2.1 — 13-lifecycle-point hook scripts.

Verifies:
- _lib/emit.sh writes valid JSONL to the sink
- emit.sh is silent when the sink is not writable
- Each lifecycle script has the concept-only attribution header
- flock-based write safety (concurrent invocations produce valid JSON lines)
"""

import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).parent.parent / "config" / "hooks"
EMIT_SH = HOOKS_DIR / "_lib" / "emit.sh"

LIFECYCLE_DIRS = [
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SubagentStop",
    "Notification",
    "PreCompact",
    "PostCompact",
    "PreModelInvoke",
    "PostModelInvoke",
    "Error",
]

ATTRIBUTION_HEADER = "# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased)."


def _run_emit(event: str, sink: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Source emit.sh and call emit() from a subshell."""
    env = os.environ.copy()
    env["BUMBA_HOOKS_TELEMETRY"] = sink
    env["CLAUDE_SESSION_ID"] = "test-session-abc"
    if extra_env:
        env.update(extra_env)
    script = f'. "{EMIT_SH}"; emit "{event}" "key=val"'
    return subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
    )


class TestEmitHelper:
    def test_emit_writes_valid_jsonl(self, tmp_path):
        sink = str(tmp_path / "telemetry.jsonl")
        result = _run_emit("PreToolUse", sink)
        assert result.returncode == 0, f"emit.sh failed: {result.stderr}"
        lines = Path(sink).read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "PreToolUse"
        assert record["session_id"] == "test-session-abc"
        assert "ts" in record
        assert "payload" in record
        assert record["payload"]["key"] == "val"

    def test_emit_silent_on_unwritable_sink(self):
        """Must exit 0 even if the sink path is unwritable."""
        result = _run_emit("PreToolUse", "/dev/null/nope/telemetry.jsonl")
        assert result.returncode == 0, f"emit.sh should fail silently: {result.stderr}"

    def test_emit_multiple_events_appends(self, tmp_path):
        sink = str(tmp_path / "telemetry.jsonl")
        for event in ["SessionStart", "PreToolUse", "PostToolUse", "Stop"]:
            _run_emit(event, sink)
        lines = Path(sink).read_text().strip().splitlines()
        assert len(lines) == 4
        events = [json.loads(l)["event"] for l in lines]
        assert events == ["SessionStart", "PreToolUse", "PostToolUse", "Stop"]

    def test_emit_concurrent_writes_produce_valid_lines(self, tmp_path):
        """10 concurrent emit calls must produce 10 parseable JSONL lines."""
        sink = str(tmp_path / "concurrent.jsonl")
        errors = []

        def run_emit(i):
            result = _run_emit("PreToolUse", sink, extra_env={"EMIT_INDEX": str(i)})
            if result.returncode != 0:
                errors.append(result.stderr)

        threads = [threading.Thread(target=run_emit, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Some emits failed: {errors}"
        raw = Path(sink).read_text().strip()
        lines = [l for l in raw.splitlines() if l.strip()]
        assert len(lines) == 10, f"Expected 10 lines, got {len(lines)}: {raw}"
        for line in lines:
            json.loads(line)  # raises on malformed JSON


class TestLifecycleScripts:
    def test_all_13_lifecycle_dirs_exist(self):
        for name in LIFECYCLE_DIRS:
            d = HOOKS_DIR / name
            assert d.is_dir(), f"Lifecycle directory missing: {d}"

    def test_each_lifecycle_dir_has_at_least_one_script(self):
        for name in LIFECYCLE_DIRS:
            d = HOOKS_DIR / name
            scripts = list(d.glob("*.sh"))
            assert scripts, f"No .sh scripts found in {d}"

    def test_each_script_has_attribution_header(self):
        missing = []
        for name in LIFECYCLE_DIRS:
            d = HOOKS_DIR / name
            for script in sorted(d.glob("*.sh")):
                content = script.read_text()
                if ATTRIBUTION_HEADER not in content:
                    missing.append(str(script))
        assert not missing, f"Scripts missing attribution header: {missing}"

    def test_each_script_passes_bash_syntax_check(self):
        errors = []
        all_scripts = list(HOOKS_DIR.glob("**/*.sh"))
        assert all_scripts, "No .sh scripts found under hooks dir"
        for script in all_scripts:
            result = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                errors.append(f"{script}: {result.stderr.strip()}")
        assert not errors, "Syntax errors in scripts:\n" + "\n".join(errors)

    def test_emit_lib_exists_and_is_executable(self):
        assert EMIT_SH.exists(), f"emit.sh not found at {EMIT_SH}"
        assert os.access(EMIT_SH, os.X_OK), "emit.sh is not executable"

    def test_lifecycle_script_emits_correct_event(self, tmp_path):
        """Spot-check: SessionEnd/01-emit.sh emits event=SessionEnd."""
        script = HOOKS_DIR / "SessionEnd" / "01-emit.sh"
        if not script.exists():
            pytest.skip(f"{script} not found")
        sink = str(tmp_path / "telemetry.jsonl")
        env = os.environ.copy()
        env["BUMBA_HOOKS_TELEMETRY"] = sink
        env["CLAUDE_SESSION_ID"] = "smoke-session"
        result = subprocess.run(
            ["bash", str(script)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        lines = Path(sink).read_text().strip().splitlines()
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["event"] == "SessionEnd"
