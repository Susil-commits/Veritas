import { describe, it, expect } from 'vitest'
import { COGNITIVE_DAG_NODES, getDomainBadgeStyle, SKILLS_REGISTRY } from './skillsData'

describe('skillsData', () => {
  it('resolves valid translucent badge styles instead of invalid hex suffixes on CSS vars', () => {
    const violetStyle = getDomainBadgeStyle('var(--violet)')
    expect(violetStyle.background).toBe('rgba(124, 93, 250, 0.12)')
    expect(violetStyle.border).toContain('rgba(')

    const customStyle = getDomainBadgeStyle('var(--custom-teal)')
    expect(customStyle.background).toContain('color-mix')
    expect(customStyle.background).not.toMatch(/var\(--[^)]+\)\d+/)
    expect(customStyle.border).toContain('color-mix')
  })

  it('aligns 6.EE.A.2 priors with backend BKT registry', () => {
    const node = COGNITIVE_DAG_NODES['6.EE.A.2']
    expect(node.prior).toBe(0.2)
    expect(node.learn).toBe(0.13)
    expect(node.guess).toBe(0.2)
    expect(node.slip).toBe(0.1)
    expect(Object.keys(SKILLS_REGISTRY).length).toBe(10)
  })
})
