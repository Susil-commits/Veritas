import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import DigitalCanvas, { type DigitalCanvasRef } from '../components/DigitalCanvas'
import MathText from '../components/MathText'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import { streamDiagnosis } from '../lib/api'
import type { Diagnosis, Problem, SessionData } from '../lib/api'
import { getSkillMeta } from '../lib/skillsData'
import {
  ArrowLeft,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  MessageSquare,
  HelpCircle,
  Lightbulb,
  ChevronDown,
  ChevronUp,
  Award,
} from 'lucide-react'
import './Scratchpad.css'

const DEFAULT_FALLBACK_PROBLEM: Problem = {
  id: 'scratchpad-default-prob',
  title: 'Two-Step Linear Equation',
  text: 'Solve for x: \\(3x + 7 = 22\\). Show each step clearly on the canvas.',
  skill_id: 'equations_linear_2step',
  difficulty: 2,
}

function sanitizeSessionForStorage(session: Record<string, unknown> | SessionData): Record<string, unknown> {
  const rest = { ...(session as Record<string, unknown>) }
  delete rest.latest_image_bytes
  delete rest.image
  return rest
}

export default function Scratchpad() {
  const navigate = useNavigate()
  const { user, role, avatar } = useAuth()
  const canvasRef = useRef<DigitalCanvasRef>(null)

  const [session, setSession] = useState<SessionData | null>(null)
  const [currentProblem, setCurrentProblem] = useState<Problem>(DEFAULT_FALLBACK_PROBLEM)
  const [isProblemCollapsed, setIsProblemCollapsed] = useState(false)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [thinkingSteps, setThinkingSteps] = useState<string[]>([])
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [hasStroke, setHasStroke] = useState(false)

  // Load existing session and current problem from sessionStorage
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('session')
      if (raw) {
        const parsed: SessionData = JSON.parse(raw)
        setSession(parsed)
        if (parsed.current_problem) {
          setCurrentProblem(parsed.current_problem)
        }
      }
    } catch (e) {
      console.error('Error loading session from storage in Scratchpad:', e)
    }
  }, [])

  const skillMeta = getSkillMeta(currentProblem.skill_id)

  const handleReturnToSession = () => {
    navigate('/student-session')
  }

  const handleClearDiagnosis = () => {
    setDiagnosis(null)
    setErrorMsg(null)
  }

  const handleCheckSteps = async () => {
    if (!canvasRef.current) return
    setErrorMsg(null)

    const blob = await canvasRef.current.getBlob()
    if (!blob) {
      setErrorMsg('Please write your math steps on the scratchpad canvas before checking.')
      return
    }

    const sessionId = session?.session_id || 'demo-scratchpad-session'
    const workFile = new File([blob], 'scratchpad_step_work.jpg', { type: 'image/jpeg' })

    setIsAnalyzing(true)
    setThinkingSteps([])
    setDiagnosis(null)

    streamDiagnosis(
      sessionId,
      workFile,
      (step: string) => {
        setThinkingSteps((prev) => [...prev, step])
      },
      (diag: Diagnosis, mastery: Record<string, number>, nextProb: Problem | null) => {
        setDiagnosis(diag)
        setIsAnalyzing(false)

        // If we have an active session, update it with new mastery & problem
        if (session) {
          const updated: SessionData = {
            ...session,
            current_problem: nextProb || session.current_problem,
            mastery_state: mastery || session.mastery_state,
          }
          setSession(updated)
          sessionStorage.setItem('session', JSON.stringify(sanitizeSessionForStorage(updated)))
        }
      },
      (err: Error) => {
        console.error('Scratchpad analysis error:', err)
        setIsAnalyzing(false)
        const msg = err?.message || ''
        if (msg.includes('429') || msg.includes('Rate limit')) {
          setErrorMsg('Tutor AI is busy. Please wait a few moments and try checking again.')
        } else {
          setErrorMsg('Could not verify handwriting steps. Please write clearly and try again.')
        }
      }
    )
  }

  const handleSendToTutorChat = () => {
    if (!diagnosis || !session) {
      navigate('/student-session')
      return
    }

    const corrective = diagnosis.corrective_question || "Let's review the steps you wrote on your scratchpad!"
    const tutorMsg = {
      role: 'tutor' as const,
      content: corrective,
      timestamp: new Date().toISOString(),
    }

    try {
      const chatKey = `veritas_chat_${session.session_id}`
      const existingRaw = sessionStorage.getItem(chatKey)
      const existing = existingRaw ? JSON.parse(existingRaw) : []
      existing.push(tutorMsg)
      sessionStorage.setItem(chatKey, JSON.stringify(existing))
    } catch (e) {
      console.error('Failed to append tutor message to chat storage:', e)
    }

    navigate('/student-session')
  }

  return (
    <div className="scratchpad-page">
      {/* ── Top Header ── */}
      <header className="scratchpad-header">
        <div className="scratchpad-header-left">
          <button
            type="button"
            className="btn btn-ghost btn-sm scratchpad-back-btn"
            onClick={handleReturnToSession}
            title="Return to Tutor Chat Session"
          >
            <ArrowLeft size={16} />
            <span>Return to Session</span>
          </button>
          <div className="scratchpad-brand" onClick={() => navigate('/')}>
            <span className="brand-logo">Veritas<span className="brand-dot">.</span></span>
            <span className="scratchpad-badge">Digital Scratchpad</span>
          </div>
        </div>

        <div className="scratchpad-header-center">
          <span className="scratchpad-topic-pill">
            <span className="topic-dot" />
            Topic: <strong>{skillMeta.title}</strong>
          </span>
        </div>

        <div className="scratchpad-header-right">
          <ThemeToggle />
          <div className="scratchpad-user-pill">
            <UserAvatar
              avatar={avatar}
              name={session?.student_name || user?.user_metadata?.name || 'Student'}
              role={role}
              size="xs"
            />
            <span className="user-name">{session?.student_name || 'Student'}</span>
          </div>
        </div>
      </header>

      {/* ── Main Workspace ── */}
      <main className="scratchpad-content">
        {/* Problem Card / Banner */}
        <div className="scratchpad-problem-card">
          <div className="problem-card-header">
            <div className="problem-meta-left">
              <span className="badge badge-violet">{skillMeta.grade}</span>
              <span className="problem-title-text">{currentProblem.title}</span>
              <div className="problem-diff-dots" title={`Difficulty: ${currentProblem.difficulty}/5`}>
                {Array.from({ length: 5 }).map((_, i) => (
                  <span key={i} className={`diff-dot ${i < currentProblem.difficulty ? 'active' : ''}`} />
                ))}
              </div>
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-xs problem-toggle-btn"
              onClick={() => setIsProblemCollapsed((prev) => !prev)}
              title={isProblemCollapsed ? 'Expand problem details' : 'Collapse problem details'}
            >
              {isProblemCollapsed ? (
                <>
                  <span>Show Problem</span>
                  <ChevronDown size={14} />
                </>
              ) : (
                <>
                  <span>Hide Details</span>
                  <ChevronUp size={14} />
                </>
              )}
            </button>
          </div>

          {!isProblemCollapsed && (
            <div className="problem-body animate-fadein">
              <div className="problem-prompt">
                <MathText content={currentProblem.text} />
              </div>
              <p className="problem-guidance">
                Write out each intermediate step clearly on the grid paper below with your stylus or mouse.
              </p>
            </div>
          )}
        </div>

        {/* Scratchpad Canvas Area */}
        <div className="scratchpad-canvas-card">
          <DigitalCanvas
            ref={canvasRef}
            height={520}
            onStrokeDrawn={() => setHasStroke(true)}
            disabled={isAnalyzing}
          />

          {/* Action Ribbon Under Canvas */}
          <div className="scratchpad-actions-bar">
            <div className="actions-left-hints">
              <HelpCircle size={15} />
              <span>Use stylus, mouse, or touch. Click <strong>Check My Steps</strong> when you want AI tutor feedback.</span>
            </div>

            <div className="actions-right-buttons">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  canvasRef.current?.clear()
                  setHasStroke(false)
                  setDiagnosis(null)
                  setErrorMsg(null)
                }}
                disabled={isAnalyzing}
                title="Reset drawing canvas"
              >
                <RotateCcw size={14} />
                <span>Clear Canvas</span>
              </button>

              <button
                type="button"
                className="btn btn-primary btn-sm check-steps-btn"
                onClick={handleCheckSteps}
                disabled={isAnalyzing || !hasStroke}
                title={hasStroke ? 'Analyze handwritten mathematical steps with Gemini Vision' : 'Draw your steps on the canvas first'}
              >
                <Sparkles size={16} className={isAnalyzing ? 'animate-spin' : ''} />
                <span>{isAnalyzing ? 'Checking Handwriting…' : '✨ Check My Steps'}</span>
              </button>
            </div>
          </div>
        </div>

        {/* Error Notification */}
        {errorMsg && (
          <div className="scratchpad-error-banner animate-fadein" role="alert">
            <AlertTriangle size={18} />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Real-time Thinking Trace */}
        {isAnalyzing && (
          <div className="scratchpad-thinking-card animate-fadein">
            <div className="thinking-spinner-row">
              <span className="thinking-pulse-dot" />
              <strong>Veritas Socratic Vision is analyzing your handwritten steps…</strong>
            </div>
            {thinkingSteps.length > 0 && (
              <div className="thinking-steps-list">
                {thinkingSteps.map((step, idx) => (
                  <div key={idx} className="thinking-step-item">
                    <span className="step-bullet">›</span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Diagnosis Result Card */}
        {diagnosis && (
          <div
            className={`scratchpad-diagnosis-card animate-fadein ${
              diagnosis.is_correct ? 'is-correct' : 'has-misconception'
            }`}
          >
            <div className="diagnosis-top-row">
              <div className="diagnosis-badge-row">
                {diagnosis.is_correct ? (
                  <div className="diagnosis-pill correct">
                    <CheckCircle2 size={16} />
                    <span>Correct Reasoning Demonstrated!</span>
                  </div>
                ) : (
                  <div className="diagnosis-pill incorrect">
                    <AlertTriangle size={16} />
                    <span>Misconception at Step {diagnosis.step_number || 1}</span>
                  </div>
                )}
                {diagnosis.misconception_type && !diagnosis.is_correct && (
                  <span className="badge badge-amber">
                    {diagnosis.misconception_type.replace(/_/g, ' ')}
                  </span>
                )}
              </div>

              <button
                type="button"
                className="btn btn-ghost btn-xs"
                onClick={handleClearDiagnosis}
                title="Dismiss result"
              >
                ✕ Close
              </button>
            </div>

            <div className="diagnosis-body">
              {diagnosis.is_correct ? (
                <div className="diagnosis-correct-content">
                  <p className="correct-title">
                    <Award size={20} className="award-icon" />
                    Fantastic work! Your mathematical steps are verified and conceptually sound.
                  </p>
                  {diagnosis.ocr_text && (
                    <div className="ocr-preview">
                      <span className="ocr-label">Recognized Steps:</span>
                      <code>{diagnosis.ocr_text}</code>
                    </div>
                  )}
                  <p className="correct-desc">
                    Ready to discuss this problem or move to the next challenge with your Socratic tutor?
                  </p>
                </div>
              ) : (
                <div className="diagnosis-error-content">
                  <div className="error-description">
                    <p><strong>What happened:</strong> {diagnosis.description}</p>
                    {diagnosis.ocr_text && (
                      <div className="ocr-preview">
                        <span className="ocr-label">Your written steps:</span>
                        <code>{diagnosis.ocr_text}</code>
                      </div>
                    )}
                  </div>

                  <div className="corrective-prompt-box">
                    <div className="prompt-header">
                      <Lightbulb size={16} />
                      <span>Socratic Guidance:</span>
                    </div>
                    <p className="prompt-text">
                      "{diagnosis.corrective_question || "Take another look at the last operation you performed on both sides."}"
                    </p>
                  </div>
                </div>
              )}
            </div>

            <div className="diagnosis-actions-row">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setDiagnosis(null)}
              >
                ✏️ Continue Drawing on Pad
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm return-tutor-btn"
                onClick={handleSendToTutorChat}
                title="Discuss this feedback with your tutor in the main chat"
              >
                <MessageSquare size={15} />
                <span>Return to Tutor Chat with this Step →</span>
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
