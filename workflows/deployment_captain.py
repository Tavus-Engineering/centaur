"""Durable CVI/RQH release supervision with exact GitHub identifiers."""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any

from api.workflow_engine import WorkflowContext

WORKFLOW_NAME = "deployment_captain"

_POLL_SECONDS = 60
_RUN_DISCOVERY_ATTEMPTS = 20
_MAX_RELEASE_POLLS = 720
_ANNOUNCEMENT_CHANNEL = "C08GJASBJD8"


@dataclasses.dataclass
class Input:
    service: str
    pr_number: int
    head_sha: str
    confirmation: str
    slack_channel: str
    slack_thread_ts: str
    soak_minutes: int = 10


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


def _agent_result_text(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("result_text") or "").strip()
    return str(result).strip()


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
        if not until_gates_ready and status.get("status") == "completed":
            return status

        failed = _failed_jobs(status)
        if failed and failed != last_failed:
            await _notify(
                ctx,
                inp,
                f"{step_prefix}-failed-jobs-{attempt}",
                f"{inp.service.upper()} deployment run {run_id} has failed jobs: "
                f"{', '.join(failed)}. I am holding and will notice an exact-run rerun.",
            )
            last_failed = failed
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
        if status.get("status") == "completed":
            return status

        failed = _failed_jobs(status)
        if failed and failed != last_failed:
            await _notify(
                ctx,
                inp,
                f"{step_prefix}-failed-jobs-{attempt}",
                f"{inp.service.upper()} deployment run {run_id} has failed jobs: "
                f"{', '.join(failed)}. I am holding and will notice an exact-run rerun.",
            )
            last_failed = failed
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
        await ctx.sleep(f"{step_prefix}-wait-{attempt}", _POLL_SECONDS)
    raise RuntimeError(f"Timed out supervising deployment run {run_id}.")


async def _wait_for_facade(
    ctx: WorkflowContext,
    repository_service: str,
    workflow_file: str,
    request_id: str,
    step_prefix: str,
) -> dict[str, Any]:
    for attempt in range(120):
        status = await ctx.step(
            f"{step_prefix}-status-{attempt}",
            lambda: _tool(
                ctx,
                "workflow_dispatch_status",
                {
                    "repository_service": repository_service,
                    "workflow_file": workflow_file,
                    "request_id": request_id,
                },
            ),
        )
        if status.get("found") and status.get("status") == "completed":
            if status.get("conclusion") != "success":
                raise RuntimeError(
                    f"Facade workflow {workflow_file} failed: {status.get('url')}"
                )
            return status
        await ctx.sleep(f"{step_prefix}-wait-{attempt}", 15)
    raise RuntimeError(f"Timed out waiting for facade workflow {workflow_file}.")


async def _set_cvi_stage_fraction(
    ctx: WorkflowContext,
    stage_fraction: int,
    request_id: str,
    step_prefix: str,
) -> dict[str, Any]:
    confirmation = f"SET CVI STAGE TO {stage_fraction} FOR {request_id}"
    await ctx.step(
        f"{step_prefix}-dispatch",
        lambda: _tool(
            ctx,
            "dispatch_cvi_traffic",
            {
                "stage_fraction": stage_fraction,
                "request_id": request_id,
                "confirmation": confirmation,
            },
        ),
    )
    return await _wait_for_facade(
        ctx,
        "rqh",
        "cvi-traffic-routing.yml",
        request_id,
        step_prefix,
    )


async def _soak_assessment(
    ctx: WorkflowContext,
    inp: Input,
    run_id: int,
    merge_commit_sha: str,
) -> Any:
    prompt = f"""Assess the active CVI canary soak. This is observation-only.

Exact deployment:
- GitHub repository: Tavus-Engineering/realtime-replica
- workflow run id: {run_id}
- merge commit SHA: {merge_commit_sha}
- CVI_STAGE_FRACTION: 5

Use SigNoz and GitHub read operations to check error rate, latency, CVI health/FPS signals,
and failed jobs for this exact release window. Do not approve deployments, change traffic,
rerun jobs, rollback, or mutate any system. Return a concise GO/HOLD recommendation with
the evidence and links. If a required signal is unavailable, say HOLD and name the gap.
"""
    return await ctx.step(
        "cvi-soak-observability-assessment",
        lambda: ctx.agent_turn(
            prompt,
            thread_key=f"deployment-captain:{ctx.run_id}:soak",
            message_id=f"deployment-captain:{ctx.run_id}:soak",
            metadata={
                "source": "deployment_captain",
                "service": inp.service,
                "github_run_id": run_id,
                "merge_commit_sha": merge_commit_sha,
            },
        ),
    )


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

    if service == "rqh":
        gates = await _poll_release(
            ctx,
            inp,
            merge_commit_sha,
            run_id,
            until_gates_ready=True,
            step_prefix="rqh-production-gate",
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
            await _notify(
                ctx,
                inp,
                "notify-rqh-production-ready",
                f"RQH run {run_id} is ready at `Manual Approval for Production`: "
                f"{run_url}. A distinct eligible human must approve it.",
            )
            final = await _poll_production(
                ctx,
                inp,
                merge_commit_sha,
                run_id,
                run_url,
                str(started.get("version") or ""),
                staging_announcement,
                step_prefix="rqh-release",
            )
        await _notify(
            ctx,
            inp,
            "notify-rqh-finished",
            f"RQH run {run_id} finished with `{final.get('conclusion')}`: {run_url}",
        )
        return {
            "service": service,
            "version": started.get("version"),
            "run_id": run_id,
            "run_url": run_url,
            "conclusion": final.get("conclusion"),
            "production_approval": "human",
        }

    shifted_to_stage = False
    restore_error: str | None = None
    try:
        gates = await _poll_release(
            ctx,
            inp,
            merge_commit_sha,
            run_id,
            until_gates_ready=True,
            step_prefix="cvi-canary",
        )
        if gates.get("status") == "completed":
            await _notify(
                ctx,
                inp,
                "notify-cvi-ended-before-gates",
                f"CVI run {run_id} ended before all production gates became ready: "
                f"`{gates.get('conclusion')}`. Stage traffic was not changed.",
            )
            return {
                "service": service,
                "run_id": run_id,
                "run_url": run_url,
                "conclusion": gates.get("conclusion"),
                "stage_traffic_changed": False,
            }

        stage_request_id = f"{ctx.run_id}-stage-5"
        await _set_cvi_stage_fraction(ctx, 5, stage_request_id, "cvi-stage-5")
        shifted_to_stage = True
        await _notify(
            ctx,
            inp,
            "notify-cvi-stage-five",
            f"CVI stage is receiving 5% of new conversations for run {run_id}. "
            f"Soaking for {inp.soak_minutes} minutes; do not approve production yet.",
        )
        await ctx.sleep(
            "cvi-soak-window",
            dt.timedelta(minutes=max(5, min(int(inp.soak_minutes), 60))),
        )
        assessment = await _soak_assessment(ctx, inp, run_id, merge_commit_sha)
        assessment_text = _agent_result_text(assessment)
        await _notify(
            ctx,
            inp,
            "notify-cvi-soak-assessment",
            f"CVI soak assessment for run {run_id}:\n{assessment_text}\n\n"
            "The production provider gates still require a human approver.",
        )

        if not assessment_text.upper().startswith("GO"):
            await _notify(
                ctx,
                inp,
                "notify-cvi-soak-hold",
                f"HOLDING CVI run {run_id}. Production gates must remain unapproved until "
                "the reported soak issue is resolved and reassessed.",
            )
            return {
                "service": service,
                "version": started.get("version"),
                "run_id": run_id,
                "run_url": run_url,
                "conclusion": "hold",
                "production_approval": "withheld",
                "soak_assessment": assessment_text,
            }

        staging_announcement = await _announce_release(
            ctx,
            inp,
            transition="staging-ready",
            version=str(started.get("version") or ""),
            run_id=run_id,
            run_url=run_url,
            merge_commit_sha=merge_commit_sha,
        )
        final = await _poll_production(
            ctx,
            inp,
            merge_commit_sha,
            run_id,
            run_url,
            str(started.get("version") or ""),
            staging_announcement,
            step_prefix="cvi-production",
        )
        return {
            "service": service,
            "version": started.get("version"),
            "run_id": run_id,
            "run_url": run_url,
            "conclusion": final.get("conclusion"),
            "production_approval": "human",
            "soak_assessment": assessment_text,
        }
    finally:
        if shifted_to_stage:
            try:
                restore_request_id = f"{ctx.run_id}-stage-0"
                await _set_cvi_stage_fraction(ctx, 0, restore_request_id, "cvi-stage-0")
                await _notify(
                    ctx,
                    inp,
                    "notify-cvi-stage-restored",
                    f"Restored CVI routing to 100% production / 0% stage after run {run_id}.",
                )
            except Exception as exc:
                restore_error = str(exc)
                await _notify(
                    ctx,
                    inp,
                    "notify-cvi-stage-restore-failed",
                    f"URGENT: automatic CVI stage reset failed after run {run_id}: "
                    f"{restore_error}. Manually restore 100/0/0 before ending captain duty.",
                )
        if restore_error:
            raise RuntimeError(restore_error)
