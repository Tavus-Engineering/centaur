import { describe, expect, it } from 'bun:test'
import { buildWatchAgentHomeView } from './home'

describe('Watch Agent Home view', () => {
  it('builds a Slack Home tab with the expected capability sections', () => {
    const view = buildWatchAgentHomeView()
    const body = JSON.stringify(view.blocks)

    expect(view.type).toBe('home')
    expect(view.callback_id).toBe('watch_agent_home_v1')
    expect(view.blocks.length).toBeLessThanOrEqual(100)
    expect(body).toContain('Watch Agent')
    expect(body).toContain('Connected Systems')
    expect(body).toContain('CLI And Harnesses')
    expect(body).toContain('tavus-context')
    expect(body).toContain('tavus-investigate-conversation')
    expect(body).toContain('signoz-generating-queries')
    expect(body).toContain('Sample Prompts')
  })
})
