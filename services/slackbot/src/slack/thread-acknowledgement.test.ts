import { describe, expect, it, mock } from 'bun:test'
import type { WebClient } from '@slack/web-api'
import {
  acknowledgeThreadInvestigation,
  shouldAcknowledgeThreadInvestigation
} from './thread-acknowledgement'
import type { NormalizedSlackEvent } from './types'

describe('thread investigation acknowledgement', () => {
  it('adds mag to an addressed mention without changing its inline destination', async () => {
    const reactionsAdd = mock(async () => ({ ok: true }))
    const client = { reactions: { add: reactionsAdd } } as unknown as WebClient
    const event = channelThreadMentionEvent()

    await acknowledgeThreadInvestigation(client, event)

    expect(reactionsAdd).toHaveBeenCalledWith({
      channel: 'C123',
      timestamp: '1778883001.000000',
      name: 'mag'
    })
    expect(event).toMatchObject({
      thread_key: 'slack:T123:C123:1778883000.000000',
      channel_id: 'C123',
      thread_ts: '1778883000.000000'
    })
  })

  it('does not add an investigating reaction outside addressed channel threads', async () => {
    const reactionsAdd = mock(async () => ({ ok: true }))
    const client = { reactions: { add: reactionsAdd } } as unknown as WebClient
    const events = [
      channelThreadMentionEvent({ channel_id: 'D123' }),
      channelThreadMentionEvent({ thread_ts: '1778883001.000000' }),
      channelThreadMentionEvent({ is_mention: false }),
      channelThreadMentionEvent({ is_addressed: false })
    ]

    for (const event of events) {
      expect(shouldAcknowledgeThreadInvestigation(event)).toBe(false)
      await acknowledgeThreadInvestigation(client, event)
    }

    expect(reactionsAdd).not.toHaveBeenCalled()
  })
})

function channelThreadMentionEvent(
  overrides: Partial<NormalizedSlackEvent> = {}
): NormalizedSlackEvent {
  return {
    thread_key: 'slack:T123:C123:1778883000.000000',
    message_id: 'slack:T123:C123:1778883001.000000',
    team_id: 'T123',
    user_id: 'U123',
    channel_id: 'C123',
    thread_ts: '1778883000.000000',
    is_mention: true,
    is_addressed: true,
    parts: [{ type: 'text', text: '<@UBOT> investigate this' }],
    slack: {
      message_ts: '1778883001.000000'
    },
    ...overrides
  }
}
