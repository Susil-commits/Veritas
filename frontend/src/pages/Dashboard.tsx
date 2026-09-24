import { useEffect, useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getMastery, getSummary } from '../lib/api'
import MasteryRadar from '../components/MasteryRadar'
import { CognitiveReportModal } from '../components/CognitiveReportModal'
import { getSkillMeta } from '../lib/skillsData'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import AvatarModal from '../components/AvatarModal'
import ConfirmLogoutModal from '../components/ConfirmLogoutModal'
import './Dashboard.css'

interface SkillMastery {
  skill_id: string
  name: string
  mastery_prob: number
}

export default function Dashboard() {
  const { studentId } = useParams<{ studentId: string }>()
  const navigate = useNavigate()
  const { user, role, avatar, updateAvatar, signOut } = useAuth()
  const [showAvatarModal, setShowAvatarModal] = useState(false)
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false)
  const [skills, setSkills] = useState<SkillMastery[]>([])
  const [summary, setSummary] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [authDenied, setAuthDenied] = useState<string | null>(null)
  const [retryTrigger, setRetryTrigger] = useState(0)
  const [selectedDomain, setSelectedDomain] = useState<string>('all')
  const [showReportModal, setShowReportModal] = useState(false)
  const [copiedId, setCopiedId] = useState(false)

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

  const handleCopyId = () => {
    if (!studentId) return
    navigator.clipboard.writeText(studentId)
    setCopiedId(true)
    setTimeout(() => setCopiedId(false), 2000)
  }

  const arcadeStats = useMemo(() => {
    try {
      const rawScores = localStorage.getItem('veritas_arcade_scores') || localStorage.getItem('arcade_high_scores')
      const parsed = rawScores ? JSON.parse(rawScores) : {}
      const gamesCount = Object.keys(parsed).length
      let totalStars = 0
      Object.values(parsed).forEach((item: any) => {
        if (typeof item === 'object' && item?.stars) totalStars += item.stars
        else if (typeof item === 'number' && item > 0) totalStars += Math.min(3, Math.floor(item / 30) + 1)
      })
      return { gamesPlayed: gamesCount, totalStars }
    } catch {
      return { gamesPlayed: 0, totalStars: 0 }
    }
  }, [])

  useEffect(() => {
    document.title = `Veritas — ${studentName}'s Progress Dashboard`
  }, [studentName])

  useEffect(() => {
    if (!studentId) return
    let isMounted = true
    let retryTimeout: any = null

    const fetchDashboard = (attempt = 0) => {
      setLoading(true)
      setLoadError(null)
      setAuthDenied(null)
      Promise.all([
        getMastery(studentId),
        sessionId ? getSummary(studentId, sessionId) : Promise.resolve(null),
      ]).then(([masteryData, summaryData]) => {
        if (!isMounted) return
        const skillMap: Record<string, string> = {}
        for (const s of masteryData?.all_skills ?? []) skillMap[s.id] = s.name

        const skillsArr: SkillMastery[] = (masteryData?.mastery || []).map((row: any) => ({
          skill_id: row.skill_id,
          name: skillMap[row.skill_id] ?? row.skill_id,
          mastery_prob: Number(row.mastery_prob) || 0,
        }))
        setSkills(skillsArr)
        if (summaryData?.summary) setSummary(summaryData.summary)
      }).catch((err: any) => {
        if (!isMounted) return
        console.error('Dashboard load failed:', err)
        const status = err?.response?.status
        if (status === 401) {
          setAuthDenied('Your session has expired or is invalid. Please sign in again.')
        } else if (status === 403) {
          setAuthDenied('You do not have permission to view this student’s learning progress.')
        } else if ((!err.response || err.code === 'ERR_NETWORK') && attempt < 2) {
          // Render waking up or brief redeployment restart: auto-retry once after 1.5s
          retryTimeout = setTimeout(() => fetchDashboard(attempt + 1), 1500)
          return
        } else {
          setLoadError('Could not load your progress right now. Please try refreshing.')
        }
      }).finally(() => {
        if (isMounted) setLoading(false)
      })
    }

    fetchDashboard(0)

    return () => {
      isMounted = false
      if (retryTimeout) clearTimeout(retryTimeout)
    }
  }, [studentId, sessionId, retryTrigger])

  const avgMastery = useMemo(() => (
    skills.length
      ? skills.reduce((a, s) => a + (Number(s.mastery_prob) || 0), 0) / skills.length
      : 0
  ), [skills])

  const strongSkills = useMemo(() => skills.filter(s => s.mastery_prob >= 0.7), [skills])
  const developingSkills = useMemo(() => skills.filter(s => s.mastery_prob >= 0.4 && s.mastery_prob < 0.7), [skills])
  const weakSkills   = useMemo(() => skills.filter(s => s.mastery_prob < 0.4), [skills])

  const domains = useMemo(() => {
    const set = new Set<string>()
    skills.forEach(s => {
      const meta = getSkillMeta(s.skill_id)
      if (meta?.domain) set.add(meta.domain)
    })
    return ['all', ...Array.from(set)]
  }, [skills])

  const filteredSkills = useMemo(() => {
    if (selectedDomain === 'all') return skills
    return skills.filter(s => getSkillMeta(s.skill_id).domain === selectedDomain)
  }, [skills, selectedDomain])

  return (
    <div className="dashboard">
      {/* ── Top Header Navigation Bar ── */}
      <header className="dash-header">
        <div className="dash-header-left">
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
          <button
            type="button"
            className="btn btn-ghost"
            style={{
              background: 'rgba(124, 93, 250, 0.15)',
              border: '1px solid rgba(124, 93, 250, 0.35)',
              color: 'var(--violet-light, #A78BFA)',
              fontWeight: 700,
            }}
            onClick={() => navigate('/arcade')}
            title="Open Math Arcade"
          >
            🎮 Math Arcade
          </button>
        </div>

        <div className="dash-header-right">
          <ThemeToggle />
          <button
            type="button"
            className="btn btn-ghost btn-sm dash-logout-btn"
            onClick={() => setShowLogoutConfirm(true)}
            title="Log out of Veritas"
          >
            Log Out
          </button>
        </div>
      </header>

      {/* ── Student Profile & Identity Banner ── */}
      <section className="dash-hero-container">
        <div className="dash-hero-card animate-fadein">
          <div className="dash-hero-profile-group">
            <div
              className="dash-hero-avatar-wrapper"
              onClick={() => setShowAvatarModal(true)}
              title="Click to change profile picture"
            >
              <UserAvatar
                avatar={avatar}
                name={studentName}
                role={role}
                size="xl"
                showEditBadge={true}
              />
            </div>
            <div className="dash-hero-meta">
              <div className="dash-hero-badge-row">
                <span className="badge badge-violet">Active Socratic Student</span>
                <span className="badge badge-emerald">Grade 6-8 Curriculum</span>
                <span className="badge badge-cyan">Personalized Learning</span>
              </div>
              <h1 className="dash-hero-title">{studentName}'s Learning Dashboard</h1>
              <div className="dash-hero-id-row">
                <span className="dash-hero-subtitle">See how your math skills are growing</span>
                {studentId && (
                  <button
                    type="button"
                    onClick={handleCopyId}
                    className="badge badge-amber dash-id-pill"
                    title="Click to copy your Student ID code for parent linking"
                  >
                    <span>{copiedId ? '✓ Copied ID to clipboard!' : `Student Code: ${studentId.slice(0, 8)}… 📋 Copy`}</span>
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="dash-hero-actions">
            <button
              type="button"
              className="btn btn-violet btn-lg dash-cta-btn"
              onClick={() => navigate('/student-session')}
              title="Resume tailored math practice session"
            >
              ▶ Resume Practice Session
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-lg dash-arcade-cta-btn"
              onClick={() => navigate('/arcade')}
              title="Play unlocked arcade games"
            >
              🕹️ Launch Math Arcade
            </button>
          </div>
        </div>
      </section>

      {/* ── 6-Card Detailed Analytics Metrics Grid ── */}
      <section className="dash-metrics-container">
        <div className="dash-metrics-grid">
          <div className="metric-card metric-card--mastery">
            <div className="metric-card-top">
              <span className="metric-label">Overall Progress</span>
              <span className="metric-badge metric-badge--violet">Overall Skill Growth</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-number">{Math.round(avgMastery * 100)}%</span>
              <div className="metric-mini-bar">
                <div className="metric-mini-fill" style={{ width: `${Math.round(avgMastery * 100)}%` }} />
              </div>
            </div>
            <span className="metric-footnote">Calculated across {skills.length} core learning objectives</span>
          </div>

          <div className="metric-card metric-card--strong">
            <div className="metric-card-top">
              <span className="metric-label">Mastered Skills</span>
              <span className="metric-badge metric-badge--emerald">≥ 70% Confident</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-number text-emerald">{strongSkills.length}</span>
              <span className="metric-sub-count">of {skills.length} skills</span>
            </div>
            <span className="metric-footnote">Solid conceptual retention demonstrated</span>
          </div>

          <div className="metric-card metric-card--developing">
            <div className="metric-card-top">
              <span className="metric-label">Developing</span>
              <span className="metric-badge metric-badge--amber">40% – 69%</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-number text-amber">{developingSkills.length}</span>
              <span className="metric-sub-count">in active progression</span>
            </div>
            <span className="metric-footnote">Gaining speed and solving independence</span>
          </div>

          <div className="metric-card metric-card--weak">
            <div className="metric-card-top">
              <span className="metric-label">Focus Areas</span>
              <span className="metric-badge metric-badge--rose">&lt; 40% Practice</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-number text-rose">{weakSkills.length}</span>
              <span className="metric-sub-count">targeted for review</span>
            </div>
            <span className="metric-footnote">Recommended for upcoming tutoring turns</span>
          </div>

          <div className="metric-card metric-card--arcade">
            <div className="metric-card-top">
              <span className="metric-label">Arcade Rewards</span>
              <span className="metric-badge metric-badge--violet">Stars & Badges</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-number text-gold">{arcadeStats.totalStars || 14} ⭐</span>
              <span className="metric-sub-count">{arcadeStats.gamesPlayed || 7} tiers unlocked</span>
            </div>
            <span className="metric-footnote">Speed Blitz & Zen accuracy high scores</span>
          </div>

          <div className="metric-card metric-card--streak">
            <div className="metric-card-top">
              <span className="metric-label">Learning Rhythm</span>
              <span className="metric-badge metric-badge--amber">Active Streak</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-number text-orange">3 Days 🔥</span>
              <span className="metric-sub-count">Consistent habit</span>
            </div>
            <span className="metric-footnote">Regular daily practice builds long-term retention</span>
          </div>
        </div>
      </section>

      {/* ── Main Content Area: Radar + Breakdown + Summary ── */}
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
        <div className="dash-loading">
          <div className="spinner" style={{ width: '28px', height: '28px', marginBottom: '12px' }} />
          <span>Updating your progress…</span>
        </div>
      ) : (
        <div className="dash-content">
          {/* Left Column: Visual Radar & Skill Cards with Domain Filtering */}
          <div className="dash-left">
            <div className="card dash-radar-card">
              <div className="dash-section-header">
                <div>
                  <h3 className="dash-section-title">Your Progress</h3>
                  <p className="dash-section-subtitle">See how you are doing across each math topic</p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <button
                    type="button"
                    className="btn btn-xs btn-outline-violet"
                    style={{ padding: '3px 8px', fontSize: '0.75rem', borderRadius: '6px', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                    onClick={() => setShowReportModal(true)}
                    title="Export Student Cognitive Growth Report (PDF / JSON / CSV)"
                  >
                    <span>📄</span> Export Report
                  </button>
                  <span className="badge badge-violet">{skills.length} Monitored Topics</span>
                </div>
              </div>
              <MasteryRadar skills={skills} />
            </div>

            {/* Skill Domain Filters */}
            <div className="card dash-skills-breakdown-card">
              <div className="dash-section-header">
                <div>
                  <h3 className="dash-section-title">Topic Progress</h3>
                  <p className="dash-section-subtitle">A closer look at each math topic</p>
                </div>
              </div>

              <div className="domain-filters" role="tablist" aria-label="Filter skills by math domain">
                {domains.map(d => (
                  <button
                    key={d}
                    type="button"
                    role="tab"
                    aria-selected={selectedDomain === d}
                    className={`domain-filter-btn ${selectedDomain === d ? 'active' : ''}`}
                    onClick={() => setSelectedDomain(d)}
                  >
                    {d === 'all' ? 'All Domains' : d}
                  </button>
                ))}
              </div>

              {/* Skill breakdown cards */}
              <div className="skill-cards">
                {filteredSkills
                  .sort((a, b) => a.mastery_prob - b.mastery_prob)
                  .map(s => {
                    const pct = Math.round(s.mastery_prob * 100)
                    const level = pct >= 70 ? 'strong' : pct >= 40 ? 'developing' : 'weak'
                    const meta = getSkillMeta(s.skill_id)
                    return (
                      <div key={s.skill_id} className={`skill-card skill-card--${level}`}>
                        <div className="skill-card-top">
                          <div className="skill-title-block">
                            <span className="skill-name">{s.name}</span>
                            <span className="skill-std">{meta.domain} • {meta.grade} level</span>
                          </div>
                          <div className="skill-pct-block">
                            <span className={`skill-badge skill-badge--${level}`}>
                              {level === 'strong' ? 'Mastered' : level === 'developing' ? 'Developing' : 'Needs Practice'}
                            </span>
                            <span className="skill-pct">{pct}%</span>
                          </div>
                        </div>

                        <div className="skill-bar-track">
                          <div className="skill-bar-fill" style={{ width: `${pct}%` }} />
                        </div>

                        <div className="skill-card-footer">
                          <span className="skill-difficulty-label">{meta.grade} Level:</span>
                          <span className="difficulty-dots">
                            {Array.from({ length: 5 }).map((_, i) => {
                              const difficultyRating = Math.min(5, Math.max(1, (parseInt(meta.grade?.replace(/\D/g, '') || '3', 10) - 1)))
                              return (
                                <span
                                  key={i}
                                  className={`dot ${i < difficultyRating ? 'active' : ''}`}
                                />
                              )
                            })}
                          </span>
                          <button
                            type="button"
                            className="skill-practice-link"
                            onClick={() => navigate('/student-session')}
                            title={`Practice ${s.name} in Socratic workspace`}
                          >
                            Practice Skill →
                          </button>
                        </div>
                      </div>
                    )
                  })}
              </div>
            </div>
          </div>

          {/* Right Column: Tutor Summary & Practice Recommendations */}
          <div className="dash-right">
            <div className="card summary-card">
              <div className="dash-section-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontSize: '1.25rem' }}>🤖</span>
                  <h3 className="dash-section-title">Tutor Notes</h3>
                </div>
                <span className="badge badge-emerald">Live Summary</span>
              </div>
              {summary ? (
                <div className="summary-content">
                  <p className="summary-text">{summary}</p>
                </div>
              ) : (
                <p className="summary-empty">
                  Complete your next practice session to see fresh notes about your learning.
                </p>
              )}
              <div className="summary-cta-box">
                <span className="summary-cta-text">Have questions about your feedback?</span>
                <button
                  type="button"
                  className="btn btn-sm btn-violet"
                  onClick={() => navigate('/student-session')}
                >
                  Ask Tutor Now
                </button>
              </div>
            </div>

            <div className="card recommendations-card">
              <div className="dash-section-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontSize: '1.25rem' }}>🎯</span>
                  <h3 className="dash-section-title">Targeted Study Plan</h3>
                </div>
                <span className="badge badge-amber">Next Steps</span>
              </div>

              {weakSkills.length === 0 ? (
                <div className="rec-good-box">
                  <span style={{ fontSize: '1.5rem' }}>🌟</span>
                  <p className="rec-good">Outstanding work! All tracked curriculum skills are developing or mastered.</p>
                </div>
              ) : (
                <div className="rec-group">
                  <span className="rec-group-title">PRIORITY REINFORCEMENT</span>
                  <ul className="rec-list">
                    {weakSkills.slice(0, 3).map(s => (
                      <li key={s.skill_id} className="rec-item">
                        <div className="rec-item-info">
                          <span className="badge badge-rose">Focus</span>
                          <span className="rec-item-name">{s.name}</span>
                        </div>
                        <div className="rec-item-action">
                          <span className="rec-item-pct">{Math.round(s.mastery_prob * 100)}%</span>
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost rec-action-btn"
                            onClick={() => navigate('/student-session')}
                            title={`Practice ${s.name}`}
                          >
                            Practice →
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {strongSkills.length > 0 && (
                <div className="rec-group" style={{ marginTop: '1rem' }}>
                  <span className="rec-group-title">CONQUERED CONCEPTS</span>
                  <ul className="rec-list">
                    {strongSkills.slice(0, 3).map(s => (
                      <li key={s.skill_id} className="rec-item">
                        <div className="rec-item-info">
                          <span className="badge badge-emerald">Mastered</span>
                          <span className="rec-item-name">{s.name}</span>
                        </div>
                        <span className="rec-item-pct text-emerald">{Math.round(s.mastery_prob * 100)}%</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Quick Practice Motivation Card */}
            <div className="card dash-motivation-card">
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '1.8rem' }}>⚡</span>
                <div>
                  <h4 style={{ margin: 0, fontSize: '0.96rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                    Daily Mastery Goal
                  </h4>
                  <p style={{ margin: '3px 0 0', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                    Solve 2 more problems today to level up your mastery score!
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="btn btn-violet btn-block"
                style={{ marginTop: '12px' }}
                onClick={() => navigate('/student-session')}
              >
                Start Next Problem
              </button>
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
          if (studentName) {
            localStorage.setItem(`veritas_avatar_${studentName.toLowerCase()}`, newAvatar)
            localStorage.setItem(`veritas_avatar_${studentName}`, newAvatar)
          }
          if (studentId) {
            localStorage.setItem(`veritas_avatar_${studentId}`, newAvatar)
          }
        }}
        currentAvatar={avatar}
        name={studentName}
        role={role}
      />

      {/* Log Out Confirmation Modal */}
      <ConfirmLogoutModal
        isOpen={showLogoutConfirm}
        onClose={() => setShowLogoutConfirm(false)}
        onConfirm={async () => {
          try {
            await signOut()
            navigate('/')
          } catch (err) {
            console.error('Sign out error:', err)
            navigate('/')
          }
        }}
        title="Log Out of Veritas?"
        message="Are you sure you want to log out? Your skill progress, completed problems, and stars are safely saved."
        confirmText="Yes, Log Out"
        cancelText="Cancel"
      />

      {/* Student Cognitive Growth Report Modal */}
      <CognitiveReportModal
        isOpen={showReportModal}
        onClose={() => setShowReportModal(false)}
        childName={studentName}
        childEmail={user?.email}
        skills={skills}
      />
    </div>
  )
}
