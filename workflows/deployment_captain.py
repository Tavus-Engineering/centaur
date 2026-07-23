"""Durable CVI/RQH release supervision with exact GitHub identifiers."""

from __future__ import annotations

import dataclasses
from typing import Any

from api.workflow_engine import WorkflowContext

WORKFLOW_NAME = "deployment_captain"

_POLL_SECONDS = 60
_RUN_DISCOVERY_ATTEMPTS = 20
_MAX_RELEASE_POLLS = 720
_ANNOUNCEMENT_CHANNEL = "C08GJASBJD8"
_RERUNNABLE_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}


@dataclasses.dataclass
class Input:
    service: str
    pr_number: int
    head_sha: str
    confirmation: str
    slack_channel: str
    slack_thread_ts: str


async def _tool(
    ctx: WorkflowContext,
    method: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    result = await ctx.call_tool("deployment-captain", method, args)
    if not isinstance(result, dict):
        raise RuntimeError(f"deployment-captain.{method} returned a non-object result")
    return result


async def _notify(ctx: WorkflowContext, inp: Input, step: str, text: str) -> None:
    await ctx.step(
        step,
        lambda: ctx.post_to_slack(
            inp.slack_channel,
            text,
            thread_ts=inp.slack_thread_ts,
        ),
    )


async def _wait_for_release_run(
    ctx: WorkflowContext,
    inp: Input,
    merge_commit_sha: str,
) -> dict[str, Any]:
    for attempt in range(_RUN_DISCOVERY_ATTEMPTS):
        status = await ctx.step(
            f"discover-release-run-{attempt}",
            lambda: _tool(
                ctx,
                "release_run_status",
                {"service": inp.service, "merge_commit_sha": merge_commit_sha},
            ),
        )
        if status.get("found"):
            return status
        await ctx.sleep(f"wait-for-release-run-{attempt}", 15)
    raise RuntimeError(
        f"No exact {inp.service.upper()} deployment run appeared for {merge_commit_sha}."
    )


def _failed_jobs(status: dict[str, Any]) -> list[str]:
    bad = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
    return [
        str(job.get("name"))
        for job in status.get("jobs", [])
        if job.get("status") == "completed" and job.get("conclusion") in bad
    ]


async def _poll_release(
    ctx: WorkflowContext,
    inp: Input,
    merge_commit_sha: str,
    run_id: int,
    *,
    until_gates_ready: bool,
    step_prefix: str,
) -> dict[str, Any]:
    last_failed: list[str] = []
    for attempt in range(_MAX_RELEASE_POLLS):
        status = await ctx.step(
            f"{step_prefix}-status-{attempt}",
            lambda: _tool(
                ctx,
                "release_run_status",
                {
                    "service": inp.service,
                    "merge_commit_sha": merge_commit_sha,
                    "run_id": run_id,
                },
            ),
        )
        if not status.get("found"):
            raise RuntimeError(f"Exact deployment run {run_id} disappeared.")
        if until_gates_ready and status.get("all_production_gates_ready"):
            return status
        if (
            status.get("status") == "completed"
            and status.get("conclusion") not in _RERUNNABLE_CONCLUSIONS
        ):
            return status

        failed = _failed_jobs(status)
        if (
            status.get("status") == "completed"
            and status.get("conclusion") in _RERUNNABLE_CONCLUSIONS
            and not failed
        ):
            failed = [f"workflow conclusion: {status.get('conclusion')}"]
        if failed and failed != last_failed:
            await _notify(
                ctx,
                inp,
                f"{step_prefix}-failed-jobs-{attempt}",
                f"{inp.service.upper()} deployment run {run_id} has failed jobs: "
                f"{', '.join(failed)}. I am holding and will notice an exact-run rerun.",
            )
            last_failed = failed
        elif not failed:
            last_failed = []
        await ctx.sleep(f"{step_prefix}-wait-{attempt}", _POLL_SECONDS)
    raise RuntimeError(f"Timed out supervising deployment run {run_id}.")


async def _announce_release(
    ctx: WorkflowContext,
    inp: Input,
    *,
    transition: str,
    version: str,
    run_id: int,
    run_url: str,
    merge_commit_sha: str,
    prior_announcement: Any = None,
) -> Any:
    service = inp.service.upper()
    if transition == "staging-ready":
        instruction = (
            "Post the staging-ready announcement now. The exact staging/canary deployment "
            "is healthy and ready for change-owner verification."
        )
    elif transition == "production-promotion":
        instruction = (
            "Post the production-promotion announcement now. A human consumed the GitHub "
            "production gate and promotion has begun. Reply in the same release announcement "
            "thread created by the staging-ready turn."
        )
    else:
        raise RuntimeError(f"Unsupported release announcement transition: {transition}")

    prompt = f"""Use $tavus-announce-release for this announcement-only task.

{instruction}

Exact release:
- service: {service}
- version: {version}
- GitHub Actions run: {run_url}
- run ID: {run_id}
- merge commit SHA: {merge_commit_sha}
- destination channel ID: {_ANNOUNCEMENT_CHANNEL}
- transition: {transition}
- prior announcement result: {prior_announcement!r}

Follow the current July 17 policy: no pre-deployment coordination post, acknowledgements,
author polling, or wait window. Do not deploy, approve, merge, change traffic, rerun, or roll
back anything. Return the Slack permalink after posting.
"""
    try:
        return await ctx.step(
            f"announce-{transition}",
            lambda: ctx.agent_turn(
                prompt,
                thread_key=f"deployment-captain:{ctx.run_id}:announce",
                message_id=f"deployment-captain:{ctx.run_id}:{transition}",
                metadata={
                    "source": "deployment_captain",
                    "service": inp.service,
                    "github_run_id": run_id,
                    "merge_commit_sha": merge_commit_sha,
                    "transition": transition,
                },
            ),
        )
    except Exception as exc:
        await _notify(
            ctx,
            inp,
            f"notify-{transition}-announcement-failed",
            f"{service} {transition} announcement failed: {exc}. "
            "The release remains under exact-run supervision.",
        )
        return None


async def _poll_production(
    ctx: WorkflowContext,
    inp: Input,
    merge_commit_sha: str,
    run_id: int,
    run_url: str,
    version: str,
    staging_announcement: Any,
    step_prefix: str,
) -> dict[str, Any]:
    last_failed: list[str] = []
    promotion_announced = False
    for attempt in range(_MAX_RELEASE_POLLS):
        status = await ctx.step(
            f"{step_prefix}-status-{attempt}",
            lambda: _tool(
                ctx,
                "release_run_status",
                {
                    "service": inp.service,
                    "merge_commit_sha": merge_commit_sha,
                    "run_id": run_id,
                },
            ),
        )
        if not status.get("found"):
            raise RuntimeError(f"Exact deployment run {run_id} disappeared.")

        failed = _failed_jobs(status)
        if (
            status.get("status") == "completed"
            and status.get("conclusion") in _RERUNNABLE_CONCLUSIONS
            and not failed
        ):
            failed = [f"workflow conclusion: {status.get('conclusion')}"]
        if failed and failed != last_failed:
            await _notify(
                ctx,
                inp,
                f"{step_prefix}-failed-jobs-{attempt}",
                f"{inp.service.upper()} deployment run {run_id} has failed jobs: "
                f"{', '.join(failed)}. I am holding and will notice an exact-run rerun.",
            )
            last_failed = failed
        elif not failed:
            last_failed = []
        if not failed and not status.get("all_production_gates_ready") and not promotion_announced:
            await _announce_release(
                ctx,
                inp,
                transition="production-promotion",
                version=version,
                run_id=run_id,
                run_url=run_url,
                merge_commit_sha=merge_commit_sha,
                prior_announcement=staging_announcement,
            )
            promotion_announced = True
        if (
            status.get("status") == "completed"
            and status.get("conclusion") not in _RERUNNABLE_CONCLUSIONS
        ):
            return status
        await ctx.sleep(f"{step_prefix}-wait-{attempt}", _POLL_SECONDS)
    raise RuntimeError(f"Timed out supervising deployment run {run_id}.")


async def handler(inp: Input, ctx: WorkflowContext) -> dict[str, Any]:
    service = inp.service.strip().lower()
    if service not in {"cvi", "rqh"}:
        raise RuntimeError("service must be cvi or rqh")

    started = await ctx.step(
        "start-exact-release",
        lambda: _tool(
            ctx,
            "start_release",
            {
                "service": service,
                "pr_number": inp.pr_number,
                "head_sha": inp.head_sha,
                "confirmation": inp.confirmation,
            },
        ),
    )
    merge_commit_sha = str(started.get("merge_commit_sha") or "")
    if not merge_commit_sha:
        raise RuntimeError("Release merge did not return a merge commit SHA.")
    await _notify(
        ctx,
        inp,
        "notify-release-started",
        f"Started {service.upper()} {started.get('version')} from PR #{inp.pr_number}. "
        f"I am supervising merge commit `{merge_commit_sha}` and will not approve production.",
    )

    discovered = await _wait_for_release_run(ctx, inp, merge_commit_sha)
    run_id = int(discovered["run_id"])
    run_url = str(discovered.get("url") or "")
    await _notify(
        ctx,
        inp,
        "notify-run-discovered",
        f"Bound {service.upper()} release to exact GitHub Actions run {run_id}: {run_url}",
    )

    gates = await _poll_release(
        ctx,
        inp,
        merge_commit_sha,
        run_id,
        until_gates_ready=True,
        step_prefix=f"{service}-production-gates",
    )
    if gates.get("status") == "completed":
        final = gates
    else:
        staging_announcement = await _announce_release(
            ctx,
            inp,
            transition="staging-ready",
            version=str(started.get("version") or ""),
            run_id=run_id,
            run_url=run_url,
            merge_commit_sha=merge_commit_sha,
        )
        pending_names = [
            str(item.get("name"))
            for item in gates.get("pending_environments", [])
            if item.get("name")
        ]
        gate_summary = ", ".join(pending_names) or "the existing production gates"
        await _notify(
            ctx,
            inp,
            f"notify-{service}-production-ready",
            f"{service.upper()} run {run_id} is ready at {gate_summary}: {run_url}. "
            "An eligible human must approve in GitHub.",
        )
        final = await _poll_production(
            ctx,
            inp,
            merge_commit_sha,
            run_id,
            run_url,
            str(started.get("version") or ""),
            staging_announcement,
            step_prefix=f"{service}-release",
        )

    await _notify(
        ctx,
        inp,
        f"notify-{service}-finished",
        f"{service.upper()} run {run_id} finished with `{final.get('conclusion')}`: {run_url}",
    )
    return {
        "service": service,
        "version": started.get("version"),
        "run_id": run_id,
        "run_url": run_url,
        "conclusion": final.get("conclusion"),
        "production_approval": "human",
    }
