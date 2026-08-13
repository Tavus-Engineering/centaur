---
name: qa
description: "Smoke test the full running Tavus Centaur system from a new Slack thread. Use when asked to QA the stack, run a smoke test, verify a deployment, check stack health, check deploy readiness, or prove Slack tools, file upload/download, company context, SigNoz, Tavus API, and tool loading work end to end."
---

# Centaur QA

Run this skill from a new Slack thread in a channel where the bot is present. The goal is to prove the user-facing agent path works, not just that APIs respond.

Default behavior: start immediately, run the in-thread smoke test, and return a concise pass/fail report. Do not ask clarifying questions unless the current Slack channel or thread cannot be inferred.

If the user asks for deploy readiness, staging QA, preview QA, promotion gating, concurrency checks, scheduler checks, or deadlock checks, run the in-thread smoke test first, then run the relevant extended checks below.

## Success Criteria

The smoke test passes only when all core workflows work from the running agent session:

- A list of tools loads and includes expected tools.
- Slack file upload to the current thread works.
- Slack file download from the current thread works.
- Slack file download from the current channel, then re-upload to the current thread, works.
- Slack token search works after bounded retries.
- Slack overall message search works.
- Current thread history works.
- Company context can connect to the Tavus company-context database and return indexed documents or a valid empty result.
- Watch Agent's critical Tavus tools load as packaged CLIs and pass their `health` commands through brokered auth.
- Focused tool validation uses `<tool> health` as the canonical smoke surface. Do not invent ad hoc probes or substitute raw endpoint/search calls unless a health check fails and you are triaging that failure.
- SigNoz is reachable through its hosted MCP and Tavus public API authentication succeeds without returning customer data.

Treat auth, permission, DNS, schema, and timeout errors as failures. Treat empty search results as warnings only when the tool successfully queried the backing service.

For promotion or deploy-readiness requests, the final status is `PASS` only if the requested extended checks also pass or are explicitly accepted by the owner.

## In-Thread Smoke Test

Use direct tool CLIs when available. Use `centaur-tools call <tool> <method> '<json>'` when a tool has no standalone CLI command for the method you need.

First capture session context:

```bash
echo "THREAD_KEY=${CENTAUR_THREAD_KEY:-}"
echo "SLACK_CHANNEL_ID=${SLACK_CHANNEL_ID:-}"
echo "SLACK_THREAD_TS=${SLACK_THREAD_TS:-}"
echo "SLACK_CHANNEL_NAME=${SLACK_CHANNEL_NAME:-}"
```

If `SLACK_CHANNEL_ID` or `SLACK_THREAD_TS` is missing, infer it from `CENTAUR_THREAD_KEY` when possible. Slack thread keys are usually `slack:<channel_id>:<thread_ts>`.

### 1. Tool Loading

```bash
centaur-tools list
```

Verify that the list is non-empty and includes at least `slack`, `company_context`, `signoz`, and `tavus-api`. If a tool is absent, record the failure before continuing.

### 2. Upload File To Current Thread

Upload a tiny deterministic file to the current Slack thread:

```bash
QA_TOKEN="centaur-qa-$(date +%s)"
QA_B64=$(printf '%s\n' "$QA_TOKEN" | base64 | tr -d '\n')
centaur-tools call slack upload_file "{
  \"channel_id\": \"${SLACK_CHANNEL_ID}\",
  \"thread_ts\": \"${SLACK_THREAD_TS}\",
  \"filename\": \"centaur-qa-upload.txt\",
  \"title\": \"Centaur QA Upload\",
  \"comment\": \"QA upload smoke test: ${QA_TOKEN}\",
  \"content_base64\": \"${QA_B64}\"
}"
```

Verify the response contains a Slack file object, permalink, or URL. Save any `url_private` value for the next step. If the response omits file metadata, use thread history in step 4 to find the uploaded file.

### 3. Download File From Current Thread

Fetch the current thread history and find the uploaded file's `url_private`:

```bash
slack thread "${SLACK_CHANNEL_ID}:${SLACK_THREAD_TS}" --json --limit 20
```

Then download it to a sandbox-local temp directory:

```bash
QA_DOWNLOAD_DIR="/tmp/centaur-qa-files-${QA_TOKEN}"
mkdir -p "$QA_DOWNLOAD_DIR"
slack files "${URL_PRIVATE_FROM_CURRENT_THREAD}" --download --output "$QA_DOWNLOAD_DIR"
```

Verify the command prints a downloaded path and that the file exists with non-zero size.

### 4. Current Thread History

```bash
slack thread "${SLACK_CHANNEL_ID}:${SLACK_THREAD_TS}" --json --limit 20
```

Verify the returned messages include the QA request and the file upload message. Record the number of messages returned.

### 5. Search Uploaded Token

Search for the unique token uploaded in step 2:

```bash
for attempt in 1 2 3; do
  slack search "$QA_TOKEN" --limit 5 --full && break
  sleep 10
done
```

Verify at least one result points to the current channel or current thread. Retry up to three total attempts with 10 seconds between attempts to handle Slack indexing lag. If all three attempts complete successfully but return no matching result, record `WARN: token not indexed yet` and continue.

### 6. Search Overall Messages

Run a separate broader message search for a stable term from the current channel:

```bash
slack search "${SLACK_CHANNEL_NAME:-centaur}" --limit 5 --full
```

Pass when the command succeeds and returns valid search output. Empty results are a warning only when the query reached Slack successfully.

### 7. Download File From Current Channel And Re-Upload

Find another accessible Slack file from the current channel. Prefer a result outside the current thread, but do not use files from other channels. `search_files` filters by filename or title, so start broad with an empty query:

```bash
centaur-tools call slack search_files '{"channel_id":"'"${SLACK_CHANNEL_ID}"'","query":"","max_results":5}'
```

Pick a result whose `channels` includes `${SLACK_CHANNEL_ID}`. If possible, avoid the file uploaded earlier in this QA run so the check proves download-and-reupload of an existing channel file. Download it:

```bash
QA_REUPLOAD_DIR="/tmp/centaur-qa-reupload-${QA_TOKEN}"
mkdir -p "$QA_REUPLOAD_DIR"
slack files "${URL_PRIVATE_FROM_CURRENT_CHANNEL}" --download --output "$QA_REUPLOAD_DIR"
```

Save the downloaded file path, then re-upload it to the current thread:

```bash
slack upload "${SLACK_CHANNEL_ID}" "${DOWNLOADED_FILE_FROM_CURRENT_CHANNEL}" \
  --thread "${SLACK_THREAD_TS}" \
  --comment "QA re-upload from current channel"
```

Verify the current thread now shows the re-uploaded file. If no accessible current-channel file exists, record `SKIP: no readable file in current channel` and include the `search_files` result.

### 8. Tavus Company Context

This verifies the database-backed context path and row-level permissions:

```bash
company_context list --limit 3 --json
company_context search "centaur" --limit 3 --json
```

Pass when the tool returns a valid JSON payload with `status: ok`, even if no documents match. Fail on database connection errors, permission errors, missing `COMPANY_CONTEXT_DSN`, or malformed results.

If company context returns `upstream connection failed`, use SigNoz runtime evidence before suggesting a code fix:

```bash
signoz search-logs "upstream connection failed" --time-range 2h --json
signoz search-logs "${CENTAUR_THREAD_KEY}" --time-range 2h --json
```

Classify whether the failure is a database proxy upstream issue, missing database selection, secret-resolution failure, or tool schema/client error. Include the failing tool command and thread key in the report.

### 9. Observability Via SigNoz

```bash
signoz health
signoz search-logs "${CENTAUR_THREAD_KEY}" --time-range 2h --json
```

Pass when SigNoz MCP authentication succeeds and the bounded current-thread search returns valid JSON log entries or a valid empty result. Fail on DNS, HTTP, MCP, or authentication errors. Keep this check scoped to the current deployment state visible from the current thread.

Do not run broad error searches such as `error OR ERROR` as part of the default QA pass/fail decision. The goal is to prove the Watch Agent SigNoz connection works, not to audit unrelated services. Only query error logs when a preceding check failed and you need runtime evidence to classify that specific failure.

### 10. Tavus Public API

Use the tool's privacy-preserving health check. It authenticates and requests at most one persona but returns no customer payload:

```bash
tavus-api health --env prod
```

Pass when the command exits zero and returns JSON with `ok: true`. Fail on DNS, HTTP, brokered-auth, permission, or malformed-response errors. Do not include the probe's underlying customer data in the QA report.

### 11. Watch Agent Tool Validation

Run these checks for deploy readiness or tool smoke confidence. They validate that Watch Agent's key Tavus tools are packaged correctly, visible in the catalog, compatible with brokered auth, and able to reach their authenticated upstreams from the current deployment.

First prove the tools are installed as CLIs and visible to the tool catalog:

```bash
centaur-tools list
slack --help
company_context --help
signoz --help
tavus-api --help
```

Then exercise each tool's focused health command without requiring local env-only secrets:

```bash
slack health
company_context health
signoz health
tavus-api health --env prod
```

Pass only when each health command exits zero and returns valid JSON with `ok: true`. Fail when a CLI import/package error prevents startup, brokered auth does not replace a placeholder credential, an authenticated endpoint returns `401`/`403`, or company context returns upstream/proxy errors.

If a health command fails, triage the specific failing tool with the smallest safe read-only command that exercises the same path. Examples:

```bash
slack --help
company_context --help
signoz ready --json
tavus-api get /v2/personas?limit=1 --env prod --json
```

Only run bespoke search or raw endpoint calls after recording the failed health result and only when needed to classify the failure.

## Extended Checks

Run these after the core smoke test when the user asks for staging, preview, deploy readiness, scheduler, concurrency, or promotion confidence.

### Deployment Health

Record the target environment, namespace or URL, commit/build if visible, current timestamp, and thread key. Verify:

- The target is serving traffic.
- `centaur-tools list` succeeds from the running session.
- SigNoz connectivity succeeds with `signoz health` and a small current-thread query. Do not fail deployment health on broad recent error volume unless those errors are tied to a failed QA step or to the current QA thread.
- The user-visible Slack thread receives the final QA report.
- Use tool CLIs, runtime-owned state, logs, metrics, and the user-visible Slack surface for verification. Do not require direct cluster control-plane access for this skill.

### Concurrent Agent Turns

When asked to check concurrency or deadlocks, start 3-5 QA prompts in separate Slack threads in the same channel. Use distinct `QA_TOKEN` values and ask each agent to do a different read-only task:

- Read thread history and summarize earlier messages.
- Call two tools and summarize grounded results.
- Query SigNoz logs for its own thread key.
- Search messages for a synthetic token.
- Use company context for a small internal DB lookup.

Pass when every turn reaches a terminal response in Slack, no thread remains stuck busy, and durable session events or bounded SigNoz queries show one coherent execution per prompt without duplicate final delivery.

### User Context

Verify requester context when the user asks for Slack/user-context coverage:

- The response can refer to the current Slack channel and thread.
- The agent can identify or mention the requesting user only from available Slack context.
- Missing GitHub handles or profile fields are reported as unavailable, not invented.
- Mid-thread prompts use earlier thread facts accurately.

### Scheduler Checks

Run only when the target includes scheduler workflows, alerts, cron jobs, or background smoke loops. Use the scheduler's canonical workflow state, DB rows, or logs. Verify:

- The scheduler creates the expected current tick.
- It does not create a duplicate tick while a prior tick is pending or running.
- It does not backfill every missed tick when the last run is far in the past; it creates only the most recent eligible tick.

Pass only with evidence from scheduler-owned state and logs, not just absence of visible failures.

### Promotion Gate

A deployment is ready for promotion only when:

- The core in-thread smoke test passes.
- Requested extended checks pass or failures are explicitly accepted by the owner.
- The same commit/build was tested and is the one being promoted.
- The report includes enough evidence for another engineer to verify: Slack permalinks, thread key, execution IDs, workflow IDs, log query windows, or DB row counts.

## Report Format

Reply in the Slack thread with a digestible QA report, not a prose paragraph. The
first line must answer the outcome:

```text
Overall: PASS|FAIL|PARTIAL - <one short reason>
```

Use `PASS` only when every required smoke check passed. Use `PARTIAL` when the
user-facing path mostly worked but at least one required check warned, skipped,
or could not be verified. Use `FAIL` when any required check hit an auth,
permission, DNS, schema, timeout, malformed-response, upload/download, or
backing-service error.

Then include a Slack-friendly digest. Do not use Markdown tables in Slack
responses; Slack does not render them reliably. Use this exact shape:

```text
*Setup*
- *Thread context:* PASS - C123:1712345678.000000, key slack:C123:...
- *Tool loading:* PASS - 72 tools; expected slack/company_context/signoz/tavus-api present

*Slack*
- *Upload current-thread file:* PASS - F123, centaur-qa-upload.txt
- *Download current-thread file:* PASS - centaur-qa-upload.txt, 22 bytes, token matched
- *Re-upload current-channel file:* SKIP - no readable prior file found in channel
- *Search uploaded token:* WARN - 3 attempts, 0 results; likely indexing lag
- *Search overall messages:* PASS - query "centaur", 5 results
- *Current thread history:* PASS - 4 messages; QA request and upload present

*Data + Observability*
- *Company context:* PASS - list 0, search 0, status ok
- *SigNoz:* PASS - hosted MCP health ok, thread query 0
- *Tavus API:* PASS - production auth health ok

*Watch Agent Tools*
- *Slack:* PASS - health ok, brokered auth path reached
- *Company context:* PASS - health ok, database path reached
- *SigNoz:* PASS - health ok, brokered auth path reached
- *Tavus API:* PASS - health ok, brokered auth path reached

*Extended*
- *Requested extended checks:* SKIP - not requested
```

Rules for the digest:

- Keep each evidence phrase to one short sentence fragment. Prefer concrete IDs,
  counts, filenames, byte counts, query names, and attempt counts.
- Do not write `mostly PASS`. Use `PARTIAL` and put each warning or skipped item
  on its own line.
- Do not paste raw JSON, stack traces, credentials, tokens, or long command
  output. Summarize the failure class and the command or endpoint that failed.
- If Slack file upload creates visible artifacts, mention the uploaded filenames
  and file IDs so the user can correlate them with thread attachments.
- If a check is skipped because no suitable input exists, mark only that row
  `SKIP`; do not hide it in prose.
- If using the Slack API directly, a Block Kit version is acceptable only when
  the message still contains the same information: headline, grouped sections,
  per-check result, and evidence. Do not require Block Kit for normal assistant
  replies.

After the grouped digest, add at most three short bullets. Use Slack mrkdwn list items with `- ` prefixes:

- `Failures:` highest-signal failed rows and likely owner.
- `Warnings:` non-blocking warnings such as Slack indexing lag or empty-but-valid
  search/log results.
- `Promotion:` `ready`, `not ready`, or `not evaluated`, with one reason.

Omit any bullet that has no content. The whole report should fit comfortably in
one Slack message.

## Known Gotchas

| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| Missing Slack env vars | Invocation did not come through Slack, or runtime metadata was not injected | Derive from `CENTAUR_THREAD_KEY`; otherwise fail early |
| `slack files --download` rejects URL | URL is not a Slack `url_private` file URL | Read thread history or `search_files` JSON and use `url_private` |
| Search cannot find just-uploaded token | Slack search indexing lag | Retry up to three total attempts, then warn and run the separate overall message search |
| `company_context` permission denied | Principal lacks DB-backed reader grant | Report principal/channel and ask owner to grant company context access |
| `company_context` upstream connection failed | Database proxy upstream, database selection, or secret-resolution failure | Check thread events and bounded SigNoz queries for upstream connect and secret fetch errors before proposing a code change |
| Tool CLI import error | Package entrypoint or relative import packaging regression | Run `<tool> health`, `<tool> --help`, package build checks, and report the broken console script |
| Tool crashes when an API key env var is absent | Client assumes local env auth despite brokered credentials | Re-run `<tool> health` with the env var unset and verify client construction does not raise |
| SigNoz MCP returns 401/403 | Brokered `SIGNOZ-API-KEY` injection or instance URL is wrong | Run `signoz health`, then `signoz ready --json`; verify the configured MCP host and secret grant |
| Tavus API returns 401/403 | Production API key grant or `x-api-key` replacement failed | Run `tavus-api health --env prod`; verify the `tavus-api` tool grant and target host |
| Expected tools missing | Tool catalog did not load or overlay masked base tools | Report the missing tool names and include `centaur-tools list` output |
| Concurrent runs hang | Runtime assignment, execution queue, or final delivery issue | Check execution state, SigNoz thread trace, and delivery outbox |
| Scheduler duplicate or catch-up storm | Scheduler idempotency regression | Inspect scheduler-owned DB rows and logs before proposing a code fix |

## Failure Triage

When a flow fails, inspect runtime evidence before redesigning:

- Stuck execution: check durable execution state, session events, and a bounded SigNoz thread-key search.
- Missing Slack response: check Slackbot logs, final delivery state, and the Slack thread surface.
- File failure: check Slack file metadata, `url_private`, downloaded byte size, and upload response.
- Tool failure: classify credential, DNS, upstream, schema, timeout, or runtime errors separately.
- Brokered-auth failure: verify whether the tool should work without local env vars and whether the proxy injected the expected headers.
- Context bug: inspect thread history, requester context, and message ordering.
- Scheduler bug: inspect scheduler-owned rows and logs for duplicate or catch-up decisions.

## References

| Reference | When To Read |
|-----------|--------------|
| [../tool-health-smoke/SKILL.md](../tool-health-smoke/SKILL.md) | When doing broad all-tool health smoke coverage |
| [references/test-inputs.md](references/test-inputs.md) | Only for deeper read-only triage after a tool health check fails |

## Templates

| Template | Purpose |
|----------|---------|
| [templates/tool-qa-report-template.md](templates/tool-qa-report-template.md) | Optional full QA report file for local stack runs |
