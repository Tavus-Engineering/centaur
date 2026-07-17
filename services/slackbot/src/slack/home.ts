import type { AnyBlock, HomeView } from '@slack/types'
import type { WebClient } from '@slack/web-api'

const CALLBACK_ID = 'watch_agent_home_v1'

export function buildWatchAgentHomeView(): HomeView {
  return {
    type: 'home',
    callback_id: CALLBACK_ID,
    blocks: [
      header('Watch Agent'),
      section(
        '*Centaur-powered Tavus engineering agent*\n' +
          'Use this app in DMs or mention it in a channel thread when you want a persistent AI teammate that can read context, inspect code, query observability, and run Centaur workflows.'
      ),
      context(
        'Live tools can differ by deployment and overlay. Ask `what tools are live right now?` for an exact inventory before relying on a specific connector.'
      ),
      divider(),
      header('What It Can Do'),
      fields([
        '*Investigate Tavus incidents*\nTrace CVI conversations, personas, transcripts, realtime-replica, request-handler, worker logs, and CloudWatch/SigNoz evidence.',
        '*Review and ship code*\nRead Tavus repos, review branches/PRs, run focused tests, commit/push approved changes, and watch CI when asked.',
        '*Find internal context*\nSearch across code, PRs, issues, Slack decisions, Linear projects, docs, and Coda-backed context where configured.',
        '*Operate Centaur*\nRun local stack QA, inspect agent executions, check VictoriaLogs/VictoriaMetrics, and debug Slackbot delivery paths.',
        '*Build tools and workflows*\nCreate tool plugins, durable workflows, dashboards, alerts, saved views, and recurring agent loops.',
        '*Synthesize updates*\nDraft Linear status posts, weekly all-hands rollups, RCA summaries, QA reports, and comparison artifacts.'
      ]),
      divider(),
      header('Connected Systems'),
      fields([
        '*MCP and connector-style systems*\nTavus CLI/MCP, SigNoz, Slack, Coda, GitHub, Linear, AWS, Google Workspace, Notion, Figma, and deployment-specific tool overlays.',
        '*Centaur API tools*\nUse `call tools` for the live list, then `call discover <tool>` before invoking methods. Tool calls route through Centaur auth and audit logging.',
        '*Observability*\nVictoriaLogs, VictoriaMetrics, SigNoz queries, dashboard/alert workflows, execution timelines, tool analytics, and prompt/model analytics.',
        '*Repository access*\nMounted Tavus repos, GitHub API, local code search, PR metadata, issue context, CI checks, and deployment notes.'
      ]),
      divider(),
      header('CLI And Harnesses'),
      fields([
        '*Harness selectors*\nDefault is Codex. Add `--codex`, `--amp`, `--claude`, or `--pi` when you want a specific runtime.',
        '*Repo and shell tools*\n`git`, `gh`, `rg`, `fd`, `jq`, `uv`, `node`, `bun`, `pnpm`, `rust`, `forge`, `cast`, `anvil`, `tmux`, `cmake`, and protobuf tooling.',
        '*Centaur helper*\nInside the sandbox, API tools are called with `call <tool> <method> <json>`. Legacy `call search` and `call sql` shorthands are not used.',
        '*Durable workflows*\nAsk for recurring checks or long-running tasks; Centaur can run child workflows and report back after sleeps, events, or agent turns.'
      ]),
      divider(),
      header('Tavus Skills'),
      section(
        [
          '`tavus-context` - cross-system Tavus research across GitHub, Linear, Slack, and docs.',
          '`tavus-repos` - map Tavus repos, services, env vars, webhooks, and ownership boundaries.',
          '`tavus-investigate-conversation` - RCA a CVI conversation from config, traces, logs, and code.',
          '`tavus-investigate-persona` - inspect persona config, tools, guardrails, and behavior.',
          '`tavus-weekly-rollup` - summarize merged PRs across Tavus engineering repos.',
          '`linear-sync` - draft and post M/W/F Linear project status updates.',
          '`commit-pr` - preflight, commit, push, open/update a PR, and watch CI.',
          '`install-tools` - repair or verify Tavus CLIs and MCP servers.'
        ].join('\n')
      ),
      header('Centaur And SigNoz Skills'),
      section(
        [
          '`qa`, `dogfood`, `auth-failure-log-triage`, `creating-tools`, `learning-synthesis`, `improve-gap-task`.',
          '`signoz-generating-queries`, `signoz-investigating-alerts`, `signoz-creating-dashboards`, `signoz-creating-alerts`, `signoz-setting-up-observability`, plus dashboard, alert, view, docs, MCP setup, and ClickHouse-query helpers.'
        ].join('\n')
      ),
      divider(),
      header('Sample Prompts'),
      section(
        [
          '- `Investigate conversation c123. Why did the user hear silence? Include RQH, realtime-replica, SigNoz, and CloudWatch evidence.`',
          '- `What tools and personas are live in this Watch Agent deployment right now?`',
          '- `Review PR 123 in request-handler against main and tell me if it is merge-ready.`',
          '- `Run Centaur QA locally and give me failures with exact repro steps.`',
          '- `Find the full Tavus context for why we changed persona tool ownership.`',
          '- `Create a weekly all-hands rollup of merged Tavus engineering PRs.`',
          '- `Query p95 latency and error rate for realtime-replica over the last hour.`',
          '- `Look up persona p123, list attached tools, and explain likely behavior risks.`'
        ].join('\n')
      ),
      divider(),
      context(
        'Tip: mention Watch Agent in a channel for shared work, or use the Messages tab for a private one-on-one thread.'
      )
    ]
  }
}

export async function publishWatchAgentHome(client: WebClient, userId: string): Promise<unknown> {
  return client.views.publish({
    user_id: userId,
    view: buildWatchAgentHomeView()
  })
}

function header(text: string): AnyBlock {
  return {
    type: 'header',
    text: {
      type: 'plain_text',
      text,
      emoji: false
    }
  }
}

function section(text: string): AnyBlock {
  return {
    type: 'section',
    text: {
      type: 'mrkdwn',
      text
    }
  }
}

function fields(items: string[]): AnyBlock {
  return {
    type: 'section',
    fields: items.map(text => ({
      type: 'mrkdwn',
      text
    }))
  }
}

function context(text: string): AnyBlock {
  return {
    type: 'context',
    elements: [
      {
        type: 'mrkdwn',
        text
      }
    ]
  }
}

function divider(): AnyBlock {
  return { type: 'divider' }
}
