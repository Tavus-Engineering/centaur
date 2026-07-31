import { describe, expect, test } from 'bun:test'
import type { Chat, Logger, Thread } from 'chat'
import {
  extractSlackOrigin,
  isSlackDmThreadId,
  OriginPostbackManager,
  POSTBACK_APPROVAL_EMOJI,
  slackChannelFromThreadId
} from '../src/origin-postback'

const noopLogger: Logger = {
  child: () => noopLogger,
  debug: () => undefined,
  error: () => undefined,
  info: () => undefined,
  warn: () => undefined
}

describe('extractSlackOrigin', () => {
  test('parses a channel permalink into channel/message/thread ts', () => {
    const origin = extractSlackOrigin(
      'Investigate https://tavus.slack.com/archives/C0B8BBZEBE2/p1785502809426239 please'
    )
    expect(origin).toEqual({
      channel: 'C0B8BBZEBE2',
      messageTs: '1785502809.426239',
      threadTs: '1785502809.426239',
      permalink: 'https://tavus.slack.com/archives/C0B8BBZEBE2/p1785502809426239'
    })
  })

  test('uses thread_ts from the query when the link targets a reply', () => {
    const origin = extractSlackOrigin(
      'see <https://tavus.slack.com/archives/C0BANBTAKLL/p1785362251116219?thread_ts=1785354165.148179&cid=C0BANBTAKLL>'
    )
    expect(origin?.messageTs).toBe('1785362251.116219')
    expect(origin?.threadTs).toBe('1785354165.148179')
  })

  test('ignores DM links and the excluded channel', () => {
    expect(
      extractSlackOrigin('https://tavus.slack.com/archives/D0B7DPBT69M/p1785503912388849')
    ).toBeUndefined()
    expect(
      extractSlackOrigin(
        'https://tavus.slack.com/archives/C0B8BBZEBE2/p1785502809426239',
        'C0B8BBZEBE2'
      )
    ).toBeUndefined()
    expect(extractSlackOrigin('no links here')).toBeUndefined()
    expect(extractSlackOrigin(undefined)).toBeUndefined()
  })

  test('picks the first channel link when several are present', () => {
    const origin = extractSlackOrigin(
      'https://tavus.slack.com/archives/D0B7DPBT69M/p1000000000000001 then ' +
        'https://tavus.slack.com/archives/C11111111/p2000000000000002 and ' +
        'https://tavus.slack.com/archives/C22222222/p3000000000000003'
    )
    expect(origin?.channel).toBe('C11111111')
  })
})

describe('thread id helpers', () => {
  test('extracts the channel and detects DMs', () => {
    expect(slackChannelFromThreadId('slack:D0B7DPBT69M:')).toBe('D0B7DPBT69M')
    expect(slackChannelFromThreadId('slack:C123:1234.5678')).toBe('C123')
    expect(slackChannelFromThreadId('discord:whatever')).toBeUndefined()
    expect(isSlackDmThreadId('slack:D0B7DPBT69M:')).toBe(true)
    expect(isSlackDmThreadId('slack:C0B8BBZEBE2:1234.5678')).toBe(false)
  })
})

type FakePost = { threadId: string; text: string }

function fakeEnvironment() {
  const posts: FakePost[] = []
  const reactions: string[] = []
  const makeThread = (threadId: string): Thread =>
    ({
      id: threadId,
      post: async (text: string) => {
        posts.push({ threadId, text })
        return {
          id: `msg-${posts.length}`,
          addReaction: async (emoji: string) => {
            reactions.push(emoji)
          }
        }
      }
    }) as unknown as Thread
  const chat = { thread: (threadId: string) => makeThread(threadId) } as unknown as Chat
  return { chat, makeThread, posts, reactions }
}

function reactionBody(overrides?: { user?: string; ts?: string; reaction?: string }): string {
  return JSON.stringify({
    type: 'event_callback',
    event: {
      type: 'reaction_added',
      user: overrides?.user ?? 'U0AQJ5GNT4P',
      reaction: overrides?.reaction ?? POSTBACK_APPROVAL_EMOJI,
      item: { type: 'message', channel: 'D0B7DPBT69M', ts: overrides?.ts ?? 'msg-1' }
    }
  })
}

describe('OriginPostbackManager', () => {
  const origin = {
    channel: 'C0B8BBZEBE2',
    messageTs: '1785502809.426239',
    threadTs: '1785502809.426239',
    permalink: 'https://tavus.slack.com/archives/C0B8BBZEBE2/p1785502809426239'
  }
  const session = { threadId: 'slack:D0B7DPBT69M:', afterEventId: 7 }

  async function offeredManager(env = fakeEnvironment()) {
    const manager = new OriginPostbackManager()
    manager.bind({ chat: env.chat, logger: noopLogger, recomposeAnswer: async () => 'the answer' })
    manager.rememberOrigin('slack:D0B7DPBT69M:', origin, 'U0AQJ5GNT4P')
    await manager.offerAfterRender(env.makeThread('slack:D0B7DPBT69M:'), session)
    return { manager, env }
  }

  test('offers once and posts to the origin thread on approval by the requester', async () => {
    const { manager, env } = await offeredManager()
    expect(env.posts).toHaveLength(1)
    expect(env.posts[0]?.text).toContain(POSTBACK_APPROVAL_EMOJI)
    expect(env.reactions).toEqual([POSTBACK_APPROVAL_EMOJI])

    const task = manager.handleWebhookBody(reactionBody())
    expect(task).toBeDefined()
    await task
    const originPost = env.posts.find(post => post.threadId === 'slack:C0B8BBZEBE2:1785502809.426239')
    expect(originPost?.text).toContain('the answer')
    expect(originPost?.text).toContain('<@U0AQJ5GNT4P>')
    // DM confirmation posted after the origin post.
    expect(env.posts.at(-1)?.text).toContain('Posted to')
    // Approval is one-shot.
    expect(manager.handleWebhookBody(reactionBody())).toBeUndefined()
  })

  test('ignores reactions from other users, other emoji, and unknown messages', async () => {
    const { manager } = await offeredManager()
    expect(manager.handleWebhookBody(reactionBody({ user: 'USOMEONE' }))).toBeUndefined()
    expect(manager.handleWebhookBody(reactionBody({ reaction: 'thumbsup' }))).toBeUndefined()
    expect(manager.handleWebhookBody(reactionBody({ ts: 'other-ts' }))).toBeUndefined()
    expect(manager.handleWebhookBody('not json')).toBeUndefined()
  })

  test('does not offer without a remembered origin', async () => {
    const env = fakeEnvironment()
    const manager = new OriginPostbackManager()
    manager.bind({ chat: env.chat, logger: noopLogger, recomposeAnswer: async () => 'x' })
    await manager.offerAfterRender(env.makeThread('slack:D0B7DPBT69M:'), session)
    expect(env.posts).toHaveLength(0)
  })

  test('reports a failure to the DM when the origin post is rejected', async () => {
    const env = fakeEnvironment()
    const posts = env.posts
    const failingChat = {
      thread: (threadId: string) => {
        if (threadId.startsWith('slack:C')) {
          return {
            id: threadId,
            post: async () => {
              throw new Error('not_in_channel')
            }
          } as unknown as Thread
        }
        return env.makeThread(threadId)
      }
    } as unknown as Chat
    const manager = new OriginPostbackManager()
    manager.bind({ chat: failingChat, logger: noopLogger, recomposeAnswer: async () => 'the answer' })
    manager.rememberOrigin('slack:D0B7DPBT69M:', origin, 'U0AQJ5GNT4P')
    await manager.offerAfterRender(env.makeThread('slack:D0B7DPBT69M:'), session)
    await manager.handleWebhookBody(reactionBody())
    expect(posts.at(-1)?.text).toContain('could not post')
    expect(posts.at(-1)?.text).toContain('not_in_channel')
  })
})
