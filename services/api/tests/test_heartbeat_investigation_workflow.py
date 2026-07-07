from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from api.runtime_control import ControlPlaneError
from api.webhooks import HeaderTriggerKey, HmacAuth
from api.workflows.heartbeat_investigation import (
    WEBHOOKS,
    Input,
    _build_prompt,
    handler,
)


class FakeContext:
    run_id = "run-123"


def _webhook_input(**failure_overrides) -> Input:
    failure = {
        "family": "CVI/fal",
        "env": "prod",
        "provider": "fal",
        "job_id": "job-42",
        "error": "boom: timed out",
        "logs_url": "https://heartbeat.tavus.io/job/job-42",
        "conversation_id": "c123",
        **failure_overrides,
    }
    return Input(
        webhook={
            "body": {
                "failure": failure,
                "delivery": {"channel": "C_HEARTBEATS", "thread_ts": "1700.99"},
            }
        }
    )


def test_webhook_spec_is_hmac_signed_with_header_trigger_key():
    assert len(WEBHOOKS) == 1
    spec = WEBHOOKS[0]
    assert spec.slug == "heartbeat"
    assert isinstance(spec.auth, HmacAuth)
    assert spec.auth.secret_ref == "HEARTBEAT_WEBHOOK_SECRET"
    assert isinstance(spec.trigger_key, HeaderTriggerKey)
    assert spec.trigger_key.header == "X-Heartbeat-Event-Id"


def test_input_parses_failure_and_delivery():
    inp = _webhook_input()
    assert inp.failure["provider"] == "fal"
    assert inp.delivery_target == {"channel": "C_HEARTBEATS", "thread_ts": "1700.99"}


def test_build_prompt_includes_context_and_tldr_instruction():
    prompt = _build_prompt(_webhook_input().failure)
    assert "CVI/fal" in prompt
    assert "job-42" in prompt
    assert "c123" in prompt
    assert "boom: timed out" in prompt
    assert "TL;DR" in prompt


def test_build_prompt_requires_realtime_replica_rate_limit_checklist():
    prompt = _build_prompt(_webhook_input(conversation_id="c67c1c61738c44c9").failure)
    assert "Required SigNoz checklist" in prompt
    assert "call signoz ready" in prompt
    assert '"service":"realtime-replica"' in prompt
    assert '"searchText":"c67c1c61738c44c9"' in prompt
    assert "Too Many Requests" in prompt
    assert "429" in prompt
    assert "ConnectError" in prompt
    assert "HTTP error" in prompt
    assert "TransportStep failed to boot" in prompt
    assert "livekit_ffi" in prompt


@pytest.mark.asyncio
async def test_handler_dispatches_investigation_to_failure_thread():
    inp = _webhook_input()
    with patch("api.workflow_engine.do_agent_turn", new_callable=AsyncMock) as do_turn:
        do_turn.return_value = {"result_text": "investigated"}
        await handler(inp, FakeContext())

    do_turn.assert_awaited_once()
    _, kwargs = do_turn.call_args
    assert kwargs["persona"] == "eng"
    assert kwargs["thread_key"] == "heartbeat:fal:job-42"
    delivery = kwargs["delivery"]
    assert delivery.platform == "slack"
    assert delivery.channel == "C_HEARTBEATS"
    assert delivery.thread_ts == "1700.99"
    assert kwargs["parts"] and kwargs["parts"][0]["type"] == "text"


@pytest.mark.asyncio
async def test_handler_rejects_missing_delivery_target():
    inp = Input(webhook={"body": {"failure": {"job_id": "x"}, "delivery": {}}})
    with pytest.raises(ControlPlaneError):
        await handler(inp, FakeContext())
