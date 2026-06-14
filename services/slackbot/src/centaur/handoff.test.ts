import { describe, expect, it, mock } from 'bun:test'
import { CentaurHandoff } from './handoff'
import type { AppConfig } from '../config'
import type { NormalizedSlackEvent } from '../slack/types'

const config: AppConfig = {
  NODE_ENV: 'test',
  PORT: 3001,
  CENTAUR_API_URL: 'http://centaur-api.test',
  CENTAUR_SLACK_EVENTS_PATH: '/api/webhooks/slack',
  RUNTIME_ERROR_ALERT_CHANNEL: '',
  SLACK_EVENT_DEDUP_TTL_MS: 600000,
  SLACK_SIGNATURE_MAX_AGE_SECONDS: 300,
  SLACK_FEEDBACK_COMMANDS: ['/website-feedback'],
  SLACK_FEEDBACK_LINEAR_TEAM_ID: 'team-test',
  SLACK_FEEDBACK_LINEAR_PROJECT_ID: 'project-test',
  SLACK_FEEDBACK_ALLOWED_CHANNELS: [],
  SLACKBOT_EXTERNAL_ORG_ALLOWLIST: [],
  SLACKBOT_TRIGGER_BOT_ALLOWLIST: []
}

describe('CentaurHandoff', () => {
  it('omits envelope-specific Slack event metadata from idempotent workflow input', async () => {
    const originalFetch = globalThis.fetch
    let capturedInit: RequestInit | undefined
    const fetchMock = mock(async (_input: string | URL | Request, init?: RequestInit) => {
      capturedInit = init
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })
    globalThis.fetch = fetchMock as any
    try {
      const handoff = new CentaurHandoff(config)
      const event: NormalizedSlackEvent = {
        thread_key: 'slack:T123:C123:1778883099.579529',
        message_id: 'slack:T123:C123:1778883099.579529',
        team_id: 'T123',
        user_id: 'U123',
        channel_id: 'C123',
        thread_ts: '1778883099.579529',
        is_mention: true,
        is_addressed: true,
        parts: [{ type: 'text', text: 'hello' }],
        slack: {
          event_id: 'Ev-envelope-one',
          event_ts: '1778883100.000000',
          message_ts: '1778883099.579529',
          enterprise_id: 'E123'
        }
      }

      await handoff.emit(event)

      expect(capturedInit).toBeDefined()
      expect(capturedInit?.headers).toMatchObject({
        'Content-Type': 'application/json',
        'X-Centaur-Thread-Key': event.thread_key
      })
      const bodyText = capturedInit?.body
      expect(typeof bodyText).toBe('string')
      if (typeof bodyText !== 'string') throw new Error('expected JSON request body')
      const body = JSON.parse(bodyText) as {
        trigger_key: string
        input: { metadata: { slack: unknown } }
      }
      expect(body.trigger_key).toBe(event.message_id)
      expect(body.input.metadata.slack).toEqual({
        message_ts: '1778883099.579529',
        enterprise_id: 'E123'
      })
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  it('passes Slack attachment parts through workflow input', async () => {
    const originalFetch = globalThis.fetch
    let capturedInit: RequestInit | undefined
    const fetchMock = mock(async (_input: string | URL | Request, init?: RequestInit) => {
      capturedInit = init
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })
    globalThis.fetch = fetchMock as any
    try {
      const handoff = new CentaurHandoff(config)
      const event: NormalizedSlackEvent = {
        thread_key: 'slack:T123:C123:1778883099.579529',
        message_id: 'slack:T123:C123:1778883099.579529',
        team_id: 'T123',
        user_id: 'U123',
        channel_id: 'C123',
        thread_ts: '1778883099.579529',
        is_mention: true,
        is_addressed: true,
        parts: [
          { type: 'text', text: 'review this' },
          {
            type: 'document',
            name: 'report.pdf',
            mime_type: 'application/pdf',
            size: 8,
            slack_file_id: 'F123',
            source: {
              type: 'base64',
              media_type: 'application/pdf',
              data: 'JVBERi0xLjQ='
            }
          }
        ],
        slack: {
          event_ts: '1778883100.000000',
          message_ts: '1778883099.579529'
        }
      }

      await handoff.emit(event)

      const bodyText = capturedInit?.body
      expect(typeof bodyText).toBe('string')
      if (typeof bodyText !== 'string') throw new Error('expected JSON request body')
      const body = JSON.parse(bodyText) as {
        input: { parts: NormalizedSlackEvent['parts'] }
      }
      expect(body.input.parts[1]).toMatchObject({
        type: 'document',
        name: 'report.pdf',
        mime_type: 'application/pdf',
        slack_file_id: 'F123',
        source: {
          type: 'base64',
          media_type: 'application/pdf',
          data: 'JVBERi0xLjQ='
        }
      })
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  it('uses recipient_team_id for Slack Connect delivery routing', async () => {
    const originalFetch = globalThis.fetch
    let capturedInit: RequestInit | undefined
    const fetchMock = mock(async (_input: string | URL | Request, init?: RequestInit) => {
      capturedInit = init
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })
    globalThis.fetch = fetchMock as any
    try {
      const handoff = new CentaurHandoff(config)
      const event: NormalizedSlackEvent = {
        thread_key: 'slack:THOME:C123:1778883099.579529',
        message_id: 'slack:THOME:C123:1778883099.579529',
        team_id: 'THOME',
        recipient_team_id: 'TEXTERNAL',
        user_id: 'UEXTERNAL',
        channel_id: 'C123',
        thread_ts: '1778883099.579529',
        is_mention: true,
        is_addressed: true,
        parts: [{ type: 'text', text: 'hello' }],
        slack: {
          event_ts: '1778883100.000000',
          message_ts: '1778883099.579529',
          user_team: 'TEXTERNAL'
        }
      }

      await handoff.emit(event)

      const bodyText = capturedInit?.body
      expect(typeof bodyText).toBe('string')
      if (typeof bodyText !== 'string') throw new Error('expected JSON request body')
      const body = JSON.parse(bodyText) as {
        input: { delivery: { recipient_team_id: string; recipient_user_id: string } }
      }
      expect(body.input.delivery).toMatchObject({
        recipient_team_id: 'TEXTERNAL',
        recipient_user_id: 'UEXTERNAL'
      })
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  it('includes routed thread metadata while delivering to the DM thread', async () => {
    const originalFetch = globalThis.fetch
    let capturedInit: RequestInit | undefined
    const fetchMock = mock(async (_input: string | URL | Request, init?: RequestInit) => {
      capturedInit = init
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })
    globalThis.fetch = fetchMock as any
    try {
      const handoff = new CentaurHandoff(config)
      const event: NormalizedSlackEvent = {
        thread_key: 'slack:T123:D123:1778884000.000000',
        message_id: 'slack:T123:C123:1778883001.000000',
        team_id: 'T123',
        user_id: 'U123',
        channel_id: 'D123',
        thread_ts: '1778884000.000000',
        is_mention: true,
        is_addressed: true,
        parts: [{ type: 'text', text: 'routed request' }],
        route: {
          mode: 'dm_from_thread_mention',
          source_team_id: 'T123',
          source_channel_id: 'C123',
          source_thread_ts: '1778883000.000000',
          source_message_ts: '1778883001.000000',
          source_request_url: 'https://slack.com/archives/C123/p1778883001000000',
          source_thread_url: 'https://slack.com/archives/C123/p1778883000000000',
          dm_channel_id: 'D123',
          dm_thread_ts: '1778884000.000000'
        },
        slack: {
          event_ts: '1778883001.000000',
          message_ts: '1778883001.000000'
        }
      }

      await handoff.emit(event)

      const bodyText = capturedInit?.body
      expect(typeof bodyText).toBe('string')
      if (typeof bodyText !== 'string') throw new Error('expected JSON request body')
      const body = JSON.parse(bodyText) as {
        input: {
          metadata: { route: NormalizedSlackEvent['route'] }
          delivery: { channel: string; thread_ts: string }
        }
      }
      expect(body.input.metadata.route).toEqual(event.route)
      expect(body.input.delivery).toMatchObject({
        channel: 'D123',
        thread_ts: '1778884000.000000'
      })
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  it('returns the newest completed execution result for routed DM publish approval', async () => {
    const originalFetch = globalThis.fetch
    const requestedUrls: string[] = []
    const fetchMock = mock(async (input: string | URL | Request) => {
      const url = input instanceof Request ? input.url : String(input)
      requestedUrls.push(url)
      if (url.includes('/agent/threads/')) {
        return new Response(
          JSON.stringify({
            executions: [
              { execution_id: 'exe_running', status: 'running' },
              { execution_id: 'exe_empty', status: 'completed' },
              { execution_id: 'exe_success', status: 'completed' }
            ]
          }),
          { status: 200 }
        )
      }
      if (url.endsWith('/agent/executions/exe_empty')) {
        return new Response(JSON.stringify({ execution_id: 'exe_empty', result_text: '   ' }), {
          status: 200
        })
      }
      if (url.endsWith('/agent/executions/exe_success')) {
        return new Response(
          JSON.stringify({ execution_id: 'exe_success', result_text: 'Final answer\n' }),
          { status: 200 }
        )
      }
      return new Response(JSON.stringify({ error: 'unexpected_url' }), { status: 404 })
    })
    globalThis.fetch = fetchMock as any
    try {
      const handoff = new CentaurHandoff(config)

      const result = await handoff.latestPostableExecutionResult(
        'slack:T123:D123:1778884000.000000'
      )

      expect(result).toEqual({ execution_id: 'exe_success', result_text: 'Final answer' })
      expect(requestedUrls).toEqual([
        'http://centaur-api.test/agent/threads/slack%3AT123%3AD123%3A1778884000.000000/executions?limit=10',
        'http://centaur-api.test/agent/executions/exe_empty',
        'http://centaur-api.test/agent/executions/exe_success'
      ])
    } finally {
      globalThis.fetch = originalFetch
    }
  })
})
