---
name: deployment-captain
description: Prepare, start, supervise, rerun, cancel, or roll back Tavus CVI and RQH production releases. Use when a user asks Watch Agent to deploy CVI/realtime-replica or RQH/request-handler, check a release, manage canary traffic, handle GitHub production gates, or perform the deployment-captain handbook duties.
---

# Deployment Captain

Use the `deployment-captain` CLI for every release operation. Never merge a
release PR or dispatch a deployment with raw `gh`, AWS, Cerebrium, or HTTP calls.

Read [references/playbook.md](references/playbook.md) before the first operation
in a thread.

## Prepare

Treat any initial “deploy CVI/RQH” request as preparation unless Watch Agent
already prepared the current exact PR and full head SHA in the same thread and
the user's new message is exactly `deploy`.

1. Run `deployment-captain prepare <cvi|rqh> --json`.
2. Report every blocker, including stale `waiting` runs. Never select “latest.”
   If `ready_to_start` is false, resolve the blockers first and prepare again.
3. Report the exact service, version, PR, full head SHA, checks, and known
   blockers. Do not post a pre-deployment coordination message, collect
   acknowledgements, poll authors, or wait ten minutes.
4. Tell the user: `Reply deploy to start this exact release.`

Preparation is read-only. Do not launch the durable workflow yet.

## Start

Start only when all of the following are true in the current Slack thread:

- Watch Agent prepared the exact service, release PR, and full head SHA in its
  immediately preceding release plan.
- The user's new message is exactly `deploy`.
- The prepared PR number and full head SHA still match.
- `ready_to_start` is true.

Then run:

```bash
deployment-captain launch <cvi|rqh> \
  --pr <number> \
  --head-sha <full-sha> \
  --confirmation deploy \
  --slack-channel <current-channel-id> \
  --slack-thread-ts <current-thread-ts> \
  --json
```

The durable workflow binds the release PR, merge SHA, and Actions run ID. It
uses the Skillshare `tavus-announce-release` skill only after the exact
staging/canary deployment is healthy and again when a human approval starts
production promotion. That skill is announcement-only and must never deploy,
approve, merge, change traffic, rerun, or roll back.

CVI waits for all provider canary gates, shifts new conversations to 5% stage,
soaks, obtains an observation-only SigNoz assessment, and asks for human
production approval. It always attempts to restore routing to 100/0/0.

RQH waits at `Manual Approval for Production` and announces when it is ready.
GitHub does not allow the deployment initiator to self-approve. Default to a
human approval. Only use `deployment-captain approve` after a separate explicit
approval confirmation and only when `GITHUB_APPROVER_TOKEN` is provisioned for
a distinct eligible identity.

## Supervise

- Change owners must proactively communicate holds, deployment ordering,
  migrations, and main-to-stage verification requirements. Treat a known hold
  as blocking even though there is no acknowledgement poll.
- When an exact run has failed jobs, report their names and remain in HOLD.
  Never rerun automatically. Show the user this exact authorization string:
  `RERUN FAILED <CVI|RQH> RUN <run-id> AT <full-merge-sha>`. Only after the user
  repeats it, run `deployment-captain rerun-failed` with the same run ID and
  merge SHA. The durable supervisor will notice that same-run retry.
- Use the exact run ID and merge SHA in every status, cancel, or rerun operation.
- Never cancel stale runs implicitly. Show the exact cancel confirmation first.
- Never approve a production gate with the same GitHub identity that initiated
  the release. Default to a human GitHub approval.
- If the CVI workflow reports a HOLD, leave production gates unapproved.
- If automatic stage reset fails, make the 100/0/0 restoration the top-priority
  human action.

## Emergency rollback

Do not infer rollback authorization from “deploy.” Require an active `#outages`
thread/call, exact known-good `build-*` IDs for both Phoenix 3 and Phoenix 4,
and the tool's exact rollback confirmation. The repository-owned workflow
validates both builds before changing either app and redeploys Phoenix 3 first.

After rollback, verify provider health and announce resolution in `#outages`,
`#cvi-dev`, and `#ext-cerebrium-tavus` as applicable.
