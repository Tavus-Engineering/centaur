"""Regression tests for runtime resilience paths."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from api.sandbox.base import RuntimeState, SandboxSession


class _EOFReattachBackend:
    def __init__(self) -> None:
        self.stream_calls = 0
        self.status_calls = 0
        self.close_streams = AsyncMock()
        self.attach = AsyncMock()

    async def stream_stdout(self, _session):
        self.stream_calls += 1
        if self.stream_calls == 1:
            if False:
                yield ""
            return
        yield json.dumps({"type": "result", "subtype": "success", "result": "OK"})

    async def status(self, _session):
        self.status_calls += 1
        return "running" if self.status_calls == 1 else "gone"


class _KnownUserEventBackend:
    async def stream_stdout(self, _session):
        yield json.dumps({"type": "user", "message": {"content": []}})
        yield json.dumps({"type": "turn.done", "result": "OK"})

    async def status(self, _session):
        return "gone"


class _UnknownEventBackend:
    async def stream_stdout(self, _session):
        yield json.dumps({"type": "mystery_event"})
        yield json.dumps({"type": "turn.done", "result": "OK"})

    async def status(self, _session):
        return "gone"


class _CodexTurnFailedBackend:
    """Codex turn that streams commentary, then dies (e.g. remote compaction 502)."""

    async def stream_stdout(self, _session):
        yield json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agentMessage",
                    "id": "msg_1",
                    "text": "One ambiguity remains; narrowing it down.",
                },
            }
        )
        yield json.dumps(
            {
                "type": "turn.failed",
                "error": {
                    "message": (
                        "Error running remote compact task: unexpected status "
                        "502 Bad Gateway"
                    ),
                },
            }
        )

    async def status(self, _session):
        return "gone"


def test_elapsed_since_uses_monotonic_delta_when_available() -> None:
    from api.agent import _elapsed_since

    with (
        patch("api.agent.time.monotonic", return_value=105.25),
        patch("api.agent.time.time", return_value=9999.0),
    ):
        assert _elapsed_since(100.0) == 5.25


def test_elapsed_since_falls_back_when_start_looks_like_epoch_time() -> None:
    from api.agent import _elapsed_since

    with (
        patch("api.agent.time.monotonic", return_value=200.0),
        patch("api.agent.time.time", return_value=1005.2),
    ):
        assert _elapsed_since(1000.0) == 5.2


@pytest.mark.asyncio
async def test_stream_stdout_reattaches_when_running_eof() -> None:
    from api.agent import _stream_stdout

    session = SandboxSession(
        sandbox_id="sbx-reattach-1",
        thread_key="test:reattach",
        harness="amp",
        engine="amp",
    )
    rt = RuntimeState()
    rt.turn_counter = 1
    backend = _EOFReattachBackend()

    with (
        patch("api.agent._persist_turn_messages", new_callable=AsyncMock),
        patch("api.agent._db_complete_inflight_turn", new_callable=AsyncMock),
        patch("api.agent.STREAM_EOF_REATTACH_BACKOFF_S", 0),
    ):
        events = [
            event
            async for event in _stream_stdout(
                session,
                backend,
                rt,
                turn_id=1,
                t0=time.monotonic(),
            )
        ]

    decoded = [json.loads(item["data"]) for item in events]
    assert any(
        evt.get("type") == "turn.done" and evt.get("result") == "OK" for evt in decoded
    )
    backend.close_streams.assert_awaited_once_with(session)
    backend.attach.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_stream_stdout_accepts_user_events_without_warning() -> None:
    from api.agent import _stream_stdout

    session = SandboxSession(
        sandbox_id="sbx-known-user",
        thread_key="test:known-user",
        harness="amp",
        engine="amp",
    )
    rt = RuntimeState()
    backend = _KnownUserEventBackend()

    with (
        patch("api.agent._persist_turn_messages", new_callable=AsyncMock),
        patch("api.agent._db_complete_inflight_turn", new_callable=AsyncMock),
        patch("api.agent.log.warning") as warning,
    ):
        [
            event
            async for event in _stream_stdout(
                session,
                backend,
                rt,
                turn_id=1,
                t0=time.monotonic(),
            )
        ]

    assert not any(
        call.args and call.args[0] == "stdout_unknown_event_type"
        for call in warning.call_args_list
    )


def test_terminal_error_extracted_from_codex_turn_failed() -> None:
    from api.agent import _terminal_error_from_harness_event

    assert (
        _terminal_error_from_harness_event(
            {"type": "turn.failed", "error": {"message": "compact task failed"}}
        )
        == "compact task failed"
    )
    assert (
        _terminal_error_from_harness_event(
            {"type": "turn.failed", "error": "plain string error"}
        )
        == "plain string error"
    )
    assert (
        _terminal_error_from_harness_event({"type": "turn.failed"})
        == "Harness reported a failed turn"
    )
    assert _terminal_error_from_harness_event({"type": "turn.completed"}) is None


@pytest.mark.asyncio
async def test_stream_stdout_marks_codex_turn_failed_as_error() -> None:
    from api.agent import _stream_stdout

    session = SandboxSession(
        sandbox_id="sbx-turn-failed",
        thread_key="test:turn-failed",
        harness="codex",
        engine="codex",
    )
    rt = RuntimeState()
    rt.turn_counter = 1
    backend = _CodexTurnFailedBackend()

    with (
        patch("api.agent._persist_turn_messages", new_callable=AsyncMock),
        patch("api.agent._db_complete_inflight_turn", new_callable=AsyncMock),
    ):
        events = [
            event
            async for event in _stream_stdout(
                session,
                backend,
                rt,
                turn_id=1,
                t0=time.monotonic(),
            )
        ]

    decoded = [json.loads(item["data"]) for item in events]
    turn_done = next(evt for evt in decoded if evt.get("type") == "turn.done")
    assert turn_done["is_error"] is True
    assert "502 Bad Gateway" in turn_done["error"]
    # The streamed commentary stays as the result so context is not lost.
    assert turn_done["result"] == "One ambiguity remains; narrowing it down."


@pytest.mark.asyncio
async def test_stream_stdout_warns_for_unknown_event_types() -> None:
    from api.agent import _stream_stdout

    session = SandboxSession(
        sandbox_id="sbx-unknown",
        thread_key="test:unknown-event",
        harness="amp",
        engine="amp",
    )
    rt = RuntimeState()
    backend = _UnknownEventBackend()

    with (
        patch("api.agent._persist_turn_messages", new_callable=AsyncMock),
        patch("api.agent._db_complete_inflight_turn", new_callable=AsyncMock),
        patch("api.agent.log.warning") as warning,
    ):
        [
            event
            async for event in _stream_stdout(
                session,
                backend,
                rt,
                turn_id=1,
                t0=time.monotonic(),
            )
        ]

    warning.assert_any_call(
        "stdout_unknown_event_type",
        type="mystery_event",
        thread_key="test:unknown-event",
        sandbox="sbx-unknown",
    )


@pytest.mark.asyncio
async def test_reconcile_tick_falls_back_to_gone_when_suspended_missing() -> None:
    from api.agent import reconcile_tick

    rows = [{"thread_key": "thread-1", "sandbox_id": "sandbox-1", "state": "running"}]
    pool = AsyncMock()
    pool.fetch = AsyncMock(side_effect=[rows, []])

    async def _execute(query: str, *args):
        if "SET state = 'suspended'" in query:
            raise RuntimeError("invalid input value for state")
        return None

    pool.execute = AsyncMock(side_effect=_execute)

    backend = AsyncMock()
    backend.status_by_id = AsyncMock(return_value="exited")

    with (
        patch("api.agent._get_pool", return_value=pool),
        patch("api.agent.get_backend", return_value=backend),
        patch("api.agent._drop_runtime"),
    ):
        await reconcile_tick()

    state_updates = [
        call.args
        for call in pool.execute.await_args_list
        if "UPDATE sandbox_sessions SET state" in call.args[0]
    ]
    assert any("SET state = 'gone'" in query for query, *_ in state_updates)


@pytest.mark.asyncio
async def test_reconcile_tick_isolates_row_failures() -> None:
    from api.agent import reconcile_tick

    rows = [
        {"thread_key": "thread-1", "sandbox_id": "sandbox-1", "state": "running"},
        {"thread_key": "thread-2", "sandbox_id": "sandbox-2", "state": "running"},
    ]
    pool = AsyncMock()
    pool.fetch = AsyncMock(side_effect=[rows, []])

    async def _execute(query: str, *args):
        thread_key = args[0] if args else None
        if "SET state = 'suspended'" in query and thread_key == "thread-1":
            raise RuntimeError("thread-1 suspended update failed")
        if "SET state = 'gone'" in query and thread_key == "thread-1":
            raise RuntimeError("thread-1 gone fallback failed")
        return None

    pool.execute = AsyncMock(side_effect=_execute)

    backend = AsyncMock()
    backend.status_by_id = AsyncMock(return_value="exited")

    with (
        patch("api.agent._get_pool", return_value=pool),
        patch("api.agent.get_backend", return_value=backend),
        patch("api.agent._drop_runtime"),
    ):
        await reconcile_tick()

    touched_threads = [
        args[1]
        for args in (call.args for call in pool.execute.await_args_list)
        if len(args) >= 2 and "UPDATE sandbox_sessions SET state" in args[0]
    ]
    assert "thread-2" in touched_threads
