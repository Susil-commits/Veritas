import { useEffect, useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getMastery, getSummary } from '../lib/api'
import MasteryRadar from '../components/MasteryRadar'
import { getSkillMeta } from '../lib/skillsData'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import AvatarModal from '../components/AvatarModal'
import './Dashboard.css'

interface SkillMastery {
  skill_id: string
  name: string
  mastery_prob: number
}

export default function Dashboard() {
  const { studentId } = useParams<{ studentId: string }>()
  const navigate = useNavigate()
  const { role, avatar, updateAvatar, signOut } = useAuth()
  const [showAvatarModal, setShowAvatarModal] = useState(false)
  const [skills, setSkills] = useState<SkillMastery[]>([])
  const [summary, setSummary] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [authDenied, setAuthDenied] = useState<string | null>(null)
  const [retryTrigger, setRetryTrigger] = useState(0)
  const cachedSession = useMemo(() => {
    try {
      const raw = sessionStorage.getItem('session')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (!studentId || parsed.student_id === studentId) {
          return parsed
        }
      }
    } catch {}
    return null
  }, [studentId])
  const sessionId = cachedSession?.session_id || null
  const studentName = cachedSession?.student_name || 'Student'

  useEffect(() => {
    document.title = `Veritas — ${studentName}'s Progress Dashboard`
  }, [studentName])

  useEffect(() => {
    if (!studentId) return
    setLoading(true)
    setLoadError(null)
    setAuthDenied(null)
    Promise.all([
      getMastery(studentId),
      sessionId ? getSummary(studentId, sessionId) : Promise.resolve(null),
    ]).then(([masteryData, summaryData]) => {
      // Build skills array with names from all_skills
      const skillMap: Record<string, string> = {}
      for (const s of masteryData?.all_skills ?? []) skillMap[s.id] = s.name

      const skillsArr: SkillMastery[] = (masteryData?.mastery || []).map((row: any) => ({
        skill_id: row.skill_id,
        name: skillMap[row.skill_id] ?? row.skill_id,
        mastery_prob: row.mastery_prob,
      }))
      setSkills(skillsArr)
      if (summaryData?.summary) setSummary(summaryData.summary)
    }).catch((err: any) => {
      console.error('Dashboard load failed:', err)
      const status = err?.response?.status
      if (status === 401) {
        setAuthDenied('Your session has expired or is invalid. Please sign in again.')
      } else if (status === 403) {
        setAuthDenied('You do not have permission to view this student’s learning progress.')
      } else {
        setLoadError('Could not load your progress right now. Please try refreshing.')
      }
    }).finally(() => setLoading(false))
  }, [studentId, sessionId, retryTrigger])

  const avgMastery = useMemo(() => (
    skills.length
      ? skills.reduce((a, s) => a + s.mastery_prob, 0) / skills.length
      : 0
  ), [skills])

  const strongSkills = useMemo(() => skills.filter(s => s.mastery_prob >= 0.7), [skills])
  const weakSkills   = useMemo(() => skills.filter(s => s.mastery_prob < 0.4), [skills])

  return (
    <div className="dashboard">
      <header className="dash-header">
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => navigate('/')}
            aria-label="Back to Home"
            title="Return to Home Landing Page"
          >
            ← Home
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              if (role === 'parent') {
                navigate('/parent-dashboard')
              } else {
                navigate('/student-session')
              }
            }}
            aria-label={role === 'parent' ? 'Back to Parent Portal' : 'Back to Session'}
          >
            {role === 'parent' ? '← Parent Portal' : '← Back to Session'}
          </button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            onClick={() => setShowAvatarModal(true)}
            style={{ cursor: 'pointer' }}
            title="Click to update profile picture"
          >
            <UserAvatar
              avatar={avatar}
              name={studentName}
              role={role}
              size="md"
              showEditBadge={true}
            />
          </div>
          <div>
            <h2>{studentName}'s Learning Dashboard</h2>
            <p className="dash-sub">Real-time skill progress & practice summary</p>
          </div>
        </div>
        <div className="dash-stats">
          <div className="dash-stat">
            <span>{Math.round(avgMastery * 100)}%</span>
            <label>Overall Progress</label>
          </div>
          <div className="dash-stat">
            <span>{strongSkills.length}</span>
            <label>Mastered</label>
          </div>
          <div className="dash-stat">
            <span>{weakSkills.length}</span>
            <label>Practicing</label>
          </div>
          <ThemeToggle />
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              signOut()
                .then(() => navigate('/'))
                .catch(() => navigate('/'))
            }}
            title="Log out of Veritas"
          >
            Log Out
          </button>
        </div>
      </header>

      {authDenied ? (
        <div
          className="dash-access-denied"
          role="alert"
          style={{
            textAlign: 'center',
            padding: '3rem 1.5rem',
            maxWidth: '540px',
            margin: '3rem auto',
            background: 'rgba(239, 68, 68, 0.08)',
            border: '1px solid rgba(239, 68, 68, 0.25)',
            borderRadius: '12px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '1rem',
          }}
        >
          <span style={{ fontSize: '2.5rem' }} aria-hidden="true">🔒</span>
          <h3 style={{ margin: 0, fontSize: '1.3rem', color: '#F87171' }}>Access Restricted</h3>
          <p style={{ margin: 0, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{authDenied}</p>
          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem', flexWrap: 'wrap', justifyContent: 'center' }}>
            <button
              className="btn btn-primary"
              onClick={() => {
                if (role === 'parent') {
                  navigate('/parent-dashboard')
                } else {
                  navigate('/student-session')
                }
              }}
            >
              {role === 'parent' ? 'Go to Parent Portal' : 'Go to My Practice'}
            </button>
            <button className="btn btn-ghost" onClick={() => navigate('/')}>
              Return Home
            </button>
          </div>
        </div>
      ) : loadError ? (
        <div className="dash-error-banner" role="alert">
          <div className="dash-error-content">
            <span className="dash-error-icon">⚠️</span>
            <span>{loadError}</span>
          </div>
          <button
            className="btn btn-sm btn-ghost"
            style={{ border: '1px solid rgba(252, 165, 165, 0.4)', color: '#FCA5A5' }}
            onClick={() => setRetryTrigger(c => c + 1)}
          >
            Retry
          </button>
        </div>
      ) : null}

      {!authDenied && (loading ? (
        <div className="dash-loading">Loading your progress…</div>
      ) : (
        <div className="dash-content">
          <div className="dash-left">
            <MasteryRadar skills={skills} />

            {/* Skill breakdown cards */}
            <div className="skill-cards">
              {skills
                .sort((a, b) => a.mastery_prob - b.mastery_prob)
                .map(s => {
                  const pct = Math.round(s.mastery_prob * 100)
                  const level = pct >= 70 ? 'strong' : pct >= 40 ? 'developing' : 'weak'
                  return (
                    <div key={s.skill_id} className={`skill-card skill-card--${level}`}>
                      <div className="skill-card-top">
                        <span className="skill-name">{s.name}</span>
                        <span className="skill-pct">{pct}%</span>
                      </div>
                      <div className="skill-bar-track">
                        <div className="skill-bar-fill" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="skill-std">{getSkillMeta(s.skill_id).domain}</span>
                    </div>
                  )
                })}
            </div>
          </div>

          <div className="dash-right">
            <div className="card summary-card">
              <h3>Session Summary</h3>
              {summary ? (
                <p className="summary-text">{summary}</p>
              ) : (
                <p className="summary-empty">
                  Complete a tutoring session to generate an AI-written summary for teachers and parents.
                </p>
              )}
            </div>

            <div className="card recommendations-card">
              <h3>Recommendations</h3>
              {weakSkills.length === 0 ? (
                <p className="rec-good">All skills are developing or strong!</p>
              ) : (
                <ul className="rec-list">
                  {weakSkills.slice(0, 3).map(s => (
                    <li key={s.skill_id}>
                      <span className="badge badge-rose">Focus</span>
                      {s.name} — {Math.round(s.mastery_prob * 100)}% mastery
                    </li>
                  ))}
                </ul>
              )}
              {strongSkills.length > 0 && (
                <>
                  <h4 style={{ marginTop: '1rem', color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Ready to advance</h4>
                  <ul className="rec-list">
                    {strongSkills.slice(0, 2).map(s => (
                      <li key={s.skill_id}>
                        <span className="badge badge-emerald">Mastered</span>
                        {s.name}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        </div>
      ))}

      {/* Avatar Selection & Profile Modal */}
      <AvatarModal
        isOpen={showAvatarModal}
        onClose={() => setShowAvatarModal(false)}
        onSave={async (newAvatar) => {
          await updateAvatar(newAvatar)
        }}
        currentAvatar={avatar}
        name={studentName}
        role={role}
      />
    </div>
  )
}
