import { describe, expect, it } from 'bun:test'
import { EventDeduper, slackDedupKey, slackDedupKeys } from './dedup'

describe('EventDeduper', () => {
  it('rejects duplicate keys until the TTL expires', () => {
    const deduper = new EventDeduper(100)

    expect(deduper.checkAndRemember('event:Ev123', 1_000)).toBe(true)
    expect(deduper.checkAndRemember('event:Ev123', 1_050)).toBe(false)
    expect(deduper.checkAndRemember('event:Ev123', 1_101)).toBe(true)
  })

  it('rejects duplicate key batches if any key is still live', () => {
    const deduper = new EventDeduper(100)

    expect(deduper.checkAndRememberAll(['message:T123:C123:1', 'event:Ev-app'], 1_000)).toEqual({
      ok: true
    })
    expect(deduper.checkAndRememberAll(['message:T123:C123:1', 'event:Ev-message'], 1_050)).toEqual(
      {
        ok: false,
        key: 'message:T123:C123:1'
      }
    )
    expect(deduper.checkAndRememberAll(['message:T123:C123:1', 'event:Ev-message'], 1_101)).toEqual(
      {
        ok: true
      }
    )
  })

  it('prefers Slack event IDs and falls back to message identity', () => {
    expect(
      slackDedupKey({
        eventId: 'Ev123',
        teamId: 'T123',
        channelId: 'C123',
        messageTs: '1778883099.579529'
      })
    ).toBe('event:Ev123')

    expect(
      slackDedupKey({
        teamId: 'T123',
        channelId: 'C123',
        messageTs: '1778883099.579529'
      })
    ).toBe('message:T123:C123:1778883099.579529')
  })

  it('uses message identity before event ID for Slack message callbacks', () => {
    expect(
      slackDedupKeys({
        eventId: 'Ev-app',
        eventType: 'app_mention',
        teamId: 'T123',
        channelId: 'C123',
        messageTs: '1778883099.579529'
      })
    ).toEqual(['message:T123:C123:1778883099.579529', 'event:Ev-app'])

    expect(
      slackDedupKeys({
        eventId: 'Ev-home',
        eventType: 'app_home_opened'
      })
    ).toEqual(['event:Ev-home'])
  })
})
