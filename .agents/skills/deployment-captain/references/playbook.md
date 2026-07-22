# CVI and RQH release policy

Canonical handbook: <https://docs.superhuman.com/d/Engineering-and-Research_dn31gYMNRyD/CVI-RQH-Deployment-Playbook_sutEjOom#_lupA-OPv>

Current communication policy: <https://tavus.slack.com/archives/C08GJASBJD8/p1784325444635319>

The July 17 communication policy supersedes the handbook's older pre-cut
acknowledgement process. The deployment coordinator does not create a
coordination poll, collect author acknowledgements, or wait ten minutes.
Change owners remain responsible for testing on main/staging and must
proactively communicate holds, migrations, and deployment-order constraints.

## Cadence and timing

- Cut at least one release per day when changes are ready.
- A merge to `main` does not deploy immediately by itself. Release Please opens
  a `chore(main): release X.Y.Z` PR; merging that release PR creates the tag and
  starts the deployment workflow.
- Multiple daily releases are acceptable, but only one release state machine may
  be active per repository and a new Release Please PR must exist.
- RQH normally takes about 15 minutes. CVI can take hours; begin at least six
  hours before the captain will be offline.

## Release communication

Do not post a pre-cut coordination message. Use the Skillshare
`tavus-announce-release` skill to announce only these observed transitions:

- the exact staging/canary deployment is healthy and ready for change-owner
  verification;
- a human has consumed the GitHub production gate and production promotion is
  beginning.

The announcement skill does not deploy, approve, merge, change traffic, rerun,
or roll back. A known hold or sequencing constraint still blocks the relevant
release action; the absence of an acknowledgement poll is not permission to
ignore it.

For a controlled Watch Agent drill, RQH recognizes the opt-in marker
`.watch-agent/rqh-deployment-failure-drill`. It fails only the first run attempt
for that exact marker in a pre-staging job, before AWS staging or production work
begins. The marker state is persisted before the intentional failure, so an
explicitly authorized rerun of the exact failed run proceeds normally on attempt
two and later releases cannot retrigger it accidentally. Remove the marker in a
follow-up PR after the drill.

## Production flow

RQH has one GitHub environment gate: `Manual Approval for Production`.

CVI has independent provider gates:

- `approve-cerebrium` / `promote-to-prod-cerebrium`
- `approve-modal` / `promote-to-prod-modal`
- `approve-fal` / `promote-to-prod-fal`

GitHub prevents self-review when the initiator is also the approver. Use a human
reviewer or a separately provisioned approver identity. Never approve a provider
whose canary or observability evidence is missing or unhealthy.

## CVI routing invariant

The source of truth is AWS Secrets Manager secret `prod/rqh/secrets` in
`us-west-1`:

- `CVI_PROD_FRACTION`
- `CVI_STAGE_FRACTION`
- `CVI_DEV_FRACTION`

Weights must sum to 100 and must never all be zero. The automation exposes only
the two handbook states:

- normal: `100 / 0 / 0`
- canary soak: `95 / 5 / 0`

Changes affect new conversations immediately. Restore stage to zero after the
release or on failure.

## Emergency CVI rollback

1. Notify `#outages` with `@channel` and create/attach an incident call.
2. Select explicit known-good Cerebrium `build-*` IDs.
3. Redeploy Phoenix 3 production first, then Phoenix 4 production, using
   Cerebrium's build `rebuild?redeploy_only=true` operation.
4. Verify rollout and provider health.
5. Notify `#ext-cerebrium-tavus` when Cerebrium coordination is needed.

Never use “latest successful build” as a rollback selector.
