"""Workflow: auto-investigate a CVI heartbeat failure with the Watch Agent.

Triggered by an HMAC-signed webhook from the ``cvi-heartbeat`` service. When a
heartbeat fails, cvi-heartbeat posts a permanent failure message to the
``#heartbeat-plus-minus`` channel (the A/B "new style" channel, run in parallel
with the legacy ``#heartbeat-plus-plus``) and fires this webhook with the
failure context + the Slack coordinates of that message. The Watch Agent
(``eng`` persona) investigates the failure and its result is delivered as a
threaded reply on the failure message, so the analysis travels with the failure
as it scrolls up the channel.

Auth: HMAC over the raw request body (``X-Webhook-Signature: sha256=<hex>``),
verified by the shared webhook router. The idempotency/trigger key is taken from
``X-Heartbeat-Event-Id`` (the heartbeat job id), so a retried webhook doesn't
start a second investigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from api.runtime_control import ControlPlaneError
from api.webhooks import HeaderTriggerKey, HmacAuth, WebhookSpec
from api.workflow_engine import Delivery, WorkflowContext

WORKFLOW_NAME = "heartbeat_investigation"

# First (and currently only) consumer of the webhook mechanism. Reachable at
# POST /webhooks/heartbeat; the shared secret lives in HEARTBEAT_WEBHOOK_SECRET.
WEBHOOKS = [
    WebhookSpec(
        slug="heartbeat",
        auth=HmacAuth(secret_ref="HEARTBEAT_WEBHOOK_SECRET"),
        trigger_key=HeaderTriggerKey(header="X-Heartbeat-Event-Id"),
    )
]

# The Watch Agent's engineering persona (Tavus investigation tooling: tavus-api,
# signoz, laminar). This is the only registered persona; do NOT change to a name
# that isn't loaded or do_agent_turn will reject it.
_PERSONA = "eng"


@dataclass
class Input:
    # The webhook router delivers the request under a single ``webhook`` key.
    webhook: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> dict[str, Any]:
        body = self.webhook.get("body")
        return body if isinstance(body, dict) else {}

    @property
    def failure(self) -> dict[str, Any]:
        failure = self.body.get("failure")
        return failure if isinstance(failure, dict) else {}

    @property
    def delivery_target(self) -> dict[str, Any]:
        delivery = self.body.get("delivery")
        return delivery if isinstance(delivery, dict) else {}


def _build_prompt(failure: dict[str, Any]) -> str:
    """Investigation instructions for the Watch Agent, from the failure payload."""
    family = failure.get("family") or "a Tavus heartbeat"
    lines = [
        f"A `{family}` heartbeat just failed. Investigate the root cause and report "
        "back in this Slack thread.",
        "",
        "Failure context:",
    ]
    for label, key in (
        ("Environment", "env"),
        ("Provider", "provider"),
        ("Job ID", "job_id"),
        ("Conversation ID", "conversation_id"),
        ("Logs", "logs_url"),
    ):
        value = failure.get(key)
        if value:
            lines.append(f"• {label}: {value}")
    error = failure.get("error")
    if error:
        lines.append("")
        lines.append("Error:")
        lines.append(f"```\n{str(error)[:3000]}\n```")
    lines += [
        "",
        "Use the tools available to you (tavus-api, signoz, laminar) to correlate "
        "traces/logs around the failure, and the conversation id when present.",
        "",
        "Format your reply as:",
        "1. A first line `*TL;DR:* <one sentence: most likely cause + recommended "
        "next step>`.",
        "2. A blank line, then the detailed investigation: evidence, the code path or "
        "service implicated, and any follow-up worth taking.",
        "Be concise — this is a Slack thread reply, not a report.",
    ]
    return "\n".join(lines)


async def handler(inp: Input, ctx: WorkflowContext) -> dict[str, Any]:
    """Run one Watch Agent investigation turn, delivered to the failure thread."""
    from api.workflow_engine import do_agent_turn

    failure = inp.failure
    target = inp.delivery_target
    channel = target.get("channel")
    thread_ts = target.get("thread_ts")
    if not channel or not thread_ts:
        raise ControlPlaneError(
            "INVALID_WORKFLOW_INPUT",
            "heartbeat_investigation requires delivery.channel and delivery.thread_ts",
            422,
        )

    job_id = str(failure.get("job_id") or ctx.run_id)
    provider = failure.get("provider") or "unknown"
    thread_key = f"heartbeat:{provider}:{job_id}"

    return await do_agent_turn(
        ctx,
        thread_key=thread_key,
        parts=[{"type": "text", "text": _build_prompt(failure)}],
        metadata={"source": "heartbeat_investigation", "failure": failure},
        delivery=Delivery.slack(channel, thread_ts),
        persona=_PERSONA,
    )
