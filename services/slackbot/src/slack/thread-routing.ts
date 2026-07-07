import type { WebClient } from '@slack/web-api'
import { logWarn } from '../logging'
import type { NormalizedSlackEvent, NormalizedTextPart } from './types'

const THREAD_MENTION_DM_REACTION = 'incoming_envelope'
const ROUTE_METADATA_TYPE = 'centaur_thread_dm_route'
const RESULT_POSTED_METADATA_TYPE = 'centaur_thread_result_posted'
const POSTBACK_PROMPT_METADATA_TYPE = 'centaur_thread_postback_prompt'

type SlackMessageWithMetadata = {
  metadata?: {
    event_type?: string
    event_payload?: unknown
  }
}

type RoutedThreadPayload = {
  source_team_id: string
  source_channel_id: string
  source_thread_ts: string
  source_message_ts: string
  source_request_url: string
  source_thread_url: string
}

export type PostableExecutionResult = {
  execution_id: string
  result_text: string
}

type RoutedThreadState = {
  routePayload: RoutedThreadPayload | null
  prompted: boolean
}

export function shouldRouteThreadMentionToDm(event: NormalizedSlackEvent): boolean {
  if (!isChannelThreadReply(event)) return false
  if (!event.is_mention || !event.is_addressed) return false
  return !requestsInlineThreadReply(event)
}

export async function routeThreadMentionToDm(
  client: WebClient,
  event: NormalizedSlackEvent
): Promise<NormalizedSlackEvent> {
  if (!shouldRouteThreadMentionToDm(event)) return event

  await addDmReaction(client, event)

  const dmChannelId = await openDmChannel(client, event.user_id)
  const sourceRequestUrl = slackMessageUrl(
    event.channel_id,
    event.slack.message_ts,
    event.thread_ts
  )
  const sourceThreadUrl = slackMessageUrl(event.channel_id, event.thread_ts)
  const routePayload: RoutedThreadPayload = {
    source_team_id: event.team_id,
    source_channel_id: event.channel_id,
    source_thread_ts: event.thread_ts,
    source_message_ts: event.slack.message_ts,
    source_request_url: sourceRequestUrl,
    source_thread_url: sourceThreadUrl
  }

  const dmRoot = await client.chat.postMessage({
    channel: dmChannelId,
    text: [
      'I moved this Watch Agent request into DM to avoid adding noise to the original thread.',
      '',
      `Original request: ${sourceRequestUrl}`,
      `Original thread: ${sourceThreadUrl}`,
      '',
      'I will reply in this DM thread.'
    ].join('\n'),
    metadata: {
      event_type: ROUTE_METADATA_TYPE,
      event_payload: routePayload
    }
  } as Parameters<typeof client.chat.postMessage>[0])
  if (!dmRoot.ok || !dmRoot.ts) {
    throw new Error(`Failed to open routed DM thread: ${dmRoot.error ?? 'missing_ts'}`)
  }

  const dmThreadTs = dmRoot.ts
  return {
    ...event,
    thread_key: `slack:${event.team_id}:${dmChannelId}:${dmThreadTs}`,
    channel_id: dmChannelId,
    thread_ts: dmThreadTs,
    parts: [routingInstructionPart(routePayload), ...event.parts],
    route: {
      mode: 'dm_from_thread_mention',
      ...routePayload,
      dm_channel_id: dmChannelId,
      dm_thread_ts: dmThreadTs
    }
  }
}

export async function maybePublishApprovedDmResultToThread(opts: {
  client: WebClient
  event: NormalizedSlackEvent
  latestPostableResult: (threadKey: string) => Promise<PostableExecutionResult | null>
}): Promise<boolean> {
  if (!isDmThreadReply(opts.event)) return false
  if (!isPublishApproval(eventText(opts.event))) return false

  const routePayload = await loadRoutePayloadFromDmRoot(opts.client, opts.event)
  if (!routePayload) return false

  const result = await opts.latestPostableResult(opts.event.thread_key)
  if (!result) {
    await opts.client.chat.postMessage({
      channel: opts.event.channel_id,
      thread_ts: opts.event.thread_ts,
      text: 'I do not have a successful result to post yet.'
    })
    return true
  }

  const posted = await opts.client.chat.postMessage({
    channel: routePayload.source_channel_id,
    thread_ts: routePayload.source_thread_ts,
    text: [
      `Posted from a private Watch Agent follow-up for <@${opts.event.user_id}>.`,
      '',
      result.result_text
    ].join('\n'),
    metadata: {
      event_type: RESULT_POSTED_METADATA_TYPE,
      event_payload: {
        source_dm_channel_id: opts.event.channel_id,
        source_dm_thread_ts: opts.event.thread_ts,
        source_execution_id: result.execution_id,
        approved_by_user_id: opts.event.user_id
      }
    }
  } as Parameters<typeof opts.client.chat.postMessage>[0])
  if (!posted.ok) {
    throw new Error(`Failed to post routed result: ${posted.error ?? 'unknown_error'}`)
  }

  await opts.client.chat.postMessage({
    channel: opts.event.channel_id,
    thread_ts: opts.event.thread_ts,
    text: posted.ts
      ? `Posted to the original thread: ${slackMessageUrl(
          routePayload.source_channel_id,
          posted.ts,
          routePayload.source_thread_ts
        )}`
      : 'Posted to the original thread.'
  })
  return true
}

export async function maybePromptRoutedDmPostback(opts: {
  client: WebClient
  channelId: string
  threadTs: string
}): Promise<boolean> {
  if (!opts.channelId.startsWith('D')) return false

  const state = await loadRoutedThreadStateFromDmRoot(opts.client, opts.channelId, opts.threadTs)
  if (!state.routePayload || state.prompted) return false

  const response = await opts.client.chat.postMessage({
    channel: opts.channelId,
    thread_ts: opts.threadTs,
    text: [
      'I can post this answer back to the original thread.',
      'Reply `post it` in this DM thread and I will copy the latest successful answer back there.'
    ].join('\n'),
    metadata: {
      event_type: POSTBACK_PROMPT_METADATA_TYPE,
      event_payload: {
        source_channel_id: state.routePayload.source_channel_id,
        source_thread_ts: state.routePayload.source_thread_ts
      }
    }
  } as Parameters<typeof opts.client.chat.postMessage>[0])
  if (!response.ok) {
    throw new Error(
      `Failed to post routed DM postback prompt: ${response.error ?? 'unknown_error'}`
    )
  }
  return true
}

function isChannelThreadReply(event: NormalizedSlackEvent): boolean {
  return !event.channel_id.startsWith('D') && event.slack.message_ts !== event.thread_ts
}

function isDmThreadReply(event: NormalizedSlackEvent): boolean {
  return event.channel_id.startsWith('D') && event.slack.message_ts !== event.thread_ts
}

async function addDmReaction(client: WebClient, event: NormalizedSlackEvent): Promise<void> {
  try {
    await client.reactions.add({
      channel: event.channel_id,
      timestamp: event.slack.message_ts,
      name: THREAD_MENTION_DM_REACTION
    })
  } catch (error) {
    logWarn('slack_thread_dm_reaction_failed', {
      channel_id: event.channel_id,
      thread_ts: event.thread_ts,
      message_ts: event.slack.message_ts,
      error: error instanceof Error ? error.message : String(error)
    })
  }
}

async function openDmChannel(client: WebClient, userId: string): Promise<string> {
  const response = await client.conversations.open({ users: userId })
  const channelId = response.channel?.id
  if (!response.ok || !channelId) {
    throw new Error(`Failed to open DM channel: ${response.error ?? 'missing_channel_id'}`)
  }
  return channelId
}

async function loadRoutePayloadFromDmRoot(
  client: WebClient,
  event: NormalizedSlackEvent
): Promise<RoutedThreadPayload | null> {
  const state = await loadRoutedThreadStateFromDmRoot(client, event.channel_id, event.thread_ts)
  return state.routePayload
}

async function loadRoutedThreadStateFromDmRoot(
  client: WebClient,
  channelId: string,
  threadTs: string
): Promise<RoutedThreadState> {
  const response = await client.conversations.replies({
    channel: channelId,
    ts: threadTs,
    limit: 20
  })
  if (!response.ok || !Array.isArray(response.messages)) {
    return { routePayload: null, prompted: false }
  }

  let routePayload: RoutedThreadPayload | null = null
  let prompted = false
  for (const message of response.messages as SlackMessageWithMetadata[]) {
    const metadata = message.metadata
    if (metadata?.event_type === ROUTE_METADATA_TYPE) {
      routePayload = parseRoutePayload(metadata.event_payload)
      continue
    }
    if (metadata?.event_type === POSTBACK_PROMPT_METADATA_TYPE) {
      prompted = true
    }
  }
  return { routePayload, prompted }
}

function parseRoutePayload(value: unknown): RoutedThreadPayload | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Record<string, unknown>
  const source_team_id = stringField(payload, 'source_team_id')
  const source_channel_id = stringField(payload, 'source_channel_id')
  const source_thread_ts = stringField(payload, 'source_thread_ts')
  const source_message_ts = stringField(payload, 'source_message_ts')
  const source_request_url = stringField(payload, 'source_request_url')
  const source_thread_url = stringField(payload, 'source_thread_url')
  if (
    !source_team_id ||
    !source_channel_id ||
    !source_thread_ts ||
    !source_message_ts ||
    !source_request_url ||
    !source_thread_url
  ) {
    return null
  }
  return {
    source_team_id,
    source_channel_id,
    source_thread_ts,
    source_message_ts,
    source_request_url,
    source_thread_url
  }
}

function stringField(payload: Record<string, unknown>, key: string): string {
  const value = payload[key]
  return typeof value === 'string' ? value.trim() : ''
}

function routingInstructionPart(payload: RoutedThreadPayload): NormalizedTextPart {
  return {
    type: 'text',
    text: [
      'Slack routing note: this Watch Agent request was moved from an existing Slack thread into this private DM thread to avoid spamming the original thread.',
      `Original request: ${payload.source_request_url}`,
      `Original top-level thread: ${payload.source_thread_url}`,
      'Use the backfilled original thread history as context, keep the answer in this DM, and end your final answer with: "Do you want me to post this answer if it succeeds?"'
    ].join('\n')
  }
}

function requestsInlineThreadReply(event: NormalizedSlackEvent): boolean {
  return INLINE_REPLY_RE.test(eventText(event))
}

function eventText(event: NormalizedSlackEvent): string {
  return event.parts
    .filter(part => part.type === 'text')
    .map(part => part.text)
    .join('\n')
}

const INLINE_REPLY_RE =
  /\b(?:post|reply|respond|answer)\s+(?:(?:just|only)\s+)?(?:the\s+)?(?:(?:answer|results?|response|reply|it|this)\s+)?(?:inline|here|in\s+(?:this|the)\s+thread)\b|\b(?:keep|leave)\s+(?:it|this|the\s+(?:answer|results?|response|reply))\s+(?:inline|here|in\s+(?:this|the)\s+thread)\b/i

function isPublishApproval(text: string): boolean {
  const normalized = text
    .toLowerCase()
    .replace(/[!?.,…]+/gu, ' ')
    .replace(/\s+/gu, ' ')
    .trim()
  if (!normalized || normalized.length > 120) return false
  if (
    new Set([
      'yes',
      'yes please',
      'yep',
      'yup',
      'yeah',
      'sure',
      'sure thing',
      'ok',
      'okay',
      'sgtm',
      'please do',
      'go ahead',
      'do it'
    ]).has(normalized)
  ) {
    return true
  }
  return (
    (/\bpost\b/.test(normalized) &&
      /\b(it|this|answer|results?|thread|there|back|original)\b/.test(normalized)) ||
    /\b(?:post|send|share|copy)\b.*\b(?:back|original|thread|there)\b/.test(normalized)
  )
}

export function slackMessageUrl(channelId: string, messageTs: string, threadTs?: string): string {
  const url = new URL(`https://slack.com/archives/${channelId}/p${messageTs.replace('.', '')}`)
  if (threadTs && threadTs !== messageTs) {
    url.searchParams.set('thread_ts', threadTs)
    url.searchParams.set('cid', channelId)
  }
  return url.toString()
}
