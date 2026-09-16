import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getParentChildren, addChild, getChildDetails, deleteParentData, type ChildItem } from '../lib/api'
import { supabase } from '../lib/supabase'
import MasteryRadar from '../components/MasteryRadar'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import AvatarModal from '../components/AvatarModal'
import { getSkillMeta, getMasteryTierInfo, getBarGradient } from '../lib/skillsData'
import { validateEmailFormat, validateNameFormat, sanitizeNameInput } from '../lib/emailValidation'
import './ParentDashboard.css'

interface SkillItem {
  skill_id: string
  name: string
  mastery_prob: number
}

export default function ParentDashboard() {
  const navigate = useNavigate()
  const { user, signOut, role, avatar, updateAvatar } = useAuth()
  const [showAvatarModal, setShowAvatarModal] = useState(false)
  const [childrenList, setChildrenList] = useState<ChildItem[]>([])
  const [selectedChildId, setSelectedChildId] = useState<string | null>(null)
  const [childDetails, setChildDetails] = useState<any>(null)
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [childrenLoading, setChildrenLoading] = useState(true)
  const [detailsError, setDetailsError] = useState<string | null>(null)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [showAddModal, setShowAddModal] = useState(false)
  const [newChildEmail, setNewChildEmail] = useState('')
  const [newChildName, setNewChildName] = useState('')
  const [addError, setAddError] = useState('')
  const [addingChild, setAddingChild] = useState(false)
  const [liveIndicator, setLiveIndicator] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deletingData, setDeletingData] = useState(false)
  const [deleteSuccessMsg, setDeleteSuccessMsg] = useState('')
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

  const deleteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const liveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (deleteTimerRef.current) clearTimeout(deleteTimerRef.current)
      if (liveTimerRef.current) clearTimeout(liveTimerRef.current)
    }
  }, [])

  useEffect(() => {
    if (!warmupBadge) return
    const t = setTimeout(() => setWarmupBadge(null), 3500)
    return () => clearTimeout(t)
  }, [warmupBadge])

  const parentId = user?.id || '99999999-8888-7777-6666-555555555555'
  const parentEmail = user?.email || 'parent.sarah@veritas.dev'

  const handleDeleteData = () => {
    setDeletingData(true)
    deleteParentData(parentId)
      .then((res) => {
        setDeleteSuccessMsg(res.message || 'All activity data successfully purged.')
        if (deleteTimerRef.current) clearTimeout(deleteTimerRef.current)
        deleteTimerRef.current = setTimeout(() => {
          setShowDeleteModal(false)
          setDeleteSuccessMsg('')
          refreshChildren().catch(() => {})
        }, 1200)
      })
      .catch((err: any) => {
        alert('Failed to delete data: ' + (err.response?.data?.detail || err.message))
      })
      .finally(() => {
        setDeletingData(false)
      })
  }

  // Fetch children list
  const refreshChildren = useCallback(() => {
    setLoadError(null)
    setChildrenLoading(true)
    return getParentChildren(parentId)
      .then((res) => {
        const list = res.children || []
        setChildrenList(list)
        if (list.length > 0) {
          setSelectedChildId(prev => (!prev || !list.some(c => c.student_id === prev) ? list[0].student_id : prev))
        }
      })
      .catch((err) => {
        console.error('Could not load parent children:', err)
        setLoadError('Could not load student profiles right now. Please try refreshing.')
      })
      .finally(() => {
        setChildrenLoading(false)
      })
  }, [parentId])

  // Initial load
  useEffect(() => {
    document.title = 'Veritas — Parent Dashboard'
    refreshChildren().catch(() => {})
  }, [refreshChildren])

  // Fetch selected child details & mastery
  const refreshChildDetails = useCallback((childId: string) => {
    setDetailsError(null)
    setDetailsLoading(true)
    return getChildDetails(parentId, childId)
      .then((data) => {
        setChildDetails(data)

        const skillMap: Record<string, string> = {}
        for (const s of data.all_skills ?? []) skillMap[s.id] = s.name

        const skillsArr: SkillItem[] = (data.mastery || []).map((row: any) => ({
          skill_id: row.skill_id,
          name: skillMap[row.skill_id] ?? row.skill_id,
          mastery_prob: row.mastery_prob,
        }))
        setSkills(skillsArr)
      })
      .catch((err) => {
        console.error('Error loading child details:', err)
        setDetailsError('Could not load learning details for this student. Please try again.')
      })
      .finally(() => {
        setDetailsLoading(false)
      })
  }, [parentId])

  useEffect(() => {
    if (selectedChildId) {
      refreshChildDetails(selectedChildId).catch(() => {})
    }
  }, [selectedChildId, refreshChildDetails])

  // Real-time updates: Subscribe to Supabase Realtime + Polling fallback
  useEffect(() => {
    if (!selectedChildId) return

    let channel: any = null
    // 1. Supabase Realtime subscription
    try {
      channel = supabase
        .channel(`parent-radar-${selectedChildId}`)
        .on(
          'postgres_changes',
          {
            event: 'INSERT',
            schema: 'public',
            table: 'session_events',
            filter: `student_id=eq.${selectedChildId}`,
          },
          (payload) => {
            console.log('Realtime learning event received:', payload)
            setLiveIndicator(true)
            if (liveTimerRef.current) clearTimeout(liveTimerRef.current)
            liveTimerRef.current = setTimeout(() => setLiveIndicator(false), 2000)
            refreshChildDetails(selectedChildId).catch(() => {})
          }
        )
        .subscribe()
    } catch (err) {
      console.warn('Supabase realtime subscription failed:', err)
    }

    // 2. Polling fallback (every 20 seconds) — paused when tab is not visible
    const pollTimer = setInterval(() => {
      if (!document.hidden) {
        refreshChildDetails(selectedChildId).catch(() => {})
      }
    }, 20000)

    return () => {
      clearInterval(pollTimer)
      if (liveTimerRef.current) {
        clearTimeout(liveTimerRef.current)
      }
      if (channel) {
        supabase.removeChannel(channel)
      }
    }
  }, [selectedChildId, refreshChildDetails])

  const handleAddChild = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmedInput = newChildEmail.trim()
    if (!trimmedInput) {
      setAddError("Please enter your child's email address or Student Code.")
      return
    }
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(trimmedInput)
    if (!isUuid) {
      const emailVal = validateEmailFormat(trimmedInput)
      if (!emailVal.valid) {
        setAddError(emailVal.reason || "Please enter a valid email address or 36-character Student Code.")
        return
      }
    }
    if (newChildName.trim()) {
      const nameVal = validateNameFormat(newChildName)
      if (!nameVal.valid) {
        setAddError(nameVal.reason || "Please enter a valid name.")
        return
      }
    }
    setAddingChild(true)
    setAddError('')
    addChild(parentId, trimmedInput, newChildName.trim(), parentEmail)
      .then((res) => {
        setShowAddModal(false)
        setNewChildEmail('')
        setNewChildName('')
        refreshChildren().catch(() => {})
        if (res.child?.student_id) {
          setSelectedChildId(res.child.student_id)
        }
      })
      .catch((err: any) => {
        setAddError(err?.response?.data?.detail || err?.message || 'Could not link child. Please try again.')
      })
      .finally(() => {
        setAddingChild(false)
      })
  }

  const selectedChild = useMemo(
    () => childrenList.find((c) => c.student_id === selectedChildId),
    [childrenList, selectedChildId]
  )

  const avgMastery = useMemo(() => (
    skills.length
      ? Math.round((skills.reduce((a, s) => a + s.mastery_prob, 0) / skills.length) * 100)
      : 0
  ), [skills])

  return (
    <div className="parent-dashboard">
      {warmupBadge && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          zIndex: 9999,
          background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.95), rgba(15, 23, 42, 0.98))',
          border: '1px solid #818CF8',
          borderRadius: '12px',
          padding: '10px 18px',
          color: '#FFFFFF',
          boxShadow: '0 8px 24px rgba(0,0,0,0.5), 0 0 16px rgba(129, 140, 248, 0.3)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontSize: '0.9rem',
          fontWeight: 600,
          animation: 'fadein 0.3s ease-out',
        }}>
          <span>💡</span>
          <span>Parent warm-up: <strong>{warmupBadge.score}/{warmupBadge.total}</strong> insights discovered!</span>
        </div>
      )}
      {/* Top Navbar */}
      <header className="parent-navbar">
        <div className="parent-nav-left">
          <div className="parent-brand" onClick={() => navigate('/')}>
            <span className="brand-title">Veritas<span className="brand-dot">.</span></span>
            <span className="parent-badge">Parent Portal</span>
          </div>
          <div className={`live-pulse-badge ${liveIndicator ? 'live-pulse-badge--active' : ''}`}>
            <span className="pulse-dot" />
            <span>Live Progress</span>
          </div>
        </div>

        <div className="parent-nav-right">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => navigate('/')}
            title="Return to Home Landing Page"
          >
            ← Home
          </button>
          <div
            className="parent-user-pill parent-user-pill--interactive"
            onClick={() => setShowAvatarModal(true)}
            title="Click to update profile picture"
          >
            <UserAvatar
              avatar={avatar}
              name={user?.user_metadata?.name || 'Parent'}
              role="parent"
              size="xs"
              showEditBadge={true}
            />
            <span className="parent-email">{parentEmail}</span>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              signOut()
                .then(() => navigate('/'))
                .catch((err) => {
                  console.error('Sign out error:', err)
                  navigate('/')
                })
            }}
          >
            Log Out
          </button>
          <ThemeToggle />
        </div>
      </header>

      <main className="parent-content">
        {/* Children Management Ribbon */}
        <section className="children-ribbon">
          <div className="ribbon-header">
            <div className="ribbon-title">
              <h3>Your Children</h3>
              <span className="children-count">{childrenList.length}</span>
            </div>
            <button
              className="btn btn-sm btn-outline-violet"
              onClick={() => setShowAddModal(true)}
              id="add-child-btn"
            >
              Add Child
            </button>
          </div>

          <div className="children-cards-list">
            {childrenLoading && childrenList.length === 0 ? (
              <div className="children-loading-state">
                <span>Loading student profiles…</span>
              </div>
            ) : loadError ? (
              <div className="parent-error-banner" role="alert">
                <div className="parent-error-content">
                  <span className="parent-error-icon">⚠️</span>
                  <span>{loadError}</span>
                </div>
                <button
                  className="btn btn-sm btn-outline-violet"
                  onClick={refreshChildren}
                >
                  Retry
                </button>
              </div>
            ) : childrenList.length === 0 ? (
              <div className="children-empty-state">
                <span>No student profiles linked yet. Click <strong>Add Child</strong> to link your student.</span>
              </div>
            ) : (
              childrenList.map((child) => {
                const isSelected = child.student_id === selectedChildId
                return (
                  <div
                    key={child.student_id}
                    className={`child-card ${isSelected ? 'child-card--active' : ''}`}
                    onClick={() => setSelectedChildId(child.student_id)}
                  >
                    <div className="child-card-header">
                      <UserAvatar
                        avatar={null}
                        name={child.student_name}
                        role="student"
                        size="sm"
                      />
                      <div className="child-meta">
                        <h4>{child.student_name}</h4>
                        <p>{child.student_email}</p>
                      </div>
                    </div>
                    {child.has_fraction_gap && (
                      <div className="gap-pill">
                        <span>{child.fraction_alert_message}</span>
                      </div>
                    )}
                    <div className="child-card-footer">
                      <span>{child.session_count} sessions</span>
                      <span className="footer-link">
                        View Skills
                      </span>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </section>

        {/* Selected Child Detailed View */}
        {selectedChild ? (
          <div className="child-detail-view">
            {/* Demo Highlight Banner */}
            {selectedChild.has_fraction_gap && (
              <div className="alert-banner">
                <div className="alert-content">
                  <h4>Inactivity Warning — Practice Gap Spotted</h4>
                  <p>
                    <strong>{selectedChild.student_name}</strong> has not practiced fractions in{' '}
                    <strong>{selectedChild.days_since_practice} days</strong>. Concept retention declines rapidly
                    without reinforcement. Start a practice session to guide them through fraction addition.
                  </p>
                </div>
                <button
                  className="btn btn-amber alert-action-btn"
                  onClick={() => {
                    // Open a student session in a new tab. TutorSession will initialize
                    // a fresh session once the student (or parent on behalf) authenticates.
                    window.open('/student-session', '_blank')
                  }}
                >
                  Start Kid Session
                </button>
              </div>
            )}

            {/* Main Grid: Live Mastery Radar + Skill Breakdown */}
            <div className="radar-grid">
              <div className="radar-panel">
                <div className="panel-header">
                  <div>
                    <h3>Live Skill Map</h3>
                    <p className="panel-sub">
                      Visualizing live skill progress. Watch this update as your child solves problems!
                    </p>
                  </div>
                  <div className="overall-badge">
                    <span>{avgMastery}% Overall</span>
                  </div>
                </div>

                <div className="radar-container">
                  {detailsLoading && skills.length === 0 ? (
                    <div className="radar-empty">Loading skill map…</div>
                  ) : detailsError ? (
                    <div className="radar-error-box">
                      <p>⚠️ {detailsError}</p>
                      {selectedChildId && (
                        <button
                          className="btn btn-sm btn-outline-violet"
                          onClick={() => refreshChildDetails(selectedChildId)}
                          style={{ marginTop: '8px' }}
                        >
                          Retry Loading Details
                        </button>
                      )}
                    </div>
                  ) : skills.length > 0 ? (
                    <MasteryRadar skills={skills} showBars={false} />
                  ) : (
                    <div className="radar-empty">No skill records available for this student yet.</div>
                  )}
                </div>
              </div>

              {/* Skills breakdown — enriched with human-readable metadata */}
              <div className="skills-panel">
                <div className="panel-header">
                  <h3>Math Skills</h3>
                  <span className="skills-badge">{skills.length} Skills</span>
                </div>

                <div className="skills-list">
                  {skills.map((s) => {
                    const meta = getSkillMeta(s.skill_id)
                    const tierInfo = getMasteryTierInfo(s.mastery_prob)
                    const pct = Math.round(s.mastery_prob * 100)
                    return (
                      <div
                        key={s.skill_id}
                        className="skill-item"
                        style={{ borderColor: tierInfo.borderColor }}
                      >
                        {/* Top row: domain badge + std code + tier badge */}
                        <div className="skill-item-top">
                          <div className="skill-item-badges">
                            <span
                              className="skill-domain-badge"
                              style={{
                                color: meta.domainColor,
                                background: `${meta.domainColor}18`,
                                border: `1px solid ${meta.domainColor}35`,
                              }}
                            >
                              {meta.grade} · {meta.domainAbbr}
                            </span>
                            <span className="skill-std-code">{meta.shortTitle || meta.title}</span>
                          </div>
                          <span
                            className="skill-tier-badge"
                            style={{
                              color: tierInfo.color,
                              background: tierInfo.bgColor,
                              border: `1px solid ${tierInfo.borderColor}`,
                            }}
                          >
                            {tierInfo.icon} {tierInfo.label}
                          </span>
                        </div>

                        {/* Title + Percent */}
                        <div className="skill-item-main">
                          <span className="skill-name-text">{meta.title}</span>
                          <span className="skill-percent" style={{ color: tierInfo.color }}>{pct}%</span>
                        </div>

                        {/* Gradient progress bar */}
                        <div className="progress-track">
                          <div
                            className="progress-fill"
                            style={{
                              width: `${pct}%`,
                              background: getBarGradient(tierInfo.tier),
                            }}
                          />
                        </div>

                        {/* Concept description */}
                        <p className="skill-desc">{meta.description}</p>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            {/* Session History & Recent Problem Attempts */}
            <div className="history-section">
              <div className="panel-header">
                <div>
                  <h3>Session History & Problem Log</h3>
                  <p className="panel-sub">Recent Socratic conversations and step-by-step work checks</p>
                </div>
              </div>

              <div className="history-grid">
                <div className="history-column">
                  <h4>Recent Sessions</h4>
                  {childDetails?.sessions?.length > 0 ? (
                    <div className="history-list">
                      {childDetails.sessions.map((sess: any, i: number) => (
                        <div key={sess.id || i} className="session-history-item">
                          <div className="session-icon">
                            <span className="session-bullet">•</span>
                          </div>
                          <div className="session-meta">
                            <span className="session-date">
                              {sess.started_at
                                ? new Date(sess.started_at).toLocaleDateString('en-US', {
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  })
                                : 'Recent session'}
                            </span>
                            <span className="session-tag">Math Tutoring Session</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-history">No sessions recorded yet. Launch a session to start learning!</div>
                  )}
                </div>

                <div className="history-column">
                  <h4>Recent Problem Diagnoses</h4>
                  {childDetails?.recent_events?.length > 0 ? (
                    <div className="events-list">
                      {childDetails.recent_events.map((evt: any, i: number) => (
                        <div key={evt.id || i} className="event-history-item">
                          <div className={`event-status ${evt.is_correct ? 'event-status--correct' : 'event-status--attempt'}`}>
                            <span className="status-text">{evt.is_correct ? 'Correct' : 'Needs Work'}</span>
                          </div>
                          <div className="event-info">
                            <h5>{evt.problems?.title || 'Math Practice'}</h5>
                            <p className="event-problem">{evt.problems?.text || 'Student worked through problem step.'}</p>
                            {evt.agent_response && (
                              <p className="event-tutor-guide">
                                <strong>Tutor guidance:</strong> {evt.agent_response}
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-history">Problem attempts will appear here in real-time as your child practices.</div>
                  )}
                </div>
              </div>
            </div>

            {/* Student Privacy & Parental Data Rights Card */}
            <div className="privacy-trust-card">
              <div className="privacy-trust-content">
                <div className="privacy-trust-header">
                  <span className="privacy-shield-icon">🛡️</span>
                  <div>
                    <h4>Student Data Privacy & Parental Control</h4>
                    <p>
                      In alignment with student privacy best practices, parents have full control over recorded learning history.
                      You can purge all past practice sessions, OCR diagnosis attempts, and child associations at any time.
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-danger-outline"
                  onClick={() => setShowDeleteModal(true)}
                >
                  Delete Activity Data
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="no-child-selected">
            <div className="no-child-card">
              <h3>No Child Linked Yet</h3>
              <p>Add your child’s email to start viewing their real-time math mastery radar and learning history.</p>
              <button className="btn btn-violet" onClick={() => setShowAddModal(true)}>
                Link Your First Child
              </button>
            </div>
          </div>
        )}
      </main>

      {/* Add Child Modal */}
      {showAddModal && (
        <div className="modal-backdrop" onClick={() => setShowAddModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-box">
                <h3>Link Child to Your Dashboard</h3>
              </div>
              <button
                className="close-btn"
                onClick={() => setShowAddModal(false)}
                title="Close modal"
                aria-label="Close modal"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>

            <p className="modal-sub">
              Enter your child's student email address or their unique Student Code (found in their math practice header). Once linked, their live learning journey and skill mastery will sync directly to your radar in real-time.
            </p>

            <form onSubmit={handleAddChild} className="add-child-form">
              <div className="form-group">
                <label>Child's Email or Student Code *</label>
                <input
                  type="text"
                  className="input modal-input"
                  placeholder="e.g. alex@example.com or paste Student Code"
                  value={newChildEmail}
                  onChange={(e) => {
                    setNewChildEmail(e.target.value)
                    setAddError('')
                  }}
                  autoFocus
                  required
                />
              </div>

              <div className="form-group">
                <label>Child's Name (Optional)</label>
                <input
                  type="text"
                  className="input modal-input"
                  placeholder="e.g. Alex"
                  value={newChildName}
                  onChange={(e) => {
                    setNewChildName(sanitizeNameInput(e.target.value))
                    setAddError('')
                  }}
                  maxLength={50}
                />
              </div>

              {addError && <p className="error-msg">{addError}</p>}

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setShowAddModal(false)}
                  disabled={addingChild}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-violet" disabled={addingChild}>
                  {addingChild ? 'Linking…' : 'Link Child'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Data Confirmation Modal */}
      {showDeleteModal && (
        <div className="modal-backdrop" onClick={() => !deletingData && setShowDeleteModal(false)}>
          <div className="modal-card modal-card--danger" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-box">
                <h3 className="text-danger">Purge Activity & Learning History</h3>
              </div>
              <button
                className="close-btn"
                onClick={() => !deletingData && setShowDeleteModal(false)}
                title="Close modal"
                disabled={deletingData}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>

            <p className="modal-sub">
              Are you sure you want to permanently delete all tutoring session logs, problem diagnoses, and student event records? This action cannot be undone.
            </p>

            {deleteSuccessMsg && (
              <div className="success-banner">
                ✓ {deleteSuccessMsg}
              </div>
            )}

            <div className="modal-actions">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setShowDeleteModal(false)}
                disabled={deletingData}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={handleDeleteData}
                disabled={deletingData}
              >
                {deletingData ? 'Purging Records…' : 'Yes, Delete All Data'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Avatar Selection & Profile Modal */}
      <AvatarModal
        isOpen={showAvatarModal}
        onClose={() => setShowAvatarModal(false)}
        onSave={async (newAvatar) => {
          await updateAvatar(newAvatar)
        }}
        currentAvatar={avatar}
        name={user?.user_metadata?.name || 'Parent'}
        role={role || 'parent'}
      />
    </div>
  )
}
