/**
 * Enterprise HTML & Math Output Sanitizer.
 * Uses DOM-based sanitization in browser environments (with regex fallback for non-DOM runtimes)
 * to strip dangerous tags, event handlers, and unsafe URI schemes from KaTeX / Markdown HTML.
 */

const DANGEROUS_TAGS = new Set([
  'script',
  'iframe',
  'object',
  'embed',
  'base',
  'form',
  'style',
  'link',
  'meta',
  'template',
  'noscript',
])

const URI_ATTRS = new Set(['href', 'src', 'xlink:href', 'action', 'formaction', 'data'])

const DANGEROUS_PATTERNS = [
  /<script\b[^>]*>[\s\S]*?<\/script>/gi,
  /<script\b[^>]*\/?>/gi,
  /<iframe\b[^>]*>[\s\S]*?<\/iframe>/gi,
  /<iframe\b[^>]*\/?>/gi,
  /<object\b[^>]*>[\s\S]*?<\/object>/gi,
  /<style\b[^>]*>[\s\S]*?<\/style>/gi,
  /<(?:embed|base|form|link|meta|template)\b[^>]*>/gi,
  /\bon\w+\s*=\s*(?:"[^"]*"|'[^']*'|`[^`]*`|[^\s>]+)/gi,
  /javascript\s*:/gi,
  /vbscript\s*:/gi,
  /data:\s*text\/html/gi,
  /expression\s*\([^)]*\)/gi,
]

function isUnsafeUri(rawValue: string): boolean {
  // Decode basic HTML entities and strip whitespace/control chars before scheme inspection
  const normalized = rawValue
    .replace(/&#x([0-9a-f]+);?/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/&#(\d+);?/g, (_, dec) => String.fromCharCode(parseInt(dec, 10)))
  const decoded = Array.from(normalized)
    .filter((ch) => ch.charCodeAt(0) > 32)
    .join('')
    .toLowerCase()
  return (
    decoded.startsWith('javascript:') ||
    decoded.startsWith('vbscript:') ||
    decoded.startsWith('data:text/html')
  )
}

export function escapeHtml(str: string): string {
  if (!str) return ''
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function sanitizeHtml(htmlString: string): string {
  if (!htmlString) return ''

  if (typeof DOMParser !== 'undefined') {
    try {
      const doc = new DOMParser().parseFromString(htmlString, 'text/html')
      const elements = Array.from(doc.body.querySelectorAll('*'))
      for (const el of elements) {
        const tag = el.tagName.toLowerCase()
        if (DANGEROUS_TAGS.has(tag)) {
          el.remove()
          continue
        }
        for (const attr of Array.from(el.attributes)) {
          const name = attr.name.toLowerCase()
          const val = attr.value
          if (name.startsWith('on') || name === 'srcdoc') {
            el.removeAttribute(attr.name)
          } else if (URI_ATTRS.has(name) && isUnsafeUri(val)) {
            el.removeAttribute(attr.name)
          } else if (name === 'style' && /(?:expression\s*\(|javascript\s*:|vbscript\s*:|url\s*\(\s*['"]?\s*(?:javascript|vbscript|data:text\/html))/i.test(val)) {
            el.removeAttribute(attr.name)
          }
        }
      }
      return doc.body.innerHTML
    } catch {
      // Fall through to regex sanitization if DOMParser fails
    }
  }

  let clean = htmlString
  let prev = ''
  // Fixed-point loop to defeat nested bypass attempts (e.g., <scr<script>ipt>)
  let iterations = 0
  while (clean !== prev && iterations < 5) {
    prev = clean
    for (const pattern of DANGEROUS_PATTERNS) {
      clean = clean.replace(pattern, '')
    }
    iterations++
  }
  return clean
}
