import type { WebClient } from '@slack/web-api'
import { logWarn } from '../logging'
import type { NormalizedSlackEvent } from './types'

const INVESTIGATING_REACTION = 'mag'

export function shouldAcknowledgeThreadInvestigation(event: NormalizedSlackEvent): boolean {
  return (
    !event.channel_id.startsWith('D') &&
    event.slack.message_ts !== event.thread_ts &&
    event.is_mention &&
    event.is_addressed
  )
}

export async function acknowledgeThreadInvestigation(
  client: WebClient,
  event: NormalizedSlackEvent
): Promise<void> {
  if (!shouldAcknowledgeThreadInvestigation(event)) return

  try {
    await client.reactions.add({
      channel: event.channel_id,
      timestamp: event.slack.message_ts,
      name: INVESTIGATING_REACTION
    })
  } catch (error) {
    logWarn('slack_thread_investigating_reaction_failed', {
      channel_id: event.channel_id,
      thread_ts: event.thread_ts,
      message_ts: event.slack.message_ts,
      error: error instanceof Error ? error.message : String(error)
    })
  }
}
