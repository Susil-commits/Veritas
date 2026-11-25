import { describe, it, expect } from 'vitest'
import { sanitizeHtml, escapeHtml } from './sanitizeHtml'

describe('sanitizeHtml', () => {
  it('strips script tags, event handlers, and srcdoc attributes', () => {
    const dirty =
      '<div onclick="alert(1)"><script>alert(2)</script><iframe srcdoc="<script>x</script>"></iframe><b onmouseover="evil()">Safe</b></div>'
    const clean = sanitizeHtml(dirty)
    expect(clean).not.toContain('<script')
    expect(clean).not.toContain('onclick')
    expect(clean).not.toContain('onmouseover')
    expect(clean).not.toContain('<iframe')
    expect(clean).not.toContain('srcdoc')
    expect(clean).toContain('<b>Safe</b>')
  })

  it('blocks entity-encoded javascript URIs and unsafe style expressions', () => {
    const dirty =
      '<a href="&#106;&#97;vascript:alert(1)">Click</a><span style="background:url(javascript:alert(1))">Styled</span>'
    const clean = sanitizeHtml(dirty)
    expect(clean.toLowerCase()).not.toContain('javascript:')
    expect(clean).not.toContain('style=')
    expect(clean).toContain('Click')
    expect(clean).toContain('Styled')
  })

  it('escapes plain HTML characters safely', () => {
    expect(escapeHtml(`<script>"&'</script>`)).toBe('&lt;script&gt;&quot;&amp;&#39;&lt;/script&gt;')
  })
})
