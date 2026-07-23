# Fork changes

This is Tavus's fork of [paradigmxyz/centaur](https://github.com/paradigmxyz/centaur).
This file is the single source of truth for how this fork differs from upstream.

**Rule: every PR merged into this fork adds exactly one line to the table below**
— the PR's head commit hash, a one-line description of the change, and the PR URL.
Add the line as part of the PR itself. If a change is later upstreamed, remove its
line in the PR that syncs it back.

| Commit | Change | PR |
|---|---|---|
| 24025565 | add FORK.md divergence tracking + AGENTS.md/CLAUDE.md policy | [#5](https://github.com/Tavus-Engineering/centaur/pull/5) |
| 24f6cebb | slack: read non-member public channels/threads via SLACK_SEARCH_TOKEN user-token fallback | [#6](https://github.com/Tavus-Engineering/centaur/pull/6) |
| ff489b5b | pylon tool: read issue threads (get_issue_context/messages/threads, issue-ref normalization) | [#8](https://github.com/Tavus-Engineering/centaur/pull/8) |
| dde06b4c | codex config: use gpt-5.5 medium without fast mode | [#9](https://github.com/Tavus-Engineering/centaur/pull/9) |
| 06a05515 | slackbot: dedupe Slack messages by message identity (team:channel:ts) so an app_mention + message double-delivery collapses to one DM handoff | [#16](https://github.com/Tavus-Engineering/centaur/pull/16) |
| 342b02b1 | tools/sandbox prompt: add Watch Agent Tavus API and SigNoz investigation access | [#17](https://github.com/Tavus-Engineering/centaur/pull/17) |
| 3a3cae9e | sandbox: use Codex's supported flex service tier in the baked sandbox config | [#20](https://github.com/Tavus-Engineering/centaur/pull/20) |
| 447565b9 | slackbot: prompt routed DM users to post successful results back to the original thread | [#21](https://github.com/Tavus-Engineering/centaur/pull/21) |
| 5301a4f1 | slackbot: read full routed DM metadata payloads before posting approved results back | [#22](https://github.com/Tavus-Engineering/centaur/pull/22) |
| 866b8047 | slackbot: restore fork slackbot (v1) dropped by the upstream sync and strip the DM-only "post this answer?" question from results posted back to public threads | [#24](https://github.com/Tavus-Engineering/centaur/pull/24) |
| 886a448e | deployment captain: interactively deploy CVI, RQH, and Tavus API through existing GitHub workflows, with complete immutable Centaur runtime rollouts | [#25](https://github.com/Tavus-Engineering/centaur/pull/25) |
