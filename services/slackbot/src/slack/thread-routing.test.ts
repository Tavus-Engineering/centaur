import { describe, expect, it, mock } from 'bun:test'
import type { WebClient } from '@slack/web-api'
import {
  maybePublishApprovedDmResultToThread,
  maybePromptRoutedDmPostback,
  routeThreadMentionToDm,
  shouldRouteThreadMentionToDm
} from './thread-routing'
import type { NormalizedSlackEvent } from './types'

describe('thread mention DM routing', () => {
  it('moves channel thread mentions into a DM thread', async () => {
    const reactionsAdd = mock(async () => ({ ok: true }))
    const conversationsOpen = mock(async () => ({ ok: true, channel: { id: 'D123' } }))
    const chatPostMessage = mock(async () => ({
      ok: true,
      channel: 'D123',
      ts: '1778884000.000000'
    }))
    const client = slackClient({
      reactions: { add: reactionsAdd },
      conversations: { open: conversationsOpen },
      chat: { postMessage: chatPostMessage }
    })
    const event = channelThreadMentionEvent()

    const routed = await routeThreadMentionToDm(client, event)

    expect(routed).not.toBe(event)
    expect(routed.channel_id).toBe('D123')
    expect(routed.thread_ts).toBe('1778884000.000000')
    expect(routed.thread_key).toBe('slack:T123:D123:1778884000.000000')
    expect(routed.route).toMatchObject({
      mode: 'dm_from_thread_mention',
      source_channel_id: 'C123',
      source_thread_ts: '1778883000.000000',
      source_message_ts: '1778883001.000000',
      dm_channel_id: 'D123',
      dm_thread_ts: '1778884000.000000'
    })
    expect(routed.parts[0]).toMatchObject({
      type: 'text',
      text: expect.stringContaining('Do you want me to post this answer if it succeeds?')
    })
    expect(reactionsAdd).toHaveBeenCalledWith({
      channel: 'C123',
      timestamp: '1778883001.000000',
      name: 'incoming_envelope'
    })
    expect(conversationsOpen).toHaveBeenCalledWith({ users: 'U123' })
    expect(chatPostMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        channel: 'D123',
        metadata: expect.objectContaining({
          event_type: 'centaur_thread_dm_route',
          event_payload: expect.objectContaining({
            source_channel_id: 'C123',
            source_thread_ts: '1778883000.000000',
            source_message_ts: '1778883001.000000'
          })
        })
      })
    )
  })

  it('keeps explicit inline requests in the original thread', async () => {
    const client = slackClient({
      reactions: { add: mock(async () => ({ ok: true })) },
      conversations: { open: mock(async () => ({ ok: true, channel: { id: 'D123' } })) },
      chat: { postMessage: mock(async () => ({ ok: true, channel: 'D123', ts: '1.0' })) }
    })
    const event = channelThreadMentionEvent({
      parts: [{ type: 'text', text: '<@UBOT> investigate this and post it inline' }]
    })

    expect(shouldRouteThreadMentionToDm(event)).toBe(false)
    expect(routeThreadMentionToDm(client, event)).resolves.toBe(event)
    expect(client.reactions.add).not.toHaveBeenCalled()
    expect(client.conversations.open).not.toHaveBeenCalled()
    expect(client.chat.postMessage).not.toHaveBeenCalled()
  })

  it('posts the latest successful DM result back when the user approves', async () => {
    const chatPostMessage = mock(async () => ({
      ok: true,
      channel: 'C123',
      ts: '1778885000.000000'
    }))
    const client = slackClient({
      conversations: {
        replies: mock(async () => ({
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
        }))
      },
      chat: { postMessage: chatPostMessage }
    })
    const latestPostableResult = mock(async () => ({
      execution_id: 'exe_123',
      result_text: 'Final answer'
    }))
    const event = dmApprovalEvent()

    expect(
      maybePublishApprovedDmResultToThread({ client, event, latestPostableResult })
    ).resolves.toBe(true)

    expect(latestPostableResult).toHaveBeenCalledWith('slack:T123:D123:1778884000.000000')
    expect(chatPostMessage).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        channel: 'C123',
        thread_ts: '1778883000.000000',
        text: expect.stringContaining('Final answer'),
        metadata: expect.objectContaining({
          event_type: 'centaur_thread_result_posted',
          event_payload: expect.objectContaining({
            source_dm_channel_id: 'D123',
            source_dm_thread_ts: '1778884000.000000',
            source_execution_id: 'exe_123',
            approved_by_user_id: 'U123'
          })
        })
      })
    )
    expect(chatPostMessage).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        channel: 'D123',
        thread_ts: '1778884000.000000',
        text: expect.stringContaining('Posted to the original thread:')
      })
    )
  })

  it('treats post back as DM result approval', async () => {
    const chatPostMessage = mock(async () => ({
      ok: true,
      channel: 'C123',
      ts: '1778885000.000000'
    }))
    const client = slackClient({
      conversations: {
        replies: mock(async () => ({
          ok: true,
          messages: [routedDmRootMessage()]
        }))
      },
      chat: { postMessage: chatPostMessage }
    })
    const latestPostableResult = mock(async () => ({
      execution_id: 'exe_123',
      result_text: 'Final answer'
    }))
    const event = dmApprovalEvent({
      parts: [{ type: 'text', text: 'post back' }]
    })

    expect(
      maybePublishApprovedDmResultToThread({ client, event, latestPostableResult })
    ).resolves.toBe(true)
    expect(chatPostMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        channel: 'C123',
        thread_ts: '1778883000.000000',
        text: expect.stringContaining('Final answer')
      })
    )
  })

  it('prompts routed DM users to post successful results back', async () => {
    const chatPostMessage = mock(async () => ({
      ok: true,
      channel: 'D123',
      ts: '1778885001.000000'
    }))
    const client = slackClient({
      conversations: {
        replies: mock(async () => ({
          ok: true,
          messages: [routedDmRootMessage()]
        }))
      },
      chat: { postMessage: chatPostMessage }
    })

    expect(
      maybePromptRoutedDmPostback({
        client,
        channelId: 'D123',
        threadTs: '1778884000.000000'
      })
    ).resolves.toBe(true)

    expect(chatPostMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        channel: 'D123',
        thread_ts: '1778884000.000000',
        text: expect.stringContaining('Reply `post it`'),
        metadata: expect.objectContaining({
          event_type: 'centaur_thread_postback_prompt',
          event_payload: expect.objectContaining({
            source_channel_id: 'C123',
            source_thread_ts: '1778883000.000000'
          })
        })
      })
    )
  })

  it('does not duplicate routed DM postback prompts', async () => {
    const chatPostMessage = mock(async () => ({
      ok: true,
      channel: 'D123',
      ts: '1778885001.000000'
    }))
    const client = slackClient({
      conversations: {
        replies: mock(async () => ({
          ok: true,
          messages: [
            routedDmRootMessage(),
            {
              ts: '1778885001.000000',
              metadata: {
                event_type: 'centaur_thread_postback_prompt',
                event_payload: {
                  source_channel_id: 'C123',
                  source_thread_ts: '1778883000.000000'
                }
              }
            }
          ]
        }))
      },
      chat: { postMessage: chatPostMessage }
    })

    expect(
      maybePromptRoutedDmPostback({
        client,
        channelId: 'D123',
        threadTs: '1778884000.000000'
      })
    ).resolves.toBe(false)
    expect(chatPostMessage).not.toHaveBeenCalled()
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
      event_id: 'Ev123',
      event_ts: '1778883001.000000',
      message_ts: '1778883001.000000',
      bot_user_id: 'UBOT'
    },
    ...overrides
  }
}

function dmApprovalEvent(overrides: Partial<NormalizedSlackEvent> = {}): NormalizedSlackEvent {
  return {
    thread_key: 'slack:T123:D123:1778884000.000000',
    message_id: 'slack:T123:D123:1778884001.000000',
    team_id: 'T123',
    user_id: 'U123',
    channel_id: 'D123',
    thread_ts: '1778884000.000000',
    is_mention: false,
    is_addressed: true,
    parts: [{ type: 'text', text: 'yes please post it' }],
    slack: {
      event_id: 'Ev456',
      event_ts: '1778884001.000000',
      message_ts: '1778884001.000000',
      bot_user_id: 'UBOT'
    },
    ...overrides
  }
}

function slackClient(value: unknown): WebClient {
  return value as WebClient
}

function routedDmRootMessage() {
  return {
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
}
