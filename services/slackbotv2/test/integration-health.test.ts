import { describe, expect, test } from 'bun:test'
import type { Logger } from 'chat'
import {
  CODEX_CHECK_NAME,
  diffForAlerts,
  formatHomeBlocks,
  IntegrationHealth,
  runHealthChecks,
  statusMap,
  type HealthResult
} from '../src/integration-health'

const fullEnv = {
  SIGNOZ_URL: 'https://signoz.example',
  SIGNOZ_API_KEY: 'sk',
  CODA_API_KEY: 'ck',
  LINEAR_API_KEY: 'lk',
  SLACK_BOT_TOKEN: 'xoxb-test',
  GITHUB_TOKEN: 'ghp-test',
  BRAINTRUST_API_KEY: 'bk',
  LOGROCKET_API_TOKEN: 'lt'
}

function okFetch(url: string, init?: RequestInit): Response {
  if (url.includes('slack.com')) {
    return new Response(JSON.stringify({ ok: true, user: 'watch_agent' }), { status: 200 })
  }
  if (url.includes('linear.app')) {
    return new Response(JSON.stringify({ data: { viewer: { id: 'v1' } } }), { status: 200 })
  }
  const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
  if (body?.method === 'initialize') {
    return new Response(
      `event: message\ndata: ${JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} })}\n\n`,
      {
        status: 200,
        headers: {
          'content-type': 'text/event-stream',
          ...(url.includes('docs.superhuman.com') ? { 'mcp-session-id': 'session-1' } : {})
        }
      }
    )
  }
  if (body?.method === 'notifications/initialized') return new Response(null, { status: 202 })
  if (body?.method === 'tools/list') {
    return new Response(
      JSON.stringify({
        jsonrpc: '2.0',
        id: body.id,
        result: { tools: [{ name: 'search' }, { name: 'get' }, { name: 'list' }] }
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    )
  }
  if (body?.method === 'tools/call') {
    return new Response(JSON.stringify({ jsonrpc: '2.0', id: body.id, result: { content: [] } }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    })
  }
  return new Response('{}', { status: 200 })
}

describe('runHealthChecks', () => {
  test('reports ok for every configured integration when calls succeed', async () => {
    const urls: string[] = []
    const results = await runHealthChecks(fullEnv, (async (
      url: string | URL | Request,
      init?: RequestInit
    ) => {
      urls.push(String(url))
      return okFetch(String(url), init)
    }) as unknown as typeof fetch)
    expect(results.map(r => `${r.name}=${r.status}`).sort()).toEqual([
      'Braintrust=ok',
      'Coda=ok',
      'GitHub=ok',
      'Linear=ok',
      'LogRocket=ok',
      'SigNoz=ok',
      'Slack=ok'
    ])
    expect(urls.some(url => url.includes('mcp.us.signoz.cloud/mcp'))).toBe(true)
    expect(results.find(result => result.name === 'LogRocket')?.toolSurface).toBe('3 MCP tools')
    expect(results.find(result => result.name === 'GitHub')?.toolSurface).toBe('gh CLI')
    expect(urls.filter(url => url.includes('api.braintrust.dev/mcp'))).toHaveLength(4)
  })

  test('fails Braintrust when discovery is public but the authenticated probe fails', async () => {
    const results = await runHealthChecks(fullEnv, (async (
      url: string | URL | Request,
      init?: RequestInit
    ) => {
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
      if (String(url).includes('api.braintrust.dev') && body?.method === 'tools/call') {
        return new Response(
          JSON.stringify({
            jsonrpc: '2.0',
            id: body.id,
            result: { isError: true, content: [{ type: 'text', text: 'unauthorized' }] }
          }),
          { status: 200, headers: { 'content-type': 'application/json' } }
        )
      }
      return okFetch(String(url), init)
    }) as unknown as typeof fetch)

    const braintrust = results.find(result => result.name === 'Braintrust')
    expect(braintrust?.status).toBe('fail')
    expect(braintrust?.error).toBe('MCP authenticated probe failed')
  })

  test('reports unconfigured when credentials are absent', async () => {
    const results = await runHealthChecks({}, (async () => okFetch('')) as unknown as typeof fetch)
    expect(new Set(results.map(r => r.status))).toEqual(new Set(['unconfigured']))
  })

  test('reports fail with the error for non-2xx and slack ok=false', async () => {
    const results = await runHealthChecks(fullEnv, (async (
      url: string | URL | Request,
      init?: RequestInit
    ) => {
      const u = String(url)
      if (u.includes('slack.com')) {
        return new Response(JSON.stringify({ ok: false, error: 'invalid_auth' }), { status: 200 })
      }
      if (u.includes('docs.superhuman.com')) return new Response('nope', { status: 401 })
      return okFetch(u, init)
    }) as unknown as typeof fetch)
    const byName = new Map(results.map(r => [r.name, r]))
    expect(byName.get('Slack')?.status).toBe('fail')
    expect(byName.get('Slack')?.error).toBe('invalid_auth')
    expect(byName.get('Coda')?.status).toBe('fail')
    expect(byName.get('Coda')?.error).toBe('HTTP 401')
    expect(byName.get('GitHub')?.status).toBe('ok')
  })
})

function result(name: string, status: HealthResult['status'], error?: string): HealthResult {
  return { name, status, error, latencyMs: 5, checkedAtMs: 1_785_500_000_000 }
}

describe('diffForAlerts', () => {
  test('alerts on new failures and recoveries only', () => {
    const previous = statusMap([
      result('SigNoz', 'ok'),
      result('Coda', 'fail'),
      result('Slack', 'fail')
    ])
    const alerts = diffForAlerts(previous, [
      result('SigNoz', 'fail', 'HTTP 500'), // ok -> fail: alert
      result('Coda', 'fail', 'HTTP 401'), // still failing: no alert
      result('Slack', 'ok'), // fail -> ok: recovery
      result('LogRocket', 'unconfigured') // never alerts
    ])
    expect(alerts).toHaveLength(2)
    expect(alerts[0]).toContain('SigNoz')
    expect(alerts[0]).toContain('DOWN')
    expect(alerts[1]).toContain('Slack')
    expect(alerts[1]).toContain('recovered')
  })

  test('first cycle alerts only on failures', () => {
    const alerts = diffForAlerts(undefined, [result('SigNoz', 'ok'), result('Coda', 'fail', 'x')])
    expect(alerts).toHaveLength(1)
    expect(alerts[0]).toContain('Coda')
  })
})

describe('formatHomeBlocks', () => {
  test('renders heartbeat lines, freshness footer, then the usage guide', () => {
    const blocks = formatHomeBlocks(
      [result('SigNoz', 'ok'), result('Coda', 'fail', 'HTTP 401'), result('LogRocket', 'unconfigured')],
      12 * 60 * 60 * 1000
    ) as Array<{ type: string; text?: { text: string }; elements?: Array<{ text: string }> }>
    expect(blocks[0]?.type).toBe('header')
    const body = blocks[1]?.text?.text ?? ''
    expect(body).toContain(':large_green_circle: *SigNoz* — healthy (5ms)')
    expect(body).toContain(':red_circle: *Coda* — *DOWN*: HTTP 401')
    expect(body).toContain(':white_circle: *LogRocket* — not configured')
    const footer = blocks[2]?.elements?.[0]?.text ?? ''
    expect(footer).toContain('re-checked every 12h')
    expect(footer).toContain('<!date^1785500000^')
    // Usage guide restored below the heartbeat.
    const rendered = JSON.stringify(blocks)
    expect(rendered).toContain('What It Can Do')
    expect(rendered).toContain('Sample Prompts')
    expect(rendered).toContain('tavus-investigate-conversation')
    expect(blocks.length).toBeGreaterThan(10)
  })
})

const testLogger: Logger = {
  child: () => testLogger,
  debug: () => undefined,
  error: () => undefined,
  info: () => undefined,
  warn: () => undefined
}

describe('IntegrationHealth codex ping', () => {
  test('lists the codex sandbox and tool check first, ok when the ping resolves', async () => {
    const health = new IntegrationHealth({
      codexPing: async () => undefined,
      env: {},
      fetchImpl: (async () => okFetch('')) as unknown as typeof fetch,
      logger: testLogger
    })
    const results = await health.runCycle()
    expect(results[0]?.name).toBe(CODEX_CHECK_NAME)
    expect(results[0]?.status).toBe('ok')
  })

  test('marks the codex check failed with the thrown error after one re-verify', async () => {
    let attempts = 0
    const health = new IntegrationHealth({
      codexPing: async () => {
        attempts++
        throw new Error('sandbox spawn failed')
      },
      env: { SLACKBOT_HEALTH_RETRY_DELAY_MS: '0' },
      fetchImpl: (async () => okFetch('')) as unknown as typeof fetch,
      logger: testLogger
    })
    const results = await health.runCycle()
    expect(results[0]?.status).toBe('fail')
    expect(results[0]?.error).toBe('sandbox spawn failed')
    expect(attempts).toBe(2)
  })

  test('a transient codex failure recovers on the re-verify pass without alerting', async () => {
    let attempts = 0
    const health = new IntegrationHealth({
      codexPing: async () => {
        attempts++
        if (attempts === 1) throw new Error('transient connect error')
      },
      env: { SLACKBOT_HEALTH_RETRY_DELAY_MS: '0' },
      fetchImpl: (async () => okFetch('')) as unknown as typeof fetch,
      logger: testLogger
    })
    const results = await health.runCycle()
    expect(results[0]?.status).toBe('ok')
    expect(attempts).toBe(2)
  })

  test('shows unconfigured without a ping callback and defaults to 12h', async () => {
    const health = new IntegrationHealth({
      env: {},
      fetchImpl: (async () => okFetch('')) as unknown as typeof fetch,
      logger: testLogger
    })
    expect(health.intervalMs).toBe(12 * 60 * 60 * 1000)
    const results = await health.runCycle()
    expect(results[0]?.name).toBe(CODEX_CHECK_NAME)
    expect(results[0]?.status).toBe('unconfigured')
  })
})
