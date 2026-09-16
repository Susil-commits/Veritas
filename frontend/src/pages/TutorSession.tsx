import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { streamMessage, startSession, fetchNextProblem, resetSession } from '../lib/api'
import { useSpeechInput, useTTS } from '../hooks/useVoice'
import { useAuth } from '../context/AuthContext'
import WorkUpload from '../components/WorkUpload'
import ThinkingTrace from '../components/ThinkingTrace'
import MasteryRadar from '../components/MasteryRadar'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import AvatarModal from '../components/AvatarModal'
import { getSkillMeta } from '../lib/skillsData'
import type { SessionData, Problem, Diagnosis } from '../lib/api'
import './TutorSession.css'

interface Message {
  role: 'student' | 'tutor' | 'system'
  content: string
  timestamp: Date
}

function cleanProblemTitle(title?: string): string {
  if (!title) return ''
  return title.replace(/^GSM8K:\s*/i, '').trim()
}

function formatSkillName(id: string): string {
  if (!id) return 'Math Practice'
  const meta = getSkillMeta(id)
  if (meta && meta.title && meta.title !== id) return meta.title
  const map: Record<string, string> = {
    fractions_add_unlike: 'Adding Fractions',
    fractions_multiply: 'Multiplying Fractions',
    equations_linear_1step: '1-Step Equations',
    equations_linear_2step: '2-Step Equations',
    word_problems_ratios: 'Ratios & Proportions',
    geometry_area_perimeter: 'Area & Perimeter',
    '3.OA.A.1': 'Understanding Multiplication',
    '3.OA.A.2': 'Understanding Division',
    '3.OA.D.8': 'Two-Step Word Problems',
    '4.NF.A.1': 'Equivalent Fractions',
    '4.NF.B.3': 'Adding & Subtracting Fractions',
    '4.NF.B.4': 'Multiplying Fractions by Whole Numbers',
    '5.NF.B.7': 'Dividing Fractions & Whole Numbers',
    '6.EE.A.2': 'Evaluating Algebraic Expressions',
    '6.EE.B.7': 'Solving One-Step Equations',
    '7.EE.B.4': 'Solving Multi-Step Equations',
  }
  if (map[id]) return map[id]
  return id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function renderMessageContent(content: string) {
  if (!content?.trim()) return <span className="typing">…</span>
  const lines = content.split('\n')
  return lines.map((line, lineIdx) => {
    const parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g)
    return (
      <span key={lineIdx}>
        {parts.map((part, partIdx) => {
          if (part.startsWith('**') && part.endsWith('**')) {
            return <strong key={partIdx}>{part.slice(2, -2)}</strong>
          }
          if (part.startsWith('*') && part.endsWith('*')) {
            return <em key={partIdx}>{part.slice(1, -1)}</em>
          }
          if (part.startsWith('`') && part.endsWith('`')) {
            return <code key={partIdx} style={{ background: 'rgba(255,255,255,0.1)', padding: '1px 4px', borderRadius: '4px' }}>{part.slice(1, -1)}</code>
          }
          return part
        })}
        {lineIdx < lines.length - 1 && <br />}
      </span>
    )
  })
}

export default function TutorSession() {
  const navigate = useNavigate()
  const { user, signOut, role, avatar, updateAvatar, loading: authLoading } = useAuth()
  const [showAvatarModal, setShowAvatarModal] = useState(false)
  const [session, setSession] = useState<SessionData | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [thinkingSteps, setThinkingSteps] = useState<string[]>([])
  const [masteryState, setMasteryState] = useState<Record<string, number>>({})
  const [currentProblem, setCurrentProblem] = useState<Problem | null>(null)
  const [problemSolved, setProblemSolved] = useState(false)
  const [isLoadingNextProblem, setIsLoadingNextProblem] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [sessionRetryCount, setSessionRetryCount] = useState(0)
  const [mobileTab, setMobileTab] = useState<'chat' | 'problem' | 'progress'>('chat')
  const [showResetModal, setShowResetModal] = useState(false)
  const [isResetting, setIsResetting] = useState(false)
  const [copiedCode, setCopiedCode] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const { isSpeaking, speak, stop } = useTTS()
  // Stabilize `speak` ref to prevent session init from re-running on every TTS state change
  const speakRef = useRef(speak)
  useEffect(() => { speakRef.current = speak }, [speak])
  const stableSpeak = useCallback((text: string) => speakRef.current(text), [])
  const { isListening, interimText, startListening, stopListening, isSupported } = useSpeechInput(
    (text) => { setInput(text) }
  )

  const handleCopyCode = useCallback(() => {
    const code = session?.student_id || ''
    if (!code) return
    navigator.clipboard.writeText(code)
    setCopiedCode(true)
    setTimeout(() => setCopiedCode(false), 2000)
  }, [session?.student_id])

  const handleResetProgress = useCallback(async () => {
    if (!session?.student_id) return
    setIsResetting(true)
    try {
      const fresh = await resetSession(session.student_id, session.session_id)
      if (session?.session_id) {
        sessionStorage.removeItem(`veritas_chat_${session.session_id}`)
      }
      sessionStorage.setItem('session', JSON.stringify(fresh))
      setSession(fresh)
      setCurrentProblem(fresh.current_problem)
      setMasteryState(fresh.mastery_state || {})
      setProblemSolved(false)
      setMessages([
        { role: 'system', content: `Progress reset for ${fresh.student_name}`, timestamp: new Date() },
        { role: 'tutor', content: fresh.welcome_message, timestamp: new Date() },
      ])
      setShowResetModal(false)
      stableSpeak(fresh.welcome_message)
    } catch (err) {
      console.error('Failed to reset session:', err)
      alert('Could not reset progress right now. Please try again.')
    } finally {
      setIsResetting(false)
    }
  }, [session?.student_id, session?.session_id, stableSpeak])

  const [warmupBadge, setWarmupBadge] = useState<{ score: number; total: number } | null>(() => {
    try {
      const rawBadge = sessionStorage.getItem('veritas_warmup_badge')
      if (rawBadge) {
        sessionStorage.removeItem('veritas_warmup_badge')
        const data = JSON.parse(rawBadge)
        if (data && typeof data.score === 'number') {
          return { score: data.score, total: data.total }
        }
      }
    } catch {}
    return null
  })

  useEffect(() => {
    if (!warmupBadge) return
    const t = setTimeout(() => setWarmupBadge(null), 3500)
    return () => clearTimeout(t)
  }, [warmupBadge])

  // Load session from sessionStorage or initialize from logged-in user
  useEffect(() => {
    let mounted = true

    async function initSession() {
      if (authLoading) return
      setSessionError(null)
      const raw = sessionStorage.getItem('session')
      if (raw) {
        try {
          const s: SessionData = JSON.parse(raw)
          if (s && s.session_id) {
            // Only reuse the cached session if it explicitly belongs to the current user
            if (user && s.student_id && s.student_id === user.id) {
              setSession(s)
              document.title = `Veritas — Math Practice (${s.student_name})`
              setMasteryState(s.mastery_state || {})
              setCurrentProblem(s.current_problem || null)
              // Rehydrate chat history if reloading an active session
              const savedChatRaw = sessionStorage.getItem(`veritas_chat_${s.session_id}`)
              if (savedChatRaw) {
                try {
                  const savedChat = JSON.parse(savedChatRaw)
                  if (Array.isArray(savedChat) && savedChat.length > 0) {
                    setMessages(savedChat.map((m: any) => ({
                      ...m,
                      timestamp: new Date(m.timestamp),
                    })))
                    return
                  }
                } catch {}
              }

              setMessages([
                { role: 'system', content: `Session started for ${s.student_name}`, timestamp: new Date() },
                { role: 'tutor', content: s.welcome_message, timestamp: new Date() },
              ])
              stableSpeak(s.welcome_message)
              return
            } else {
              // Mismatched or unauthenticated cached session token: purge to prevent token reuse
              sessionStorage.removeItem('session')
            }
          }
        } catch {}
      }

      // If user is authenticated, start session directly with their user.id
      if (user) {
        const studentName = user.user_metadata?.name || user.email?.split('@')[0] || 'Student'
        return startSession(studentName, user.id, user.email)
          .then((s) => {
            if (!mounted) return
            sessionStorage.setItem('session', JSON.stringify(s))
            setSession(s)
            document.title = `Veritas — Math Practice (${s.student_name})`
            setMasteryState(s.mastery_state || {})
            setCurrentProblem(s.current_problem || null)
            setMessages([
              { role: 'system', content: `Session started for ${s.student_name}`, timestamp: new Date() },
              { role: 'tutor', content: s.welcome_message, timestamp: new Date() },
            ])
            stableSpeak(s.welcome_message)
          })
          .catch((e) => {
            console.error('Could not auto-start session:', e)
            if (mounted) {
              setSessionError('Could not start your tutoring session right now. Please try again.')
            }
          })
      }

      if (mounted) {
        navigate('/')
      }
    }

    initSession().catch((e) => {
      console.error('initSession unexpected error:', e)
    })
    return () => { mounted = false }
  }, [navigate, user, authLoading, stableSpeak, sessionRetryCount])

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Persist conversation messages for session reload resilience
  useEffect(() => {
    if (session?.session_id && messages.length > 0) {
      try {
        sessionStorage.setItem(`veritas_chat_${session.session_id}`, JSON.stringify(messages))
      } catch {}
    }
  }, [session?.session_id, messages])

  const sendMessage = useCallback(() => {
    if (!input.trim() || !session || isStreaming) return
    const userMsg: Message = { role: 'student', content: input.trim(), timestamp: new Date() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setThinkingSteps([])
    setIsStreaming(true)

    let responseAcc = ''
    const botMsg: Message = { role: 'tutor', content: '', timestamp: new Date() }

    setMessages(prev => [...prev, botMsg])

    streamMessage(
      session.session_id,
      userMsg.content,
      (step) => setThinkingSteps(prev => [...prev, step]),
      (text, _done) => {
        responseAcc = text
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = { ...botMsg, content: text }
          return updated
        })
      },
      (newMastery, solved) => {
        if (newMastery && Object.keys(newMastery).length) {
          setMasteryState(newMastery)
          setSession(prev => {
            if (!prev) return prev
            const updated = { ...prev, mastery_state: newMastery }
            sessionStorage.setItem('session', JSON.stringify(updated))
            return updated
          })
        }
        if (solved) setProblemSolved(true)
        setIsStreaming(false)
        if (responseAcc) stableSpeak(responseAcc)
      },
      (_err) => {
        setIsStreaming(false)
        const errorContent = "I had trouble connecting just now. Please try sending your message again!"
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = { ...botMsg, content: errorContent }
          return updated
        })
      },
    )
  }, [input, session, isStreaming, stableSpeak])

  const handleRequestHint = useCallback(() => {
    if (!session || isStreaming) return
    const hintPrompt = "I'm feeling a bit stuck on this step. Can you give me a small guiding hint to help me think about the first step without telling me the answer?"
    const userMsg: Message = { role: 'student', content: "I'm stuck. Can I get a hint?", timestamp: new Date() }
    setMessages(prev => [...prev, userMsg])
    setThinkingSteps([])
    setIsStreaming(true)

    let responseAcc = ''
    const botMsg: Message = { role: 'tutor', content: '', timestamp: new Date() }
    setMessages(prev => [...prev, botMsg])

    streamMessage(
      session.session_id,
      hintPrompt,
      (step) => setThinkingSteps(prev => [...prev, step]),
      (text, _done) => {
        responseAcc = text
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = { ...botMsg, content: text }
          return updated
        })
      },
      (newMastery, solved) => {
        if (newMastery && Object.keys(newMastery).length) {
          setMasteryState(newMastery)
          setSession(prev => {
            if (!prev) return prev
            const updated = { ...prev, mastery_state: newMastery }
            sessionStorage.setItem('session', JSON.stringify(updated))
            return updated
          })
        }
        if (solved) setProblemSolved(true)
        setIsStreaming(false)
        if (responseAcc) stableSpeak(responseAcc)
      },
      (_err) => {
        setIsStreaming(false)
        const errorContent = "I had trouble connecting just now. Please try requesting a hint again!"
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = { ...botMsg, content: errorContent }
          return updated
        })
      },
    )
  }, [session, isStreaming, stableSpeak])

  const handleNextProblem = useCallback(async (markCorrect?: boolean) => {
    if (!session?.session_id || isLoadingNextProblem) return
    setIsLoadingNextProblem(true)
    const shouldCredit = typeof markCorrect === 'boolean' ? markCorrect : problemSolved
    try {
      const res = await fetchNextProblem(session.session_id, shouldCredit)
      if (res && res.current_problem) {
        setCurrentProblem(res.current_problem)
        setMasteryState(res.mastery_state || {})
        setProblemSolved(false)
        const updatedSession: SessionData = {
          ...session,
          current_problem: res.current_problem,
          mastery_state: res.mastery_state || session.mastery_state,
        }
        setSession(updatedSession)
        sessionStorage.setItem('session', JSON.stringify(updatedSession))
        const tutorMsg: Message = {
          role: 'tutor',
          content: res.tutor_message,
          timestamp: new Date(),
        }
        setMessages(prev => [...prev, tutorMsg])
        stableSpeak(res.tutor_message)
      }
    } catch (err) {
      console.error('Failed to fetch next problem:', err)
    } finally {
      setIsLoadingNextProblem(false)
    }
  }, [session, isLoadingNextProblem, problemSolved, stableSpeak])

  const handleDiagnosis = (d: Diagnosis, mastery: Record<string, number>, next: Problem | null) => {
    setMasteryState(mastery)
    if (next) {
      setCurrentProblem(next)
      setProblemSolved(false)
    }
    if (session) {
      const updatedSession: SessionData = {
        ...session,
        current_problem: next || session.current_problem,
        mastery_state: mastery,
      }
      setSession(updatedSession)
      sessionStorage.setItem('session', JSON.stringify(updatedSession))
    }
    const tutorMsg: Message = { role: 'tutor', content: d.corrective_question, timestamp: new Date() }
    setMessages(prev => [...prev, tutorMsg])
    stableSpeak(d.corrective_question)
  }

  const masterySkills = Object.entries(masteryState).map(([skill_id, prob]) => {
    const meta = getSkillMeta(skill_id)
    return {
      skill_id,
      name: meta.title,
      mastery_prob: prob,
    }
  })

  if (!session) {
    if (sessionError) {
      return (
        <div className="session-error-container">
          <div className="session-error-card">
            <span className="session-error-icon">⚠️</span>
            <h3>Session Connection Error</h3>
            <p>{sessionError}</p>
            <div className="session-error-actions">
              <button
                className="btn btn-violet"
                onClick={() => setSessionRetryCount(c => c + 1)}
              >
                Retry Starting Session
              </button>
              <button
                className="btn btn-ghost"
                onClick={() => navigate('/')}
              >
                Back to Home
              </button>
            </div>
          </div>
        </div>
      )
    }
    return <div className="session-loading">Loading session…</div>
  }

  return (
    <div className="session-layout">
      {warmupBadge && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          zIndex: 9999,
          background: 'linear-gradient(135deg, rgba(22, 101, 52, 0.95), rgba(15, 23, 42, 0.98))',
          border: '1px solid #34D399',
          borderRadius: '12px',
          padding: '10px 18px',
          color: '#FFFFFF',
          boxShadow: '0 8px 24px rgba(0,0,0,0.5), 0 0 16px rgba(52, 211, 153, 0.3)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontSize: '0.9rem',
          fontWeight: 600,
          animation: 'fadein 0.3s ease-out',
        }}>
          <span>🔥</span>
          <span>Warm-up score: <strong>{warmupBadge.score}/{warmupBadge.total}</strong> — ready to learn!</span>
        </div>
      )}

      {/* ── Mobile Top Header & Segmented Tab Navigation (<= 1024px) ── */}
      <div className="session-mobile-nav">
        <div className="session-header-mini session-header-mini--mobile">
          <div className="session-header-top-row">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <div
                style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}
                onClick={() => setShowAvatarModal(true)}
                title="Change profile picture"
              >
                <UserAvatar
                  avatar={avatar}
                  name={session.student_name}
                  role={role}
                  size="sm"
                  showEditBadge={true}
                />
                <span className="badge badge-violet">{session.student_name}</span>
              </div>
              <button
                type="button"
                onClick={handleCopyCode}
                className="badge badge-amber"
                style={{ cursor: 'pointer', border: 'none', background: 'rgba(245, 158, 11, 0.15)', color: 'var(--amber, #F59E0B)', display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '2px 8px', fontSize: '0.72rem' }}
                title="Click to copy your Student ID code for your parents to link your account in their portal"
              >
                <span>{copiedCode ? '✓ Copied' : `Code: ${session.student_id ? session.student_id.slice(0, 8) : ''}… 📋`}</span>
              </button>
            </div>
            <ThemeToggle />
          </div>
          <div className="session-header-actions-row">
            <button
              type="button"
              className="btn btn-ghost"
              style={{ padding: '5px 8px', fontSize: '0.74rem' }}
              onClick={() => {
                stop()
                navigate('/')
              }}
              aria-label="Back to Home"
              title="Return to Home Landing Page"
            >
              ← Home
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              style={{
                padding: '5px 8px',
                fontSize: '0.74rem',
                background: 'rgba(124, 93, 250, 0.15)',
                border: '1px solid rgba(124, 93, 250, 0.35)',
                color: 'var(--violet-light, #A78BFA)',
                fontWeight: 700,
              }}
              onClick={() => {
                stop()
                navigate('/arcade')
              }}
              title="Open Math Arcade games"
            >
              🎮 Arcade
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ padding: '5px 8px', fontSize: '0.74rem', color: '#F87171' }}
              onClick={() => setShowResetModal(true)}
              aria-label="Reset learning progress and start fresh"
              title="Reset all practice progress and skill mastery back to problem 1"
            >
              🔄 Reset
            </button>
            {role === 'parent' && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ padding: '5px 8px', fontSize: '0.74rem' }}
                onClick={() => {
                  stop()
                  navigate('/parent-dashboard')
                }}
                title="Go to Parent Portal"
              >
                Parent Portal
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost"
              style={{ padding: '5px 8px', fontSize: '0.74rem' }}
              onClick={() => {
                stop()
                navigate(`/dashboard/${session.student_id}`)
              }}
              aria-label="View learning dashboard"
              title="View Student Progress Dashboard"
            >
              Dashboard
            </button>
            {user && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ padding: '5px 8px', fontSize: '0.74rem' }}
                onClick={() => {
                  stop()
                  if (session?.session_id) {
                    sessionStorage.removeItem(`veritas_chat_${session.session_id}`)
                  }
                  sessionStorage.removeItem('session')
                  signOut()
                    .then(() => navigate('/'))
                    .catch((err) => {
                      console.error('Sign out error:', err)
                      navigate('/')
                    })
                }}
                aria-label="Log out"
                title="Log out"
              >
                Log Out
              </button>
            )}
          </div>
        </div>

        <div className="mobile-session-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mobileTab === 'chat'}
            className={`mobile-tab-btn ${mobileTab === 'chat' ? 'mobile-tab-btn--active' : ''}`}
            onClick={() => setMobileTab('chat')}
          >
            <span>💬</span> Tutor Chat
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mobileTab === 'problem'}
            className={`mobile-tab-btn ${mobileTab === 'problem' ? 'mobile-tab-btn--active' : ''}`}
            onClick={() => setMobileTab('problem')}
          >
            <span>📝</span> Problem & Work
            {currentProblem && <span className="mobile-tab-indicator" />}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mobileTab === 'progress'}
            className={`mobile-tab-btn ${mobileTab === 'progress' ? 'mobile-tab-btn--active' : ''}`}
            onClick={() => setMobileTab('progress')}
          >
            <span>📊</span> Skill Map
          </button>
        </div>
      </div>

      {/* ── Left sidebar: problem + upload ── */}
      <aside className={`session-sidebar ${mobileTab !== 'problem' ? 'mobile-hidden' : ''}`}>
        <div className="session-header-mini session-header-mini--desktop">
          <div className="session-header-top-row">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <div
                style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}
                onClick={() => setShowAvatarModal(true)}
                title="Change profile picture"
              >
                <UserAvatar
                  avatar={avatar}
                  name={session.student_name}
                  role={role}
                  size="sm"
                  showEditBadge={true}
                />
                <span className="badge badge-violet">{session.student_name}</span>
              </div>
              <button
                type="button"
                onClick={handleCopyCode}
                className="badge badge-amber"
                style={{ cursor: 'pointer', border: 'none', background: 'rgba(245, 158, 11, 0.15)', color: 'var(--amber, #F59E0B)', display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '2px 8px', fontSize: '0.74rem' }}
                title="Click to copy your Student ID code for your parents to link your account in their portal"
              >
                <span>{copiedCode ? '✓ Copied' : `Code: ${session.student_id ? session.student_id.slice(0, 8) : ''}… 📋`}</span>
              </button>
            </div>
            <ThemeToggle />
          </div>
          <div className="session-header-actions-row">
            <button
              type="button"
              className="btn btn-ghost"
              style={{ padding: '5px 10px', fontSize: '0.78rem' }}
              onClick={() => {
                stop()
                navigate('/')
              }}
              aria-label="Back to Home"
              title="Return to Home Landing Page"
            >
              ← Home
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              style={{
                padding: '5px 10px',
                fontSize: '0.78rem',
                background: 'rgba(124, 93, 250, 0.15)',
                border: '1px solid rgba(124, 93, 250, 0.35)',
                color: 'var(--violet-light, #A78BFA)',
                fontWeight: 700,
              }}
              onClick={() => {
                stop()
                navigate('/arcade')
              }}
              title="Open Math Arcade games"
            >
              🎮 Math Arcade
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ padding: '5px 10px', fontSize: '0.78rem', color: '#F87171' }}
              onClick={() => setShowResetModal(true)}
              aria-label="Reset learning progress and start fresh"
              title="Reset all practice progress and skill mastery back to problem 1"
            >
              🔄 Reset Progress
            </button>
            {role === 'parent' && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ padding: '5px 10px', fontSize: '0.78rem' }}
                onClick={() => {
                  stop()
                  navigate('/parent-dashboard')
                }}
                title="Go to Parent Portal"
              >
                Parent Portal
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost"
              style={{ padding: '5px 10px', fontSize: '0.78rem' }}
              onClick={() => {
                stop()
                navigate(`/dashboard/${session.student_id}`)
              }}
              aria-label="View learning dashboard"
              title="View Student Progress Dashboard"
            >
              Dashboard
            </button>
            {user && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ padding: '5px 10px', fontSize: '0.78rem' }}
                onClick={() => {
                  stop()
                  if (session?.session_id) {
                    sessionStorage.removeItem(`veritas_chat_${session.session_id}`)
                  }
                  sessionStorage.removeItem('session')
                  signOut()
                    .then(() => navigate('/'))
                    .catch((err) => {
                      console.error('Sign out error:', err)
                      navigate('/')
                    })
                }}
                aria-label="Log out"
                title="Log out"
              >
                Log Out
              </button>
            )}
          </div>
        </div>

        {currentProblem && (
          <div className="problem-card card animate-fadein">
            <div className="problem-header">
              <span className="badge badge-amber">Topic: {formatSkillName(currentProblem.skill_id)}</span>
              <span className="difficulty-dots">
                {Array.from({ length: 5 }).map((_, i) => (
                  <span key={i} className={`dot ${i < currentProblem.difficulty ? 'active' : ''}`} />
                ))}
              </span>
            </div>
            <h3>{cleanProblemTitle(currentProblem.title)}</h3>
            <p className="problem-text">{currentProblem.text}</p>
            
            <div className="problem-card-actions">
              <button
                type="button"
                className="btn btn-primary problem-action-btn"
                onClick={() => handleNextProblem(problemSolved)}
                disabled={isLoadingNextProblem || isStreaming}
                title="Advance to the next tailored practice problem"
              >
                {isLoadingNextProblem ? <span className="spinner" /> : 'Next Problem →'}
              </button>
              <button
                type="button"
                className="btn btn-ghost problem-action-btn problem-action-btn--skip"
                onClick={() => handleNextProblem(false)}
                disabled={isLoadingNextProblem || isStreaming}
                title="Try a different practice problem"
              >
                Skip Problem
              </button>
            </div>
          </div>
        )}

        <WorkUpload
          sessionId={session.session_id}
          onThinking={(step) => setThinkingSteps(prev => [...prev, step])}
          onDiagnosis={handleDiagnosis}
        />

        <div className="mobile-only-return-chat">
          <button
            type="button"
            className="btn btn-primary btn-block"
            onClick={() => setMobileTab('chat')}
          >
            ← Return to Tutor Chat
          </button>
        </div>
      </aside>

      {/* ── Main chat ── */}
      <main className={`session-main ${mobileTab !== 'chat' ? 'mobile-hidden' : ''}`}>
        {/* Mobile sticky mini-problem banner */}
        {currentProblem && (
          <div className="mobile-problem-banner" onClick={() => setMobileTab('problem')}>
            <div className="mobile-problem-banner-left">
              <span className="badge badge-amber">{formatSkillName(currentProblem.skill_id)}</span>
              <span className="mobile-problem-banner-title">{cleanProblemTitle(currentProblem.title)}</span>
            </div>
            <span className="mobile-problem-banner-action">View Work & Camera →</span>
          </div>
        )}

        <div className="chat-messages">
          {messages.map((msg, i) => (
            msg.role === 'system' ? null : (
              <div key={i} className={`chat-bubble ${msg.role} animate-fadein`}>
                {msg.role === 'tutor' && (
                  <div className="tutor-avatar">AI</div>
                )}
                <div className="bubble-body">
                  <p className="bubble-text">{renderMessageContent(msg.content)}</p>
                  <span className="bubble-time">
                    {(msg.timestamp instanceof Date ? msg.timestamp : new Date(msg.timestamp)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              </div>
            )
          ))}
          {problemSolved && (
            <div className="problem-solved-banner animate-fadein" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', flexWrap: 'wrap', gap: '10px' }}>
                <div className="solved-banner-info">
                  <span className="solved-banner-badge">🎉 Problem Solved!</span>
                  <p className="solved-banner-text">Great math thinking! Ready to take on the next challenge?</p>
                </div>
                <button
                  type="button"
                  className="btn btn-primary solved-banner-action"
                  onClick={() => handleNextProblem(true)}
                  disabled={isLoadingNextProblem}
                >
                  {isLoadingNextProblem ? <span className="spinner" /> : 'Next Problem →'}
                </button>
              </div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: 'rgba(124, 93, 250, 0.12)',
                border: '1px solid rgba(124, 93, 250, 0.3)',
                borderRadius: '8px',
                padding: '8px 14px',
                width: '100%',
                gap: '10px',
                flexWrap: 'wrap',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.86rem', color: 'var(--text-primary)' }}>
                  <span style={{ fontSize: '1.2rem' }}>🎮</span>
                  <span><strong>Math Arcade Challenge:</strong> You earned progress toward game unlocks!</span>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-violet"
                  style={{ fontWeight: 700, padding: '4px 12px', fontSize: '0.8rem' }}
                  onClick={() => {
                    stop()
                    navigate('/arcade')
                  }}
                  title="Play unlocked games in Math Arcade"
                >
                  Play Arcade 🕹️
                </button>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Voice waveform indicator */}
        {isListening && (
          <div className="voice-indicator">
            <div className="waveform">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="wave-bar" style={{ animationDelay: `${i * 0.1}s` }} />
              ))}
            </div>
            <span>{interimText || 'Listening…'}</span>
          </div>
        )}

        {/* Action bar for stuck-student hint affordance & mute speaking */}
        <div className="chat-actions-bar">
          <div className="chat-actions-left">
            <button
              className="btn-hint"
              onClick={handleRequestHint}
              disabled={isStreaming || isListening}
              aria-label="Request a hint from the tutor"
              title="Ask the tutor for a small guiding hint without giving away the answer"
            >
              Need a hint?
            </button>
            <button
              className="btn-advance-problem"
              onClick={() => handleNextProblem(problemSolved)}
              disabled={isStreaming || isLoadingNextProblem}
              aria-label="Move to next problem"
              title="Ready for the next problem"
            >
              {isLoadingNextProblem ? 'Loading…' : 'Next Problem →'}
            </button>
          </div>
          {isSpeaking && (
            <button
              className="btn-stop-speaking animate-fadein"
              onClick={stop}
              aria-label="Stop tutor voice"
              title="Stop tutor from speaking"
            >
              🔇 Stop Voice
            </button>
          )}
        </div>

        {/* Input area */}
        <div className="chat-input-area">
          <button
            className={`btn ${isListening ? 'btn-amber' : 'btn-ghost'} voice-btn ${!isSupported ? 'voice-btn--disabled' : ''}`}
            onClick={!isSupported ? undefined : (isListening ? stopListening : startListening)}
            disabled={!isSupported || isStreaming}
            title={
              !isSupported
                ? 'Voice input is supported in Chrome & Edge browsers. Please type your answer!'
                : isListening
                ? 'Stop listening'
                : 'Speak your answer'
            }
            aria-label={
              !isSupported
                ? 'Voice input not supported in this browser'
                : isListening
                ? 'Stop listening to voice'
                : 'Speak your answer with microphone'
            }
          >
            {isListening ? 'Mute' : 'Mic'}
          </button>

          <input
            className="input chat-input"
            placeholder={isSupported ? "Type your answer, or use the mic…" : "Type your answer here…"}
            value={isListening ? interimText : input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            disabled={isListening || isStreaming}
            aria-label="Type your math answer or reasoning"
          />

          <button
            className="btn btn-primary"
            onClick={sendMessage}
            disabled={!input.trim() || isStreaming || isListening}
            aria-label="Send answer to tutor"
          >
            {isStreaming ? <span className="spinner" /> : 'Send'}
          </button>

          {isSpeaking && (
            <div className="speaking-badge" role="status">
              Speaking
            </div>
          )}
        </div>
      </main>

      {/* ── Right sidebar: live intelligence (reasoning trace + mastery radar) ── */}
      <aside className={`session-mastery ${mobileTab !== 'progress' ? 'mobile-hidden' : ''}`}>
        <div className="intel-header">
          <div className="intel-title-row">
            <span className="live-pulse-dot" />
            <span className="intel-title">LIVE PROGRESS</span>
          </div>
          <span className="intel-caption">Tutor Guidance & Skill Map</span>
        </div>

        <ThinkingTrace steps={thinkingSteps} isActive={isStreaming} />

        <MasteryRadar skills={masterySkills} />

        <div className="mobile-only-return-chat">
          <button
            type="button"
            className="btn btn-primary btn-block"
            onClick={() => setMobileTab('chat')}
          >
            ← Return to Tutor Chat
          </button>
        </div>
      </aside>

      <AvatarModal
        isOpen={showAvatarModal}
        onClose={() => setShowAvatarModal(false)}
        onSave={async (newAvatar) => {
          await updateAvatar(newAvatar)
        }}
        currentAvatar={avatar}
        name={session?.student_name || user?.user_metadata?.name}
        role={role}
      />

      {showResetModal && (
        <div
          className="modal-backdrop animate-fadein"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            padding: '1rem',
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: '440px',
              width: '100%',
              background: 'var(--card-bg, #1e1e2f)',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              borderRadius: '16px',
              padding: '24px',
              boxShadow: '0 12px 36px rgba(0,0,0,0.6)',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: '2.4rem', marginBottom: '12px' }}>🔄</div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '8px', color: 'var(--text-primary)' }}>
              Reset Practice Progress?
            </h3>
            <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: '20px' }}>
              This will reset your BKT skill mastery back to baseline (30%), clear your current conversation, and start fresh from problem 1.
            </p>
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setShowResetModal(false)}
                disabled={isResetting}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn"
                style={{ background: '#DC2626', color: '#FFFFFF', border: 'none', fontWeight: 600, padding: '8px 16px', borderRadius: '8px' }}
                onClick={handleResetProgress}
                disabled={isResetting}
              >
                {isResetting ? 'Resetting…' : 'Yes, Reset Progress'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
