# CVI and RQH release policy

Canonical handbook: <https://docs.superhuman.com/d/Engineering-and-Research_dn31gYMNRyD/CVI-RQH-Deployment-Playbook_sutEjOom#_lupA-OPv>

Current communication policy: <https://tavus.slack.com/archives/C08GJASBJD8/p1784325444635319>

The July 17 communication policy supersedes the handbook's older pre-cut
acknowledgement process. The deployment coordinator does not create a
coordination poll, collect author acknowledgements, or wait ten minutes.
Change owners remain responsible for testing on main/staging and must
proactively communicate holds, migrations, and deployment-order constraints.

Watch Agent operates the existing Release Please and GitHub Actions flow. No
RQH or realtime-replica deployment facade, traffic workflow, failure-drill
hook, or standalone rollback workflow is required.

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

## Production flow

RQH has one GitHub environment gate: `Manual Approval for Production`.

CVI has independent provider gates:

- `approve-cerebrium` / `promote-to-prod-cerebrium`
- `approve-modal` / `promote-to-prod-modal`
- `approve-fal` / `promote-to-prod-fal`

Watch Agent never approves these gates. It reports the exact run and pending
environments so an eligible human can approve in GitHub. The existing
repository workflows own their rollout and rollback jobs; Watch Agent supervises
the exact run and reports failures without introducing a parallel control
plane.
