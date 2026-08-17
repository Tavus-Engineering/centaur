import { randomUUID } from 'node:crypto'
import { assertSlackOk, callSlackApi } from '@chat-adapter/slack/api'
import { Message as ChatSdkMessage, parseMarkdown, type Message as ChatMessage, type StateAdapter, type Thread } from 'chat'
import { channelIdFromThreadId } from './channel-defaults'
import { fetchWithTimeout, slackApiTimeoutMs } from './session-api'
import type { SlackbotV2Options, SlackbotV2ThreadState } from './types'
import { errorMessage, isJsonObject, stringValue, traceLog, traceWarn } from './utils'

const ROUTE_TTL_MS = 30 * 24 * 60 * 60 * 1000
const ROUTE_LEASE_TTL_MS = 30_000
const ROUTE_WAIT_MS = 2_000
const ROUTE_WAIT_INTERVAL_MS = 50
const ROOT_REQUEST_MAX_CHARS = 3_000

type InvestigationRoute = {
  sourceChannelId: string
  sourceThreadId: string
  sourceThreadTs: string
  targetChannelId: string
  targetThreadId: string
  targetThreadTs: string
}

export type InvestigationHandoffResult = {
  message: ChatMessage
  sourceChannelId: string
  sourceThreadTs: string
  thread: Thread<SlackbotV2ThreadState>
}

type InvestigationHandoffDependencies = {
  options: SlackbotV2Options
  state: StateAdapter
  threadForId(threadId: string): Thread<SlackbotV2ThreadState>
}

/**
 * Moves second-and-later Watch Agent turns out of an ordinary Slack thread and
 * into one reusable thread in the configured investigations channel.
 *
 * The route itself is stored in the shared Chat SDK state backend so pod
 * restarts and Slack redeliveries cannot fork an investigation into multiple
 * channel threads.
 */
export class InvestigationHandoffManager {
  constructor(private readonly deps: InvestigationHandoffDependencies) {}

  async route(
    sourceThread: Thread<SlackbotV2ThreadState>,
    sourceMessage: ChatMessage
  ): Promise<InvestigationHandoffResult | null> {
    const targetChannelId = this.deps.options.investigationsChannelId
    const sourceChannelId = channelIdFromThreadId(sourceThread.id)
    if (
      !targetChannelId ||
      !sourceChannelId ||
      sourceThread.isDM ||
      sourceChannelId === targetChannelId
    ) {
      return null
    }

    const sourceState = (await sourceThread.state) ?? {}
    const alreadyAnswered =
      sourceState.activeExecution === true || (sourceState.executedMessageIds?.length ?? 0) > 0
    if (!alreadyAnswered) return null

    const sourceThreadTs = slackThreadTs(sourceThread.id, sourceMessage)
    if (!sourceThreadTs) return null

    const route = await this.getOrCreateRoute({
      sourceChannelId,
      sourceMessage,
      sourceThread,
      sourceThreadTs,
      targetChannelId
    })
    await sourceThread.post(
      `I moved this follow-up to <#${route.targetChannelId}>: <${slackMessageUrl(route.targetChannelId, route.targetThreadTs)}|open the investigation thread>. Please continue there.`
    )

    traceLog(this.deps.options, 'slackbotv2_investigation_handoff_routed', undefined, {
      source_thread_id: route.sourceThreadId,
      target_thread_id: route.targetThreadId
    })
    return {
      message: routedMessage(sourceMessage, route),
      sourceChannelId: route.sourceChannelId,
      sourceThreadTs: route.sourceThreadTs,
      thread: this.deps.threadForId(route.targetThreadId)
    }
  }

  private async getOrCreateRoute(input: {
    sourceChannelId: string
    sourceMessage: ChatMessage
    sourceThread: Thread<SlackbotV2ThreadState>
    sourceThreadTs: string
    targetChannelId: string
  }): Promise<InvestigationRoute> {
    const routeKey = investigationRouteKey(input.sourceThread.id)
    const existing = parseInvestigationRoute(await this.deps.state.get(routeKey))
    if (existing) return existing

    const leaseKey = `${routeKey}:lease`
    const leaseToken = randomUUID()
    const ownsLease = await this.deps.state.setIfNotExists(
      leaseKey,
      leaseToken,
      ROUTE_LEASE_TTL_MS
    )
    if (!ownsLease) {
      const route = await this.waitForRoute(routeKey)
      if (route) return route
      throw new Error('another request is still creating the investigation handoff')
    }

    try {
      const afterLease = parseInvestigationRoute(await this.deps.state.get(routeKey))
      if (afterLease) return afterLease

      const sourceMessageTs = slackMessageTs(input.sourceMessage)
      const sourceThreadUrl = slackMessageUrl(input.sourceChannelId, input.sourceThreadTs)
      const sourceMessageUrl = slackMessageUrl(
        input.sourceChannelId,
        sourceMessageTs,
        input.sourceThreadTs
      )
      const rootText = investigationRootText(
        input.sourceMessage,
        sourceThreadUrl,
        sourceMessageUrl,
        this.deps.options.botUserId
      )
      const targetThreadTs = await postSlackMessage(
        this.deps.options,
        input.targetChannelId,
        rootText
      )
      const route: InvestigationRoute = {
        sourceChannelId: input.sourceChannelId,
        sourceThreadId: input.sourceThread.id,
        sourceThreadTs: input.sourceThreadTs,
        targetChannelId: input.targetChannelId,
        targetThreadId: `slack:${input.targetChannelId}:${targetThreadTs}`,
        targetThreadTs
      }
      await this.deps.state.set(routeKey, route, ROUTE_TTL_MS)
      traceLog(this.deps.options, 'slackbotv2_investigation_handoff_created', undefined, {
        source_thread_id: route.sourceThreadId,
        target_thread_id: route.targetThreadId
      })
      return route
    } catch (error) {
      traceWarn(this.deps.options, 'slackbotv2_investigation_handoff_create_failed', undefined, {
        error: errorMessage(error),
        source_thread_id: input.sourceThread.id
      })
      throw error
    } finally {
      try {
        if ((await this.deps.state.get(leaseKey)) === leaseToken) {
          await this.deps.state.delete(leaseKey)
        }
      } catch (error) {
        traceWarn(this.deps.options, 'slackbotv2_investigation_handoff_lease_cleanup_failed', undefined, {
          error: errorMessage(error),
          source_thread_id: input.sourceThread.id
        })
      }
    }
  }

  private async waitForRoute(routeKey: string): Promise<InvestigationRoute | null> {
    const deadline = Date.now() + ROUTE_WAIT_MS
    while (Date.now() < deadline) {
      const route = parseInvestigationRoute(await this.deps.state.get(routeKey))
      if (route) return route
      await new Promise(resolve => setTimeout(resolve, ROUTE_WAIT_INTERVAL_MS))
    }
    return parseInvestigationRoute(await this.deps.state.get(routeKey))
  }
}

/**
 * Investigation threads are dedicated to Watch Agent. A human reply there is
 * therefore a bot follow-up unless it explicitly mentions somebody else and
 * does not mention/name Watch Agent.
 */
export function isDirectedAtWatchAgent(
  message: ChatMessage,
  botUserId: string | undefined
): boolean {
  if (message.isMention === true) return true
  if (/\bwatch\s+agent\b/i.test(message.text)) return true

  const mentionedUsers = slackMentionedUserIds(message.raw)
  if (botUserId && mentionedUsers.has(botUserId)) return true
  return mentionedUsers.size === 0
}

/**
 * Ordinary shared threads need a stronger signal than dedicated investigation
 * threads before an unmentioned reply is treated as a Watch Agent follow-up.
 */
export function isLikelyWatchAgentFollowup(
  message: ChatMessage,
  botUserId: string | undefined
): boolean {
  if (message.isMention === true || /\bwatch\s+agent\b/i.test(message.text)) return true
  const mentionedUsers = slackMentionedUserIds(message.raw)
  if (botUserId && mentionedUsers.has(botUserId)) return true
  if (mentionedUsers.size > 0) return false
  if (message.attachments.length > 0) return true

  const text = message.text.trim()
  return (
    /\?$/.test(text) ||
    /^(?:also\b|and\b|but\b|can\b|check\b|continue\b|could\b|do\b|explain\b|find\b|fix\b|how\b|investigate\b|look\b|now\b|please\b|rerun\b|retry\b|show\b|tell\b|then\b|try\b|update\b|verify\b|what\b|when\b|where\b|who\b|why\b|will\b|would\b)/i.test(
      text
    )
  )
}

function slackMentionedUserIds(value: unknown, result = new Set<string>()): Set<string> {
  if (typeof value === 'string') {
    for (const match of value.matchAll(/<@([A-Z0-9]+)(?:\|[^>]+)?>/g)) {
      if (match[1]) result.add(match[1])
    }
    return result
  }
  if (Array.isArray(value)) {
    for (const item of value) slackMentionedUserIds(item, result)
    return result
  }
  if (!isJsonObject(value)) return result
  if (value.type === 'user') {
    const userId = stringValue(value.user_id)
    if (userId) result.add(userId)
  }
  for (const item of Object.values(value)) slackMentionedUserIds(item, result)
  return result
}

function routedMessage(message: ChatMessage, route: InvestigationRoute): ChatMessage {
  const note = [
    'Slack routing note: this is a follow-up moved from another channel after Watch Agent replied there once.',
    `Original thread: ${slackMessageUrl(route.sourceChannelId, route.sourceThreadTs)}`,
    'Keep every response and follow-up in this investigation thread.'
  ].join('\n')
  const text = `${note}\n\n${message.text}`
  const raw = isJsonObject(message.raw)
    ? {
        ...message.raw,
        channel: route.targetChannelId,
        text,
        thread_ts: route.targetThreadTs,
        ts: message.id
      }
    : message.raw
  return new ChatSdkMessage({
    attachments: message.attachments,
    author: message.author,
    formatted: parseMarkdown(text),
    id: message.id,
    isMention: true,
    links: message.links,
    metadata: message.metadata,
    raw,
    text,
    threadId: route.targetThreadId
  })
}

function investigationRootText(
  message: ChatMessage,
  sourceThreadUrl: string,
  sourceMessageUrl: string,
  botUserId: string | undefined
): string {
  const userId = stringValue(message.author.userId)
  const requester = userId ? `<@${userId}>` : 'A teammate'
  const request = stripBotMention(message.text, botUserId).slice(0, ROOT_REQUEST_MAX_CHARS).trim()
  return [
    `${requester} continued a Watch Agent request after the first reply in <${sourceThreadUrl}|the original thread>.`,
    `<${sourceMessageUrl}|Open the follow-up that started this investigation>.`,
    request ? `\n> ${request.replace(/\n/g, '\n> ')}` : ''
  ].join('\n')
}

function stripBotMention(text: string, botUserId: string | undefined): string {
  if (!botUserId) return text
  return text.replace(new RegExp(`<@${escapeRegExp(botUserId)}(?:\\|[^>]+)?>`, 'g'), '').trim()
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

async function postSlackMessage(
  options: SlackbotV2Options,
  channelId: string,
  text: string
): Promise<string> {
  const fetchFn = options.fetch ?? fetch
  const timeoutFetch = Object.assign(
    (input: RequestInfo | URL, init?: RequestInit) =>
      fetchWithTimeout(
        fetchFn,
        input,
        init ?? {},
        slackApiTimeoutMs(options),
        'Slack API chat.postMessage'
      ),
    { preconnect: fetch.preconnect }
  )
  const payload = await callSlackApi(
    'chat.postMessage',
    { channel: channelId, text },
    {
      apiUrl: options.slackApiUrl,
      fetch: timeoutFetch,
      token: options.botToken
    }
  )
  assertSlackOk('chat.postMessage', payload)
  const ts = stringValue(payload.ts)
  if (!ts) throw new Error('Slack chat.postMessage returned no timestamp')
  return ts
}

function slackThreadTs(threadId: string, message: ChatMessage): string {
  if (isJsonObject(message.raw)) {
    const rawThreadTs = stringValue(message.raw.thread_ts)
    if (rawThreadTs) return rawThreadTs
  }
  const channelId = channelIdFromThreadId(threadId)
  if (!channelId) return ''
  const parts = threadId.split(':')
  const channelIndex = parts.indexOf(channelId)
  return parts[channelIndex + 1] ?? message.id
}

function slackMessageTs(message: ChatMessage): string {
  return isJsonObject(message.raw) ? stringValue(message.raw.ts) ?? message.id : message.id
}

function investigationRouteKey(sourceThreadId: string): string {
  return `slackbotv2:investigation-handoff:${sourceThreadId}`
}

function parseInvestigationRoute(value: unknown): InvestigationRoute | null {
  if (!isJsonObject(value)) return null
  const sourceChannelId = stringValue(value.sourceChannelId)
  const sourceThreadId = stringValue(value.sourceThreadId)
  const sourceThreadTs = stringValue(value.sourceThreadTs)
  const targetChannelId = stringValue(value.targetChannelId)
  const targetThreadId = stringValue(value.targetThreadId)
  const targetThreadTs = stringValue(value.targetThreadTs)
  if (
    !sourceChannelId ||
    !sourceThreadId ||
    !sourceThreadTs ||
    !targetChannelId ||
    !targetThreadId ||
    !targetThreadTs
  ) {
    return null
  }
  return {
    sourceChannelId,
    sourceThreadId,
    sourceThreadTs,
    targetChannelId,
    targetThreadId,
    targetThreadTs
  }
}

export function slackMessageUrl(channelId: string, messageTs: string, threadTs?: string): string {
  const url = new URL(`https://slack.com/archives/${channelId}/p${messageTs.replace('.', '')}`)
  if (threadTs && threadTs !== messageTs) {
    url.searchParams.set('thread_ts', threadTs)
    url.searchParams.set('cid', channelId)
  }
  return url.toString()
}
