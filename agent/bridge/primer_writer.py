"""Bridge-native primer writer (#488).

Replaces the M1.2 Claude Code hook mechanism with a bridge-native writer.
See docs/specs/2026-04-17-488-primer-writer-spec.md for full design.

Triggered from:
  - session_manager.expire_session → write_primer(..., trigger_source="expire")
  - commands._cmd_reset → write_primer(..., trigger_source="reset")

NOT triggered from warm-process cycling (too noisy).

Writes to /opt/bumba-harness/data/primer.json (bridge artifact, not Claude Code).
"""

from __future__ import annotations

import json
import logging
import os
import pwd
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Module constants
# ─────────────────────────────────────────────────────────────────────

def _resolve_data_root() -> Path:
    """Resolve data dir via the canonical helper (#1501 F4)."""
    from bridge.paths import data_root
    return data_root()


DATA_DIR = _resolve_data_root()
PRIMER_PATH = DATA_DIR / "primer.json"
PRIMER_STATE_PATH = DATA_DIR / "primer_state.json"

MAX_CONSECUTIVE_FAILURES = 3
"""After N consecutive total failures, emit a Discord-worthy alert."""

SYNTHESIS_COST_CAP_USD = 0.01
"""Per-invocation cost cap for the Haiku synthesis call."""

SCHEMA_VERSION = "1.0"

DEFAULT_MOOD = "unknown"
DEFAULT_SUMMARY = ""


# ─────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────


class PrimerSynthesisError(Exception):
    """LLM narrative synthesis failed (timeout, error, malformed, over-cost)."""


# ─────────────────────────────────────────────────────────────────────
# PrimerV1 dataclass
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PrimerV1:
    schema_version: str
    generated_at: str
    session_id: str
    expires_at: str
    current_track: dict[str, Any]
    active_projects: list[dict[str, Any]]
    recent_decisions: list[dict[str, Any]]
    open_blockers: list[dict[str, Any]]
    pending_tasks: list[dict[str, Any]]
    session_summary: str
    operator_context: dict[str, Any]
    trigger_source: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────
# Deterministic facts collection
# ─────────────────────────────────────────────────────────────────────


def _collect_deterministic_facts(deps: Any, session_id: str) -> dict[str, Any]:
    """Pure function — reads from bridge state, returns PrimerV1-shaped dict.

    Each backend call is wrapped in try/except; on failure the field
    degrades to an empty list/default. The primer survives partial
    bridge degradation rather than failing entirely.
    """
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    expires_at = (now + timedelta(hours=24)).isoformat()

    # Active projects
    try:
        projects = deps.project_registry.list_active() or []
    except Exception:
        log.warning("primer: project_registry.list_active failed", exc_info=True)
        projects = []

    # Recent decisions from memory
    try:
        decisions = deps.memory_store.recent_decisions() or []
    except Exception:
        log.warning("primer: memory_store.recent_decisions failed", exc_info=True)
        decisions = []

    # Open blockers from task_queue (HITL pending approvals)
    try:
        blockers = deps.task_queue.pending() or []
    except Exception:
        log.warning("primer: task_queue.pending failed", exc_info=True)
        blockers = []

    # Pending tasks from plan_state
    try:
        tasks = deps.plan_state.pending_tasks() or []
    except Exception:
        log.warning("primer: plan_state.pending_tasks failed", exc_info=True)
        tasks = []

    # Current track: first active project if any, else "System"
    current_track = {"name": "System", "type": "system", "switched_at": None}
    if projects:
        current_track = {
            "name": projects[0].get("name", "System"),
            "type": projects[0].get("type", "product"),
            "switched_at": projects[0].get("switched_at"),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "session_id": session_id,
        "expires_at": expires_at,
        "current_track": current_track,
        "active_projects": projects,
        "recent_decisions": decisions,
        "open_blockers": blockers,
        "pending_tasks": tasks,
        "operator_last_seen": generated_at,
    }


# ─────────────────────────────────────────────────────────────────────
# LLM narrative synthesis
# ─────────────────────────────────────────────────────────────────────


_SYNTHESIS_PROMPT = """Produce a session primer narrative. Return ONE JSON object, nothing else.

Schema (all keys required):
{{
  "session_summary": "<2-4 sentence summary of what happened. Focus on decisions and work accomplished, not trivia.>",
  "mood": "<one of: focused | stressed | exploratory | unknown>",
  "notes": "<one sentence of cross-session context worth remembering, OR null>"
}}

Rules:
- Your entire output must be valid JSON.
- No markdown, no code fences, no prose before or after.
- No comments.
- If unsure about mood, use "unknown".
- If no cross-session notes, use null (not "null", the JSON null).

Facts from the session:
{facts}

Recent daily-log tail:
{log_tail}

Now return the JSON object:"""


def _extract_json_object(text: str) -> str:
    """Best-effort extraction of a JSON object from LLM output.

    Handles common wrapper patterns: markdown code fences, preface text like
    "Here's the JSON:", trailing prose, etc. Returns the raw JSON string.
    Raises ValueError if no plausible object found.
    """
    if not text:
        raise ValueError("empty response")

    # Strip ```json fences if present
    stripped = text.strip()
    if stripped.startswith("```"):
        # ```json or ``` prefix
        nl = stripped.find("\n")
        if nl != -1:
            stripped = stripped[nl + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    # Find first { and last matching }
    first = stripped.find("{")
    if first == -1:
        raise ValueError("no object-open brace found")

    # Walk to find the matching closing brace (handles nested objects)
    depth = 0
    last = -1
    in_string = False
    escape_next = False
    for i in range(first, len(stripped)):
        ch = stripped[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last = i
                break

    if last == -1:
        raise ValueError("no matching close brace found")

    return stripped[first:last + 1]


async def _synthesize_narrative(
    deps: Any,
    facts: dict[str, Any],
    log_tail: str,
) -> dict[str, Any]:
    """Call Haiku to produce session_summary + mood + notes.

    Cost-capped at SYNTHESIS_COST_CAP_USD. Raises PrimerSynthesisError
    on timeout, error, malformed response, or over-cost.
    """
    prompt = _SYNTHESIS_PROMPT.format(
        facts=json.dumps(facts, indent=2)[:2000],  # truncate to stay cheap
        log_tail=log_tail[:1500] if log_tail else "(no recent log)",
    )

    try:
        result = await deps.claude_runner.invoke(
            prompt=prompt,
            model="haiku",
            session_id=f"primer-{facts['session_id'][:8]}",
            max_turns=1,
        )
    except Exception as e:
        raise PrimerSynthesisError(f"claude_runner.invoke failed: {e}") from e

    if not isinstance(result, dict):
        raise PrimerSynthesisError(f"unexpected result type: {type(result).__name__}")

    if result.get("is_error"):
        raise PrimerSynthesisError("claude_runner returned is_error=True")

    cost = result.get("cost_usd", 0.0)
    if cost > SYNTHESIS_COST_CAP_USD:
        raise PrimerSynthesisError(
            f"synthesis cost ${cost:.4f} exceeded cap ${SYNTHESIS_COST_CAP_USD}"
        )

    response = result.get("response_text", "")
    if not response.strip():
        raise PrimerSynthesisError("empty response_text from runner")

    # Best-effort JSON extraction — Claude often wraps in prose or fences
    try:
        json_text = _extract_json_object(response)
    except ValueError as e:
        raise PrimerSynthesisError(
            f"no JSON object in response: {e}. First 200 chars: {response[:200]!r}"
        ) from e

    try:
        narrative = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise PrimerSynthesisError(
            f"malformed JSON: {e}. Extracted: {json_text[:200]!r}"
        ) from e

    # Validate required keys
    for key in ("session_summary", "mood", "notes"):
        if key not in narrative:
            raise PrimerSynthesisError(f"missing required key: {key}")

    return {
        "session_summary": str(narrative["session_summary"]),
        "mood": str(narrative["mood"]),
        "notes": narrative["notes"],  # may be None
    }


# ─────────────────────────────────────────────────────────────────────
# Merge
# ─────────────────────────────────────────────────────────────────────


def _merge(
    facts: dict[str, Any],
    narrative: dict[str, Any],
    *,
    trigger_source: str,
) -> PrimerV1:
    """Pure merge — facts + narrative → PrimerV1."""
    operator_context = {
        "mood": narrative.get("mood") or DEFAULT_MOOD,
        "last_seen": facts.get("operator_last_seen", facts.get("generated_at", "")),
        "notes": narrative.get("notes"),
    }
    return PrimerV1(
        schema_version=facts["schema_version"],
        generated_at=facts["generated_at"],
        session_id=facts["session_id"],
        expires_at=facts["expires_at"],
        current_track=facts["current_track"],
        active_projects=facts["active_projects"],
        recent_decisions=facts["recent_decisions"],
        open_blockers=facts["open_blockers"],
        pending_tasks=facts["pending_tasks"],
        session_summary=narrative.get("session_summary") or DEFAULT_SUMMARY,
        operator_context=operator_context,
        trigger_source=trigger_source,
    )


# ─────────────────────────────────────────────────────────────────────
# Atomic write
# ─────────────────────────────────────────────────────────────────────


def _atomic_write(primer: PrimerV1, path: Path | None = None) -> Path:
    """Temp-file + os.replace. Last-write-wins. No lock.

    Sets ownership to bumba-agent:staff when possible (best-effort).
    Resolves path at call-time so tests that monkeypatch PRIMER_PATH work.
    """
    # Import here so monkeypatched module-level PRIMER_PATH is honored
    from bridge import primer_writer as _self
    path = Path(path) if path else _self.PRIMER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp", prefix=".primer-")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(primer.to_json())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise

    # Best-effort ownership fix (only matters when run as root)
    try:
        info = pwd.getpwnam("bumba-agent")
        os.chown(path, info.pw_uid, info.pw_gid)
    except (KeyError, PermissionError, OSError):
        pass

    try:
        os.chmod(path, 0o644)
    except OSError:
        pass

    return path


# ─────────────────────────────────────────────────────────────────────
# Failure-state tracking
# ─────────────────────────────────────────────────────────────────────


def _load_state(path: Path | None = None) -> dict[str, Any]:
    from bridge import primer_writer as _self
    path = Path(path) if path else _self.PRIMER_STATE_PATH
    if not path.exists():
        return {"consecutive_failures": 0, "last_write_success": None, "last_write_at": None}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"consecutive_failures": 0, "last_write_success": None, "last_write_at": None}


def _save_state(state: dict[str, Any], path: Path | None = None) -> None:
    from bridge import primer_writer as _self
    path = Path(path) if path else _self.PRIMER_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp", prefix=".primer_state-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            Path(tmp_name).unlink()
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────
# Observability
# ─────────────────────────────────────────────────────────────────────


def _log_completion(status: str, primer: PrimerV1 | None, error: str | None = None) -> None:
    """Append `[PRIMER][<STATUS>]` line to the daily log. Best-effort."""
    try:
        from bridge.daily_log import append_line
        if primer is not None:
            size = len(primer.to_json())
            line = (
                f"[PRIMER][{status}] "
                f"session={primer.session_id[:8]} "
                f"trigger={primer.trigger_source} "
                f"projects={len(primer.active_projects)} "
                f"decisions={len(primer.recent_decisions)} "
                f"size={size}B"
            )
        else:
            line = f"[PRIMER][{status}] error={error or 'unknown'}"
        append_line(line, category="memory")
    except Exception:
        log.debug("primer: daily_log append failed", exc_info=True)


def _publish(deps: Any, event_type: str, payload: dict[str, Any]) -> None:
    if deps is None:
        return
    bus = getattr(deps, "event_bus", None)
    if bus is None:
        return
    try:
        bus.publish(event_type, payload=payload, source="primer_writer")
    except Exception:
        log.debug("primer: event publish failed", exc_info=True)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


async def write_primer(
    deps: Any,
    session_id: str,
    trigger_source: Literal["expire", "reset"],
) -> Path | None:
    """Orchestrate a primer write. Returns path on success, None on total failure.

    Flow:
      1. Collect deterministic facts (errors degrade fields individually)
      2. LLM narrative synthesis (errors fall back to empty narrative)
      3. Merge
      4. Atomic write
      5. Log + event + failure-counter update

    Silent-degrade failure model: LLM failures produce a DEGRADED write with
    empty narrative; total failures (collect or write fails) log and return
    None. After MAX_CONSECUTIVE_FAILURES total failures, fire an alert event.
    """
    # Step 1 — collect
    try:
        facts = _collect_deterministic_facts(deps, session_id=session_id)
    except Exception as e:
        log.exception("primer: facts collection failed")
        _log_completion("FAIL", None, error=f"collect: {e}")
        _record_failure(deps)
        return None

    # Step 2 — narrative synthesis (LLM); degrade on failure
    narrative: dict[str, Any]
    llm_ok = True
    try:
        log_tail = ""
        try:
            tail_fn = getattr(deps, "daily_log_tail", None)
            if callable(tail_fn):
                log_tail = tail_fn() or ""
        except Exception:
            log_tail = ""
        narrative = await _synthesize_narrative(deps, facts, log_tail)
    except PrimerSynthesisError as e:
        log.warning("primer: LLM synthesis failed, degrading: %s", e)
        narrative = {}
        llm_ok = False
    except Exception:
        log.exception("primer: LLM synthesis unexpected error")
        narrative = {}
        llm_ok = False

    # Step 3 — merge
    primer = _merge(facts, narrative, trigger_source=trigger_source)

    # Step 4 — atomic write
    try:
        path = _atomic_write(primer)
    except Exception as e:
        log.exception("primer: atomic write failed")
        _log_completion("FAIL", None, error=f"write: {e}")
        _publish(deps, "primer.write.failed", {"session_id": session_id, "error": str(e)})
        _record_failure(deps)
        return None

    # Step 5 — success or degraded
    status = "OK" if llm_ok else "DEGRADED"
    _log_completion(status, primer)
    _publish(
        deps,
        "primer.write.success" if llm_ok else "primer.write.degraded",
        {
            "session_id": session_id,
            "trigger": trigger_source,
            "path": str(path),
            "size_bytes": len(primer.to_json()),
            "projects": len(primer.active_projects),
        },
    )
    _reset_failure_counter()
    return path


def _record_failure(deps: Any) -> None:
    """Increment failure counter; emit alert at threshold."""
    state = _load_state()
    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    state["last_write_success"] = False
    state["last_write_at"] = datetime.now(timezone.utc).isoformat()

    if state["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
        _publish(
            deps,
            "primer.write.alert",
            {
                "consecutive_failures": state["consecutive_failures"],
                "message": f"Primer writer has failed {state['consecutive_failures']} times consecutively",
            },
        )
        # Reset counter after alert (prevents spam; next failure fires again at 3)
        state["consecutive_failures"] = 0

    _save_state(state)


def _reset_failure_counter() -> None:
    state = _load_state()
    state["consecutive_failures"] = 0
    state["last_write_success"] = True
    state["last_write_at"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)


def read_primer(path: Path | None = None) -> PrimerV1 | None:
    """Read primer.json from disk. Returns None if missing/malformed."""
    from bridge import primer_writer as _self
    target = Path(path) if path else _self.PRIMER_PATH
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        log.warning("primer: read_primer failed to parse %s", target, exc_info=True)
        return None

    try:
        return PrimerV1(
            schema_version=data["schema_version"],
            generated_at=data["generated_at"],
            session_id=data["session_id"],
            expires_at=data["expires_at"],
            current_track=data["current_track"],
            active_projects=data["active_projects"],
            recent_decisions=data["recent_decisions"],
            open_blockers=data["open_blockers"],
            pending_tasks=data["pending_tasks"],
            session_summary=data["session_summary"],
            operator_context=data["operator_context"],
            trigger_source=data.get("trigger_source", "unknown"),
        )
    except KeyError as e:
        log.warning("primer: missing required key %s in %s", e, target)
        return None


def get_primer_health() -> dict[str, Any]:
    """Used by /health. Returns two fields."""
    from bridge import primer_writer as _self
    primer_path = _self.PRIMER_PATH
    if not primer_path.is_file():
        return {
            "primer_last_write_success": False,
            "primer_last_write_age_minutes": None,
        }

    try:
        data = json.loads(primer_path.read_text())
        generated_at = datetime.fromisoformat(data["generated_at"])
        age_minutes = (datetime.now(timezone.utc) - generated_at).total_seconds() / 60
        return {
            "primer_last_write_success": True,
            "primer_last_write_age_minutes": age_minutes,
        }
    except Exception:
        return {
            "primer_last_write_success": False,
            "primer_last_write_age_minutes": None,
        }
