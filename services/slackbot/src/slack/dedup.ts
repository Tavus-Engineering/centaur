export class EventDeduper {
  readonly ttlMs: number
  private readonly seen = new Map<string, number>()

  constructor(ttlMs: number) {
    this.ttlMs = ttlMs
  }

  checkAndRemember(key: string, now = Date.now()): boolean {
    this.prune(now)
    const expiresAt = this.seen.get(key)
    if (expiresAt && expiresAt > now) return false
    this.seen.set(key, now + this.ttlMs)
    return true
  }

  checkAndRememberAll(keys: string[], now = Date.now()): { ok: true } | { ok: false; key: string } {
    this.prune(now)
    for (const key of keys) {
      const expiresAt = this.seen.get(key)
      if (expiresAt && expiresAt > now) return { ok: false, key }
    }
    const expiresAt = now + this.ttlMs
    for (const key of keys) {
      this.seen.set(key, expiresAt)
    }
    return { ok: true }
  }

  private prune(now: number): void {
    for (const [key, expiresAt] of this.seen) {
      if (expiresAt <= now) this.seen.delete(key)
    }
  }
}

export function slackDedupKey(opts: {
  eventId?: string
  teamId?: string
  channelId?: string
  messageTs?: string
}): string {
  if (opts.eventId) return `event:${opts.eventId}`
  return `message:${opts.teamId ?? 'unknown'}:${opts.channelId ?? 'unknown'}:${opts.messageTs ?? 'unknown'}`
}

export function slackDedupKeys(opts: {
  eventId?: string
  eventType?: string
  teamId?: string
  channelId?: string
  messageTs?: string
}): string[] {
  const keys: string[] = []
  if (isSlackMessageCallback(opts.eventType) && opts.channelId && opts.messageTs) {
    keys.push(messageDedupKey(opts))
  }
  if (opts.eventId) keys.push(`event:${opts.eventId}`)
  if (!keys.length) keys.push(messageDedupKey(opts))
  return keys
}

function isSlackMessageCallback(eventType: string | undefined): boolean {
  return eventType === 'app_mention' || eventType === 'message'
}

function messageDedupKey(opts: {
  teamId?: string
  channelId?: string
  messageTs?: string
}): string {
  return `message:${opts.teamId ?? 'unknown'}:${opts.channelId ?? 'unknown'}:${opts.messageTs ?? 'unknown'}`
}
