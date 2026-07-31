import { describe, expect, test } from 'bun:test'
import type { Logger } from 'chat'
import { dmChannelId, DmParticipationGuard } from '../src/dm-guard'

const warnings: Array<{ event: string; fields: unknown }> = []
const testLogger: Logger = {
  child: () => testLogger,
  debug: () => undefined,
  error: () => undefined,
  info: () => undefined,
  warn: (event: string, fields: unknown) => {
    warnings.push({ event, fields })
  }
}

function guardWith(responses: Record<string, unknown>, calls: string[] = []) {
  return new DmParticipationGuard({
    botToken: 'xoxb-test',
    fetchImpl: (async (url: string | URL | Request) => {
      const u = String(url)
      calls.push(u)
      const channel = new URL(u).searchParams.get('channel') ?? ''
      const body = responses[channel] ?? { ok: false, error: 'channel_not_found' }
      return new Response(JSON.stringify(body), { status: 200 })
    }) as unknown as typeof fetch,
    logger: testLogger
  })
}

describe('dmChannelId', () => {
  test('extracts DM channels only', () => {
    expect(dmChannelId('slack:D0AQWNX3GDT:')).toBe('D0AQWNX3GDT')
    expect(dmChannelId('slack:D0B7DPBT69M:1785.1')).toBe('D0B7DPBT69M')
    expect(dmChannelId('slack:C0BEAU4B66T:1785.1')).toBeUndefined()
    expect(dmChannelId('slack:G123:1785.1')).toBeUndefined()
    expect(dmChannelId('discord:whatever')).toBeUndefined()
    expect(dmChannelId('slackbotv2:health:codex-ping:1')).toBeUndefined()
  })
})

describe('DmParticipationGuard', () => {
  test("blocks a DM the bot is not a party to (the overheard human-to-human case)", async () => {
    const guard = guardWith({ D0B7DPBT69M: { ok: true } })
    // D0AQWNX3GDT is Samuel<->Ari; the bot gets channel_not_found.
    expect(await guard.allows('slack:D0AQWNX3GDT:')).toBe(false)
    expect(warnings.some(w => w.event === 'slackbotv2_event_ignored_bot_not_in_dm')).toBe(true)
  })

  test("allows the bot's own DM", async () => {
    const guard = guardWith({ D0B7DPBT69M: { ok: true } })
    expect(await guard.allows('slack:D0B7DPBT69M:')).toBe(true)
  })

  test('allows channels without any API call', async () => {
    const calls: string[] = []
    const guard = guardWith({}, calls)
    expect(await guard.allows('slack:C0BEAU4B66T:1785.1')).toBe(true)
    expect(await guard.allows('slackbotv2:health:codex-ping:1')).toBe(true)
    expect(calls).toHaveLength(0)
  })

  test('fails open on inconclusive errors so a Slack blip cannot mute the bot', async () => {
    const guard = guardWith({ D0RATELIMIT: { ok: false, error: 'ratelimited' } })
    expect(await guard.allows('slack:D0RATELIMIT:')).toBe(true)
  })

  test('fails open when the request throws', async () => {
    const guard = new DmParticipationGuard({
      botToken: 'xoxb-test',
      fetchImpl: (async () => {
        throw new Error('network down')
      }) as unknown as typeof fetch,
      logger: testLogger
    })
    expect(await guard.allows('slack:D0NETWORK:')).toBe(true)
  })

  test('caches per channel and expires after the TTL', async () => {
    const calls: string[] = []
    let now = 1_000_000
    const guard = new DmParticipationGuard({
      botToken: 'xoxb-test',
      fetchImpl: (async (url: string | URL | Request) => {
        calls.push(String(url))
        return new Response(JSON.stringify({ ok: true }), { status: 200 })
      }) as unknown as typeof fetch,
      logger: testLogger,
      now: () => now
    })
    expect(await guard.allows('slack:D0CACHED:')).toBe(true)
    expect(await guard.allows('slack:D0CACHED:1785.1')).toBe(true)
    expect(calls).toHaveLength(1)
    now += 11 * 60 * 1000
    expect(await guard.allows('slack:D0CACHED:')).toBe(true)
    expect(calls).toHaveLength(2)
  })
})
