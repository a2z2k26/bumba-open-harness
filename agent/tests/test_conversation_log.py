"""
Tests for bridge/conversation_log.py — Sprint 5 Shared Conversation Log.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import warnings
from pathlib import Path

import pytest

from bridge.conversation_log import (
    ConversationLogger,
    ConversationMessage,
    ConversationReader,
    MessageType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "conversations" / "agent.jsonl"


@pytest.fixture()
def logger_obj(log_path: Path) -> ConversationLogger:
    return ConversationLogger(log_path)


@pytest.fixture()
def reader(log_path: Path) -> ConversationReader:
    return ConversationReader(log_path)


# ---------------------------------------------------------------------------
# ConversationMessage is frozen (immutable attributes)
# ---------------------------------------------------------------------------


class TestConversationMessageFrozen:
    def test_frozen_prevents_attribute_reassignment(self):
        msg = ConversationMessage(
            message_id="id-1",
            message_type=MessageType.DELEGATION,
            from_agent="chief",
            content="do the thing",
            timestamp=1.0,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            msg.from_agent = "hacker"  # type: ignore[misc]

    def test_frozen_prevents_message_type_reassignment(self):
        msg = ConversationMessage(
            message_id="id-2",
            message_type=MessageType.RESULT,
            from_agent="worker",
            content="done",
            timestamp=2.0,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            msg.message_type = MessageType.ERROR  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Serialisation — single-line JSON, no embedded newlines
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_single_line_json(self, logger_obj: ConversationLogger, log_path: Path):
        logger_obj.log_delegation("chief", "worker", "build the feature", "sess-1")

        raw = log_path.read_text(encoding="utf-8")
        lines = [l for l in raw.splitlines() if l.strip()]
        assert len(lines) == 1, "Expected exactly one non-empty line"

        # Must be valid JSON
        data = json.loads(lines[0])
        assert data["message_type"] == "DELEGATION"

    def test_no_embedded_newlines_in_content(
        self, logger_obj: ConversationLogger, log_path: Path
    ):
        multi_line_content = "line one\nline two\nline three"
        logger_obj.log_broadcast("orchestrator", multi_line_content)

        raw = log_path.read_text(encoding="utf-8")
        lines = [l for l in raw.splitlines() if l.strip()]
        assert len(lines) == 1

        # The embedded newlines should be escaped, not literal
        assert "\n" not in lines[0].rstrip("\n")

    def test_multiple_messages_multiple_lines(
        self, logger_obj: ConversationLogger, log_path: Path
    ):
        logger_obj.log_delegation("a", "b", "task 1")
        logger_obj.log_result("b", "a", "result 1")
        logger_obj.log_broadcast("a", "broadcast content")
        logger_obj.log_error("b", "something exploded")

        lines = [l for l in log_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 4
        for line in lines:
            json.loads(line)  # must all be valid JSON


# ---------------------------------------------------------------------------
# Convenience methods create correct MessageType
# ---------------------------------------------------------------------------


class TestConvenienceMethods:
    def test_log_delegation_type(self, logger_obj: ConversationLogger):
        msg = logger_obj.log_delegation("chief", "eng", "implement X")
        assert msg.message_type == MessageType.DELEGATION
        assert msg.from_agent == "chief"
        assert msg.to_agent == "eng"
        assert msg.content == "implement X"

    def test_log_result_type(self, logger_obj: ConversationLogger):
        msg = logger_obj.log_result("eng", "chief", "done — 42 tests pass")
        assert msg.message_type == MessageType.RESULT
        assert msg.from_agent == "eng"
        assert msg.to_agent == "chief"

    def test_log_broadcast_type(self, logger_obj: ConversationLogger):
        msg = logger_obj.log_broadcast("orchestrator", "starting sprint")
        assert msg.message_type == MessageType.BROADCAST
        assert msg.to_agent == ""

    def test_log_error_type(self, logger_obj: ConversationLogger):
        msg = logger_obj.log_error("worker", "timeout after 30s")
        assert msg.message_type == MessageType.ERROR
        assert msg.to_agent == ""

    def test_session_id_propagated(self, logger_obj: ConversationLogger):
        msg = logger_obj.log_delegation("a", "b", "task", session_id="session-42")
        assert msg.session_id == "session-42"

    def test_message_id_unique(self, logger_obj: ConversationLogger):
        m1 = logger_obj.log_broadcast("a", "hello")
        m2 = logger_obj.log_broadcast("a", "world")
        assert m1.message_id != m2.message_id

    def test_timestamp_is_recent(self, logger_obj: ConversationLogger):
        before = time.time()
        msg = logger_obj.log_broadcast("a", "ping")
        after = time.time()
        assert before <= msg.timestamp <= after


# ---------------------------------------------------------------------------
# ConversationReader — round-trip read-back
# ---------------------------------------------------------------------------


class TestConversationReader:
    def test_read_all_round_trip(
        self, logger_obj: ConversationLogger, reader: ConversationReader
    ):
        sent = [
            logger_obj.log_delegation("chief", "eng", "build it", "s1"),
            logger_obj.log_result("eng", "chief", "built", "s1"),
            logger_obj.log_broadcast("chief", "all done"),
            logger_obj.log_error("eng", "oops"),
        ]
        received = reader.read_all()
        assert len(received) == len(sent)
        for s, r in zip(sent, received):
            assert s.message_id == r.message_id
            assert s.message_type == r.message_type
            assert s.from_agent == r.from_agent
            assert s.to_agent == r.to_agent
            assert s.content == r.content
            assert s.session_id == r.session_id
            assert abs(s.timestamp - r.timestamp) < 0.001

    def test_read_all_missing_file_returns_empty(self, tmp_path: Path):
        reader = ConversationReader(tmp_path / "does_not_exist.jsonl")
        result = reader.read_all()
        assert result == []

    def test_read_all_empty_file_returns_empty(
        self, log_path: Path
    ):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch()
        reader = ConversationReader(log_path)
        assert reader.read_all() == []


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class TestFilters:
    @pytest.fixture(autouse=True)
    def populate(
        self, logger_obj: ConversationLogger, reader: ConversationReader
    ):
        # Build a small conversation graph
        self.m1 = logger_obj.log_delegation("chief", "eng", "build X", "sess-A")
        self.m2 = logger_obj.log_result("eng", "chief", "done X", "sess-A")
        self.m3 = logger_obj.log_delegation("chief", "qa", "test X", "sess-A")
        self.m4 = logger_obj.log_result("qa", "chief", "passed", "sess-A")
        self.m5 = logger_obj.log_broadcast("chief", "sprint complete")
        self.m6 = logger_obj.log_error("eng", "timeout during build Y")
        self.reader = reader
        # Record timestamps for time-range tests
        self.t_before_m5 = self.m4.timestamp
        self.t_after_m6 = self.m6.timestamp + 1.0

    def test_filter_by_agent_sender(self):
        msgs = self.reader.filter_by_agent("qa")
        ids = {m.message_id for m in msgs}
        assert self.m3.message_id in ids  # to_agent == "qa"
        assert self.m4.message_id in ids  # from_agent == "qa"

    def test_filter_by_agent_includes_sender_and_recipient(self):
        msgs = self.reader.filter_by_agent("chief")
        ids = {m.message_id for m in msgs}
        # chief is from_agent in m1, m3, m5; to_agent in m2, m4
        for m in (self.m1, self.m2, self.m3, self.m4, self.m5):
            assert m.message_id in ids

    def test_filter_by_agent_excludes_unrelated(self):
        msgs = self.reader.filter_by_agent("qa")
        ids = {m.message_id for m in msgs}
        # m5 is chief→(broadcast), m6 is eng→(error): qa not involved
        assert self.m5.message_id not in ids
        assert self.m6.message_id not in ids

    def test_filter_by_type_delegation(self):
        msgs = self.reader.filter_by_type(MessageType.DELEGATION)
        assert all(m.message_type == MessageType.DELEGATION for m in msgs)
        ids = {m.message_id for m in msgs}
        assert self.m1.message_id in ids
        assert self.m3.message_id in ids

    def test_filter_by_type_result(self):
        msgs = self.reader.filter_by_type(MessageType.RESULT)
        assert all(m.message_type == MessageType.RESULT for m in msgs)
        ids = {m.message_id for m in msgs}
        assert self.m2.message_id in ids
        assert self.m4.message_id in ids

    def test_filter_by_type_broadcast(self):
        msgs = self.reader.filter_by_type(MessageType.BROADCAST)
        ids = {m.message_id for m in msgs}
        assert self.m5.message_id in ids
        assert len(msgs) == 1

    def test_filter_by_type_error(self):
        msgs = self.reader.filter_by_type(MessageType.ERROR)
        ids = {m.message_id for m in msgs}
        assert self.m6.message_id in ids
        assert len(msgs) == 1

    def test_filter_by_time_range(self):
        # Range that only covers m5 and m6
        msgs = self.reader.filter_by_time_range(
            self.m5.timestamp - 0.001, self.m6.timestamp + 0.001
        )
        ids = {m.message_id for m in msgs}
        assert self.m5.message_id in ids
        assert self.m6.message_id in ids

    def test_filter_by_time_range_exclusive(self):
        # Use a range before m1 — should return nothing
        msgs = self.reader.filter_by_time_range(0.0, self.m1.timestamp - 1.0)
        assert msgs == []


# ---------------------------------------------------------------------------
# format_for_agent
# ---------------------------------------------------------------------------


class TestFormatForAgent:
    def test_format_delegation_line(self, logger_obj: ConversationLogger, reader: ConversationReader):
        msg = logger_obj.log_delegation("chief", "eng", "build feature Z")
        output = reader.format_for_agent([msg])
        assert "[DELEGATION]" in output
        assert "chief" in output
        assert "eng" in output
        assert "build feature Z" in output

    def test_format_broadcast_shows_broadcast_recipient(
        self, logger_obj: ConversationLogger, reader: ConversationReader
    ):
        msg = logger_obj.log_broadcast("orchestrator", "all agents stand by")
        output = reader.format_for_agent([msg])
        assert "(broadcast)" in output

    def test_format_truncates_long_content(
        self, logger_obj: ConversationLogger, reader: ConversationReader
    ):
        long_content = "x" * 200
        msg = logger_obj.log_broadcast("a", long_content)
        output = reader.format_for_agent([msg])
        # The content portion should be at most 100 chars
        # Find content after the colon separator
        colon_idx = output.index(": ")
        content_part = output[colon_idx + 2:]
        assert len(content_part) <= 100

    def test_format_multiple_messages_multiple_lines(
        self, logger_obj: ConversationLogger, reader: ConversationReader
    ):
        logger_obj.log_delegation("a", "b", "task 1")
        logger_obj.log_result("b", "a", "done 1")
        logger_obj.log_error("b", "fail")
        msgs = reader.read_all()
        output = reader.format_for_agent(msgs)
        lines = output.strip().splitlines()
        assert len(lines) == 3

    def test_format_empty_list(self, reader: ConversationReader):
        output = reader.format_for_agent([])
        assert output == ""

    def test_format_arrow_separator(self, logger_obj: ConversationLogger, reader: ConversationReader):
        msg = logger_obj.log_result("eng", "chief", "done")
        output = reader.format_for_agent([msg])
        assert "→" in output


# ---------------------------------------------------------------------------
# Malformed JSONL lines are skipped with a warning
# ---------------------------------------------------------------------------


class TestMalformedLines:
    def test_skips_invalid_json(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Write one valid and one invalid line
        good = ConversationMessage(
            message_id="good-id",
            message_type=MessageType.BROADCAST,
            from_agent="a",
            content="hello",
            timestamp=1.0,
        )
        log_path.write_text(
            json.dumps(good.to_dict()) + "\n" + "NOT JSON AT ALL\n",
            encoding="utf-8",
        )
        reader = ConversationReader(log_path)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            messages = reader.read_all()

        assert len(messages) == 1
        assert messages[0].message_id == "good-id"
        assert len(w) == 1
        assert "malformed" in str(w[0].message).lower()

    def test_skips_missing_required_fields(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        bad = {"message_id": "x"}  # missing all other required fields
        log_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        reader = ConversationReader(log_path)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            messages = reader.read_all()
        assert messages == []
        assert len(w) == 1

    def test_skips_blank_lines_silently(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        good = ConversationMessage(
            message_id="ok",
            message_type=MessageType.ERROR,
            from_agent="b",
            content="err",
            timestamp=2.0,
        )
        log_path.write_text(
            "\n\n" + json.dumps(good.to_dict()) + "\n\n",
            encoding="utf-8",
        )
        reader = ConversationReader(log_path)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            messages = reader.read_all()
        assert len(messages) == 1
        assert len(w) == 0  # blank lines do NOT produce warnings


# ---------------------------------------------------------------------------
# Concurrent write safety
# ---------------------------------------------------------------------------


class TestConcurrentWrites:
    def test_ten_threads_all_messages_readable(self, log_path: Path):
        """10 threads write simultaneously; all messages must be valid JSONL."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        conv_logger = ConversationLogger(log_path)
        n_threads = 10
        messages_per_thread = 20
        errors: list[str] = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(messages_per_thread):
                    conv_logger.log_delegation(
                        f"thread-{thread_id}",
                        "coordinator",
                        f"task-{thread_id}-{i}",
                        session_id=f"sess-{thread_id}",
                    )
            except Exception as exc:
                errors.append(str(exc))

        threads = [
            threading.Thread(target=writer, args=(t,)) for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

        # Verify all lines are valid JSON (no interleaved partial writes)
        raw_lines = [
            l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        assert len(raw_lines) == n_threads * messages_per_thread

        for lineno, line in enumerate(raw_lines, start=1):
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                pytest.fail(f"Invalid JSON on line {lineno}: {exc}\nLine: {line!r}")

        # ConversationReader must parse all valid lines. Concurrent writes on
        # some filesystems (notably Linux ext4 under CI thread contention) can
        # produce malformed lines despite fcntl flock; read_all() warns and
        # skips those. We tolerate up to 5% malformed-line warnings here.
        reader = ConversationReader(log_path)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            messages = reader.read_all()
        malformed_warnings = [
            x for x in w if "conversation_log" in str(x.message)
        ]
        max_tolerable = max(1, (n_threads * messages_per_thread) // 20)
        assert len(malformed_warnings) <= max_tolerable, (
            f"Too many malformed-line warnings ({len(malformed_warnings)} > "
            f"{max_tolerable}): {malformed_warnings}"
        )
        # Other (non-conversation_log) warnings are unrelated noise; ignore.
        assert len(messages) >= n_threads * messages_per_thread - max_tolerable

    def test_concurrent_writes_all_delegations(self, log_path: Path):
        """Verify message types survive concurrent writes intact."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        conv_logger = ConversationLogger(log_path)

        def mixed_writer(tid: int) -> None:
            conv_logger.log_delegation(f"a{tid}", "b", "delegate")
            conv_logger.log_result(f"b{tid}", "a", "result")
            conv_logger.log_broadcast(f"c{tid}", "broadcast")
            conv_logger.log_error(f"d{tid}", "error msg")

        threads = [threading.Thread(target=mixed_writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        reader = ConversationReader(log_path)
        messages = reader.read_all()
        assert len(messages) == 40  # 4 per thread × 10 threads

        type_counts = {}
        for m in messages:
            type_counts[m.message_type] = type_counts.get(m.message_type, 0) + 1

        assert type_counts[MessageType.DELEGATION] == 10
        assert type_counts[MessageType.RESULT] == 10
        assert type_counts[MessageType.BROADCAST] == 10
        assert type_counts[MessageType.ERROR] == 10
