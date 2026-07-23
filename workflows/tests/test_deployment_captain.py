from __future__ import annotations

import asyncio
import inspect

from workflows import deployment_captain


class FakeContext:
    def __init__(self) -> None:
        self.run_id = "wf-123"
        self.release_status_calls = 0
        self.notifications: list[str] = []
        self.announcements: list[str] = []

    async def step(self, name, fn, **kwargs):
        del name, kwargs
        result = fn()
        return await result if inspect.isawaitable(result) else result

    async def sleep(self, name, duration):
        del name, duration

    async def call_tool(self, tool, method, args):
        assert tool == "deployment-captain"
        if method == "start_release":
            return {
                "version": "3.4.5",
                "merge_commit_sha": "b" * 40,
            }
        if method == "release_run_status":
            self.release_status_calls += 1
            base = {
                "found": True,
                "run_id": 700,
                "url": "https://github.test/run/700",
                "jobs": [],
            }
            if self.release_status_calls <= 2:
                environments = (
                    [
                        {"name": "promote-to-prod-cerebrium"},
                        {"name": "promote-to-prod-fal"},
                        {"name": "promote-to-prod-modal"},
                    ]
                    if args["service"] == "cvi"
                    else [{"name": "manual-approval"}]
                )
                return {
                    **base,
                    "status": "waiting",
                    "all_production_gates_ready": True,
                    "pending_environments": environments,
                }
            if self.release_status_calls == 3:
                return {
                    **base,
                    "status": "in_progress",
                    "all_production_gates_ready": False,
                }
            return {
                **base,
                "status": "completed",
                "conclusion": "success",
                "all_production_gates_ready": False,
            }
        raise AssertionError(f"unexpected tool method: {method}")

    async def post_to_slack(self, channel, text, **kwargs):
        assert channel == "C123"
        assert kwargs["thread_ts"] == "1234.5"
        self.notifications.append(text)
        return {"ok": True}

    async def agent_turn(self, text, **kwargs):
        assert "$tavus-announce-release" in text
        transition = kwargs["metadata"]["transition"]
        self.announcements.append(transition)
        assert "no pre-deployment coordination post" in text
        return {"permalink": "https://tavus.slack.com/archives/C08GJASBJD8/p123"}


def test_cvi_workflow_uses_existing_provider_gates_without_facades():
    ctx = FakeContext()
    inp = deployment_captain.Input(
        service="cvi",
        pr_number=10,
        head_sha="a" * 40,
        confirmation="deploy",
        slack_channel="C123",
        slack_thread_ts="1234.5",
    )

    result = asyncio.run(deployment_captain.handler(inp, ctx))

    assert result["conclusion"] == "success"
    assert result["production_approval"] == "human"
    assert ctx.announcements == ["staging-ready", "production-promotion"]
    assert any(
        "promote-to-prod-cerebrium" in message for message in ctx.notifications
    )
    assert any("approve in GitHub" in message for message in ctx.notifications)


def test_rqh_workflow_announces_manual_production_gate():
    ctx = FakeContext()
    inp = deployment_captain.Input(
        service="rqh",
        pr_number=10,
        head_sha="a" * 40,
        confirmation="deploy",
        slack_channel="C123",
        slack_thread_ts="1234.5",
    )

    result = asyncio.run(deployment_captain.handler(inp, ctx))

    assert result["conclusion"] == "success"
    assert any(
        "manual-approval" in message for message in ctx.notifications
    )
    assert ctx.announcements == ["staging-ready", "production-promotion"]


def test_workflow_holds_failed_existing_run_then_notices_same_run_retry():
    class FailureRecoveryContext(FakeContext):
        async def call_tool(self, tool, method, args):
            if method != "release_run_status":
                return await super().call_tool(tool, method, args)

            self.release_status_calls += 1
            base = {
                "found": True,
                "run_id": 700,
                "url": "https://github.test/run/700",
            }
            if self.release_status_calls <= 2:
                return {
                    **base,
                    "status": "completed",
                    "conclusion": "failure",
                    "all_production_gates_ready": False,
                    "jobs": [
                        {
                            "name": "Build and Push Service Image to ECR (Staging)",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ],
                }
            if self.release_status_calls == 3:
                return {
                    **base,
                    "status": "in_progress",
                    "all_production_gates_ready": False,
                    "jobs": [],
                }
            if self.release_status_calls == 4:
                return {
                    **base,
                    "status": "waiting",
                    "all_production_gates_ready": True,
                    "jobs": [],
                }
            if self.release_status_calls == 5:
                return {
                    **base,
                    "status": "in_progress",
                    "all_production_gates_ready": False,
                    "jobs": [],
                }
            return {
                **base,
                "status": "completed",
                "conclusion": "success",
                "all_production_gates_ready": False,
                "jobs": [],
            }

    ctx = FailureRecoveryContext()
    inp = deployment_captain.Input(
        service="rqh",
        pr_number=10,
        head_sha="a" * 40,
        confirmation="deploy",
        slack_channel="C123",
        slack_thread_ts="1234.5",
    )

    result = asyncio.run(deployment_captain.handler(inp, ctx))

    assert result["conclusion"] == "success"
    assert any("has failed jobs" in message for message in ctx.notifications)
    assert ctx.announcements == ["staging-ready", "production-promotion"]
