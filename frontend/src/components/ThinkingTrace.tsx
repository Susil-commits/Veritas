import './ThinkingTrace.css'

interface Props {
  steps: string[]
  isActive: boolean
}

export default function ThinkingTrace({ steps, isActive }: Props) {
  return (
    <div className="thinking-trace">
      <h4>
        Veritas Status
        {isActive && (
          <span className="thinking-dot">
            <span /><span /><span />
          </span>
        )}
      </h4>
      {steps.length === 0 && (
        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          Waiting for input…
        </p>
      )}
      {steps.map((step, i) => (
        <div key={i} className="thinking-step">
          {step}
        </div>
      ))}
    </div>
  )
}
