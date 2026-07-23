---
name: deployment-captain
description: Prepare, start, supervise, rerun, or cancel Tavus CVI and RQH production releases. Use when a user asks Watch Agent to deploy CVI/realtime-replica or RQH/request-handler, check a release, handle existing GitHub production gates, or perform the deployment-captain handbook duties.
---

# Deployment Captain

Use the `deployment-captain` CLI for release PR and exact-run operations. It
operates the existing repository-owned GitHub workflows; it does not require
deployment-facade or rollback-facade changes in RQH or realtime-replica.

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

The durable workflow binds the release PR, merge SHA, and Actions run ID, then
supervises that exact existing workflow. The repository workflow owns builds,
staging/canary rollout, production promotion, and rollback jobs. Watch Agent
does not change AWS traffic or dispatch a separate rollback workflow.

Use the Skillshare `tavus-announce-release` skill only after the exact
staging/canary deployment reaches its existing production gates and again when
a human approval starts production promotion. That skill is announcement-only
and must never deploy, approve, merge, change traffic, rerun, or roll back.

RQH waits at `Manual Approval for Production`. CVI waits for all existing
provider promotion gates. An eligible human approves in GitHub; Watch Agent
never consumes a production gate.

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
- Never approve a production gate. Direct an eligible human to the exact GitHub
  Actions run.

## Rollback

Watch Agent monitors rollback jobs that are already part of the exact existing
release workflow. It does not create or dispatch a separate emergency rollback
workflow. A rollback outside that run is incident response, not deployment
captain automation; require explicit human direction and follow the owning
repository's current runbook.
