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
| 342b02b1 | tools/sandbox prompt: add Watch Agent Tavus API and SigNoz investigation access | [#17](https://github.com/Tavus-Engineering/centaur/pull/17) |
| 3a3cae9e | sandbox: use Codex's supported flex service tier in the baked sandbox config | [#20](https://github.com/Tavus-Engineering/centaur/pull/20) |
| 4c9f82b4 | deployment captain: interactively deploy CVI, RQH, and Tavus API through existing GitHub workflows, with complete immutable Centaur runtime rollouts | [#25](https://github.com/Tavus-Engineering/centaur/pull/25) |
| 3073f098 | sandbox: prune force-disabled [features.*] tables + validate rewritten codex config (fixes duplicate-key crash killing every turn) | [#26](https://github.com/Tavus-Engineering/centaur/pull/26) |
| 2e0b2dba | slackbotv2: emoji-approved postback of DM investigation answers to the linked origin thread (react ✅ in the DM) | [#28](https://github.com/Tavus-Engineering/centaur/pull/28) |
| ff2901c6 | slackbotv2: integration heartbeat — App Home status board + break/recover DM alerts for SigNoz/Coda/Linear/Slack/GitHub/Braintrust/LogRocket | [#29](https://github.com/Tavus-Engineering/centaur/pull/29) |
| 3ba0bebe | slackbotv2: heartbeat codex sandbox ping-pong + restored App Home usage guide + 12h cadence | [#30](https://github.com/Tavus-Engineering/centaur/pull/30) |
| 552fa6c7 | slackbotv2: heartbeat boot-race fix — 60s startup delay + one re-verify pass before alerting | [#31](https://github.com/Tavus-Engineering/centaur/pull/31) |
| 5f1fb5b3 | slackbotv2: never act on DMs the bot is not a party to (user-scoped event subs delivered private human-to-human DMs as instructions) | [#32](https://github.com/Tavus-Engineering/centaur/pull/32) |
| cc6dc669 | slack: keep Watch Agent investigations inline, acknowledge with :mag:, and require ISO 24495-1 plain-language output | [#33](https://github.com/Tavus-Engineering/centaur/pull/33) |
| 376cb39e | upgrade Watch Agent to Centaur 2.0 with cross-thread recall, complete service deployment, signed API/file proxy repair, and durable Tavus tool grants | [#35](https://github.com/Tavus-Engineering/centaur/pull/35) |
| 35cabfad | align Watch Agent with GPT-5.6 Sol high and verified brokered LogRocket/Coda/Braintrust/SigNoz/GitHub/Linear/Slack tool access | [#36](https://github.com/Tavus-Engineering/centaur/pull/36) |
| 6c71e32f | slackbotv2: keep one reply inline, then continue directed follow-ups in a reusable investigations-channel thread | [#37](https://github.com/Tavus-Engineering/centaur/pull/37) |
| 4dfa3bab | upgrade to Centaur 0.1.129, preserve Watch Agent runtime paths, and add bounded host cleanup | [#38](https://github.com/Tavus-Engineering/centaur/pull/38) |
