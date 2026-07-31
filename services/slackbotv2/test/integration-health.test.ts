import { describe, expect, test } from 'bun:test'
import {
  diffForAlerts,
  formatHomeBlocks,
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
  LOGROCKET_HEALTH_URL: 'https://logrocket.example/health',
  LOGROCKET_API_TOKEN: 'lt'
}

function okFetch(url: string): Response {
  if (url.includes('slack.com')) {
    return new Response(JSON.stringify({ ok: true, user: 'watch_agent' }), { status: 200 })
  }
  if (url.includes('linear.app')) {
    return new Response(JSON.stringify({ data: { viewer: { id: 'v1' } } }), { status: 200 })
  }
  return new Response('{}', { status: 200 })
}

describe('runHealthChecks', () => {
  test('reports ok for every configured integration when calls succeed', async () => {
    const urls: string[] = []
    const results = await runHealthChecks(fullEnv, (async (url: string | URL | Request) => {
      urls.push(String(url))
      return okFetch(String(url))
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
    expect(urls.some(url => url.includes('signoz.example/api/v1/version'))).toBe(true)
  })

  test('reports unconfigured when credentials are absent', async () => {
    const results = await runHealthChecks({}, (async () => okFetch('')) as unknown as typeof fetch)
    expect(new Set(results.map(r => r.status))).toEqual(new Set(['unconfigured']))
  })

  test('reports fail with the error for non-2xx and slack ok=false', async () => {
    const results = await runHealthChecks(fullEnv, (async (url: string | URL | Request) => {
      const u = String(url)
      if (u.includes('slack.com')) {
        return new Response(JSON.stringify({ ok: false, error: 'invalid_auth' }), { status: 200 })
      }
      if (u.includes('coda.io')) return new Response('nope', { status: 401 })
      return okFetch(u)
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
  test('renders one line per integration with status and freshness footer', () => {
    const blocks = formatHomeBlocks(
      [result('SigNoz', 'ok'), result('Coda', 'fail', 'HTTP 401'), result('LogRocket', 'unconfigured')],
      15 * 60 * 1000
    ) as Array<{ type: string; text?: { text: string }; elements?: Array<{ text: string }> }>
    expect(blocks[0]?.type).toBe('header')
    const body = blocks[1]?.text?.text ?? ''
    expect(body).toContain(':large_green_circle: *SigNoz* — healthy (5ms)')
    expect(body).toContain(':red_circle: *Coda* — *DOWN*: HTTP 401')
    expect(body).toContain(':white_circle: *LogRocket* — not configured')
    const footer = blocks[2]?.elements?.[0]?.text ?? ''
    expect(footer).toContain('re-checked every 15m')
    expect(footer).toContain('<!date^1785500000^')
  })
})
