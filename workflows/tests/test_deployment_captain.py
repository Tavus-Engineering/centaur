from __future__ import annotations

import asyncio
import inspect

from workflows import deployment_captain


class FakeContext:
    def __init__(self) -> None:
        self.run_id = "wf-123"
        self.traffic_fractions: list[int] = []
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
                return {**base, "status": "waiting", "all_production_gates_ready": True}
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
        if method == "dispatch_cvi_traffic":
            self.traffic_fractions.append(args["stage_fraction"])
            return {"dispatched": True}
        if method == "workflow_dispatch_status":
            return {
                "found": True,
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.test/facade",
            }
        raise AssertionError(f"unexpected tool method: {method}")

    async def post_to_slack(self, channel, text, **kwargs):
        assert channel == "C123"
        assert kwargs["thread_ts"] == "1234.5"
        self.notifications.append(text)
        return {"ok": True}

    async def agent_turn(self, text, **kwargs):
        if "$tavus-announce-release" in text:
            transition = kwargs["metadata"]["transition"]
            self.announcements.append(transition)
            assert "no pre-deployment coordination post" in text
            return {"permalink": "https://tavus.slack.com/archives/C08GJASBJD8/p123"}
        assert "observation-only" in text
        assert kwargs["thread_key"].startswith("deployment-captain:")
        return {"result_text": "GO: error rate and latency are healthy"}


def test_cvi_workflow_shifts_to_five_then_always_restores_zero():
    ctx = FakeContext()
    inp = deployment_captain.Input(
        service="cvi",
        pr_number=10,
        head_sha="a" * 40,
        confirmation="deploy",
        slack_channel="C123",
        slack_thread_ts="1234.5",
        soak_minutes=5,
    )

    result = asyncio.run(deployment_captain.handler(inp, ctx))

    assert result["conclusion"] == "success"
    assert result["production_approval"] == "human"
    assert ctx.traffic_fractions == [5, 0]
    assert ctx.announcements == ["staging-ready", "production-promotion"]
    assert any(
        "do not approve production yet" in message for message in ctx.notifications
    )
    assert any("100% production / 0% stage" in message for message in ctx.notifications)


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
        "Manual Approval for Production" in message for message in ctx.notifications
    )
    assert ctx.announcements == ["staging-ready", "production-promotion"]


def test_rqh_workflow_holds_failed_run_then_notices_same_run_retry():
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
                            "name": "Watch Agent Failure Drill (Staging Preflight)",
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


def test_cvi_hold_withholds_production_and_restores_traffic():
    class HoldContext(FakeContext):
        async def agent_turn(self, text, **kwargs):
            del text, kwargs
            return {"result_text": "HOLD: error rate is elevated"}

    ctx = HoldContext()
    inp = deployment_captain.Input(
        service="cvi",
        pr_number=10,
        head_sha="a" * 40,
        confirmation="deploy",
        slack_channel="C123",
        slack_thread_ts="1234.5",
        soak_minutes=5,
    )

    result = asyncio.run(deployment_captain.handler(inp, ctx))

    assert result["conclusion"] == "hold"
    assert result["production_approval"] == "withheld"
    assert ctx.traffic_fractions == [5, 0]
    assert ctx.announcements == []
    assert any("HOLDING CVI" in message for message in ctx.notifications)
