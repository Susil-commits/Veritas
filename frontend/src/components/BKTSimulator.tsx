import { useState, useMemo } from 'react'
import MathText from './MathText'
import { Sparkles, RotateCcw, CheckCircle2, AlertCircle, HelpCircle } from 'lucide-react'
import './BKTSimulator.css'

interface SkillDefinition {
  id: string
  name: string
  prior: number
  learn: number
  guess: number
  slip: number
  calibrated: boolean
  source: string
}

const BKT_SKILLS: SkillDefinition[] = [
  { id: '3.OA.A.1', name: 'Understanding Multiplication', prior: 0.3, learn: 0.15, guess: 0.2, slip: 0.1, calibrated: false, source: 'Corbett & Anderson Baseline' },
  { id: '3.OA.A.2', name: 'Understanding Division', prior: 0.25, learn: 0.15, guess: 0.2, slip: 0.1, calibrated: false, source: 'Corbett & Anderson Baseline' },
  { id: '3.OA.D.8', name: 'Two-Step Word Problems', prior: 0.2, learn: 0.12, guess: 0.18, slip: 0.12, calibrated: false, source: 'Corbett & Anderson Baseline' },
  { id: '4.NF.A.1', name: 'Equivalent Fractions', prior: 0.4, learn: 0.08, guess: 0.22, slip: 0.14, calibrated: true, source: 'ASSISTments 2009-2010 MLE Fit' },
  { id: '4.NF.B.3', name: 'Adding & Subtracting Fractions', prior: 0.4, learn: 0.2, guess: 0.18, slip: 0.14, calibrated: true, source: 'ASSISTments 2009-2010 MLE Fit' },
  { id: '4.NF.B.4', name: 'Multiplying Fractions by Whole Numbers', prior: 0.4, learn: 0.12, guess: 0.26, slip: 0.14, calibrated: true, source: 'ASSISTments 2009-2010 MLE Fit' },
  { id: '5.NF.B.7', name: 'Dividing Fractions & Whole Numbers', prior: 0.4, learn: 0.24, guess: 0.26, slip: 0.14, calibrated: true, source: 'ASSISTments 2009-2010 MLE Fit' },
  { id: '6.EE.A.2', name: 'Evaluating Algebraic Expressions', prior: 0.3, learn: 0.15, guess: 0.2, slip: 0.12, calibrated: false, source: 'Corbett & Anderson Baseline' },
  { id: '6.EE.B.7', name: 'Solving One-Step Equations', prior: 0.35, learn: 0.08, guess: 0.26, slip: 0.14, calibrated: true, source: 'ASSISTments 2009-2010 MLE Fit' },
  { id: '7.EE.B.4', name: 'Solving Multi-Step Equations', prior: 0.4, learn: 0.24, guess: 0.26, slip: 0.14, calibrated: true, source: 'ASSISTments 2009-2010 MLE Fit' },
]

interface StepCalculation {
  pL: number
  pLNext: number
  actionType: string
  pObsKnowing: number
  pObsNotKnowing: number
  pObsTotal: number
  pLGivenObsRaw: number
  pLGivenObsDiscounted: number
  weight: number
  delta: number
}

export default function BKTSimulator() {
  const [selectedSkillId, setSelectedSkillId] = useState('4.NF.B.3')
  const skill = useMemo(() => BKT_SKILLS.find((s) => s.id === selectedSkillId) || BKT_SKILLS[4], [selectedSkillId])

  const [currentPL, setCurrentPL] = useState<number>(skill.prior)
  const [history, setHistory] = useState<{ step: number; action: string; from: number; to: number }[]>([])
  const [lastCalc, setLastCalc] = useState<StepCalculation | null>(null)

  const handleSkillChange = (id: string) => {
    setSelectedSkillId(id)
    const newSkill = BKT_SKILLS.find((s) => s.id === id) || BKT_SKILLS[0]
    setCurrentPL(newSkill.prior)
    setHistory([])
    setLastCalc(null)
  }

  const simulateTurn = (action: 'independent_correct' | 'hinted_correct' | 'feedback_correct' | 'incorrect') => {
    const pL = currentPL
    const pT = skill.learn
    const pG = skill.guess
    const pS = skill.slip

    let pObsKnowing = 0
    let pObsNotKnowing = 0
    let weight = 1.0
    let actionLabel = ''

    if (action === 'independent_correct') {
      pObsKnowing = 1 - pS
      pObsNotKnowing = pG
      weight = 1.0
      actionLabel = 'Independent Correct (w=1.0)'
    } else if (action === 'hinted_correct') {
      pObsKnowing = 1 - pS
      pObsNotKnowing = pG
      weight = 0.6
      actionLabel = 'Hint-Assisted Correct (w=0.6)'
    } else if (action === 'feedback_correct') {
      pObsKnowing = 1 - pS
      pObsNotKnowing = pG
      weight = 0.5
      actionLabel = 'Feedback-Assisted Correct (w=0.5)'
    } else {
      pObsKnowing = pS
      pObsNotKnowing = 1 - pG
      weight = 1.0
      actionLabel = 'Incorrect Response'
    }

    const pObsTotal = pL * pObsKnowing + (1 - pL) * pObsNotKnowing
    const pLGivenObsRaw = pObsTotal > 0 ? (pL * pObsKnowing) / pObsTotal : pL

    // Pedagogical weighting
    let pLGivenObsDiscounted = pLGivenObsRaw
    if (action === 'feedback_correct') {
      pLGivenObsDiscounted = pL + 0.5 * (pLGivenObsRaw - pL)
    } else if (action === 'hinted_correct') {
      pLGivenObsDiscounted = pL + 0.6 * (pLGivenObsRaw - pL)
    }

    // Knowledge transition
    const pLNextRaw = pLGivenObsDiscounted + (1 - pLGivenObsDiscounted) * pT
    const pLNext = Math.round(Math.min(1.0, Math.max(0.0, pLNextRaw)) * 1000) / 1000
    const delta = Math.round((pLNext - pL) * 1000) / 1000

    const calc: StepCalculation = {
      pL,
      pLNext,
      actionType: actionLabel,
      pObsKnowing,
      pObsNotKnowing,
      pObsTotal: Math.round(pObsTotal * 1000) / 1000,
      pLGivenObsRaw: Math.round(pLGivenObsRaw * 1000) / 1000,
      pLGivenObsDiscounted: Math.round(pLGivenObsDiscounted * 1000) / 1000,
      weight,
      delta,
    }

    setLastCalc(calc)
    setCurrentPL(pLNext)
    setHistory((prev) => [
      ...prev,
      { step: prev.length + 1, action: actionLabel, from: pL, to: pLNext },
    ])
  }

  const handleReset = () => {
    setCurrentPL(skill.prior)
    setHistory([])
    setLastCalc(null)
  }

  return (
    <div className="bkt-simulator-card animate-fadein">
      <div className="bkt-sim-header">
        <div className="bkt-sim-title-group">
          <div className="bkt-sim-badge">
            <Sparkles size={14} />
            <span>ADAPTIVE LEARNING MODEL</span>
          </div>
          <h3 className="bkt-sim-title">Adaptive Skill Growth &amp; Mastery Simulator</h3>
          <p className="bkt-sim-subtitle">
            See how Veritas estimates student mastery in real time as they practice, solve math problems independently, or learn with guided hints.
          </p>
        </div>

        <button type="button" className="bkt-reset-btn" onClick={handleReset} title="Reset mastery level to baseline">
          <RotateCcw size={14} />
          <span>Reset to Baseline</span>
        </button>
      </div>

      {/* Skill Selector */}
      <div className="bkt-skill-select-row">
        <label htmlFor="bkt-skill-select" className="bkt-label">Curriculum Skill Standard:</label>
        <select
          id="bkt-skill-select"
          className="bkt-select"
          value={selectedSkillId}
          onChange={(e) => handleSkillChange(e.target.value)}
        >
          {BKT_SKILLS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id}: {s.name} {s.calibrated ? '★ [Calibrated Benchmark]' : '[Curriculum Baseline]'}
            </option>
          ))}
        </select>
      </div>

      {/* Model Parameters Grid */}
      <div className="bkt-params-grid">
        <div className="bkt-param-box">
          <span className="param-symbol">P(L₀)</span>
          <span className="param-name">Starting Knowledge</span>
          <span className="param-value">{(skill.prior * 100).toFixed(0)}%</span>
        </div>
        <div className="bkt-param-box">
          <span className="param-symbol">P(T)</span>
          <span className="param-name">Learning Pace</span>
          <span className="param-value">{(skill.learn * 100).toFixed(0)}%</span>
        </div>
        <div className="bkt-param-box">
          <span className="param-symbol">P(G)</span>
          <span className="param-name">Lucky Guess Chance</span>
          <span className="param-value">{(skill.guess * 100).toFixed(0)}%</span>
        </div>
        <div className="bkt-param-box">
          <span className="param-symbol">P(S)</span>
          <span className="param-name">Accidental Slip Rate</span>
          <span className="param-value">{(skill.slip * 100).toFixed(0)}%</span>
        </div>
      </div>

      {/* Live Probability Gauge */}
      <div className="bkt-gauge-card">
        <div className="gauge-header">
          <span className="gauge-label">ESTIMATED CURRENT MASTERY LEVEL:</span>
          <div className="gauge-value-display">
            <span className="gauge-pct">{(currentPL * 100).toFixed(1)}%</span>
            {lastCalc && (
              <span className={`gauge-delta ${lastCalc.delta >= 0 ? 'positive' : 'negative'}`}>
                {lastCalc.delta >= 0 ? `+${(lastCalc.delta * 100).toFixed(1)}%` : `${(lastCalc.delta * 100).toFixed(1)}%`}
              </span>
            )}
          </div>
        </div>

        <div className="bkt-progress-bar-bg">
          <div
            className={`bkt-progress-bar-fill ${
              currentPL >= 0.7 ? 'mastered' : currentPL >= 0.4 ? 'developing' : 'emerging'
            }`}
            style={{ width: `${Math.min(100, Math.max(2, currentPL * 100))}%` }}
          />
        </div>

        <div className="gauge-scale-ticks">
          <span>0% (Emerging)</span>
          <span>40% (Developing)</span>
          <span>70% (Mastered Threshold)</span>
          <span>100%</span>
        </div>
      </div>

      {/* Simulation Trigger Buttons */}
      <div className="bkt-actions-section">
        <span className="bkt-label">Simulate Next Student Practice Attempt:</span>
        <div className="bkt-btn-row">
          <button
            type="button"
            className="sim-action-btn correct-independent"
            onClick={() => simulateTurn('independent_correct')}
          >
            <CheckCircle2 size={16} />
            <div>
              <strong>Independent Correct</strong>
              <small>Solved fully on own</small>
            </div>
          </button>

          <button
            type="button"
            className="sim-action-btn correct-hinted"
            onClick={() => simulateTurn('hinted_correct')}
          >
            <HelpCircle size={16} />
            <div>
              <strong>Hint-Assisted Correct</strong>
              <small>Guided Socratic hint</small>
            </div>
          </button>

          <button
            type="button"
            className="sim-action-btn correct-feedback"
            onClick={() => simulateTurn('feedback_correct')}
          >
            <Sparkles size={16} />
            <div>
              <strong>Correct After Feedback</strong>
              <small>Learned from explanation</small>
            </div>
          </button>

          <button
            type="button"
            className="sim-action-btn incorrect"
            onClick={() => simulateTurn('incorrect')}
          >
            <AlertCircle size={16} />
            <div>
              <strong>Needs Another Try</strong>
              <small>Learning opportunity</small>
            </div>
          </button>
        </div>
      </div>

      {/* Step-by-Step Bayesian Calculation Math Card */}
      {lastCalc && (
        <div className="bkt-math-breakdown animate-fadein">
          <div className="math-breakdown-title">
            <span>Adaptive Model Derivation (Evidence Update + Learning Transition)</span>
            <span className="math-source-badge">{skill.source}</span>
          </div>

          <div className="math-steps-list">
            <div className="math-step-item">
              <span className="step-num">Step 1</span>
              <div className="step-content">
                <strong>Likelihood Calculation P(Obs):</strong>
                <MathText
                  content={
                    '$$P(\\text{Obs}) = P(L_t) \\cdot P(\\text{Obs}|L) + (1 - P(L_t)) \\cdot P(\\text{Obs}|\\neg L) = ' +
                    lastCalc.pObsTotal +
                    '$$'
                  }
                />
              </div>
            </div>

            <div className="math-step-item">
              <span className="step-num">Step 2</span>
              <div className="step-content">
                <strong>Updated Understanding P(L_t | Obs):</strong>
                <MathText
                  content={
                    '$$P(L_t|\\text{Obs}) = \\frac{P(L_t) \\cdot P(\\text{Obs}|L)}{P(\\text{Obs})} = ' +
                    lastCalc.pLGivenObsRaw.toFixed(3) +
                    '$$'
                  }
                />
                {lastCalc.weight < 1.0 && (
                  <p className="discount-note">
                    ⚡ Guided Practice Credit applied: calibrated to <strong>{(lastCalc.pLGivenObsDiscounted).toFixed(3)}</strong> to accurately reward assisted practice.
                  </p>
                )}
              </div>
            </div>

            <div className="math-step-item">
              <span className="step-num">Step 3</span>
              <div className="step-content">
                <strong>Projected Mastery State P(L_t+1):</strong>
                <MathText
                  content={
                    '$$P(L_{t+1}) = P(L_t|\\text{Obs}) + (1 - P(L_t|\\text{Obs})) \\cdot P(T) = ' +
                    lastCalc.pLNext.toFixed(3) +
                    '$$'
                  }
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* History timeline */}
      {history.length > 0 && (
        <div className="bkt-history-drawer">
          <span className="history-label">Session Practice History:</span>
          <div className="history-chips">
            {history.map((h) => (
              <span key={h.step} className="history-chip">
                #{h.step}: {h.action.split(' ')[0]} ({(h.from * 100).toFixed(0)}% → {(h.to * 100).toFixed(0)}%)
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
