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

function cleanLatexSymbols(s: string): string {
  return s
    .replace(/\\times\b/g, '×')
    .replace(/\\div\b/g, '÷')
    .replace(/\\cdot\b/g, '·')
    .replace(/\\pm\b/g, '±')
    .replace(/\\neq\b/g, '≠')
    .replace(/\\approx\b/g, '≈')
    .replace(/\\le(?:q)?\b/g, '≤')
    .replace(/\\ge(?:q)?\b/g, '≥')
    .replace(/\\degree(?:s)?\b/g, '°')
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
 * MathText Component
 * Intelligently extracts mathematical expressions delimited by:
 * - $$ ... $$ (display math)
 * - $ ... $ (inline math)
 * - \( ... \) or \[ ... \]
 * - Common fraction notations like \frac{a}{b}
 *
 * And preserves standard markdown formatting and line breaks.
 */
export const MathText = memo(function MathText({ content, className = '', inline = false }: MathTextProps) {
  if (!content) return null

  // Split lines first to preserve line breaks
  const lines = content.split('\n')

  return (
    <span className={`math-text-container ${className}`}>
      {lines.map((line, lineIdx) => {
        // Match $$...$$, $...$, \[...\], \(...\), bare \frac{a}{b}, and bare \sqrt{x}
        const regex = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([^\n]+?\\\)|\\[f]rac\{[^{}]+\}\{[^{}]+\}|\\[s]qrt\{[^{}]+\})/g
        const segments = line.split(regex)

        const renderedLine = segments.map((seg, segIdx) => {
          const key = `line-${lineIdx}-seg-${segIdx}`

          if (seg.startsWith('$$') && seg.endsWith('$$')) {
            const math = seg.slice(2, -2).trim()
            const html = renderTeX(math, true)
            return (
              <span
                key={key}
                className="math-display-block"
                style={{ display: 'block', margin: '0.4em 0', textAlign: 'center' }}
                dangerouslySetInnerHTML={{ __html: html }}
              />
            )
          }

          if (seg.startsWith('\\[') && seg.endsWith('\\]')) {
            const math = seg.slice(2, -2).trim()
            const html = renderTeX(math, true)
            return (
              <span
                key={key}
                className="math-display-block"
                style={{ display: 'block', margin: '0.4em 0', textAlign: 'center' }}
                dangerouslySetInnerHTML={{ __html: html }}
              />
            )
          }

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

          // Plain text with markdown formatting
          return renderMarkdownSegment(seg, key)
        })

        return (
          <React.Fragment key={`line-${lineIdx}`}>
            {renderedLine}
            {!inline && lineIdx < lines.length - 1 && <br />}
          </React.Fragment>
        )
      })}
    </span>
  )
})

export default MathText
