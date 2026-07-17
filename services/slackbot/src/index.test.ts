import { createHmac } from 'node:crypto'
import { afterEach, describe, expect, it, mock } from 'bun:test'

const originalEnv = { ...process.env }

afterEach(() => {
  for (const key of Object.keys(process.env)) {
    if (!(key in originalEnv)) delete process.env[key]
  }
  Object.assign(process.env, originalEnv)
})

describe('Slack event HTTP dedupe', () => {
  it('publishes the Watch Agent Home tab when App Home is opened', async () => {
    process.env.SLACK_SIGNING_SECRET = 'test-signing-secret'
    process.env.SLACK_BOT_TOKEN = 'xoxb-home-test'
    delete process.env.SLACKBOT_API_KEY
    delete process.env.CENTAUR_API_KEY

    const slackCalls: Array<{ path: string; body: Record<string, unknown> }> = []
    const slackApi = Bun.serve({
      port: 0,
      async fetch(request) {
        const url = new URL(request.url)
        const body = await slackApiBody(request)
        slackCalls.push({ path: url.pathname, body })
        if (url.pathname === '/api/auth.test') {
          return Response.json({ ok: true, user_id: 'UBOT', bot_id: 'BBOT' })
        }
        if (url.pathname === '/api/views.publish') {
          return Response.json({ ok: true, view: { id: 'VHOME' } })
        }
        return Response.json({ ok: false, error: 'unexpected_slack_method' }, { status: 404 })
      }
    })
    process.env.SLACK_API_URL = `http://127.0.0.1:${slackApi.port}/api/`

    try {
      const { app } = await import(`./index.ts?app_home=${Date.now()}`)
      const body = JSON.stringify({
        type: 'event_callback',
        event_id: 'Ev-home-opened',
        team_id: 'T123',
        event: {
          type: 'app_home_opened',
          user: 'UHOME',
          channel: 'DHOME',
          tab: 'home',
          event_ts: '1778883099.579531'
        }
      })
      const waits: Promise<unknown>[] = []
      const response = await app.request(
        '/api/webhooks/slack',
        signedJsonRequest(body, process.env.SLACK_SIGNING_SECRET),
        {},
        {
          waitUntil: (promise: Promise<unknown>) => {
            waits.push(promise)
          }
        } as any
      )

      expect(response.status).toBe(200)
      expect(await response.json()).toEqual({ ok: true })
      await Promise.allSettled(waits)

      const publish = slackCalls.find(call => call.path === '/api/views.publish')
      expect(publish?.body.user_id).toBe('UHOME')
      const view = publish?.body.view as Record<string, unknown> | undefined
      expect(view?.type).toBe('home')
      expect(JSON.stringify(view?.blocks)).toContain('Watch Agent')
      expect(JSON.stringify(view?.blocks)).toContain('tavus-context')
    } finally {
      await slackApi.stop()
    }
  })

  it('creates Linear issues from configured feedback slash commands', async () => {
    process.env.SLACK_SIGNING_SECRET = 'test-signing-secret'
    process.env.LINEAR_API_KEY = 'lin-test-key'
    process.env.SLACK_FEEDBACK_LINEAR_TEAM_ID = 'team-feedback'
    process.env.SLACK_FEEDBACK_LINEAR_PROJECT_ID = 'project-feedback'
    delete process.env.SLACK_BOT_TOKEN
    delete process.env.SLACKBOT_API_KEY
    delete process.env.CENTAUR_API_KEY

    const originalFetch = globalThis.fetch
    const fetchMock = mock(async (_input: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(init?.body as string) as {
        variables: { input: { title: string; teamId: string; projectId: string } }
      }
      expect(body.variables.input).toMatchObject({
        title: 'Button copy is confusing',
        teamId: 'team-feedback',
        projectId: 'project-feedback'
      })
      return new Response(
        JSON.stringify({
          data: {
            issueCreate: {
              issue: {
                identifier: 'DSGN-123',
                url: 'https://linear.app/paradigmxyz/issue/DSGN-123'
              }
            }
          }
        }),
        { status: 200 }
      )
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    try {
      const { app } = await import('./index')
      const body = new URLSearchParams({
        command: '/website-feedback',
        text: 'Button copy is confusing\nThe submit button should mention Linear.',
        user_id: 'U123',
        channel_id: 'C123',
        channel_name: 'design-feedback'
      }).toString()

      const response = await app.request(
        '/api/slack/commands',
        signedFormRequest(body, process.env.SLACK_SIGNING_SECRET)
      )

      expect(response.status).toBe(200)
      expect(await response.json()).toEqual({
        response_type: 'ephemeral',
        text: 'Created DSGN-123: https://linear.app/paradigmxyz/issue/DSGN-123'
      })
      expect(fetchMock).toHaveBeenCalledTimes(1)
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  it('routes addressed channel-thread mentions into one DM workflow handoff', async () => {
    process.env.SLACK_SIGNING_SECRET = 'test-signing-secret'
    process.env.SLACK_BOT_TOKEN = 'xoxb-thread-route-test'
    process.env.SLACK_EVENT_DEDUP_TTL_MS = '600000'
    delete process.env.SLACKBOT_API_KEY
    delete process.env.CENTAUR_API_KEY

    const slackCalls: Array<{ path: string; body: Record<string, unknown> }> = []
    const slackApi = Bun.serve({
      port: 0,
      async fetch(request) {
        const url = new URL(request.url)
        const body = await slackApiBody(request)
        slackCalls.push({ path: url.pathname, body })
        if (url.pathname === '/api/auth.test') {
          return Response.json({ ok: true, user_id: 'UBOT', bot_id: 'BBOT' })
        }
        if (url.pathname === '/api/conversations.replies') {
          return Response.json({
            ok: true,
            messages: [
              {
                type: 'message',
                user: 'UORIG',
                text: 'Original customer issue',
                ts: '1778883000.000000'
              }
            ]
          })
        }
        if (url.pathname === '/api/reactions.add') {
          return Response.json({ ok: true })
        }
        if (url.pathname === '/api/conversations.open') {
          return Response.json({ ok: true, channel: { id: 'D123' } })
        }
        if (url.pathname === '/api/chat.postMessage') {
          return Response.json({ ok: true, channel: 'D123', ts: '1778884000.000000' })
        }
        return Response.json({ ok: false, error: 'unexpected_slack_method' }, { status: 404 })
      }
    })
    process.env.SLACK_API_URL = `http://127.0.0.1:${slackApi.port}/api/`

    const centaurRequests: Array<{ path: string; body: Record<string, unknown> }> = []
    const centaurApi = Bun.serve({
      port: 0,
      async fetch(request) {
        const url = new URL(request.url)
        const body = (await request.json()) as Record<string, unknown>
        centaurRequests.push({ path: url.pathname, body })
        if (url.pathname === '/workflows/runs') {
          return Response.json({ ok: true, run_id: 'run_123' })
        }
        return Response.json({ ok: false, error: 'unexpected_centaur_path' }, { status: 404 })
      }
    })
    process.env.CENTAUR_API_URL = `http://127.0.0.1:${centaurApi.port}`

    try {
      const { app } = await import(`./index.ts?thread_route=${Date.now()}`)
      const mentionBody = JSON.stringify({
        type: 'event_callback',
        event_id: 'Ev-thread-route-app',
        team_id: 'T123',
        event: {
          type: 'app_mention',
          user: 'U123',
          channel: 'C123',
          thread_ts: '1778883000.000000',
          ts: '1778883001.000000',
          text: '<@UBOT> investigate this'
        }
      })
      const messageBody = JSON.stringify({
        type: 'event_callback',
        event_id: 'Ev-thread-route-message',
        team_id: 'T123',
        event: {
          type: 'message',
          user: 'U123',
          channel: 'C123',
          thread_ts: '1778883000.000000',
          ts: '1778883001.000000',
          text: '<@UBOT> investigate this'
        }
      })
      const waits: Promise<unknown>[] = []
      const mentionResponse = await app.request(
        '/api/webhooks/slack',
        signedJsonRequest(mentionBody, process.env.SLACK_SIGNING_SECRET),
        {},
        {
          waitUntil: (promise: Promise<unknown>) => {
            waits.push(promise)
          }
        } as any
      )
      const messageResponse = await app.request(
        '/api/webhooks/slack',
        signedJsonRequest(messageBody, process.env.SLACK_SIGNING_SECRET),
        {},
        {
          waitUntil: (promise: Promise<unknown>) => {
            waits.push(promise)
          }
        } as any
      )

      expect(mentionResponse.status).toBe(200)
      expect(await mentionResponse.json()).toEqual({ ok: true })
      expect(messageResponse.status).toBe(200)
      expect(await messageResponse.json()).toEqual({ ok: true, duplicate: true })
      await Promise.allSettled(waits)

      expect(slackCalls.find(call => call.path === '/api/reactions.add')?.body).toMatchObject({
        channel: 'C123',
        timestamp: '1778883001.000000',
        name: 'incoming_envelope'
      })
      expect(slackCalls.find(call => call.path === '/api/conversations.open')?.body).toMatchObject({
        users: 'U123'
      })
      const dmRootMessages = slackCalls.filter(call => call.path === '/api/chat.postMessage')
      expect(dmRootMessages).toHaveLength(1)
      const dmRoot = dmRootMessages[0]
      expect(dmRoot?.body).toMatchObject({
        channel: 'D123'
      })
      expect(dmRoot?.body.text).toContain('Original request:')
      expect(dmRoot?.body.metadata).toMatchObject({
        event_type: 'centaur_thread_dm_route',
        event_payload: expect.objectContaining({
          source_channel_id: 'C123',
          source_thread_ts: '1778883000.000000',
          source_message_ts: '1778883001.000000'
        })
      })

      const workflow = centaurRequests.find(request => request.path === '/workflows/runs')?.body as
        | { input?: Record<string, unknown> }
        | undefined
      expect(centaurRequests.filter(request => request.path === '/workflows/runs')).toHaveLength(1)
      expect(workflow?.input).toMatchObject({
        thread_key: 'slack:T123:D123:1778884000.000000',
        delivery: {
          channel: 'D123',
          thread_ts: '1778884000.000000'
        },
        metadata: {
          route: expect.objectContaining({
            mode: 'dm_from_thread_mention',
            source_channel_id: 'C123',
            source_thread_ts: '1778883000.000000',
            dm_channel_id: 'D123',
            dm_thread_ts: '1778884000.000000'
          })
        }
      })
      expect(JSON.stringify(workflow?.input)).toContain('keep the answer in this DM')
      expect(JSON.stringify(workflow?.input)).not.toContain(
        'Do you want me to post this answer if it succeeds?'
      )
    } finally {
      await slackApi.stop()
      await centaurApi.stop()
    }
  })

  it('prompts routed DM postback from final status after Codex closes the stream', async () => {
    process.env.SLACK_BOT_TOKEN = 'xoxb-routed-dm-postback-test'
    process.env.SLACKBOT_API_KEY = 'test-slackbot-api-key'
    delete process.env.CENTAUR_API_KEY

    const slackCalls: Array<{ path: string; body: Record<string, unknown> }> = []
    const slackApi = Bun.serve({
      port: 0,
      async fetch(request) {
        const url = new URL(request.url)
        const body = await slackApiBody(request)
        slackCalls.push({ path: url.pathname, body })
        if (url.pathname === '/api/auth.test') {
          return Response.json({ ok: true, user_id: 'UBOT', bot_id: 'BBOT' })
        }
        if (url.pathname === '/api/assistant.threads.setStatus') {
          return Response.json({ ok: true })
        }
        if (url.pathname === '/api/chat.startStream') {
          return Response.json({ ok: true, channel: 'D123', ts: '1778885000.000000' })
        }
        if (url.pathname === '/api/chat.stopStream') {
          return Response.json({ ok: true, channel: 'D123', ts: '1778885000.000000' })
        }
        if (url.pathname === '/api/conversations.replies') {
          return Response.json({
            ok: true,
            messages: [
              {
                ts: '1778884000.000000',
                metadata: {
                  event_type: 'centaur_thread_dm_route',
                  event_payload: {
                    source_team_id: 'T123',
                    source_channel_id: 'C123',
                    source_thread_ts: '1778883000.000000',
                    source_message_ts: '1778883001.000000',
                    source_request_url: 'https://slack.com/archives/C123/p1778883001000000',
                    source_thread_url: 'https://slack.com/archives/C123/p1778883000000000'
                  }
                }
              }
            ]
          })
        }
        if (url.pathname === '/api/chat.postMessage') {
          return Response.json({ ok: true, channel: 'D123', ts: '1778885001.000000' })
        }
        return Response.json({ ok: false, error: 'unexpected_slack_method' }, { status: 404 })
      }
    })
    process.env.SLACK_API_URL = `http://127.0.0.1:${slackApi.port}/api/`

    try {
      const { app } = await import(`./index.ts?routed_dm_done=${Date.now()}`)
      const opened = await app.request('/api/slack/agent-sessions', {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          channel: 'D123',
          parent_ts: '1778884000.000000',
          recipient_team_id: 'T123',
          recipient_user_id: 'U123',
          title: 'Watch Agent'
        })
      })
      expect(opened.status).toBe(200)
      const { session_id: sessionId } = (await opened.json()) as { session_id: string }

      const terminal = await app.request(`/api/slack/agent-sessions/${sessionId}/harness-event`, {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({ event: { type: 'turn.completed', result: 'Done.' } })
      })
      expect(terminal.status).toBe(200)
      expect(await terminal.json()).toMatchObject({ ok: true, done: true })

      const done = await app.request(`/api/slack/agent-sessions/${sessionId}/done`, {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({ status: 'completed' })
      })
      expect(done.status).toBe(200)

      const prompts = slackCalls.filter(call => call.path === '/api/chat.postMessage')
      expect(prompts).toHaveLength(1)
      expect(prompts[0]?.body).toMatchObject({
        channel: 'D123',
        thread_ts: '1778884000.000000',
        metadata: {
          event_type: 'centaur_thread_postback_prompt',
          event_payload: {
            source_channel_id: 'C123',
            source_thread_ts: '1778883000.000000'
          }
        }
      })
      expect(prompts[0]?.body.text).toContain('Reply `post it`')
    } finally {
      await slackApi.stop()
    }
  })

  it('acks duplicate Slack envelopes without scheduling duplicate processing', async () => {
    process.env.SLACK_SIGNING_SECRET = 'test-signing-secret'
    process.env.SLACK_EVENT_DEDUP_TTL_MS = '600000'
    delete process.env.SLACK_BOT_TOKEN
    delete process.env.SLACKBOT_API_KEY
    delete process.env.CENTAUR_API_KEY

    const originalError = console.error
    const originalLog = console.log
    const originalWarn = console.warn
    console.error = mock(() => {}) as typeof console.error
    console.log = mock(() => {}) as typeof console.log
    console.warn = mock(() => {}) as typeof console.warn
    try {
      const { app } = await import('./index')
      const body = JSON.stringify({
        type: 'event_callback',
        event_id: 'Ev-duplicate',
        team_id: 'T123',
        event: {
          type: 'app_mention',
          user: 'U123',
          channel: 'C123',
          ts: '1778883099.579529',
          text: '<@UBOT> hello'
        }
      })
      const waits: Promise<unknown>[] = []
      const executionCtx = {
        waitUntil: (promise: Promise<unknown>) => {
          waits.push(promise)
        },
        passThroughOnException: () => {},
        props: {}
      }

      const first = await app.request(
        '/api/webhooks/slack',
        signedJsonRequest(body, process.env.SLACK_SIGNING_SECRET),
        {},
        executionCtx as any
      )
      const second = await app.request(
        '/api/webhooks/slack',
        signedJsonRequest(body, process.env.SLACK_SIGNING_SECRET),
        {},
        executionCtx as any
      )

      expect(first.status).toBe(200)
      expect(await first.json()).toEqual({ ok: true })
      expect(second.status).toBe(200)
      expect(await second.json()).toEqual({ ok: true, duplicate: true })
      expect(console.warn).toHaveBeenCalledWith(
        'slack_duplicate_message_skipped',
        expect.objectContaining({
          dedupe_key: 'message:T123:C123:1778883099.579529',
          event_id: 'Ev-duplicate',
          team_id: 'T123',
          channel_id: 'C123',
          message_ts: '1778883099.579529',
          thread_ts: '1778883099.579529',
          event_type: 'app_mention',
          codex_thread_id: undefined,
          alert_channel_id: undefined,
          log_version_uuid: '013ca634-6a30-4047-8511-8e5483f313ea'
        })
      )
      expect(waits).toHaveLength(1)
      await Promise.allSettled(waits)
    } finally {
      console.error = originalError
      console.log = originalLog
      console.warn = originalWarn
    }
  })

  it('logs duplicate Slack messages when Slack event IDs are absent', async () => {
    process.env.SLACK_SIGNING_SECRET = 'test-signing-secret'
    process.env.SLACK_EVENT_DEDUP_TTL_MS = '600000'
    delete process.env.SLACK_BOT_TOKEN
    delete process.env.SLACKBOT_API_KEY
    delete process.env.CENTAUR_API_KEY

    const originalError = console.error
    const originalLog = console.log
    const originalWarn = console.warn
    console.error = mock(() => {}) as typeof console.error
    console.log = mock(() => {}) as typeof console.log
    console.warn = mock(() => {}) as typeof console.warn
    try {
      const { app } = await import('./index')
      const body = JSON.stringify({
        type: 'event_callback',
        team_id: 'T123',
        event: {
          type: 'message',
          user: 'U123',
          channel: 'C123',
          ts: '1778883099.579530',
          text: 'Duplicate report for Codex thread `T-019e28c1-08bb-777d-9a2e-74a393296b28`'
        }
      })
      const waits: Promise<unknown>[] = []
      const executionCtx = {
        waitUntil: (promise: Promise<unknown>) => {
          waits.push(promise)
        }
      }

      await app.request(
        '/api/webhooks/slack',
        signedJsonRequest(body, process.env.SLACK_SIGNING_SECRET),
        {},
        executionCtx as any
      )
      const second = await app.request(
        '/api/webhooks/slack',
        signedJsonRequest(body, process.env.SLACK_SIGNING_SECRET),
        {},
        executionCtx as any
      )

      expect(second.status).toBe(200)
      expect(await second.json()).toEqual({ ok: true, duplicate: true })
      expect(console.warn).toHaveBeenCalledWith(
        'slack_duplicate_message_skipped',
        expect.objectContaining({
          dedupe_key: 'message:T123:C123:1778883099.579530',
          event_id: undefined,
          team_id: 'T123',
          channel_id: 'C123',
          message_ts: '1778883099.579530',
          thread_ts: '1778883099.579530',
          event_type: 'message',
          codex_thread_id: 'T-019e28c1-08bb-777d-9a2e-74a393296b28',
          alert_channel_id: undefined,
          log_version_uuid: '013ca634-6a30-4047-8511-8e5483f313ea'
        })
      )
      expect(waits).toHaveLength(1)
      await Promise.allSettled(waits)
    } finally {
      console.error = originalError
      console.log = originalLog
      console.warn = originalWarn
    }
  })
})

function signedFormRequest(body: string, signingSecret: string): RequestInit {
  const timestamp = Math.floor(Date.now() / 1000).toString()
  const signature = `v0=${createHmac('sha256', signingSecret)
    .update(`v0:${timestamp}:${body}`)
    .digest('hex')}`
  return {
    method: 'POST',
    headers: {
      'content-type': 'application/x-www-form-urlencoded',
      'x-slack-request-timestamp': timestamp,
      'x-slack-signature': signature
    },
    body
  }
}

function signedJsonRequest(body: string, signingSecret: string): RequestInit {
  const timestamp = Math.floor(Date.now() / 1000).toString()
  const signature = `v0=${createHmac('sha256', signingSecret)
    .update(`v0:${timestamp}:${body}`)
    .digest('hex')}`
  return {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-slack-request-timestamp': timestamp,
      'x-slack-signature': signature
    },
    body
  }
}

function apiHeaders(): Record<string, string> {
  return {
    authorization: `Bearer ${process.env.SLACKBOT_API_KEY}`,
    'content-type': 'application/json'
  }
}

async function slackApiBody(request: Request): Promise<Record<string, unknown>> {
  const contentType = request.headers.get('content-type') ?? ''
  const text = await request.text()
  if (contentType.includes('application/json')) {
    return JSON.parse(text || '{}') as Record<string, unknown>
  }
  return Object.fromEntries(
    Array.from(new URLSearchParams(text).entries()).map(([key, value]) => [
      key,
      parseMaybeJson(value)
    ])
  )
}

function parseMaybeJson(value: string): unknown {
  const trimmed = value.trim()
  if (!trimmed || !['{', '['].includes(trimmed[0] ?? '')) return value
  try {
    return JSON.parse(trimmed)
  } catch {
    return value
  }
}
