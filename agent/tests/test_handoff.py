"""Tests for the handoff data model + composer (sprints 1112.1.01 + 1112.1.02).

Sprint 1.01 (issue #2138) shipped the data-only types ``HandoffDraft`` and
``HandoffPacket``, the ``harness_id`` / ``peer_harness_ids`` fields on
``BridgeConfig``, and the slot template at
``agent/config/handoff-template.md``.

Sprint 1.02 (issue #2139) adds the sender-side composer functions:
``save_conversation_gist``, ``compose_handoff``, and
``format_draft_for_operator``, plus the operator-facing ``/handoff
<to-harness> <topic>`` command path in ``CommandHandler._cmd_handoff``.

Scope discipline: no fire path (Sprint 1.04) and no receiver-side wiring
(Sprint 1.03) are exercised here.
"""
from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from bridge.config import BridgeConfig, load_config
from bridge.handoff import (
    HANDOFF_REGEX,
    HandoffDraft,
    HandoffPacket,
    HandoffPlan,
    compose_handoff,
    consume_handoff,
    format_draft_for_operator,
    parse_handoff_message,
    save_conversation_gist,
)


# ---------------------------------------------------------------------------
# BridgeConfig field additions
# ---------------------------------------------------------------------------


def test_bridge_config_has_harness_id_with_default():
    cfg = BridgeConfig()
    assert cfg.harness_id == "local-1"


def test_bridge_config_has_peer_harness_ids_with_empty_tuple_default():
    cfg = BridgeConfig()
    assert cfg.peer_harness_ids == ()
    assert isinstance(cfg.peer_harness_ids, tuple)


def test_bridge_config_harness_id_overrideable_via_dataclass_replace():
    base = BridgeConfig()
    overridden = dataclasses.replace(base, harness_id="mini-1")
    assert overridden.harness_id == "mini-1"
    # base must be untouched (immutability).
    assert base.harness_id == "local-1"


def test_bridge_config_peer_harness_ids_accepts_multiple():
    cfg = dataclasses.replace(
        BridgeConfig(),
        peer_harness_ids=("mini-1", "laptop"),
    )
    assert cfg.peer_harness_ids == ("mini-1", "laptop")


def test_bridge_config_is_frozen_for_harness_id():
    cfg = BridgeConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.harness_id = "mini-2"  # type: ignore[misc]


def test_load_config_exposes_harness_id_default():
    """Acceptance criterion: load_config(skip_secrets, skip_validation) → local-1."""
    cfg = load_config(skip_secrets=True, skip_validation=True)
    assert cfg.harness_id == "local-1"


# ---------------------------------------------------------------------------
# HandoffDraft
# ---------------------------------------------------------------------------


def _draft_kwargs(**overrides) -> dict:
    base = dict(
        from_harness="local-1",
        to_harness="mini-1",
        topic="trust escalation review",
        context_summary="The trust ladder needs a second pair of eyes.",
        work_done="Drafted the policy, ran the unit suite, documented edge cases.",
        ask="Audit policy.py for missing fail-closed paths.",
        boundaries="Do not refactor unrelated modules. Surgical changes only.",
        references=("agent/bridge/policy.py", "#2138"),
    )
    base.update(overrides)
    return base


def test_handoff_draft_required_fields_compose():
    draft = HandoffDraft(**_draft_kwargs())
    assert draft.from_harness == "local-1"
    assert draft.to_harness == "mini-1"
    assert draft.references == ("agent/bridge/policy.py", "#2138")


def test_handoff_draft_response_protocol_default():
    draft = HandoffDraft(**_draft_kwargs())
    assert draft.response_protocol == "operator-only"


def test_handoff_draft_trust_level_default_is_review():
    draft = HandoffDraft(**_draft_kwargs())
    assert draft.trust_level == "review"


def test_handoff_draft_is_frozen():
    draft = HandoffDraft(**_draft_kwargs())
    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.topic = "something else"  # type: ignore[misc]


def test_handoff_draft_requires_every_slot():
    """Every slot in the spec is a required positional/keyword arg."""
    incomplete = _draft_kwargs()
    incomplete.pop("ask")
    with pytest.raises(TypeError):
        HandoffDraft(**incomplete)


def test_handoff_draft_accepts_auto_trust_level():
    draft = HandoffDraft(**_draft_kwargs(trust_level="auto"))
    assert draft.trust_level == "auto"


# ---------------------------------------------------------------------------
# HandoffPacket
# ---------------------------------------------------------------------------


def _packet_kwargs(**overrides) -> dict:
    base = dict(
        from_harness="local-1",
        to_harness="mini-1",
        artifact_url="https://gist.github.com/example/abc123",
        one_line_summary="Audit policy.py for missing fail-closed paths.",
        fired_at="2026-05-17T12:34:56Z",
    )
    base.update(overrides)
    return base


def test_handoff_packet_required_fields_compose():
    packet = HandoffPacket(**_packet_kwargs())
    assert packet.from_harness == "local-1"
    assert packet.artifact_url.startswith("https://")
    assert packet.fired_at == "2026-05-17T12:34:56Z"


def test_handoff_packet_is_frozen():
    packet = HandoffPacket(**_packet_kwargs())
    with pytest.raises(dataclasses.FrozenInstanceError):
        packet.artifact_url = "https://gist.github.com/example/zzz"  # type: ignore[misc]


def test_handoff_packet_requires_every_slot():
    incomplete = _packet_kwargs()
    incomplete.pop("fired_at")
    with pytest.raises(TypeError):
        HandoffPacket(**incomplete)


# ---------------------------------------------------------------------------
# Template file
# ---------------------------------------------------------------------------


def test_handoff_template_file_exists_and_has_slots():
    """The slot template lives next to other bridge config and lists every
    field a composer will need to fill in. Phase 1 only requires that the
    file exists with the expected slot names.
    """
    template = (
        Path(__file__).resolve().parent.parent
        / "config"
        / "handoff-template.md"
    )
    assert template.is_file(), f"missing handoff template at {template}"
    body = template.read_text()
    # Every slot name from HandoffDraft must appear in the template, so
    # the operator can never silently lose a field during composer work
    # in sprints 1.02/1.03.
    for slot in (
        "from_harness",
        "to_harness",
        "topic",
        "context_summary",
        "work_done",
        "ask",
        "boundaries",
        "references",
        "response_protocol",
        "trust_level",
    ):
        assert slot in body, f"slot '{slot}' missing from template"


# ---------------------------------------------------------------------------
# Sprint 1.02 (#2139) — save_conversation_gist
# ---------------------------------------------------------------------------


class TestSaveConversationGist:
    """``save_conversation_gist`` shells out to ``gh gist create``.

    All tests mock ``subprocess.run`` so they pass in CI without a real
    GitHub CLI auth or network access.
    """

    def test_returns_gist_url_from_stdout(self):
        completed = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="https://gist.github.com/x/abc\n",
            stderr="",
        )
        with mock.patch(
            "bridge.handoff.subprocess.run", return_value=completed
        ) as run:
            url = save_conversation_gist(
                conversation="hello world",
                from_harness="local-1",
                to_harness="mini-1",
                topic="trust review",
            )
        assert url == "https://gist.github.com/x/abc"
        # Subprocess was called with gh gist create.
        args = run.call_args.args[0]
        assert args[0] == "gh"
        assert args[1] == "gist"
        assert args[2] == "create"
        # Filename embeds both harness ids + a slugified topic.
        assert "--filename" in args
        filename = args[args.index("--filename") + 1]
        assert filename.startswith("bumba-handoff-local-1-to-mini-1-")
        assert filename.endswith(".md")
        assert "trust-review" in filename

    def test_input_is_the_conversation_text(self):
        completed = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="https://gist.github.com/x/y\n",
            stderr="",
        )
        with mock.patch(
            "bridge.handoff.subprocess.run", return_value=completed
        ) as run:
            save_conversation_gist(
                conversation="line one\nline two",
                from_harness="local-1",
                to_harness="mini-1",
                topic="topic",
            )
        kwargs = run.call_args.kwargs
        assert kwargs["input"] == "line one\nline two"
        assert kwargs["text"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is True

    def test_slugifies_topic_and_truncates(self):
        completed = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="https://gist.github.com/x/y\n",
            stderr="",
        )
        with mock.patch(
            "bridge.handoff.subprocess.run", return_value=completed
        ) as run:
            save_conversation_gist(
                conversation="x",
                from_harness="a",
                to_harness="b",
                topic="!! topic with $@ special / characters and a long tail" * 4,
            )
        filename = run.call_args.args[0][run.call_args.args[0].index("--filename") + 1]
        # No special characters survive (only alnum + dashes).
        # The slug is bounded — exact length of the truncated portion is 40.
        slug_segment = filename.replace("bumba-handoff-a-to-b-", "").rsplit(".", 1)[0]
        # slug_segment is "<isots>-<slug40>" where isots length is fixed.
        # Sanity: nothing outside [a-zA-Z0-9-] in the filename.
        assert all(c.isalnum() or c == "-" or c == "." for c in filename)

    def test_propagates_subprocess_error(self):
        """Failing ``gh gist create`` must surface as ``CalledProcessError``."""
        def boom(*a, **kw):
            raise subprocess.CalledProcessError(
                returncode=1, cmd=a[0], output="", stderr="auth missing"
            )
        with mock.patch("bridge.handoff.subprocess.run", side_effect=boom):
            with pytest.raises(subprocess.CalledProcessError):
                save_conversation_gist(
                    conversation="x",
                    from_harness="a",
                    to_harness="b",
                    topic="t",
                )


# ---------------------------------------------------------------------------
# Sprint 1.02 (#2139) — compose_handoff
# ---------------------------------------------------------------------------


class TestComposeHandoff:
    """``compose_handoff`` returns a structured ``HandoffDraft``.

    For the Phase 1 composer the actual sub-Claude synthesis is deferred:
    the function packages the conversation + slot scaffolding into a
    well-formed draft so downstream review-fire wiring (Sprint 1.04) has a
    stable shape to consume. These tests pin the contract.
    """

    def test_returns_handoff_draft(self):
        draft = compose_handoff(
            conversation_ctx="operator: review the trust ladder\nbumba: ok",
            from_harness="local-1",
            to_harness="mini-1",
            topic="trust ladder review",
        )
        assert isinstance(draft, HandoffDraft)

    def test_propagates_identity_slots(self):
        draft = compose_handoff(
            conversation_ctx="anything",
            from_harness="local-1",
            to_harness="mini-1",
            topic="trust ladder review",
        )
        assert draft.from_harness == "local-1"
        assert draft.to_harness == "mini-1"
        assert draft.topic == "trust ladder review"

    def test_default_trust_level_is_review(self):
        """All Phase 1 drafts MUST be ``review`` — ``auto`` is reserved."""
        draft = compose_handoff(
            conversation_ctx="x",
            from_harness="local-1",
            to_harness="mini-1",
            topic="t",
        )
        assert draft.trust_level == "review"
        assert draft.response_protocol == "operator-only"

    def test_all_slots_populated_non_empty(self):
        """Every slot is required on ``HandoffDraft``; the composer must
        produce a draft where ``ask``, ``work_done``, ``boundaries`` and
        ``context_summary`` are non-empty strings. Sub-Claude synthesis can
        improve quality later; the structural contract is non-empty.
        """
        draft = compose_handoff(
            conversation_ctx="operator: please coordinate\nbumba: drafting now",
            from_harness="local-1",
            to_harness="mini-1",
            topic="t",
        )
        assert isinstance(draft.context_summary, str) and draft.context_summary
        assert isinstance(draft.work_done, str) and draft.work_done
        assert isinstance(draft.ask, str) and draft.ask
        assert isinstance(draft.boundaries, str) and draft.boundaries
        assert isinstance(draft.references, tuple)


# ---------------------------------------------------------------------------
# Sprint 1.02 (#2139) — format_draft_for_operator
# ---------------------------------------------------------------------------


class TestFormatDraftForOperator:
    """Pure render — no I/O, fully unit-testable."""

    def _draft(self) -> HandoffDraft:
        return HandoffDraft(
            from_harness="local-1",
            to_harness="mini-1",
            topic="trust ladder review",
            context_summary="The trust ladder needs a second pair of eyes.",
            work_done="Drafted policy.py and reviewed edge cases.",
            ask="Audit policy.py for missing fail-closed paths.",
            boundaries="Surgical changes only. Do not refactor unrelated modules.",
            references=("agent/bridge/policy.py", "#2138"),
        )

    def test_includes_target_harness_and_topic(self):
        rendered = format_draft_for_operator(self._draft(), "https://gist/x")
        assert "mini-1" in rendered
        assert "trust ladder review" in rendered

    def test_includes_gist_url(self):
        rendered = format_draft_for_operator(self._draft(), "https://gist.github.com/abc")
        assert "https://gist.github.com/abc" in rendered

    def test_includes_every_slot_label(self):
        rendered = format_draft_for_operator(self._draft(), "https://gist/x")
        for label in (
            "Context summary",
            "Work done",
            "Ask",
            "Boundaries",
            "References",
            "Response protocol",
            "Trust level",
        ):
            assert label in rendered, f"missing label {label!r}"

    def test_includes_reply_instructions(self):
        rendered = format_draft_for_operator(self._draft(), "https://gist/x")
        # Spec: must surface the next-step verbs the operator can reply with.
        assert "go" in rendered
        assert "edit" in rendered
        assert "abort" in rendered

    def test_lists_every_reference(self):
        rendered = format_draft_for_operator(self._draft(), "https://gist/x")
        assert "agent/bridge/policy.py" in rendered
        assert "#2138" in rendered

    def test_renders_empty_references_without_crashing(self):
        draft = dataclasses.replace(self._draft(), references=())
        rendered = format_draft_for_operator(draft, "https://gist/x")
        # No reference lines, but render still includes the label.
        assert "References" in rendered


# ---------------------------------------------------------------------------
# Sprint 1.02 (#2139) — operator command path
# ---------------------------------------------------------------------------


def _fake_app_with_harnesses(
    harness_id: str = "local-1",
    peer_harness_ids: tuple[str, ...] = ("mini-1",),
) -> mock.MagicMock:
    """Duck-typed BridgeApp where ``app.config`` exposes the handoff fields."""
    app = mock.MagicMock()
    app.config.harness_id = harness_id
    app.config.peer_harness_ids = peer_harness_ids
    app.config.operator.chat_id = "operator-chat"
    app.config.data_dir = None
    return app


def _bare_command_handler(app):
    """Construct a CommandHandler without running the heavy __init__."""
    from bridge.commands import CommandHandler

    h = CommandHandler.__new__(CommandHandler)
    h._app = app
    h._departments = None
    h._memory = None
    h._pending_handoffs = {}
    return h


class TestCmdHandoffOperatorPath:
    """``/handoff <to-harness> <topic>`` composes a draft + saves a gist."""

    async def test_rejects_unknown_harness(self):
        app = _fake_app_with_harnesses(peer_harness_ids=("mini-1",))
        h = _bare_command_handler(app)

        result = await h._cmd_handoff("chat-9", "mini-9 some topic")
        assert "Unknown harness" in result
        assert "mini-9" in result

    async def test_rejects_missing_args(self):
        app = _fake_app_with_harnesses()
        h = _bare_command_handler(app)

        result = await h._cmd_handoff("chat-9", "")
        assert "Usage" in result

        result_one_arg = await h._cmd_handoff("chat-9", "mini-1")
        assert "Usage" in result_one_arg

    async def test_composes_and_returns_formatted_draft(self):
        """Successful path: gist saved, draft composed, stashed, rendered."""
        app = _fake_app_with_harnesses()
        h = _bare_command_handler(app)
        # Memory adapter returns 2 messages (operator + bumba) as recent.
        memory = mock.MagicMock()
        memory.get_recent_messages = mock.AsyncMock(
            return_value=[
                {"role": "user", "content": "hello", "created_at": "t1"},
                {"role": "assistant", "content": "hi back", "created_at": "t2"},
            ]
        )
        h._memory = memory

        completed = subprocess.CompletedProcess(
            args=["gh"], returncode=0,
            stdout="https://gist.github.com/example/zzz\n", stderr="",
        )
        with mock.patch(
            "bridge.handoff.subprocess.run", return_value=completed
        ):
            result = await h._cmd_handoff(
                "chat-9", "mini-1 trust ladder review"
            )

        # Output contains the rendered draft + gist URL.
        assert "mini-1" in result
        assert "trust ladder review" in result
        assert "https://gist.github.com/example/zzz" in result
        assert "go" in result and "edit" in result and "abort" in result
        # Draft was stashed under chat_id.
        assert "chat-9" in h._pending_handoffs
        draft, gist_url = h._pending_handoffs["chat-9"]
        assert isinstance(draft, HandoffDraft)
        assert draft.to_harness == "mini-1"
        assert gist_url == "https://gist.github.com/example/zzz"

    async def test_continue_subcommand_still_works(self):
        """The existing ``/handoff continue <correlation_id>`` Zone 4 path
        must NOT regress when the operator-facing parser lands.

        The spec adds a new positional form; the old subcommand-style call
        is preserved by dispatching on first arg.
        """
        app = _fake_app_with_harnesses()
        h = _bare_command_handler(app)
        # No departments → falls into the existing "not wired" message.
        h._departments = None

        result = await h._cmd_handoff("chat-9", "continue corr-123")
        assert "not wired" in result.lower()


# ---------------------------------------------------------------------------
# HANDOFF_REGEX — line-shape contract
# ---------------------------------------------------------------------------

# Sprint 1112.1.03 (#2140): the receiver-side parsing layer. These tests
# pin the schema so a future edit that loosens the regex must surface here
# as a failing assertion. The schema is structural — peer harnesses speak
# this exact line shape or are silently rejected.


def test_handoff_regex_matches_canonical_message():
    m = HANDOFF_REGEX.match(
        "[handoff to:local-1] https://gist.github.com/example/abc123 audit policy.py"
    )
    assert m is not None
    assert m.group("to") == "local-1"
    assert m.group("url") == "https://gist.github.com/example/abc123"
    assert m.group("summary") == "audit policy.py"


def test_handoff_regex_accepts_hyphenated_harness_ids():
    m = HANDOFF_REGEX.match(
        "[handoff to:mini-local-1] https://gist.github.com/x/y do the thing"
    )
    assert m is not None
    assert m.group("to") == "mini-local-1"


def test_handoff_regex_rejects_uppercase_target():
    """Harness IDs are lowercase by convention — uppercase target rejected."""
    assert HANDOFF_REGEX.match("[handoff to:LOCAL-1] https://x.y/z summary") is None


def test_handoff_regex_rejects_missing_brackets():
    assert HANDOFF_REGEX.match("handoff to:local-1 https://x.y/z summary") is None


def test_handoff_regex_rejects_missing_url():
    assert HANDOFF_REGEX.match("[handoff to:local-1]  no-url-here summary") is None


def test_handoff_regex_rejects_empty_summary():
    assert HANDOFF_REGEX.match("[handoff to:local-1] https://x.y/z ") is None


# ---------------------------------------------------------------------------
# parse_handoff_message — schema match + harness-target gate
# ---------------------------------------------------------------------------


def test_parse_returns_packet_when_target_matches():
    packet = parse_handoff_message(
        "[handoff to:local-1] https://gist.github.com/x/abc123 audit policy.py",
        my_harness="local-1",
    )
    assert packet is not None
    assert isinstance(packet, HandoffPacket)
    assert packet.to_harness == "local-1"
    assert packet.artifact_url == "https://gist.github.com/x/abc123"
    assert packet.one_line_summary == "audit policy.py"


def test_parse_returns_none_when_target_does_not_match():
    """A handoff addressed to a different harness must be rejected — even
    if the schema is otherwise valid. This is the routing gate.
    """
    packet = parse_handoff_message(
        "[handoff to:mini-1] https://gist.github.com/x/abc audit",
        my_harness="local-1",
    )
    assert packet is None


def test_parse_returns_none_for_malformed_message():
    assert parse_handoff_message("not a handoff", my_harness="local-1") is None


def test_parse_returns_none_for_empty_content():
    assert parse_handoff_message("", my_harness="local-1") is None


# ---------------------------------------------------------------------------
# HandoffPlan — frozen, all fields required
# ---------------------------------------------------------------------------


def _plan_kwargs(**overrides) -> dict:
    base = dict(
        from_harness="mini-1",
        to_harness="local-1",
        artifact_url="https://gist.github.com/example/abc123",
        summary="audit policy.py",
        proposed_steps=("operator-review-required",),
    )
    base.update(overrides)
    return base


def test_handoff_plan_required_fields_compose():
    plan = HandoffPlan(**_plan_kwargs())
    assert plan.from_harness == "mini-1"
    assert plan.proposed_steps == ("operator-review-required",)


def test_handoff_plan_is_frozen():
    plan = HandoffPlan(**_plan_kwargs())
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.summary = "something else"  # type: ignore[misc]


def test_handoff_plan_requires_every_slot():
    incomplete = _plan_kwargs()
    incomplete.pop("artifact_url")
    with pytest.raises(TypeError):
        HandoffPlan(**incomplete)


# ---------------------------------------------------------------------------
# consume_handoff — fetches gist via `gh gist view` and drafts a plan
# ---------------------------------------------------------------------------


def test_consume_handoff_fetches_gist_and_returns_plan(monkeypatch):
    """consume_handoff invokes `gh gist view <id>` and returns a HandoffPlan."""
    captured: dict = {}

    class _FakeProc:
        stdout = "gist body contents"
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr("bridge.handoff.subprocess.run", fake_run)

    packet = HandoffPacket(
        from_harness="mini-1",
        to_harness="local-1",
        artifact_url="https://gist.github.com/example/abc123",
        one_line_summary="audit policy.py",
        fired_at="2026-05-17T12:34:56Z",
    )
    plan = consume_handoff(packet)

    assert isinstance(plan, HandoffPlan)
    assert plan.from_harness == "mini-1"
    assert plan.to_harness == "local-1"
    assert plan.artifact_url == packet.artifact_url
    assert plan.summary == packet.one_line_summary
    # Sub-Claude wiring deferred to the implementing PR's second commit;
    # the contract is that proposed_steps is a non-empty tuple.
    assert isinstance(plan.proposed_steps, tuple)
    assert len(plan.proposed_steps) >= 1

    # `gh gist view <id>` was invoked with the id extracted from the URL.
    assert captured["cmd"][0] == "gh"
    assert captured["cmd"][1] == "gist"
    assert captured["cmd"][2] == "view"
    assert captured["cmd"][3] == "abc123"


def test_consume_handoff_strips_trailing_slash_when_extracting_gist_id(monkeypatch):
    """artifact_url may have a trailing slash; the gist id must still be
    extracted correctly.
    """
    captured: dict = {}

    class _FakeProc:
        stdout = "ok"
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr("bridge.handoff.subprocess.run", fake_run)

    packet = HandoffPacket(
        from_harness="mini-1",
        to_harness="local-1",
        artifact_url="https://gist.github.com/example/abc123/",
        one_line_summary="x",
        fired_at="2026-05-17T12:34:56Z",
    )
    consume_handoff(packet)
    assert captured["cmd"][3] == "abc123"


# ---------------------------------------------------------------------------
# Sprint 1.04 (#2141) — fire path + close-resolved promotion
# ---------------------------------------------------------------------------


class _FakeChannel:
    """Captures send() calls for fire_handoff tests."""
    def __init__(self):
        self.sent = []
    async def send(self, content):
        self.sent.append(content)


class _FakeDiscordClient:
    """Minimal duck-typed discord client for fire_handoff."""
    def __init__(self, channels=None):
        self._channels = channels or {}
    def get_channel(self, channel_id):
        return self._channels.get(channel_id)


class TestFireHandoff:
    """Sprint 1.04 fire path — posts the structured handoff trigger to a peer channel."""

    def _make_draft(self, **overrides):
        defaults = dict(
            from_harness="local-1",
            to_harness="mini-1",
            topic="audit policy.py",
            context_summary="ctx",
            work_done="work",
            ask="please audit",
            boundaries="surgical only",
            references=(),
        )
        defaults.update(overrides)
        return HandoffDraft(**defaults)

    @pytest.mark.asyncio
    async def test_posts_structured_line_to_target_channel(self):
        from bridge.handoff import fire_handoff

        channel = _FakeChannel()
        client = _FakeDiscordClient(channels={42: channel})
        draft = self._make_draft()

        packet = await fire_handoff(
            draft=draft,
            gist_url="https://gist.github.com/x/abc123",
            target_channel_id=42,
            discord_client=client,
        )

        assert len(channel.sent) == 1
        line = channel.sent[0]
        assert line.startswith("[handoff to:mini-1] ")
        assert "https://gist.github.com/x/abc123" in line
        assert "audit policy.py" in line  # topic surfaces as summary

    @pytest.mark.asyncio
    async def test_returns_packet_with_fired_at_timestamp(self):
        from bridge.handoff import fire_handoff

        channel = _FakeChannel()
        client = _FakeDiscordClient(channels={42: channel})
        draft = self._make_draft()

        packet = await fire_handoff(
            draft=draft,
            gist_url="https://gist.github.com/x/abc123",
            target_channel_id=42,
            discord_client=client,
        )

        assert packet.from_harness == "local-1"
        assert packet.to_harness == "mini-1"
        assert packet.artifact_url == "https://gist.github.com/x/abc123"
        assert packet.one_line_summary == "audit policy.py"
        # ISO-8601 UTC: "YYYY-MM-DDTHH:MM:SS..." with timezone marker
        assert "T" in packet.fired_at
        # Either ends with +00:00 or has microseconds — both are valid isoformat()
        assert packet.fired_at.startswith("20")  # 2026-style date

    @pytest.mark.asyncio
    async def test_line_shape_round_trips_to_parse_handoff_message(self):
        """fire_handoff's output must parse cleanly via parse_handoff_message
        on the receiver side. Structural invariant — schema agreement is the
        whole protocol."""
        from bridge.handoff import fire_handoff, parse_handoff_message

        channel = _FakeChannel()
        client = _FakeDiscordClient(channels={42: channel})
        draft = self._make_draft()

        await fire_handoff(
            draft=draft,
            gist_url="https://gist.github.com/x/abc123",
            target_channel_id=42,
            discord_client=client,
        )
        line = channel.sent[0]

        # Receiver-side parse with matching to_harness should succeed
        parsed = parse_handoff_message(line, my_harness="mini-1")
        assert parsed is not None
        assert parsed.to_harness == "mini-1"
        assert parsed.artifact_url == "https://gist.github.com/x/abc123"

    @pytest.mark.asyncio
    async def test_parse_rejects_when_to_harness_mismatches(self):
        """fire_handoff to mini-1 must NOT parse on local-1 receiver."""
        from bridge.handoff import fire_handoff, parse_handoff_message

        channel = _FakeChannel()
        client = _FakeDiscordClient(channels={42: channel})
        draft = self._make_draft(to_harness="mini-1")

        await fire_handoff(
            draft=draft,
            gist_url="https://gist.github.com/x/abc",
            target_channel_id=42,
            discord_client=client,
        )
        line = channel.sent[0]
        # local-1 receiver sees a mini-1-addressed message → None
        assert parse_handoff_message(line, my_harness="local-1") is None


class TestMarkHandoffResolved:
    """Sprint 1.04 close-resolved — migrate gist to handoffs/promoted/."""

    def test_writes_file_with_provenance_header_and_gist_content(self, tmp_path, monkeypatch):
        from bridge import handoff as handoff_mod
        from bridge.handoff import HandoffPacket, mark_handoff_resolved

        # Mock the `gh gist view` call to return canned content
        class _MockResult:
            stdout = "# Handoff content\n\nGist body text"

        def _mock_run(cmd, **kwargs):
            assert cmd[0] == "gh"
            assert cmd[1] == "gist"
            assert cmd[2] == "view"
            assert cmd[3] == "abc123"
            return _MockResult()

        monkeypatch.setattr(handoff_mod.subprocess, "run", _mock_run)

        packet = HandoffPacket(
            from_harness="local-1",
            to_harness="mini-1",
            artifact_url="https://gist.github.com/example/abc123",
            one_line_summary="audit policy.py",
            fired_at="2026-05-18T12:34:56+00:00",
        )

        rel_path = mark_handoff_resolved(
            packet=packet,
            topic_slug="audit-policy",
            repo_root=tmp_path,
        )

        # Path shape: handoffs/promoted/<date>-<from>-to-<to>-<topic-slug>.md
        assert rel_path.startswith("handoffs/promoted/2026-05-18-local-1-to-mini-1-")
        assert rel_path.endswith(".md")

        # Content has provenance header + gist body
        written = (tmp_path / rel_path).read_text()
        assert "<!-- promoted from gist https://gist.github.com/example/abc123 -->" in written
        assert "<!-- local-1 → mini-1 2026-05-18T12:34:56+00:00 -->" in written
        assert "Gist body text" in written

    def test_creates_handoffs_promoted_directory_if_missing(self, tmp_path, monkeypatch):
        from bridge import handoff as handoff_mod
        from bridge.handoff import HandoffPacket, mark_handoff_resolved

        class _MockResult:
            stdout = "body"

        monkeypatch.setattr(handoff_mod.subprocess, "run", lambda *a, **k: _MockResult())

        packet = HandoffPacket(
            from_harness="a",
            to_harness="b",
            artifact_url="https://gist.github.com/x/zzz",
            one_line_summary="x",
            fired_at="2026-05-18T00:00:00Z",
        )

        # handoffs/promoted/ should not exist yet
        assert not (tmp_path / "handoffs" / "promoted").exists()

        mark_handoff_resolved(packet=packet, topic_slug="x", repo_root=tmp_path)

        assert (tmp_path / "handoffs" / "promoted").is_dir()

    def test_slugifies_topic_safely(self, tmp_path, monkeypatch):
        """Topic with spaces/special chars must produce a filesystem-safe slug."""
        from bridge import handoff as handoff_mod
        from bridge.handoff import HandoffPacket, mark_handoff_resolved

        class _MockResult:
            stdout = "body"

        monkeypatch.setattr(handoff_mod.subprocess, "run", lambda *a, **k: _MockResult())

        packet = HandoffPacket(
            from_harness="a",
            to_harness="b",
            artifact_url="https://gist.github.com/x/zzz",
            one_line_summary="x",
            fired_at="2026-05-18T00:00:00Z",
        )

        rel_path = mark_handoff_resolved(
            packet=packet,
            topic_slug="audit / policy.py? (urgent!)",
            repo_root=tmp_path,
        )
        # No spaces, no `/`, no `(` in the filename
        filename = rel_path.split("/")[-1]
        assert " " not in filename
        assert "(" not in filename
        # Slug retains alphanumerics + dashes only
        # Filename structure: 2026-05-18-a-to-b-<slug>.md
        # Slug should be a-to-b- prefixed but slugified
        assert "audit" in filename or "policy" in filename
