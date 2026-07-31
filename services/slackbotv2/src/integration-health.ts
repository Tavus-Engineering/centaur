import type { Logger } from 'chat'
import { usageGuideBlocks } from './home-view'

/**
 * Integration heartbeat: periodically checks each external integration the
 * Watch Agent depends on (cheap read-only authenticated calls), publishes a
 * status board to the Slack App Home tab, and DMs the configured users when an
 * integration breaks or recovers.
 *
 * Configuration (all env):
 * - SLACKBOT_HEALTH_ENABLED: set to "false" to disable (default on).
 * - SLACKBOT_HEALTH_INTERVAL_MS: check cadence (default 15 minutes).
 * - SLACKBOT_HEALTH_ALERT_USERS: comma-separated Slack user IDs to DM on
 *   break/recover transitions. Also the App Home publish targets.
 * - Integration credentials come from the same env the tools use
 *   (SIGNOZ_URL/SIGNOZ_API_KEY, CODA_API_KEY, LINEAR_API_KEY, SLACK_BOT_TOKEN,
 *   GITHUB_TOKEN, BRAINTRUST_API_KEY, LOGROCKET_API_TOKEN+LOGROCKET_HEALTH_URL).
 *   A missing credential shows as "not configured" (grey, never alerts).
 */

export type HealthStatus = 'ok' | 'fail' | 'unconfigured'

export type HealthResult = {
  name: string
  status: HealthStatus
  latencyMs?: number
  error?: string
  checkedAtMs: number
}

type Env = Record<string, string | undefined>
type FetchLike = typeof globalThis.fetch

const CHECK_TIMEOUT_MS = 10_000
export const DEFAULT_INTERVAL_MS = 12 * 60 * 60 * 1000
export const CODEX_CHECK_NAME = 'Codex sandbox'

type CheckSpec = {
  name: string
  /** Undefined -> unconfigured. */
  configured(env: Env): boolean
  run(env: Env, fetchImpl: FetchLike): Promise<void>
}

async function expectHttpOk(response: globalThis.Response): Promise<void> {
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
}

async function expectSlackOk(response: globalThis.Response): Promise<void> {
  await expectHttpOk(response)
  const body = (await response.json()) as { ok?: boolean; error?: string }
  if (body.ok !== true) throw new Error(body.error ?? 'slack ok=false')
}

const CHECKS: CheckSpec[] = [
  {
    name: 'SigNoz',
    configured: env => Boolean(env.SIGNOZ_URL && env.SIGNOZ_API_KEY),
    run: async (env, fetchImpl) => {
      const response = await fetchImpl(`${env.SIGNOZ_URL}/api/v1/version`, {
        headers: { 'SIGNOZ-API-KEY': env.SIGNOZ_API_KEY ?? '' },
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      await expectHttpOk(response)
    }
  },
  {
    name: 'Coda',
    configured: env => Boolean(env.CODA_API_KEY),
    run: async (env, fetchImpl) => {
      const response = await fetchImpl('https://coda.io/apis/v1/whoami', {
        headers: { Authorization: `Bearer ${env.CODA_API_KEY}` },
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      await expectHttpOk(response)
    }
  },
  {
    name: 'Linear',
    configured: env => Boolean(env.LINEAR_API_KEY),
    run: async (env, fetchImpl) => {
      const response = await fetchImpl('https://api.linear.app/graphql', {
        body: JSON.stringify({ query: '{ viewer { id } }' }),
        headers: {
          Authorization: env.LINEAR_API_KEY ?? '',
          'Content-Type': 'application/json'
        },
        method: 'POST',
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      await expectHttpOk(response)
      const body = (await response.json()) as { data?: { viewer?: { id?: string } } }
      if (!body.data?.viewer?.id) throw new Error('viewer query returned no id')
    }
  },
  {
    name: 'Slack',
    configured: env => Boolean(env.SLACK_BOT_TOKEN),
    run: async (env, fetchImpl) => {
      const response = await fetchImpl('https://slack.com/api/auth.test', {
        headers: { Authorization: `Bearer ${env.SLACK_BOT_TOKEN}` },
        method: 'POST',
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      await expectSlackOk(response)
    }
  },
  {
    name: 'GitHub',
    configured: env => Boolean(env.GITHUB_TOKEN),
    run: async (env, fetchImpl) => {
      const response = await fetchImpl('https://api.github.com/rate_limit', {
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          'User-Agent': 'centaur-slackbotv2-health'
        },
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      await expectHttpOk(response)
    }
  },
  {
    name: 'Braintrust',
    configured: env => Boolean(env.BRAINTRUST_API_KEY),
    run: async (env, fetchImpl) => {
      const response = await fetchImpl('https://api.braintrust.dev/v1/project?limit=1', {
        headers: { Authorization: `Bearer ${env.BRAINTRUST_API_KEY}` },
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      await expectHttpOk(response)
    }
  },
  {
    name: 'LogRocket',
    // LogRocket has no stable public "whoami"; the operator provides the
    // authenticated URL to probe alongside the token.
    configured: env => Boolean(env.LOGROCKET_HEALTH_URL),
    run: async (env, fetchImpl) => {
      const headers: Record<string, string> = {}
      if (env.LOGROCKET_API_TOKEN) headers.Authorization = `Token ${env.LOGROCKET_API_TOKEN}`
      const response = await fetchImpl(env.LOGROCKET_HEALTH_URL ?? '', {
        headers,
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      await expectHttpOk(response)
    }
  }
]

export async function runHealthChecks(
  env: Env,
  fetchImpl: FetchLike = globalThis.fetch
): Promise<HealthResult[]> {
  return Promise.all(
    CHECKS.map(async (check): Promise<HealthResult> => {
      const checkedAtMs = Date.now()
      if (!check.configured(env)) {
        return { name: check.name, status: 'unconfigured', checkedAtMs }
      }
      const startedAtMs = Date.now()
      try {
        await check.run(env, fetchImpl)
        return {
          name: check.name,
          status: 'ok',
          latencyMs: Date.now() - startedAtMs,
          checkedAtMs
        }
      } catch (error) {
        return {
          name: check.name,
          status: 'fail',
          latencyMs: Date.now() - startedAtMs,
          error: error instanceof Error ? error.message : String(error),
          checkedAtMs
        }
      }
    })
  )
}

const STATUS_EMOJI: Record<HealthStatus, string> = {
  ok: ':large_green_circle:',
  fail: ':red_circle:',
  unconfigured: ':white_circle:'
}

export function formatHomeBlocks(results: HealthResult[], intervalMs: number): unknown[] {
  const lines = results.map(result => {
    const emoji = STATUS_EMOJI[result.status]
    if (result.status === 'unconfigured') {
      return `${emoji} *${result.name}* — not configured`
    }
    if (result.status === 'ok') {
      return `${emoji} *${result.name}* — healthy (${result.latencyMs}ms)`
    }
    return `${emoji} *${result.name}* — *DOWN*: ${result.error}`
  })
  const checkedAt = Math.floor((results[0]?.checkedAtMs ?? Date.now()) / 1000)
  return [
    {
      type: 'header',
      text: { type: 'plain_text', text: 'Integration heartbeat', emoji: true }
    },
    { type: 'section', text: { type: 'mrkdwn', text: lines.join('\n') } },
    {
      type: 'context',
      elements: [
        {
          type: 'mrkdwn',
          text:
            `Last checked <!date^${checkedAt}^{date_short_pretty} {time}|just now> · ` +
            `re-checked every ${formatInterval(intervalMs)} · alerts DM on break/recover`
        }
      ]
    },
    ...usageGuideBlocks()
  ]
}

function formatInterval(intervalMs: number): string {
  if (intervalMs >= 60 * 60 * 1000) return `${Math.round(intervalMs / (60 * 60 * 1000))}h`
  return `${Math.round(intervalMs / 60_000)}m`
}

/** Break/recover transition messages, comparing against the previous cycle. */
export function diffForAlerts(
  previous: Map<string, HealthStatus> | undefined,
  results: HealthResult[]
): string[] {
  const messages: string[] = []
  for (const result of results) {
    const before = previous?.get(result.name)
    if (result.status === 'fail' && before !== 'fail') {
      messages.push(
        `:red_circle: *${result.name}* integration is DOWN: ${result.error ?? 'unknown error'}`
      )
    }
    if (result.status === 'ok' && before === 'fail') {
      messages.push(`:large_green_circle: *${result.name}* integration recovered.`)
    }
  }
  return messages
}

export function statusMap(results: HealthResult[]): Map<string, HealthStatus> {
  return new Map(results.map(result => [result.name, result.status]))
}

export type IntegrationHealthOptions = {
  logger: Logger
  env?: Env
  fetchImpl?: FetchLike
  intervalMs?: number
  /**
   * End-to-end codex sandbox ping (spawn a session turn, expect an answer).
   * Listed first on the board. Undefined -> shown as not configured. The
   * callback owns its own timeout; a throw marks the check failed.
   */
  codexPing?: () => Promise<void>
}

export class IntegrationHealth {
  private readonly logger: Logger
  private readonly env: Env
  private readonly fetchImpl: FetchLike
  readonly intervalMs: number
  private previous?: Map<string, HealthStatus>
  private latest: HealthResult[] = []
  private timer?: ReturnType<typeof setInterval>

  private readonly codexPing?: () => Promise<void>

  constructor(options: IntegrationHealthOptions) {
    this.logger = options.logger
    this.env = options.env ?? process.env
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch
    this.intervalMs = options.intervalMs ?? intervalFromEnv(this.env)
    this.codexPing = options.codexPing
  }

  private async runCodexCheck(): Promise<HealthResult> {
    const checkedAtMs = Date.now()
    if (!this.codexPing) {
      return { name: CODEX_CHECK_NAME, status: 'unconfigured', checkedAtMs }
    }
    const startedAtMs = Date.now()
    try {
      await this.codexPing()
      return {
        name: CODEX_CHECK_NAME,
        status: 'ok',
        latencyMs: Date.now() - startedAtMs,
        checkedAtMs
      }
    } catch (error) {
      return {
        name: CODEX_CHECK_NAME,
        status: 'fail',
        latencyMs: Date.now() - startedAtMs,
        error: error instanceof Error ? error.message : String(error),
        checkedAtMs
      }
    }
  }

  get alertUserIds(): string[] {
    return (this.env.SLACKBOT_HEALTH_ALERT_USERS ?? '')
      .split(/[\s,]+/)
      .map(part => part.trim())
      .filter(Boolean)
  }

  start(): void {
    // Without an audience there is nothing to publish or alert, so stay off —
    // this also keeps the heartbeat (and its codex ping) out of test harnesses
    // that instantiate the bot without SLACKBOT_HEALTH_ALERT_USERS.
    if (this.env.SLACKBOT_HEALTH_ENABLED === 'false' || this.alertUserIds.length === 0) {
      this.logger.info('slackbotv2_health_disabled', {
        alert_users_configured: this.alertUserIds.length
      })
      return
    }
    void this.runCycle()
    this.timer = setInterval(() => void this.runCycle(), this.intervalMs)
    this.timer.unref?.()
    this.logger.info('slackbotv2_health_started', {
      alert_users: this.alertUserIds.join(','),
      interval_ms: this.intervalMs
    })
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer)
  }

  async runCycle(): Promise<HealthResult[]> {
    try {
      const [codex, rest] = await Promise.all([
        this.runCodexCheck(),
        runHealthChecks(this.env, this.fetchImpl)
      ])
      const results = [codex, ...rest]
      this.latest = results
      const alerts = diffForAlerts(this.previous, results)
      this.previous = statusMap(results)
      this.logger.info('slackbotv2_health_cycle', {
        alerts: alerts.length,
        summary: results.map(r => `${r.name}=${r.status}`).join(' ')
      })
      for (const userId of this.alertUserIds) {
        for (const alert of alerts) {
          await this.sendDm(userId, alert)
        }
        await this.publishHome(userId)
      }
      return results
    } catch (error) {
      this.logger.warn('slackbotv2_health_cycle_failed', {
        error: error instanceof Error ? error.message : String(error)
      })
      return this.latest
    }
  }

  /** Publish the latest board to a user's App Home tab. */
  async publishHome(userId: string): Promise<void> {
    if (!this.latest.length || !this.env.SLACK_BOT_TOKEN) return
    try {
      const response = await this.fetchImpl('https://slack.com/api/views.publish', {
        body: JSON.stringify({
          user_id: userId,
          view: { type: 'home', blocks: formatHomeBlocks(this.latest, this.intervalMs) }
        }),
        headers: {
          Authorization: `Bearer ${this.env.SLACK_BOT_TOKEN}`,
          'Content-Type': 'application/json; charset=utf-8'
        },
        method: 'POST',
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      const body = (await response.json()) as { ok?: boolean; error?: string }
      if (body.ok !== true) {
        this.logger.warn('slackbotv2_health_home_publish_failed', {
          error: body.error ?? `HTTP ${response.status}`,
          user_id: userId
        })
      }
    } catch (error) {
      this.logger.warn('slackbotv2_health_home_publish_failed', {
        error: error instanceof Error ? error.message : String(error),
        user_id: userId
      })
    }
  }

  /** Re-publish when a user opens the App Home tab (app_home_opened webhook). */
  handleWebhookBody(rawBody: string): Promise<void> | undefined {
    let payload: unknown
    try {
      payload = JSON.parse(rawBody)
    } catch {
      return undefined
    }
    if (typeof payload !== 'object' || payload === null) return undefined
    const envelope = payload as { type?: unknown; event?: unknown }
    if (envelope.type !== 'event_callback') return undefined
    const event = envelope.event as { type?: unknown; user?: unknown } | undefined
    if (!event || event.type !== 'app_home_opened' || typeof event.user !== 'string') {
      return undefined
    }
    return this.publishHome(event.user)
  }

  private async sendDm(userId: string, text: string): Promise<void> {
    if (!this.env.SLACK_BOT_TOKEN) return
    try {
      const open = await this.fetchImpl('https://slack.com/api/conversations.open', {
        body: JSON.stringify({ users: userId }),
        headers: {
          Authorization: `Bearer ${this.env.SLACK_BOT_TOKEN}`,
          'Content-Type': 'application/json; charset=utf-8'
        },
        method: 'POST',
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      const opened = (await open.json()) as { ok?: boolean; channel?: { id?: string }; error?: string }
      const channel = opened.channel?.id
      if (opened.ok !== true || !channel) {
        throw new Error(opened.error ?? 'conversations.open failed')
      }
      const post = await this.fetchImpl('https://slack.com/api/chat.postMessage', {
        body: JSON.stringify({ channel, text }),
        headers: {
          Authorization: `Bearer ${this.env.SLACK_BOT_TOKEN}`,
          'Content-Type': 'application/json; charset=utf-8'
        },
        method: 'POST',
        signal: AbortSignal.timeout(CHECK_TIMEOUT_MS)
      })
      const posted = (await post.json()) as { ok?: boolean; error?: string }
      if (posted.ok !== true) throw new Error(posted.error ?? 'chat.postMessage failed')
      this.logger.info('slackbotv2_health_alert_sent', { user_id: userId })
    } catch (error) {
      this.logger.warn('slackbotv2_health_alert_failed', {
        error: error instanceof Error ? error.message : String(error),
        user_id: userId
      })
    }
  }
}

function intervalFromEnv(env: Env): number {
  const parsed = Number(env.SLACKBOT_HEALTH_INTERVAL_MS)
  return Number.isFinite(parsed) && parsed >= 60_000 ? parsed : DEFAULT_INTERVAL_MS
}
