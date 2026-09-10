import { expect, test } from 'bun:test'
import { codexSandboxPing } from '../src/index'
import type { SlackbotV2Options } from '../src/types'

test('heartbeat completes through the Slack ingress session authorization boundary', async () => {
  const requests: string[] = []
  const fetch: SlackbotV2Options['fetch'] = async (input) => {
    const url = new URL(String(input))
    const path = decodeURIComponent(url.pathname)
    requests.push(path)
    // Mirror api-rs: the Slack ingress may only access slack: sessions.
    if (!path.startsWith('/api/session/slack:')) {
      return Response.json({ ok: false, error: 'caller is not authorized for this session' }, {
        status: 403
      })
    }
    if (path.endsWith('/events')) {
      return new Response(
        'id: 1\nevent: session.execution_completed\ndata: {"result_text":"pong"}\n\n',
        { headers: { 'content-type': 'text/event-stream' } }
      )
    }
    if (path.endsWith('/execute')) {
      return Response.json({ ok: true, execution_id: 'heartbeat-execution', status: 'running' })
    }
    return Response.json({ ok: true })
  }

  await codexSandboxPing({
    apiUrl: 'http://api.test',
    apiKey: 'slack-ingress-test-key',
    botToken: 'xoxb-test',
    signingSecret: 'test-signing-secret',
    fetch
  })

  expect(requests).toHaveLength(4)
  expect(requests[0]).toMatch(/^\/api\/session\/slack:health:codex-ping:\d+$/)
  expect(requests.slice(1)).toEqual([
    `${requests[0]}/messages`,
    `${requests[0]}/execute`,
    `${requests[0]}/events`
  ])
})
