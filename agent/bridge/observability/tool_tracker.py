"""
tool_tracker.py — Zone 4 Sprint 9

Per-agent tool call tracking with secret redaction and domain violation detection.

Storage layout:
    sessions/{session_id}/{department}/tools/{agent_name}.jsonl

Each line in the JSONL file is a serialized ToolCallRecord.
"""
from __future__ import annotations

import fcntl
import json
import logging
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Fields that must have their values redacted
_SECRET_FIELD_PATTERNS = re.compile(
    r"(token|secret|password|key|auth|credential)",
    re.IGNORECASE,
)

_REDACTED = "[REDACTED]"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolCallCost:
    """Cost attribution for a single tool call."""

    input_tokens: int = 0
    output_tokens: int = 0
    estimated_usd: float = 0.0


@dataclass(frozen=True)
class ToolCallRecord:
    """Immutable record of a single tool call made by an agent."""

    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    agent_name: str = ""
    department: str = ""
    session_id: str = ""
    tool_name: str = ""
    args_summary: str = ""          # Sanitized — no secrets
    result_summary: str = ""        # Truncated result description
    status: str = "completed"       # completed, failed, blocked
    is_domain_violation: bool = False
    violation_rule: str = ""        # Populated if is_domain_violation
    cost: ToolCallCost = field(default_factory=ToolCallCost)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        # Flatten ToolCallCost into the record
        d["cost"] = asdict(self.cost)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ToolCallRecord":
        cost_data = data.pop("cost", {})
        cost = ToolCallCost(**cost_data) if cost_data else ToolCallCost()
        return cls(**data, cost=cost)


# ── Secret redaction ──────────────────────────────────────────────────────────

def sanitize_args(args: dict | str | None) -> str:
    """
    Redact secret values from tool call arguments.

    - Dicts: redact any key matching the secret pattern
    - Strings: redact values after secret-like key patterns (key=VALUE, "key": "VALUE")
    - None or non-serializable: return safe empty representation

    Always returns a string safe for logging.
    """
    if args is None:
        return ""

    if isinstance(args, dict):
        sanitized = _sanitize_dict(args)
        try:
            return json.dumps(sanitized, ensure_ascii=False, default=str)
        except Exception:
            return "{}"

    if isinstance(args, str):
        return _sanitize_string(args)

    # Fallback — try JSON serialization
    try:
        if isinstance(args, (list, tuple)):
            sanitized_list = [
                _sanitize_dict(item) if isinstance(item, dict) else item
                for item in args
            ]
            return json.dumps(sanitized_list, ensure_ascii=False, default=str)
        return json.dumps(args, ensure_ascii=False, default=str)
    except Exception:
        return str(type(args))


def _sanitize_dict(d: dict) -> dict:
    """Recursively redact secret values in a dict."""
    result = {}
    for k, v in d.items():
        if _SECRET_FIELD_PATTERNS.search(str(k)):
            result[k] = _REDACTED
        elif isinstance(v, dict):
            result[k] = _sanitize_dict(v)
        elif isinstance(v, (list, tuple)):
            result[k] = [
                _sanitize_dict(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def _sanitize_string(s: str) -> str:
    """
    Redact secret values in string representations.
    Handles patterns like: key=VALUE, "key": "VALUE", key: VALUE
    """
    # Pattern: key=value (shell-style)
    s = re.sub(
        r'(\b(?:token|secret|password|key|auth|credential)\w*\s*=\s*)([^\s&,;"\'\]})]+)',
        lambda m: m.group(1) + _REDACTED,
        s,
        flags=re.IGNORECASE,
    )
    # Pattern: "key": "value" or "key": value (JSON-style)
    s = re.sub(
        r'("(?:token|secret|password|key|auth|credential)[^"]*"\s*:\s*)"([^"]*)"',
        lambda m: m.group(1) + f'"{_REDACTED}"',
        s,
        flags=re.IGNORECASE,
    )
    return s


# ── ToolTracker ───────────────────────────────────────────────────────────────

class ToolTracker:
    """
    Records tool calls to per-agent JSONL files within a session directory.

    Storage: sessions/{session_id}/{department}/tools/{agent_name}.jsonl

    Thread-safe via fcntl.LOCK_EX on each write.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self._sessions_dir = sessions_dir

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(self, record: ToolCallRecord) -> None:
        """
        Append a ToolCallRecord to the appropriate agent JSONL file.
        Creates intermediate directories as needed.
        """
        log_path = self._tool_log_path(
            session_id=record.session_id,
            department=record.department,
            agent_name=record.agent_name,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._append_jsonl(log_path, record.to_dict())

    def log_call(
        self,
        *,
        agent_name: str,
        department: str,
        session_id: str,
        tool_name: str,
        args: dict | str | None = None,
        result: str = "",
        status: str = "completed",
        is_domain_violation: bool = False,
        violation_rule: str = "",
        cost: Optional[ToolCallCost] = None,
        duration_ms: float = 0.0,
    ) -> ToolCallRecord:
        """
        Convenience method: build and record a ToolCallRecord in one step.
        Returns the record for callers that need the record_id.
        """
        record = ToolCallRecord(
            agent_name=agent_name,
            department=department,
            session_id=session_id,
            tool_name=tool_name,
            args_summary=sanitize_args(args),
            result_summary=result[:500],  # Truncate long results
            status=status,
            is_domain_violation=is_domain_violation,
            violation_rule=violation_rule,
            cost=cost or ToolCallCost(),
            duration_ms=duration_ms,
        )
        self.record(record)
        return record

    # ── Query methods ──────────────────────────────────────────────────────────

    def get_agent_calls(
        self,
        session_id: str,
        department: str,
        agent_name: str,
    ) -> list[ToolCallRecord]:
        """Return all tool calls made by a specific agent in a session."""
        log_path = self._tool_log_path(session_id, department, agent_name)
        return self._read_jsonl(log_path)

    def get_department_calls(
        self,
        session_id: str,
        department: str,
    ) -> list[ToolCallRecord]:
        """Return all tool calls made by any agent in a department for a session."""
        tools_dir = self._tools_dir(session_id, department)
        if not tools_dir.exists():
            return []

        records: list[ToolCallRecord] = []
        for jsonl_file in sorted(tools_dir.glob("*.jsonl")):
            records.extend(self._read_jsonl(jsonl_file))

        # Sort by timestamp
        records.sort(key=lambda r: r.timestamp)
        return records

    def get_session_calls(self, session_id: str) -> list[ToolCallRecord]:
        """Return all tool calls made across all departments in a session."""
        session_dir = self._sessions_dir / session_id
        if not session_dir.exists():
            return []

        records: list[ToolCallRecord] = []
        for dept_dir in sorted(session_dir.iterdir()):
            if not dept_dir.is_dir():
                continue
            tools_dir = dept_dir / "tools"
            if not tools_dir.exists():
                continue
            for jsonl_file in sorted(tools_dir.glob("*.jsonl")):
                records.extend(self._read_jsonl(jsonl_file))

        records.sort(key=lambda r: r.timestamp)
        return records

    def get_domain_violations(
        self,
        session_id: str,
        department: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> list[ToolCallRecord]:
        """
        Return tool call records that were domain violations.

        Scope can be narrowed to a specific department or agent.
        """
        if agent_name and department:
            records = self.get_agent_calls(session_id, department, agent_name)
        elif department:
            records = self.get_department_calls(session_id, department)
        else:
            records = self.get_session_calls(session_id)

        return [r for r in records if r.is_domain_violation]

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _tool_log_path(
        self, session_id: str, department: str, agent_name: str
    ) -> Path:
        return self._tools_dir(session_id, department) / f"{agent_name}.jsonl"

    def _tools_dir(self, session_id: str, department: str) -> Path:
        return self._sessions_dir / session_id / department / "tools"

    def _append_jsonl(self, path: Path, record: dict) -> None:
        """Thread-safe append to a JSONL file."""
        try:
            line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
            with open(path, "a", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(line)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as exc:
            logger.error("Failed to write tool call record to %s: %s", path, exc)

    def _read_jsonl(self, path: Path) -> list[ToolCallRecord]:
        """Read all ToolCallRecords from a JSONL file. Skips malformed lines."""
        if not path.exists():
            return []

        records: list[ToolCallRecord] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        records.append(ToolCallRecord.from_dict(data))
                    except Exception as exc:
                        logger.warning(
                            "Skipping malformed line %d in %s: %s",
                            line_num,
                            path,
                            exc,
                        )
        except Exception as exc:
            logger.error("Failed to read tool tracker log %s: %s", path, exc)

        return records
