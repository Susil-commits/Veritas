import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import MathText from './MathText'

describe('MathText', () => {
  it('preserves English words like times, pm, degrees, and approx without LaTeX corruption', () => {
    const { container } = render(
      <MathText content="Practice 3 times before 4 pm when it is 72 degrees or approx 20 minutes." />,
    )
    const content = container.textContent || ''
    expect(content).toContain('3 times before 4 pm')
    expect(content).toContain('72 degrees')
    expect(content).toContain('approx 20 minutes')
    expect(content).not.toContain('×')
    expect(content).not.toContain('±')
    expect(content).not.toContain('°')
    expect(content).not.toContain('≈')
  })

  it('keeps currency ranges plain text while rendering true inline LaTeX with KaTeX', () => {
    const { container: currency } = render(<MathText content="A notebook costs $1.50 and a pen costs $5.50." />)
    expect(currency.querySelector('.katex')).toBeNull()
    expect(currency.textContent).toContain('$1.50')
    expect(currency.textContent).toContain('$5.50')

    const { container: latex } = render(<MathText content="Solve $x + 3 = 7$ for $x$." />)
    expect(latex.querySelector('.katex')).not.toBeNull()
  })
})
