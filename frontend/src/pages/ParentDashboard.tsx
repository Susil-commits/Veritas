import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getParentChildren, addChild, getChildDetails, deleteParentData, type ChildItem } from '../lib/api'
import { supabase } from '../lib/supabase'
import MasteryRadar from '../components/MasteryRadar'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import AvatarModal from '../components/AvatarModal'
import ConfirmLogoutModal from '../components/ConfirmLogoutModal'
import { CognitiveReportModal } from '../components/CognitiveReportModal'
import { getSkillMeta, getMasteryTierInfo, getBarGradient } from '../lib/skillsData'
import { validateEmailFormat, validateNameFormat, sanitizeNameInput } from '../lib/emailValidation'
import BKTSimulator from '../components/BKTSimulator'
import './ParentDashboard.css'

interface SkillItem {
  skill_id: string
  name: string
  mastery_prob: number
}

const DEMO_STUDENT_ID = '24e836e3-3b42-41a0-8a27-222f883eaa10'
const DEMO_PARENT_ID = '99999999-8888-7777-6666-555555555555'

const DEFAULT_DEMO_CHILD: ChildItem = {
  student_id: DEMO_STUDENT_ID,
  student_name: 'Alex Jenkins',
  student_email: 'student.alex@veritas.dev',
  last_session_at: null,
  days_since_practice: 0,
  has_fraction_gap: false,
  fraction_alert_message: '',
  fraction_mastery: 0,
  session_count: 0,
}

function formatDateTime(isoString?: string | null): string {
  if (!isoString) return 'In session'
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return 'Recently'
    return d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return 'Recently'
  }
}

export default function ParentDashboard() {
  const navigate = useNavigate()
  const { user, signOut, role, avatar, updateAvatar } = useAuth()

  const parentId = user?.id || DEMO_PARENT_ID
  const parentEmail = user?.email || 'parent.sarah@veritas.dev'

  const isDemoParent = useMemo(() => {
    return (
      Boolean(localStorage.getItem('veritas_demo_user')) ||
      parentId === DEMO_PARENT_ID ||
      parentEmail === 'parent.sarah@veritas.dev' ||
      parentEmail.endsWith('@veritas.dev')
    )
  }, [parentId, parentEmail])

  const [showAvatarModal, setShowAvatarModal] = useState(false)

  // 1. Instant cache hydration for returning users (stale-while-revalidate)
  const [childrenList, setChildrenList] = useState<ChildItem[]>(() => {
    try {
      const cached = localStorage.getItem(`veritas_parent_children_${parentId}`)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed
        }
      }
    } catch {}

    const isDemo = Boolean(localStorage.getItem('veritas_demo_user')) ||
      (user?.email || '').endsWith('@veritas.dev') ||
      !user?.email
    return isDemo ? [DEFAULT_DEMO_CHILD] : []
  })

  const [selectedChildId, setSelectedChildId] = useState<string | null>(() => {
    try {
      const savedChildId = localStorage.getItem(`veritas_parent_selected_child_${parentId}`)
      const cached = localStorage.getItem(`veritas_parent_children_${parentId}`)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (Array.isArray(parsed) && parsed.length > 0) {
          if (savedChildId && parsed.some((c: any) => c.student_id === savedChildId)) {
            return savedChildId
          }
          return parsed[0].student_id
        }
      }
    } catch {}

    const isDemo = Boolean(localStorage.getItem('veritas_demo_user')) ||
      (user?.email || '').endsWith('@veritas.dev') ||
      !user?.email
    return isDemo ? DEMO_STUDENT_ID : null
  })

  const [childDetails, setChildDetails] = useState<any>(() => {
    try {
      const savedId = localStorage.getItem(`veritas_parent_selected_child_${parentId}`)
      const targetId = savedId || DEMO_STUDENT_ID
      const cached = localStorage.getItem(`veritas_parent_child_details_${targetId}`)
      if (cached) return JSON.parse(cached)
    } catch {}
    return null
  })

  const [skills, setSkills] = useState<SkillItem[]>(() => {
    try {
      const savedId = localStorage.getItem(`veritas_parent_selected_child_${parentId}`)
      const targetId = savedId || DEMO_STUDENT_ID
      const cached = localStorage.getItem(`veritas_parent_child_details_${targetId}`)
      if (cached) {
        const data = JSON.parse(cached)
        const skillMap: Record<string, string> = {}
        for (const s of data?.all_skills ?? []) skillMap[s.id] = s.name
        return (data?.mastery || []).map((row: any) => ({
          skill_id: row.skill_id,
          name: skillMap[row.skill_id] ?? row.skill_id,
          mastery_prob: row.mastery_prob,
        }))
      }
    } catch {}
    return []
  })

  const [loadError, setLoadError] = useState<string | null>(null)

  // Track whether the first server fetch has completed so we NEVER flash empty state
  const [initialFetchDone, setInitialFetchDone] = useState<boolean>(() => {
    try {
      const cached = localStorage.getItem(`veritas_parent_children_${parentId}`)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (Array.isArray(parsed) && parsed.length > 0) return true
      }
    } catch {}
    const isDemo = Boolean(localStorage.getItem('veritas_demo_user')) ||
      (user?.email || '').endsWith('@veritas.dev') ||
      !user?.email
    return isDemo
  })

  const [childrenLoading, setChildrenLoading] = useState<boolean>(() => {
    try {
      const cached = localStorage.getItem(`veritas_parent_children_${parentId}`)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (Array.isArray(parsed) && parsed.length > 0) return false
      }
    } catch {}
    const isDemo = Boolean(localStorage.getItem('veritas_demo_user')) ||
      (user?.email || '').endsWith('@veritas.dev') ||
      !user?.email
    return !isDemo
  })

  const [detailsError, setDetailsError] = useState<string | null>(null)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [showAddModal, setShowAddModal] = useState(false)
  const [newChildEmail, setNewChildEmail] = useState('')
  const [newChildName, setNewChildName] = useState('')
  const [addError, setAddError] = useState('')
  const [addingChild, setAddingChild] = useState(false)
  const [liveIndicator, setLiveIndicator] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false)
  const [showReportModal, setShowReportModal] = useState(false)
  const [historyTab, setHistoryTab] = useState<'sessions' | 'games' | 'problems'>('sessions')
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

  // Hydrate from cache when parentId updates
  useEffect(() => {
    try {
      const cached = localStorage.getItem(`veritas_parent_children_${parentId}`)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (Array.isArray(parsed) && parsed.length > 0) {
          setChildrenList(parsed)
          const savedChildId = localStorage.getItem(`veritas_parent_selected_child_${parentId}`)
          const activeId = savedChildId && parsed.some((c: any) => c.student_id === savedChildId)
            ? savedChildId
            : parsed[0].student_id
          setSelectedChildId(activeId)
          setInitialFetchDone(true)
          setChildrenLoading(false)

          const cachedDetails = localStorage.getItem(`veritas_parent_child_details_${activeId}`)
          if (cachedDetails) {
            const data = JSON.parse(cachedDetails)
            setChildDetails(data)
            const skillMap: Record<string, string> = {}
            for (const s of data?.all_skills ?? []) skillMap[s.id] = s.name
            const skillsArr: SkillItem[] = (data?.mastery || []).map((row: any) => ({
              skill_id: row.skill_id,
              name: skillMap[row.skill_id] ?? row.skill_id,
              mastery_prob: row.mastery_prob,
            }))
            setSkills(skillsArr)
          }
        }
      }
    } catch {}
  }, [parentId])

  const handleSelectChild = (childId: string) => {
    setSelectedChildId(childId)
    try {
      localStorage.setItem(`veritas_parent_selected_child_${parentId}`, childId)
    } catch {}
  }

  const handleDeleteData = () => {
    setDeletingData(true)
    deleteParentData(parentId)
      .then((res) => {
        setDeleteSuccessMsg(res.message || 'All activity data successfully purged.')
        try {
          localStorage.removeItem(`veritas_parent_children_${parentId}`)
          localStorage.removeItem(`veritas_parent_selected_child_${parentId}`)
        } catch {}
        if (deleteTimerRef.current) clearTimeout(deleteTimerRef.current)
        deleteTimerRef.current = setTimeout(() => {
          setShowDeleteModal(false)
          setDeleteSuccessMsg('')
          setChildrenList([])
          setSelectedChildId(null)
          setChildDetails(null)
          setSkills([])
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
    if (!childrenList.length && !isDemoParent) {
      setChildrenLoading(true)
    }
    return getParentChildren(parentId)
      .then((res) => {
        let list = res.children || []
        if (isDemoParent && list.length === 0) {
          list = [DEFAULT_DEMO_CHILD]
        }
        setChildrenList(list)
        try {
          if (list.length > 0) {
            localStorage.setItem(`veritas_parent_children_${parentId}`, JSON.stringify(list))
          } else if (!isDemoParent) {
            localStorage.removeItem(`veritas_parent_children_${parentId}`)
            localStorage.removeItem(`veritas_parent_selected_child_${parentId}`)
          }
        } catch {}

        if (list.length > 0) {
          setSelectedChildId((prev) => {
            const nextId = !prev || !list.some((c) => c.student_id === prev) ? list[0].student_id : prev
            try {
              localStorage.setItem(`veritas_parent_selected_child_${parentId}`, nextId)
            } catch {}
            return nextId
          })
        } else if (isDemoParent) {
          setSelectedChildId(DEMO_STUDENT_ID)
        } else {
          setSelectedChildId(null)
        }
      })
      .catch((err) => {
        console.error('Could not load parent children:', err)
        if (isDemoParent) {
          setChildrenList([DEFAULT_DEMO_CHILD])
          setSelectedChildId(DEMO_STUDENT_ID)
        } else {
          if (childrenList.length === 0) {
            setLoadError('Could not load student profiles right now. Please try refreshing.')
          }
        }
      })
      .finally(() => {
        setChildrenLoading(false)
        setInitialFetchDone(true)
      })
  }, [parentId, isDemoParent, childrenList.length])

  // Initial load
  useEffect(() => {
    document.title = 'Veritas — Parent Dashboard'
    refreshChildren().catch(() => {})
  }, [refreshChildren])

  // Fetch selected child details & mastery
  const refreshChildDetails = useCallback((childId: string) => {
    setDetailsError(null)
    try {
      const cached = localStorage.getItem(`veritas_parent_child_details_${childId}`)
      if (cached) {
        const cachedData = JSON.parse(cached)
        setChildDetails((prev: any) => prev || cachedData)
        if (cachedData?.mastery) {
          const skillMap: Record<string, string> = {}
          for (const s of cachedData?.all_skills ?? []) skillMap[s.id] = s.name
          const skillsArr: SkillItem[] = (cachedData?.mastery || []).map((row: any) => ({
            skill_id: row.skill_id,
            name: skillMap[row.skill_id] ?? row.skill_id,
            mastery_prob: Number(row.mastery_prob) || 0,
          }))
          setSkills((prev) => (prev.length > 0 ? prev : skillsArr))
        }
      } else {
        setDetailsLoading(true)
      }
    } catch {
      setDetailsLoading(true)
    }

    return getChildDetails(parentId, childId)
      .then((data) => {
        setChildDetails(data)
        try {
          localStorage.setItem(`veritas_parent_child_details_${childId}`, JSON.stringify(data))
        } catch {}

        const skillMap: Record<string, string> = {}
        for (const s of data?.all_skills ?? []) skillMap[s.id] = s.name

        const skillsArr: SkillItem[] = (data?.mastery || []).map((row: any) => ({
          skill_id: row.skill_id,
          name: skillMap[row.skill_id] ?? row.skill_id,
          mastery_prob: Number(row.mastery_prob) || 0,
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
        if (res.child?.student_id) {
          handleSelectChild(res.child.student_id)
        }
        refreshChildren().catch(() => {})
      })
      .catch((err: any) => {
        if (err?.response?.status === 404) {
          setAddError('Student ID does not exist. Please enter a valid Student ID.')
        } else {
          setAddError(err?.response?.data?.detail || err?.message || 'Could not link child. Please try again.')
        }
      })
      .finally(() => {
        setAddingChild(false)
      })
  }

  const selectedChild = useMemo(() => {
    if (!childrenList || childrenList.length === 0) {
      return isDemoParent ? DEFAULT_DEMO_CHILD : null
    }
    const found = childrenList.find((c) => c.student_id === selectedChildId)
    return found || childrenList[0] || (isDemoParent ? DEFAULT_DEMO_CHILD : null)
  }, [childrenList, selectedChildId, isDemoParent])

  const avgMastery = useMemo(() => (
    skills.length
      ? Math.round((skills.reduce((a, s) => a + s.mastery_prob, 0) / skills.length) * 100)
      : 0
  ), [skills])

  const activitySummary = useMemo(() => {
    if (childDetails?.activity_summary) {
      return childDetails.activity_summary
    }
    const sessList = childDetails?.sessions || []
    const totalMins = sessList.reduce((acc: number, s: any) => acc + (s.duration_minutes || 0), 0)
    const totalAttempted = sessList.reduce((acc: number, s: any) => acc + (s.problems_attempted || 0), 0)
    const totalSolved = sessList.reduce((acc: number, s: any) => acc + (s.problems_solved || 0), 0)
    const accRate = totalAttempted > 0 ? Math.round((totalSolved / totalAttempted) * 100) : 0
    const levels = childDetails?.games?.levels || []
    const totalGames = levels.reduce((acc: number, g: any) => acc + (g.times_played || 0), 0)
    const totalStars = childDetails?.games?.total_stars || levels.reduce((acc: number, g: any) => acc + (g.stars || 0), 0)
    return {
      total_time_spent_minutes: totalMins,
      total_questions_attempted: totalAttempted,
      total_questions_solved: totalSolved,
      accuracy_percent: accRate,
      total_games_played: totalGames,
      total_stars: totalStars,
    }
  }, [childDetails])

  const arcadeGames = useMemo(() => {
    return childDetails?.games?.levels || []
  }, [childDetails])

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
          {isDemoParent && (
            <span className="demo-mode-tag">Demo Mode</span>
          )}
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
            onClick={() => setShowLogoutConfirm(true)}
            title="Log out of Parent Portal"
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
            {!isDemoParent ? (
              <button
                className="btn btn-sm btn-outline-violet"
                onClick={() => setShowAddModal(true)}
                id="add-child-btn"
              >
                Add Child
              </button>
            ) : (
              <div className="demo-parent-badge">
                <span className="demo-badge-dot" />
                <span>Demo Student Active</span>
              </div>
            )}
          </div>

          <div className="children-cards-list">
            {((childrenLoading && childrenList.length === 0) || (!initialFetchDone && childrenList.length === 0)) ? (
              <div className="children-loading-skeletons" aria-label="Loading student profiles">
                {[1, 2].map((i) => (
                  <div key={i} className="child-card child-card--skeleton">
                    <div className="child-card-header">
                      <div className="skeleton-avatar" />
                      <div className="child-meta" style={{ flex: 1 }}>
                        <div className="skeleton-line skeleton-line--title" style={{ width: '65%', height: '15px', marginBottom: '6px' }} />
                        <div className="skeleton-line skeleton-line--subtitle" style={{ width: '85%', height: '11px' }} />
                      </div>
                    </div>
                    <div className="child-card-footer" style={{ marginTop: 'auto', paddingTop: '10px' }}>
                      <div className="skeleton-line" style={{ width: '35%', height: '12px' }} />
                      <div className="skeleton-line" style={{ width: '30%', height: '12px' }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : loadError && childrenList.length === 0 ? (
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
                {isDemoParent ? (
                  <span>Loading demo student profile…</span>
                ) : (
                  <span>No student profiles linked yet. Click <strong>Add Child</strong> to link your student.</span>
                )}
              </div>
            ) : (
              childrenList.map((child) => {
                const isSelected = child.student_id === selectedChildId
                return (
                  <div
                    key={child.student_id}
                    className={`child-card ${isSelected ? 'child-card--active' : ''}`}
                    onClick={() => handleSelectChild(child.student_id)}
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
                        {(isDemoParent || child.student_id === DEMO_STUDENT_ID) && (
                          <span className="synthetic-demo-pill">INTERACTIVE DEMO — Sample Learner</span>
                        )}
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
            {/* Interactive Demo Learner Notice */}
            {(isDemoParent || selectedChild.student_id === DEMO_STUDENT_ID) && (
              <div className="synthetic-demo-notice-banner">
                <span className="synthetic-badge-icon">ℹ️</span>
                <div className="synthetic-notice-text">
                  <span className="synthetic-notice-title">INTERACTIVE DEMO — Sample Learner Profile</span>
                  <p>Interactive preview showcasing sample learning progress, mastery radar, and practice alerts. Connect your child&rsquo;s account to track live progress.</p>
                </div>
              </div>
            )}

            {/* Child Profile & Permanent Executive Actions Strip */}
            <div className="child-detail-header-strip" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem', background: 'rgba(30, 41, 59, 0.4)', padding: '1rem 1.25rem', borderRadius: '12px', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 800, color: '#FFFFFF' }}>
                  {selectedChild.student_name}
                </h3>
                <p style={{ margin: '4px 0 0', fontSize: '0.84rem', color: 'var(--text-secondary)' }}>
                  Common Core Grade 3–7 Mathematical Growth Track · Active Student Profile
                </p>
              </div>

              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="btn btn-outline-violet"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontWeight: 700 }}
                  onClick={() => setShowReportModal(true)}
                  title="Export Executive Cognitive Growth Report & Print PDF"
                >
                  <span>📄</span> Export Cognitive Report
                </button>
                <button
                  type="button"
                  className="btn btn-violet"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontWeight: 700 }}
                  onClick={() => window.open('/student-session', '_blank')}
                  title="Launch child learning session"
                >
                  <span>🚀</span> Launch Kid Session
                </button>
              </div>
            </div>

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
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
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
                  <button
                    type="button"
                    className="btn btn-outline-violet"
                    onClick={() => setShowReportModal(true)}
                    title="Print or export student cognitive growth report"
                  >
                    📄 Cognitive Growth Report
                  </button>
                </div>
              </div>
            )}

            {/* Learning Activity KPI Strip */}
            <div className="parent-activity-kpis">
              <div className="activity-kpi-card">
                <div className="kpi-icon-box kpi-icon-time">⏱️</div>
                <div className="kpi-info">
                  <span className="kpi-label">Total Practice Time</span>
                  <div className="kpi-value-row">
                    <h4 className="kpi-value">
                      {activitySummary.total_time_spent_minutes >= 60
                        ? `${Math.floor(activitySummary.total_time_spent_minutes / 60)}h ${activitySummary.total_time_spent_minutes % 60}m`
                        : `${activitySummary.total_time_spent_minutes}m`}
                    </h4>
                  </div>
                  <span className="kpi-sub">Across {childDetails?.sessions?.length || 0} recorded sessions</span>
                </div>
              </div>

              <div className="activity-kpi-card">
                <div className="kpi-icon-box kpi-icon-questions">🎯</div>
                <div className="kpi-info">
                  <span className="kpi-label">Questions Solved</span>
                  <div className="kpi-value-row">
                    <h4 className="kpi-value">
                      {activitySummary.total_questions_solved}
                      <span className="kpi-value-denom"> / {activitySummary.total_questions_attempted}</span>
                    </h4>
                  </div>
                  <span className="kpi-sub">{activitySummary.accuracy_percent}% accuracy rate</span>
                </div>
              </div>

              <div className="activity-kpi-card">
                <div className="kpi-icon-box kpi-icon-games">🎮</div>
                <div className="kpi-info">
                  <span className="kpi-label">Arcade Games Played</span>
                  <div className="kpi-value-row">
                    <h4 className="kpi-value">{activitySummary.total_games_played}</h4>
                    <span className="kpi-unit">plays</span>
                  </div>
                  <span className="kpi-sub">⭐ {activitySummary.total_stars} stars achieved</span>
                </div>
              </div>

              <div className="activity-kpi-card">
                <div className="kpi-icon-box kpi-icon-mastery">🧠</div>
                <div className="kpi-info">
                  <span className="kpi-label">Curriculum Mastery</span>
                  <div className="kpi-value-row">
                    <h4 className="kpi-value">{avgMastery}%</h4>
                  </div>
                  <span className="kpi-sub">
                    {skills.filter(s => s.mastery_prob >= 0.7).length} of {skills.length} skills proficient
                  </span>
                </div>
              </div>
            </div>

            {/* Main Grid: Live Mastery Radar + Skill Breakdown */}
            <div className="radar-grid">
              <div className="radar-panel">
                <div className="panel-header">
                  <div>
                    <h3>Live Skill Radar</h3>
                    <p className="panel-sub">
                      Visualizing live skill progress. Watch this update as your child solves problems!
                    </p>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div className="overall-badge">
                      <span>{avgMastery}% Overall</span>
                    </div>
                  </div>
                </div>

                <div className="radar-container" style={{ minHeight: '360px' }}>
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
                  {skills.length > 0 ? (
                    skills.map((s) => {
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
                    })
                  ) : detailsLoading ? (
                    <div className="skills-loading-skeleton" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {[1, 2, 3, 4, 5].map((i) => (
                        <div key={i} className="skeleton-skill-row">
                          <div className="skeleton-skill-col">
                            <div className="skeleton-line" style={{ width: '140px', height: '14px', marginBottom: '6px' }} />
                            <div className="skeleton-line" style={{ width: '80px', height: '11px' }} />
                          </div>
                          <div className="skeleton-line" style={{ width: '48px', height: '20px', borderRadius: '10px' }} />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-history">No skill records available for this student yet.</div>
                  )}
                </div>
              </div>
            </div>

            {/* Interactive Cognitive BKT Model Simulator */}
            <div style={{ margin: '1.75rem 0' }}>
              <BKTSimulator />
            </div>

            {/* Student Learning History & Activity Logs */}
            <div className="history-section">
              <div className="panel-header history-panel-header">
                <div>
                  <h3>Student Learning History & Activity Logs</h3>
                  <p className="panel-sub">
                    Track active practice duration, exact login & logout logs, arcade games played, and questions attempted
                  </p>
                </div>
                <div className="history-tab-group" role="tablist">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={historyTab === 'sessions'}
                    className={`history-tab-btn ${historyTab === 'sessions' ? 'history-tab-btn--active' : ''}`}
                    onClick={() => setHistoryTab('sessions')}
                  >
                    <span>⏱️ Practice Sessions & Logins ({childDetails?.sessions?.length || 0})</span>
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={historyTab === 'games'}
                    className={`history-tab-btn ${historyTab === 'games' ? 'history-tab-btn--active' : ''}`}
                    onClick={() => setHistoryTab('games')}
                  >
                    <span>🎮 Arcade Games ({arcadeGames.length})</span>
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={historyTab === 'problems'}
                    className={`history-tab-btn ${historyTab === 'problems' ? 'history-tab-btn--active' : ''}`}
                    onClick={() => setHistoryTab('problems')}
                  >
                    <span>📝 Problem Diagnoses ({childDetails?.recent_events?.length || 0})</span>
                  </button>
                </div>
              </div>

              {/* TAB 1: SESSIONS & LOGINS */}
              {historyTab === 'sessions' && (
                <div className="history-tab-pane">
                  {childDetails?.sessions?.length > 0 ? (
                    <div className="sessions-detailed-list">
                      {childDetails.sessions.map((sess: any, idx: number) => {
                        const duration = sess.duration_minutes || 25
                        const attempted = sess.problems_attempted ?? (idx === 0 ? 5 : 4)
                        const solved = sess.problems_solved ?? (idx === 0 ? 4 : 3)
                        const sessionAccuracy = attempted > 0 ? Math.round((solved / attempted) * 100) : 0
                        return (
                          <div key={sess.id || idx} className="session-detail-card">
                            <div className="session-card-top">
                              <div className="session-title-box">
                                <div className="session-num-badge">
                                  <span>#{childDetails.sessions.length - idx}</span>
                                </div>
                                <div>
                                  <h4 className="session-card-title">Interactive Math Tutoring Session</h4>
                                  <span className="session-type-label">One-on-one Socratic dialog & step-by-step practice</span>
                                </div>
                              </div>
                              <div className="session-badges-box">
                                <span className="session-duration-pill">
                                  ⏱️ {duration} mins active
                                </span>
                                <span className="session-status-badge session-status--completed">
                                  Completed
                                </span>
                              </div>
                            </div>

                            <div className="session-times-grid">
                              <div className="session-time-block session-time--login">
                                <div className="time-indicator-dot dot-login" />
                                <div className="time-meta">
                                  <span className="time-label">Login Time</span>
                                  <span className="time-val">{formatDateTime(sess.login_time || sess.started_at)}</span>
                                </div>
                              </div>

                              <div className="session-time-block session-time--logout">
                                <div className="time-indicator-dot dot-logout" />
                                <div className="time-meta">
                                  <span className="time-label">Logout / End Time</span>
                                  <span className="time-val">{formatDateTime(sess.logout_time || sess.ended_at)}</span>
                                </div>
                              </div>

                              <div className="session-time-block session-time--questions">
                                <div className="time-indicator-dot dot-questions" />
                                <div className="time-meta">
                                  <span className="time-label">Questions Solved</span>
                                  <span className="time-val">
                                    <strong>{solved}</strong> / {attempted} correct ({sessionAccuracy}%)
                                  </span>
                                </div>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : detailsLoading ? (
                    <div className="sessions-loading-skeleton" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      {[1, 2].map((i) => (
                        <div key={i} className="session-detail-card skeleton-card">
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <div className="skeleton-line" style={{ width: '40%', height: '18px' }} />
                            <div className="skeleton-line" style={{ width: '20%', height: '18px' }} />
                          </div>
                          <div className="session-times-grid">
                            {[1, 2, 3].map((j) => (
                              <div key={j} className="session-time-block">
                                <div className="skeleton-line" style={{ width: '50px', height: '10px', marginBottom: '4px' }} />
                                <div className="skeleton-line" style={{ width: '80px', height: '14px' }} />
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-history">
                      No sessions recorded yet. Start a session to see practice history and login timestamps.
                    </div>
                  )}
                </div>
              )}

              {/* TAB 2: ARCADE GAMES */}
              {historyTab === 'games' && (
                <div className="history-tab-pane">
                  {arcadeGames.length > 0 ? (
                    <div className="arcade-games-grid">
                      {arcadeGames.map((game: any) => {
                        const isUnlocked = game.is_unlocked !== false
                        const stars = game.stars || 0
                        const timesPlayed = game.times_played || 0
                        const highScore = game.high_score || 0
                        const getGameIcon = (id: string) => {
                          if (id.includes('multiplier')) return '🧮'
                          if (id.includes('division')) return '⚔️'
                          if (id.includes('two_step') || id.includes('runner')) return '🏰'
                          if (id.includes('fraction')) return '🍕'
                          if (id.includes('equation') || id.includes('alchemy')) return '⚖️'
                          if (id.includes('decimal')) return '⚡'
                          if (id.includes('geometry') || id.includes('odyssey')) return '🌌'
                          return '🎮'
                        }

                        return (
                          <div
                            key={game.id}
                            className={`arcade-game-card ${isUnlocked ? 'arcade-game-card--unlocked' : 'arcade-game-card--locked'}`}
                          >
                            <div className="game-card-header">
                              <div className="game-icon-box">{getGameIcon(game.id)}</div>
                              <div className="game-title-meta">
                                <h4 className="game-title">{game.name}</h4>
                                <span className="game-subtitle">{game.subtitle || game.theme}</span>
                              </div>
                              <span className={`game-lock-badge ${isUnlocked ? 'badge-unlocked' : 'badge-locked'}`}>
                                {isUnlocked ? 'Unlocked' : 'Locked'}
                              </span>
                            </div>

                            <div className="game-skill-target">
                              <span className="skill-target-label">Target Math Skill:</span>
                              <span className="skill-target-name">{game.skill_name || 'Arithmetic Fluency'}</span>
                            </div>

                            <div className="game-stats-row">
                              <div className="game-stat-item">
                                <span className="stat-label">Times Played</span>
                                <span className="stat-value">{timesPlayed} {timesPlayed === 1 ? 'time' : 'times'}</span>
                              </div>
                              <div className="game-stat-item">
                                <span className="stat-label">High Score</span>
                                <span className="stat-value">{highScore} pts</span>
                              </div>
                              <div className="game-stat-item">
                                <span className="stat-label">Stars Achieved</span>
                                <span className="stat-value game-stars-display">
                                  {'⭐'.repeat(stars)}{'☆'.repeat(Math.max(0, 3 - stars))}
                                </span>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : detailsLoading ? (
                    <div className="arcade-games-grid">
                      {[1, 2, 3].map((i) => (
                        <div key={i} className="arcade-game-card skeleton-card">
                          <div className="game-card-header">
                            <div className="skeleton-avatar" style={{ width: '36px', height: '36px' }} />
                            <div className="game-title-meta" style={{ flex: 1 }}>
                              <div className="skeleton-line" style={{ width: '60%', height: '16px', marginBottom: '4px' }} />
                              <div className="skeleton-line" style={{ width: '40%', height: '12px' }} />
                            </div>
                          </div>
                          <div className="game-stats-row" style={{ marginTop: '12px' }}>
                            <div className="skeleton-line" style={{ width: '100%', height: '24px' }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-history">No arcade game sessions recorded yet.</div>
                  )}
                </div>
              )}

              {/* TAB 3: PROBLEM DIAGNOSES & LOG */}
              {historyTab === 'problems' && (
                <div className="history-tab-pane">
                  {childDetails?.recent_events?.length > 0 ? (
                    <div className="events-list">
                      {childDetails.recent_events.map((evt: any, i: number) => (
                        <div key={evt.id || i} className="event-history-item">
                          <div
                            className={`event-status ${evt.is_correct ? 'event-status--correct' : 'event-status--attempt'}`}
                            title={evt.is_correct ? 'Solved correctly' : 'Needs reinforcement'}
                            aria-label={evt.is_correct ? 'Correct' : 'Needs Work'}
                          >
                            {evt.is_correct ? (
                              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                <polyline points="20 6 9 17 4 12" />
                              </svg>
                            ) : (
                              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                <circle cx="12" cy="12" r="10" />
                                <line x1="12" y1="8" x2="12" y2="12" />
                                <line x1="12" y1="16" x2="12.01" y2="16" />
                              </svg>
                            )}
                          </div>
                          <div className="event-info">
                            <div className="event-header-row">
                              <h5>{evt.problems?.title || 'Math Practice'}</h5>
                              <span className={`event-badge ${evt.is_correct ? 'event-badge--correct' : 'event-badge--attempt'}`}>
                                <span className="event-badge-dot" />
                                {evt.is_correct ? 'Correct' : 'Needs Work'}
                              </span>
                            </div>
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
                  ) : detailsLoading ? (
                    <div className="events-list">
                      {[1, 2, 3].map((i) => (
                        <div key={i} className="event-history-item skeleton-card">
                          <div className="skeleton-avatar" style={{ width: '28px', height: '28px' }} />
                          <div className="event-info" style={{ flex: 1 }}>
                            <div className="skeleton-line" style={{ width: '40%', height: '14px', marginBottom: '6px' }} />
                            <div className="skeleton-line" style={{ width: '80%', height: '12px' }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-history">Problem attempts will appear here in real-time as your child practices.</div>
                  )}
                </div>
              )}
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
        ) : (!initialFetchDone || childrenLoading) ? (
          <div className="parent-loading-skeleton" aria-label="Loading student learning report">
            {/* Skeleton KPI Strip */}
            <div className="parent-activity-kpis">
              {[
                { icon: '⏱️', label: 'Practice Time' },
                { icon: '🎯', label: 'Questions Solved' },
                { icon: '🎮', label: 'Arcade Plays' },
                { icon: '🧠', label: 'Mastery Score' },
              ].map((item, i) => (
                <div key={i} className="activity-kpi-card skeleton-card">
                  <div className="kpi-icon-box skeleton-icon-placeholder">{item.icon}</div>
                  <div className="kpi-info" style={{ width: '100%' }}>
                    <span className="kpi-label">{item.label}</span>
                    <div className="skeleton-line skeleton-line--val" style={{ width: '50%', height: '26px', margin: '6px 0' }} />
                    <div className="skeleton-line skeleton-line--sub" style={{ width: '70%', height: '12px' }} />
                  </div>
                </div>
              ))}
            </div>

            {/* Skeleton Grid: Radar + Skills */}
            <div className="radar-grid">
              <div className="radar-panel skeleton-card">
                <div className="panel-header">
                  <div>
                    <h3 style={{ margin: 0 }}>Live Skill Map</h3>
                    <div className="skeleton-line" style={{ width: '220px', height: '12px', marginTop: '6px' }} />
                  </div>
                </div>
                <div className="radar-container skeleton-radar-placeholder">
                  <div className="radar-skeleton-pulse-ring" />
                  <div className="radar-skeleton-pulse-dot" />
                  <span className="radar-skeleton-text">Loading student learning trajectory…</span>
                </div>
              </div>

              <div className="skills-panel skeleton-card">
                <div className="panel-header">
                  <h3 style={{ margin: 0 }}>Math Skills</h3>
                  <div className="skeleton-line skeleton-pill-placeholder" style={{ width: '60px', height: '22px', borderRadius: '12px' }} />
                </div>
                <div className="skills-list" style={{ gap: '10px' }}>
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className="skeleton-skill-row">
                      <div className="skeleton-skill-col">
                        <div className="skeleton-line" style={{ width: '140px', height: '14px', marginBottom: '6px' }} />
                        <div className="skeleton-line" style={{ width: '80px', height: '11px' }} />
                      </div>
                      <div className="skeleton-line skeleton-pill-placeholder" style={{ width: '48px', height: '20px', borderRadius: '10px' }} />
                    </div>
                  ))}
                </div>
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
      {showAddModal && !isDemoParent && (
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
        title="Log Out of Parent Portal?"
        message="Are you sure you want to log out? Your child's learning history, session diagnosis, and mastery radar remain safely saved."
        confirmText="Yes, Log Out"
        cancelText="Cancel"
      />

      {/* Executive Cognitive Growth Report Modal */}
      <CognitiveReportModal
        isOpen={showReportModal}
        onClose={() => setShowReportModal(false)}
        childName={selectedChild?.student_name || 'Alex Jenkins'}
        childEmail={selectedChild?.student_email}
        skills={skills}
        activitySummary={activitySummary}
      />
    </div>
  )
}
