# Fork changes

This is Tavus's fork of [paradigmxyz/centaur](https://github.com/paradigmxyz/centaur).
This file is the single source of truth for how this fork differs from upstream.

**Rule: every PR merged into this fork adds exactly one line to the table below**
— the PR's head commit hash, a one-line description of the change, and the PR URL.
Add the line as part of the PR itself. If a change is later upstreamed, remove its
line in the PR that syncs it back.

| Commit | Change | PR |
|---|---|---|
| 555ec005 | slackbot: reply to DMs and joined threads without a mention | [#2](https://github.com/Tavus-Engineering/centaur/pull/2) |
| 06128dc9 | api: select harness from bare claude/codex words in Slack turns (selectors, not wake words) | [#4](https://github.com/Tavus-Engineering/centaur/pull/4) |
| 24025565 | add FORK.md divergence tracking + AGENTS.md/CLAUDE.md policy | [#5](https://github.com/Tavus-Engineering/centaur/pull/5) |
| 24f6cebb | slack: read non-member public channels/threads via SLACK_SEARCH_TOKEN user-token fallback | [#6](https://github.com/Tavus-Engineering/centaur/pull/6) |
| 33213991 | sandbox: auto-raise codex reasoning effort to high for code/debug turns (heuristic on first message) | [#7](https://github.com/Tavus-Engineering/centaur/pull/7) |
| ff489b5b | pylon tool: read issue threads (get_issue_context/messages/threads, issue-ref normalization) | [#8](https://github.com/Tavus-Engineering/centaur/pull/8) |
| dde06b4c | cost controls: reuse unthreaded DM runtimes, shorten idle TTL, and use gpt-5.5 medium without fast mode | [#9](https://github.com/Tavus-Engineering/centaur/pull/9) |
| 1385fbfa | slackbot: ignore inaccessible DM events before agent handoff | [#10](https://github.com/Tavus-Engineering/centaur/pull/10) |
| 5a598aae | api: respawn unresumable suspended sandboxes (pod backend) + post runtime-start failures once per thread | [#11](https://github.com/Tavus-Engineering/centaur/pull/11) |
| 5ac94c35 | slackbot: channel-thread replies require @-mention (undoes joined-thread auto-reply from #2); codex wrapper falls back to fresh thread on dead rollout | [#12](https://github.com/Tavus-Engineering/centaur/pull/12) |
| a9d47a12 | api: finalize codex turn.failed as failed_permanent + post failure notice to Slack; raise iron-proxy upstream header timeout to 300s (codex remote compaction); fold signoz/aws header allowlist into base.yaml | [#13](https://github.com/Tavus-Engineering/centaur/pull/13) |
