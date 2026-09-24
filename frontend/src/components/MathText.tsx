import React, { memo } from 'react'
import katex from 'katex'

interface MathTextProps {
  content: string
  className?: string
  inline?: boolean
}

/**
 * Render a single TeX string to safe HTML using KaTeX.
 */
function renderTeX(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, {
      displayMode,
      throwOnError: false,
      strict: false,
    })
  } catch {
    return tex
  }
}

/**
 * Normalizes over-escaped strings common in LLM JSON outputs and API serialization:
 * 1. Unescapes HTML entities (&amp;, &lt;, &gt;, &quot;, &#39;)
 * 2. Unescapes JSON-escaped quotes (\" -> ", \' -> ')
 * 3. Normalizes literal escaped newlines (\\n) when not part of TeX commands
 * 4. Normalizes multi-backslash sequences (\\\\ -> \) before LaTeX commands and delimiters
 */
function normalizeContent(raw: string): string {
  if (!raw) return ''
  let text = raw

  // 1. Unescape HTML entities
  text = text
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")

  // 2. Unescape escaped quotes from JSON strings
  text = text.replace(/\\"/g, '"').replace(/\\'/g, "'")

  // 3. Normalize literal escaped newlines (e.g. "\\n" -> "\n")
  text = text.replace(/\\\\n/g, '\n')
  text = text.replace(/(?<!\\)\\n/g, (match, offset, str) => {
    // Preserve TeX commands starting with \n like \neq, \notin, \nabla, \natural, \ne
    const nextChars = str.slice(offset + 2, offset + 6)
    if (/^(eq|otin|abla|atural|e\b)/.test(nextChars)) {
      return match
    }
    return '\n'
  })

  // 4. Normalize multi-backslashes (2 or more) before TeX delimiters and commands:
  // e.g. \\( -> \(, \\) -> \), \\[ -> \[, \\] -> \], \\frac -> \frac, \\times -> \times
  text = text.replace(/\\{2,}([a-zA-Z()[\]{}])/g, '\\$1')

  return text
}

function cleanLatexSymbols(s: string): string {
  return s
    .replace(/\\*times\b/g, '×')
    .replace(/\\*div\b/g, '÷')
    .replace(/\\*cdot\b/g, '·')
    .replace(/\\*pm\b/g, '±')
    .replace(/\\*neq\b/g, '≠')
    .replace(/\\*approx\b/g, '≈')
    .replace(/\\*le(?:q)?\b/g, '≤')
    .replace(/\\*ge(?:q)?\b/g, '≥')
    .replace(/\\*degree(?:s)?\b/g, '°')
    .replace(/\\*circ\b/g, '°')
}

/**
 * Parse and render markdown formatting (bold, italic, code) within a text segment.
 */
function renderMarkdownSegment(text: string, keyPrefix: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g)
  return (
    <React.Fragment key={keyPrefix}>
      {parts.map((part, idx) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return <strong key={`${keyPrefix}-b-${idx}`}>{cleanLatexSymbols(part.slice(2, -2))}</strong>
        }
        if (part.startsWith('*') && part.endsWith('*')) {
          return <em key={`${keyPrefix}-i-${idx}`}>{cleanLatexSymbols(part.slice(1, -1))}</em>
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return (
            <code
              key={`${keyPrefix}-c-${idx}`}
              className="math-inline-code"
            >
              {part.slice(1, -1)}
            </code>
          )
        }
        return cleanLatexSymbols(part)
      })}
    </React.Fragment>
  )
}

/**
 * Render inline text with inline math expressions ($...$, \(...\), \frac{...}{...}, \sqrt{...}).
 */
function renderInlineTextWithMath(line: string, lineKey: string): React.ReactNode {
  // Matches inline math: $...$, \(...\), \frac{...}{...}, \sqrt{...}
  const inlineRegex = /(\$[^$\n]+?\$|\\\([^\n]+?\\\)|\\[f]rac\{[^{}]+\}\{[^{}]+\}|\\[s]qrt\{[^{}]+\})/g
  const parts = line.split(inlineRegex)

  return parts.map((seg, idx) => {
    const key = `${lineKey}-p-${idx}`

    if (seg.startsWith('$') && seg.endsWith('$') && seg.length > 2) {
      const math = seg.slice(1, -1).trim()
      const html = renderTeX(math, false)
      return (
        <span
          key={key}
          className="math-inline"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )
    }

    if (seg.startsWith('\\(') && seg.endsWith('\\)')) {
      const math = seg.slice(2, -2).trim()
      const html = renderTeX(math, false)
      return (
        <span
          key={key}
          className="math-inline"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )
    }

    if ((seg.startsWith('\\frac{') && seg.includes('}{')) || seg.startsWith('\\sqrt{')) {
      const html = renderTeX(seg, false)
      return (
        <span
          key={key}
          className="math-inline"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )
    }

    return renderMarkdownSegment(seg, key)
  })
}

/**
 * MathText Component
 * Intelligently extracts mathematical expressions delimited by:
 * - $$ ... $$ (display math, including multiline)
 * - \[ ... \] (display math, including multiline)
 * - $ ... $ (inline math)
 * - \( ... \) (inline math)
 * - Common fraction/radical notations like \frac{a}{b} and \sqrt{x}
 *
 * Robustly normalizes over-escaping from LLM JSON responses and preserves markdown line breaks.
 */
export const MathText = memo(function MathText({ content, className = '', inline = false }: MathTextProps) {
  if (!content) return null

  // 1. Normalize over-escaping and HTML entities
  const normalized = normalizeContent(content)

  // 2. Extract block math ($$ ... $$ and \[ ... \]) first so multiline formulas are preserved
  const blockRegex = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\])/g
  const blockSegments = normalized.split(blockRegex)

  return (
    <span className={`math-text-container ${className}`}>
      {blockSegments.map((blockSeg, bIdx) => {
        const blockKey = `block-${bIdx}`

        // Display Math: $$ ... $$
        if (blockSeg.startsWith('$$') && blockSeg.endsWith('$$')) {
          const math = blockSeg.slice(2, -2).trim()
          const html = renderTeX(math, true)
          return (
            <span
              key={blockKey}
              className="math-display-block"
              style={{ display: 'block', margin: '0.5em 0', textAlign: 'center' }}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          )
        }

        // Display Math: \[ ... \]
        if (blockSeg.startsWith('\\[') && blockSeg.endsWith('\\]')) {
          const math = blockSeg.slice(2, -2).trim()
          const html = renderTeX(math, true)
          return (
            <span
              key={blockKey}
              className="math-display-block"
              style={{ display: 'block', margin: '0.5em 0', textAlign: 'center' }}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          )
        }

        // Non-block segment: split by line breaks to preserve formatting and handle inline math
        const lines = blockSeg.split('\n')
        return (
          <React.Fragment key={blockKey}>
            {lines.map((line, lineIdx) => (
              <React.Fragment key={`${blockKey}-l-${lineIdx}`}>
                {renderInlineTextWithMath(line, `${blockKey}-l-${lineIdx}`)}
                {!inline && lineIdx < lines.length - 1 && <br />}
              </React.Fragment>
            ))}
          </React.Fragment>
        )
      })}
    </span>
  )
})

export default MathText
