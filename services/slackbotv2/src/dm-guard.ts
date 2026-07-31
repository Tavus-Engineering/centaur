import type { Logger } from 'chat'

/**
 * Guard against acting on conversations the bot is not a party to.
 *
 * The Slack app holds user-scoped event subscriptions (a user token with
 * `im:history`), so Slack delivers the authorizing user's OWN direct messages —
 * including private human-to-human DMs the bot was never invited to. slackbotv2
 * treats DM-shaped threads as "no @-mention required", so such a conversation
 * was executed as if it were addressed to the agent: on 2026-07-31 a private
 * DM between two engineers discussing a release ("lets merge as soon as its
 * ready") caused the agent to merge three pull requests.
 *
 * A bot can always read a DM it participates in, and never one it does not, so
 * `conversations.info` with the BOT token is an exact membership test:
 * `channel_not_found` means the bot is not a party and the event is something
 * we are merely overhearing.
 *
 * Non-DM channels are unaffected — the bot is a member of the channels it is
 * invited to, and channel behavior is governed by the existing mention rules.
 * Unexpected API failures fail OPEN (the message is processed) so a Slack blip
 * cannot silently mute the agent; only an explicit not-a-member answer blocks.
 */

const CACHE_TTL_MS = 10 * 60 * 1000
const LOOKUP_TIMEOUT_MS = 5_000

type CacheEntry = { participant: boolean; expiresAtMs: number }

export type DmParticipationOptions = {
  botToken: string
  logger: Logger
  fetchImpl?: typeof globalThis.fetch
  now?: () => number
}

export class DmParticipationGuard {
  private readonly cache = new Map<string, CacheEntry>()

  constructor(private readonly options: DmParticipationOptions) {}

  private get now(): number {
    return (this.options.now ?? Date.now)()
  }

  /**
   * True when the agent may act on a message in `threadId`. Only DM-shaped
   * threads are checked; everything else is allowed.
   */
  async allows(threadId: string): Promise<boolean> {
    const channelId = dmChannelId(threadId)
    if (!channelId) return true

    const cached = this.cache.get(channelId)
    if (cached && cached.expiresAtMs > this.now) return cached.participant

    const participant = await this.lookup(channelId)
    this.cache.set(channelId, {
      participant,
      expiresAtMs: this.now + CACHE_TTL_MS
    })
    if (!participant) {
      this.options.logger.warn('slackbotv2_event_ignored_bot_not_in_dm', {
        channel_id: channelId,
        thread_id: threadId
      })
    }
    return participant
  }

  private async lookup(channelId: string): Promise<boolean> {
    const fetchImpl = this.options.fetchImpl ?? globalThis.fetch
    try {
      const response = await fetchImpl(
        `https://slack.com/api/conversations.info?channel=${encodeURIComponent(channelId)}`,
        {
          headers: { Authorization: `Bearer ${this.options.botToken}` },
          signal: AbortSignal.timeout(LOOKUP_TIMEOUT_MS)
        }
      )
      const body = (await response.json()) as { ok?: boolean; error?: string }
      if (body.ok === true) return true
      // The only answer that means "the bot is not a party to this
      // conversation". Every other error (rate limits, transient failures,
      // scope problems) fails open.
      if (body.error === 'channel_not_found') return false
      this.options.logger.warn('slackbotv2_dm_participation_lookup_inconclusive', {
        channel_id: channelId,
        error: body.error ?? `HTTP ${response.status}`
      })
      return true
    } catch (error) {
      this.options.logger.warn('slackbotv2_dm_participation_lookup_failed', {
        channel_id: channelId,
        error: error instanceof Error ? error.message : String(error)
      })
      return true
    }
  }
}

/** `slack:D0AQWNX3GDT:` -> `D0AQWNX3GDT`; non-DM threads -> undefined. */
export function dmChannelId(threadId: string): string | undefined {
  const parts = threadId.split(':')
  if (parts[0] !== 'slack') return undefined
  const channel = parts[1]
  return channel?.startsWith('D') ? channel : undefined
}
