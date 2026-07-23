---
name: deployment-captain
description: Prepare, start, supervise, rerun, or cancel Tavus CVI, RQH, and Tavus API releases. Use when a user asks Watch Agent to deploy CVI/realtime-replica, RQH/request-handler, or Tavus API to staging or production; check a release; handle existing GitHub production gates; or perform the deployment-captain handbook duties.
---

# Deployment Captain

Use the `deployment-captain` CLI for release PR and exact-run operations. It
operates the existing repository-owned GitHub workflows; it does not require
deployment-facade or rollback-facade changes in Tavus API, RQH, or
realtime-replica.

Read [references/playbook.md](references/playbook.md) before the first operation
in a thread.

## Understand the request

Resolve both a service and a destination from the current Slack thread:

- `CVI` or `realtime-replica` -> `cvi`
- `RQH` or `request-handler` -> `rqh`
- `Tavus API`, `tavus-api`, or `API` -> `tavus-api`
- `stage`, `staging`, or `canary` -> `staging`
- `prod` or `production` -> `production`

If either value is missing or genuinely ambiguous, ask one concise question in
the same thread and stop. Examples: `Which service: CVI, RQH, or Tavus API?` or
`Staging or production?` Do not dump a command template or ask for identifiers
Watch Agent can discover from GitHub.

Tavus API support is staging-only. If production is requested for Tavus API,
state that limitation and ask whether the user wants staging instead.

An unambiguous imperative such as `deploy RQH to stage` or
`deploy tavus-api to staging` is authorization to prepare and launch that
staging deployment in the same turn. Do not require a second confirmation. A
bare `deploy` remains valid only when Watch Agent's immediately preceding
message prepared one exact service, destination, PR, and full head SHA.

## Prepare

1. Run:

   ```bash
   deployment-captain prepare <cvi|rqh|tavus-api> \
     --target <staging|production> \
     --json
   ```

   If GitHub returns multiple Release Please candidates, list them and ask
   which PR in the same thread. After the user chooses, prepare again with
   `--pr <number>`.
2. Report every blocker, including stale `waiting` runs. Never select “latest.”
   If `ready_to_start` is false, resolve the blockers first and prepare again.
3. Report the exact service, version, PR, full head SHA, checks, and known
   blockers. Do not post a pre-deployment coordination message, collect
   acknowledgements, poll authors, or wait ten minutes.
4. For an explicit, unambiguous deployment command, continue directly to
   **Start**. For a read-only request such as `prepare RQH staging`, stop after
   the plan. If the user has not yet authorized deployment, ask:
   `Deploy this exact release to <destination>?`

Preparation is read-only. Do not launch the durable workflow yet.

## Start

Start only when all of the following are true in the current Slack thread:

- The user gave an unambiguous imperative deployment request, or replied to
  Watch Agent's immediately preceding exact release plan with `deploy`.
- Watch Agent prepared the exact service, destination, release PR, and full head
  SHA in the current turn or immediately preceding release plan.
- The prepared PR number and full head SHA still match.
- `ready_to_start` is true.

Then run:

```bash
deployment-captain launch <cvi|rqh|tavus-api> \
  --target <staging|production> \
  --pr <number> \
  --head-sha <full-sha> \
  --confirmation deploy \
  --slack-channel <current-channel-id> \
  --slack-thread-ts <current-thread-ts> \
  --json
```

The durable workflow binds the Release Please PR, merge SHA, and Actions run ID,
then supervises that exact existing workflow. For a staging target it stops
after staging/canary is healthy and does not request production. For a
production target it continues watching while an eligible human consumes the
existing GitHub production gate. The repository workflow owns builds,
staging/canary rollout, production promotion, and rollback jobs. Watch Agent
does not change AWS traffic or dispatch a separate rollback workflow.

Use the Skillshare `tavus-announce-release` skill only after the exact
staging/canary deployment reaches its existing production gates and again when
a human approval starts production promotion. That skill is announcement-only
and must never deploy, approve, merge, change traffic, rerun, or roll back.

RQH waits at `Manual Approval for Production`. CVI reports each existing
provider promotion gate as it becomes available; those provider paths are
intentionally independent. Tavus API's existing `main` workflow deploys only
the staging stack. An eligible human approves CVI/RQH production in GitHub;
Watch Agent never consumes a production gate.

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
