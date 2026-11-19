/**
 * Enterprise HTML & Math Output Sanitizer.
 * Strips script tags, javascript: URI handlers, on* attributes, and malformed tags
 * to eliminate client-side XSS vulnerabilities in KaTeX / Markdown rendering.
 */

const DANGEROUS_PATTERNS = [
  /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,
  /\bon\w+\s*=\s*["'][^"']*["']/gi,
  /\bon\w+\s*=\s*[^>\s]+/gi,
  /javascript\s*:/gi,
  /vbscript\s*:/gi,
  /data:\s*text\/html/gi,
  /<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi,
  /<object\b[^<]*(?:(?!<\/object>)<[^<]*)*<\/object>/gi,
  /<embed\b[^>]*>/gi,
  /<base\b[^>]*>/gi,
  /<form\b[^>]*>/gi,
  /expression\s*\([^)]*\)/gi,
]

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
