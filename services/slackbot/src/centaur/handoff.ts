import { centaurApiKey, type AppConfig } from '../config'
import { clientSpanOptions, injectTraceHeaders, spanAttributes, withSpan } from '../otel'
import type { NormalizedSlackEvent } from '../slack/types'

export type CentaurHandoffResult =
  | { ok: true; status: number; body: unknown }
  | { ok: false; status: number; body: unknown }

export type CentaurPostableExecutionResult = {
  execution_id: string
  result_text: string
}

export class CentaurHandoff {
  readonly config: AppConfig

  constructor(config: AppConfig) {
    this.config = config
  }

  async emit(event: NormalizedSlackEvent): Promise<CentaurHandoffResult> {
    return withSpan(
      'centaur.slackbot.handoff',
      clientSpanOptions({
        'centaur.thread_key': event.thread_key,
        'centaur.workflow.name': 'slack_thread_turn',
        'slack.team_id': event.team_id,
        'slack.channel_id': event.channel_id,
        'slack.thread_ts': event.thread_ts,
        'slack.user_id': event.user_id
      }),
      async span => {
        const url = new URL('/workflows/runs', this.config.CENTAUR_API_URL)
        const apiKey = centaurApiKey(this.config)
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Centaur-Thread-Key': event.thread_key,
            ...injectTraceHeaders(),
            ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {})
          },
          body: JSON.stringify({
            workflow_name: 'slack_thread_turn',
            trigger_key: event.message_id,
            eager_start: true,
            input: {
              thread_key: event.thread_key,
              parts: event.parts,
              history_messages: event.history_messages ?? [],
              message_id: event.message_id,
              user_id: event.user_id,
              metadata: {
                source: 'slackbot',
                slack: {
                  message_ts: event.slack.message_ts,
                  enterprise_id: event.slack.enterprise_id,
                  user_team: event.slack.user_team,
                  source_team: event.slack.source_team,
                  bot_id: event.slack.bot_id,
                  app_id: event.slack.app_id,
                  bot_user_id: event.slack.bot_user_id
                },
                is_mention: event.is_mention,
                ...(event.route ? { route: event.route } : {})
              },
              delivery: {
                platform: 'slack',
                channel: event.channel_id,
                thread_ts: event.thread_ts,
                recipient_user_id: event.user_id,
                recipient_team_id: event.recipient_team_id ?? event.team_id
              }
            }
          })
        })

        spanAttributes(span, {
          'http.response.status_code': response.status,
          'centaur.handoff.ok': response.ok
        })
        const body = await readResponseBody(response)
        return { ok: response.ok, status: response.status, body }
      }
    )
  }

  async latestPostableExecutionResult(
    threadKey: string
  ): Promise<CentaurPostableExecutionResult | null> {
    return withSpan(
      'centaur.slackbot.latest_postable_execution_result',
      clientSpanOptions({
        'centaur.thread_key': threadKey
      }),
      async span => {
        const executionsUrl = new URL(
          `/agent/threads/${encodeURIComponent(threadKey)}/executions`,
          this.config.CENTAUR_API_URL
        )
        executionsUrl.searchParams.set('limit', '10')
        const executionsResponse = await this.fetchJson(executionsUrl, threadKey)
        spanAttributes(span, {
          'http.response.status_code': executionsResponse.response.status
        })
        if (!executionsResponse.response.ok) return null

        const executions = executionSummaries(executionsResponse.body)
        for (const execution of executions) {
          if (execution.status !== 'completed') continue
          const detailUrl = new URL(
            `/agent/executions/${encodeURIComponent(execution.execution_id)}`,
            this.config.CENTAUR_API_URL
          )
          const detailResponse = await this.fetchJson(detailUrl, threadKey)
          if (!detailResponse.response.ok) continue

          const result = postableExecutionResult(detailResponse.body)
          if (!result) continue
          spanAttributes(span, {
            'centaur.execution_id': result.execution_id,
            'centaur.slackbot.latest_postable_result_found': true
          })
          return result
        }

        spanAttributes(span, {
          'centaur.slackbot.latest_postable_result_found': false
        })
        return null
      }
    )
  }

  private async fetchJson(
    url: URL,
    threadKey: string
  ): Promise<{ response: Response; body: unknown }> {
    const apiKey = centaurApiKey(this.config)
    const response = await fetch(url, {
      headers: {
        'X-Centaur-Thread-Key': threadKey,
        ...injectTraceHeaders(),
        ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {})
      }
    })
    return { response, body: await readResponseBody(response) }
  }
}

function executionSummaries(value: unknown): Array<{ execution_id: string; status: string }> {
  if (!value || typeof value !== 'object') return []
  const executions = (value as { executions?: unknown }).executions
  if (!Array.isArray(executions)) return []
  return executions.flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const executionId = (item as { execution_id?: unknown }).execution_id
    const status = (item as { status?: unknown }).status
    if (typeof executionId !== 'string' || typeof status !== 'string') return []
    return [{ execution_id: executionId, status }]
  })
}

function postableExecutionResult(value: unknown): CentaurPostableExecutionResult | null {
  if (!value || typeof value !== 'object') return null
  const executionId = (value as { execution_id?: unknown }).execution_id
  const resultText = (value as { result_text?: unknown }).result_text
  if (typeof executionId !== 'string' || typeof resultText !== 'string') return null
  const trimmed = resultText.trim()
  return trimmed ? { execution_id: executionId, result_text: trimmed } : null
}

async function readResponseBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}
