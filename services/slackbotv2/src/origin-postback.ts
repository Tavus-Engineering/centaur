import type { Chat, Logger, Thread } from 'chat'
import type { JsonValue } from './types'
import { isJsonObject, stringValue } from './utils'

/**
 * Origin-thread postback for DM investigations.
 *
 * When a user DMs the bot a Slack permalink ("investigate <link>"), the answer
 * lands only in the DM. This module remembers the linked channel thread, offers
 * a postback after the answer renders ("react ✅ to post this to the original
 * thread"), and — when the requesting user adds the ✅ reaction — posts the
 * answer into the origin thread with attribution.
 *
 * Requires the Slack app to subscribe to the `reaction_added` bot event (with
 * the `reactions:read` scope); without it the prompt still posts but reactions
 * never arrive, so the offer is phrased as best-effort.
 *
 * Pending offers live in process memory with a TTL: a slackbot restart drops
 * unactioned offers (the user can re-ask), which keeps this feature free of
 * schema changes.
 */

export const POSTBACK_APPROVAL_EMOJI = 'white_check_mark'

const PENDING_TTL_MS = 48 * 60 * 60 * 1000
const ORIGIN_TTL_MS = 6 * 60 * 60 * 1000

export type SlackMessageOrigin = {
  channel: string
  messageTs: string
  threadTs: string
  permalink: string
}

export type PendingPostback = {
  origin: SlackMessageOrigin
  requesterUserId: string
  dmThreadId: string
  promptMessageId: string
  session: PostbackSession
  expiresAtMs: number
}

export type PostbackSession = {
  threadId: string
  executionId?: string
  afterEventId: number
}

type RememberedOrigin = {
  origin: SlackMessageOrigin
  requesterUserId: string
  expiresAtMs: number
}

/**
 * Extract the first Slack channel permalink from message text. DM links
 * (`/archives/D...`) and links into `excludeChannel` (the DM itself) are
 * ignored — only public/private channels (C/G) count as an origin thread.
 */
export function extractSlackOrigin(
  text: string | undefined,
  excludeChannel?: string
): SlackMessageOrigin | undefined {
  if (!text) return undefined
  const pattern =
    /https?:\/\/[a-zA-Z0-9.-]+\.slack\.com\/archives\/([CG][A-Z0-9]{6,})\/p(\d{16})(?:\?([^\s>|]*))?/g
  for (const match of text.matchAll(pattern)) {
    const channel = match[1]
    const packedTs = match[2]
    if (!channel || !packedTs) continue
    if (excludeChannel && channel === excludeChannel) continue
    const messageTs = `${packedTs.slice(0, 10)}.${packedTs.slice(10)}`
    const query = match[3] ?? ''
    const threadTsMatch = /(?:^|&)thread_ts=(\d+\.\d+)/.exec(query)
    return {
      channel,
      messageTs,
      threadTs: threadTsMatch?.[1] ?? messageTs,
      permalink: match[0]
    }
  }
  return undefined
}

export type OriginPostbackDeps = {
  chat: Chat
  logger: Logger
  /**
   * Recompose the durable final-answer text for a session execution (the same
   * derivation the render fallback uses). Returns null when no answer exists.
   */
  recomposeAnswer(session: PostbackSession): Promise<string | null>
}

export class OriginPostbackManager {
  private origins = new Map<string, RememberedOrigin>()
  private pending = new Map<string, PendingPostback>()
  private deps?: OriginPostbackDeps

  bind(deps: OriginPostbackDeps): void {
    this.deps = deps
  }

  /** Remember the origin linked from a DM trigger message, keyed by DM thread id. */
  rememberOrigin(dmThreadId: string, origin: SlackMessageOrigin, requesterUserId: string): void {
    this.sweep()
    this.origins.set(dmThreadId, {
      origin,
      requesterUserId,
      expiresAtMs: Date.now() + ORIGIN_TTL_MS
    })
  }

  takeOrigin(dmThreadId: string): RememberedOrigin | undefined {
    this.sweep()
    const remembered = this.origins.get(dmThreadId)
    if (remembered) this.origins.delete(dmThreadId)
    return remembered
  }

  /**
   * Offer the postback in the DM after an answer rendered. Posts the prompt,
   * pre-adds the approval reaction as an affordance, and records the pending
   * offer keyed by the prompt message so the reaction event can find it.
   */
  async offerAfterRender(thread: Thread, session: PostbackSession): Promise<void> {
    const deps = this.deps
    if (!deps) return
    const remembered = this.takeOrigin(thread.id)
    if (!remembered) return
    const { origin, requesterUserId } = remembered
    try {
      const prompt = await thread.post(
        `React with :${POSTBACK_APPROVAL_EMOJI}: to post this answer back to ` +
          `<${origin.permalink}|the original thread>.`
      )
      const promptMessageId = prompt.id
      await prompt.addReaction(POSTBACK_APPROVAL_EMOJI).catch(() => undefined)
      this.pending.set(pendingKey(slackChannelFromThreadId(thread.id), promptMessageId), {
        origin,
        requesterUserId,
        dmThreadId: thread.id,
        promptMessageId,
        session,
        expiresAtMs: Date.now() + PENDING_TTL_MS
      })
      deps.logger.info('slackbotv2_postback_offered', {
        origin_channel: origin.channel,
        origin_thread_ts: origin.threadTs,
        prompt_message_id: promptMessageId,
        requester_user_id: requesterUserId,
        thread_id: thread.id
      })
    } catch (error) {
      deps.logger.warn('slackbotv2_postback_offer_failed', {
        error: error instanceof Error ? error.message : String(error),
        thread_id: thread.id
      })
    }
  }

  /**
   * Handle a raw (signature-verified) Slack webhook body. Returns a promise
   * for the postback work when the event is an approval reaction on a pending
   * offer, undefined otherwise.
   */
  handleWebhookBody(rawBody: string): Promise<void> | undefined {
    const reaction = parseReactionAdded(rawBody)
    if (!reaction) return undefined
    this.sweep()
    const key = pendingKey(reaction.channel, reaction.ts)
    const pending = this.pending.get(key)
    if (!pending) return undefined
    if (reaction.user !== pending.requesterUserId) {
      this.deps?.logger.info('slackbotv2_postback_reaction_ignored_wrong_user', {
        reaction_user: reaction.user,
        requester_user_id: pending.requesterUserId,
        thread_id: pending.dmThreadId
      })
      return undefined
    }
    this.pending.delete(key)
    return this.post(pending)
  }

  private async post(pending: PendingPostback): Promise<void> {
    const deps = this.deps
    if (!deps) return
    const dmThread = deps.chat.thread(pending.dmThreadId)
    try {
      const answer = await deps.recomposeAnswer(pending.session)
      if (!answer) {
        await dmThread.post('I could not recover the answer text to post it back.')
        return
      }
      const originThreadId = `slack:${pending.origin.channel}:${pending.origin.threadTs}`
      await deps.chat
        .thread(originThreadId)
        .post(`${answer}\n\n_Watch Agent investigation requested by <@${pending.requesterUserId}>._`)
      await dmThread.post(
        `:outbox_tray: Posted to <${pending.origin.permalink}|the original thread>.`
      )
      deps.logger.info('slackbotv2_postback_posted', {
        origin_channel: pending.origin.channel,
        origin_thread_ts: pending.origin.threadTs,
        thread_id: pending.dmThreadId
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      deps.logger.warn('slackbotv2_postback_failed', {
        error: message,
        origin_channel: pending.origin.channel,
        thread_id: pending.dmThreadId
      })
      await dmThread
        .post(
          `I could not post to <${pending.origin.permalink}|the original thread>: ${message}. ` +
            'If the channel is private, invite the bot and try again.'
        )
        .catch(() => undefined)
    }
  }

  private sweep(): void {
    const now = Date.now()
    for (const [key, value] of this.origins) {
      if (value.expiresAtMs <= now) this.origins.delete(key)
    }
    for (const [key, value] of this.pending) {
      if (value.expiresAtMs <= now) this.pending.delete(key)
    }
  }
}

function pendingKey(channel: string | undefined, messageId: string): string {
  return `${channel ?? ''}:${messageId}`
}

/** `slack:D0B7DPBT69M:` or `slack:D0B7DPBT69M:1234.5678` -> `D0B7DPBT69M`. */
export function slackChannelFromThreadId(threadId: string): string | undefined {
  const parts = threadId.split(':')
  return parts[0] === 'slack' && parts[1] ? parts[1] : undefined
}

export function isSlackDmThreadId(threadId: string): boolean {
  const channel = slackChannelFromThreadId(threadId)
  return channel?.startsWith('D') === true
}

type ReactionAdded = { channel: string; ts: string; user: string; reaction: string }

function parseReactionAdded(rawBody: string): ReactionAdded | undefined {
  let payload: unknown
  try {
    payload = JSON.parse(rawBody)
  } catch {
    return undefined
  }
  if (!isJsonObject(payload) || payload.type !== 'event_callback') return undefined
  const event: JsonValue | undefined = payload.event
  if (!isJsonObject(event) || event.type !== 'reaction_added') return undefined
  if (stringValue(event.reaction) !== POSTBACK_APPROVAL_EMOJI) return undefined
  const item = event.item
  if (!isJsonObject(item) || item.type !== 'message') return undefined
  const channel = stringValue(item.channel)
  const ts = stringValue(item.ts)
  const user = stringValue(event.user)
  if (!channel || !ts || !user) return undefined
  return { channel, ts, user, reaction: POSTBACK_APPROVAL_EMOJI }
}
