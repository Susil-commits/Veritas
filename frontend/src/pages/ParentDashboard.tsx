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
import { getSkillMeta, getMasteryTierInfo, getBarGradient } from '../lib/skillsData'
import { validateEmailFormat, validateNameFormat, sanitizeNameInput } from '../lib/emailValidation'
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
  last_session_at: new Date(Date.now() - 3600000 * 4).toISOString(),
  days_since_practice: 5,
  has_fraction_gap: true,
  fraction_alert_message: 'Fraction practice recommended — 5 days since last session',
  fraction_mastery: 0.38,
  session_count: 6,
}

const DEFAULT_DEMO_SKILLS: SkillItem[] = [
  { skill_id: '3.OA.A.1', name: 'Understanding Multiplication', mastery_prob: 0.88 },
  { skill_id: '3.OA.A.2', name: 'Understanding Division', mastery_prob: 0.74 },
  { skill_id: '3.OA.D.8', name: 'Two-Step Word Problems', mastery_prob: 0.62 },
  { skill_id: '4.NF.A.1', name: 'Equivalent Fractions', mastery_prob: 0.38 },
  { skill_id: '4.NF.B.3', name: 'Adding & Subtracting Fractions', mastery_prob: 0.35 },
]

const DEFAULT_DEMO_DETAILS = {
  student_id: DEMO_STUDENT_ID,
  mastery: DEFAULT_DEMO_SKILLS.map(s => ({ skill_id: s.skill_id, mastery_prob: s.mastery_prob })),
  all_skills: DEFAULT_DEMO_SKILLS.map(s => ({ id: s.skill_id, name: s.name })),
  sessions: [
    {
      id: 'sess-demo-1',
      started_at: new Date(Date.now() - 3600000 * 3).toISOString(),
      login_time: new Date(Date.now() - 3600000 * 3).toISOString(),
      logout_time: new Date(Date.now() - 3600000 * 3 + 1000 * 60 * 35).toISOString(),
      duration_minutes: 35,
      problems_attempted: 5,
      problems_solved: 4,
    },
    {
      id: 'sess-demo-2',
      started_at: new Date(Date.now() - 86400000 * 2).toISOString(),
      login_time: new Date(Date.now() - 86400000 * 2).toISOString(),
      logout_time: new Date(Date.now() - 86400000 * 2 + 1000 * 60 * 40).toISOString(),
      duration_minutes: 40,
      problems_attempted: 6,
      problems_solved: 4,
    },
    {
      id: 'sess-demo-3',
      started_at: new Date(Date.now() - 86400000 * 5).toISOString(),
      login_time: new Date(Date.now() - 86400000 * 5).toISOString(),
      logout_time: new Date(Date.now() - 86400000 * 5 + 1000 * 60 * 30).toISOString(),
      duration_minutes: 30,
      problems_attempted: 4,
      problems_solved: 3,
    },
  ],
  games: {
    total_stars: 6,
    levels: [
      {
        id: 'multiplier_matrix',
        name: 'Multiplier Matrix',
        subtitle: 'Space Blitz',
        theme: 'Space Blitz',
        skill_name: 'Understanding Multiplication',
        times_played: 6,
        high_score: 420,
        stars: 3,
        is_unlocked: true,
      },
      {
        id: 'division_dungeons',
        name: 'Division Dungeons',
        subtitle: 'Gem Chest Quest',
        theme: 'Fantasy Dungeon',
        skill_name: 'Understanding Division',
        times_played: 4,
        high_score: 310,
        stars: 2,
        is_unlocked: true,
      },
      {
        id: 'two_step_runner',
        name: 'Two-Step Runner',
        subtitle: 'Formula Fortress',
        theme: 'Castle Fortress',
        skill_name: 'Two-Step Word Problems',
        times_played: 3,
        high_score: 290,
        stars: 2,
        is_unlocked: true,
      },
      {
        id: 'fraction_fusion',
        name: 'Pizza Fraction Fusion',
        subtitle: 'The Master Slicer',
        theme: 'Kitchen Artisan',
        skill_name: 'Equivalent Fractions',
        times_played: 2,
        high_score: 180,
        stars: 1,
        is_unlocked: true,
      },
      {
        id: 'equation_alchemist',
        name: 'Equation Alchemist',
        subtitle: 'Cosmic Balance Scale',
        theme: 'Alchemist Lab',
        skill_name: 'Solving One-Step Equations',
        times_played: 0,
        high_score: 0,
        stars: 0,
        is_unlocked: false,
      },
      {
        id: 'decimal_dash',
        name: 'Decimal Dash',
        subtitle: 'Neon Hyperlane',
        theme: 'Cyber City',
        skill_name: 'Operations with Decimals',
        times_played: 0,
        high_score: 0,
        stars: 0,
        is_unlocked: false,
      },
      {
        id: 'geometry_odyssey',
        name: 'Geometry Odyssey',
        subtitle: 'Cosmic Architect',
        theme: 'Celestial Galaxy',
        skill_name: 'Area & Perimeter',
        times_played: 0,
        high_score: 0,
        stars: 0,
        is_unlocked: false,
      },
    ],
  },
  activity_summary: {
    total_time_spent_minutes: 105,
    total_questions_attempted: 15,
    total_questions_solved: 11,
    accuracy_percent: 73,
    total_games_played: 12,
    total_stars: 6,
  },
  recent_events: [
    {
      id: 'evt-demo-1',
      is_correct: false,
      problems: {
        title: 'GSM8K: Knit Scarves Using Yarn',
        text: 'May can knit 3 scarves using one yarn. She bought 2 red yarns, 6 blue yarns, and 4 yellow yarns. How many scarves will she be able to make in total?',
      },
      agent_response: "I like how you're using addition to find total yarn. Now think: if 1 yarn makes 3 scarves, how do you find scarves for all 12 yarns?",
    },
    {
      id: 'evt-demo-2',
      is_correct: true,
      problems: {
        title: 'Crayon Boxes',
        text: 'A teacher bought 6 boxes of crayons. Each box contains 8 crayons. How many crayons are there in all?',
      },
      agent_response: 'Great job multiplying 6 × 8 = 48! Can you walk me through your steps out loud?',
    },
    {
      id: 'evt-demo-3',
      is_correct: false,
      problems: {
        title: 'Fraction Sharing',
        text: 'Sam ate 2/4 of a pizza and Leo ate 1/4. How much pizza did they eat altogether?',
      },
      agent_response: 'Remember, when the denominators are already the same, what happens to the numerators?',
    },
  ],
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
  const [childrenList, setChildrenList] = useState<ChildItem[]>(() => {
    const isDemo = Boolean(localStorage.getItem('veritas_demo_user')) ||
      (user?.email || '').endsWith('@veritas.dev') ||
      !user?.email
    return isDemo ? [DEFAULT_DEMO_CHILD] : []
  })
  const [selectedChildId, setSelectedChildId] = useState<string | null>(() => {
    const isDemo = Boolean(localStorage.getItem('veritas_demo_user')) ||
      (user?.email || '').endsWith('@veritas.dev') ||
      !user?.email
    return isDemo ? DEMO_STUDENT_ID : null
  })
  const [childDetails, setChildDetails] = useState<any>(() => {
    const isDemo = Boolean(localStorage.getItem('veritas_demo_user')) ||
      (user?.email || '').endsWith('@veritas.dev') ||
      !user?.email
    return isDemo ? DEFAULT_DEMO_DETAILS : null
  })
  const [skills, setSkills] = useState<SkillItem[]>(() => {
    const isDemo = Boolean(localStorage.getItem('veritas_demo_user')) ||
      (user?.email || '').endsWith('@veritas.dev') ||
      !user?.email
    return isDemo ? DEFAULT_DEMO_SKILLS : []
  })
  const [loadError, setLoadError] = useState<string | null>(null)
  const [childrenLoading, setChildrenLoading] = useState(false)
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
    if (!isDemoParent) setChildrenLoading(true)
    return getParentChildren(parentId)
      .then((res) => {
        let list = res.children || []
        if (isDemoParent && list.length === 0) {
          list = [DEFAULT_DEMO_CHILD]
        }
        setChildrenList(list)
        if (list.length > 0) {
          setSelectedChildId(prev => (!prev || !list.some(c => c.student_id === prev) ? list[0].student_id : prev))
        } else if (isDemoParent) {
          setSelectedChildId(DEMO_STUDENT_ID)
        }
      })
      .catch((err) => {
        console.error('Could not load parent children:', err)
        if (isDemoParent) {
          setChildrenList([DEFAULT_DEMO_CHILD])
          setSelectedChildId(DEMO_STUDENT_ID)
        } else {
          setLoadError('Could not load student profiles right now. Please try refreshing.')
        }
      })
      .finally(() => {
        setChildrenLoading(false)
      })
  }, [parentId, isDemoParent])

  // Initial load
  useEffect(() => {
    document.title = 'Veritas — Parent Dashboard'
    refreshChildren().catch(() => {})
  }, [refreshChildren])

  // Fetch selected child details & mastery
  const refreshChildDetails = useCallback((childId: string) => {
    setDetailsError(null)
    return getChildDetails(parentId, childId)
      .then((data) => {
        if (!data || !data.mastery || data.mastery.length === 0) {
          if (isDemoParent && childId === DEMO_STUDENT_ID) {
            setChildDetails(DEFAULT_DEMO_DETAILS)
            setSkills(DEFAULT_DEMO_SKILLS)
            return
          }
        }
        setChildDetails(data)

        const skillMap: Record<string, string> = {}
        for (const s of data.all_skills ?? []) skillMap[s.id] = s.name

        const skillsArr: SkillItem[] = (data.mastery || []).map((row: any) => ({
          skill_id: row.skill_id,
          name: skillMap[row.skill_id] ?? row.skill_id,
          mastery_prob: row.mastery_prob,
        }))
        setSkills(skillsArr.length > 0 ? skillsArr : (isDemoParent ? DEFAULT_DEMO_SKILLS : []))
      })
      .catch((err) => {
        console.error('Error loading child details:', err)
        if (isDemoParent && childId === DEMO_STUDENT_ID) {
          setChildDetails(DEFAULT_DEMO_DETAILS)
          setSkills(DEFAULT_DEMO_SKILLS)
        } else {
          setDetailsError('Could not load learning details for this student. Please try again.')
        }
      })
      .finally(() => {
        setDetailsLoading(false)
      })
  }, [parentId, isDemoParent])

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

  const selectedChild = useMemo(() => {
    const found = childrenList.find((c) => c.student_id === selectedChildId)
    if (!found && isDemoParent) {
      return DEFAULT_DEMO_CHILD
    }
    return found
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
    const totalMins = sessList.reduce((acc: number, s: any) => acc + (s.duration_minutes || 25), 0)
    const totalAttempted = sessList.reduce((acc: number, s: any) => acc + (s.problems_attempted || 4), 0)
    const totalSolved = sessList.reduce((acc: number, s: any) => acc + (s.problems_solved || 3), 0)
    const accRate = totalAttempted > 0 ? Math.round((totalSolved / totalAttempted) * 100) : 75
    const levels = childDetails?.games?.levels || DEFAULT_DEMO_DETAILS.games.levels
    const totalGames = levels.reduce((acc: number, g: any) => acc + (g.times_played || 0), 0)
    const totalStars = childDetails?.games?.total_stars || levels.reduce((acc: number, g: any) => acc + (g.stars || 0), 0)
    return {
      total_time_spent_minutes: totalMins || 105,
      total_questions_attempted: totalAttempted || 15,
      total_questions_solved: totalSolved || 11,
      accuracy_percent: accRate,
      total_games_played: totalGames || 12,
      total_stars: totalStars || 6,
    }
  }, [childDetails])

  const arcadeGames = useMemo(() => {
    return childDetails?.games?.levels || DEFAULT_DEMO_DETAILS.games.levels
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
                        {(isDemoParent || child.student_id === DEMO_STUDENT_ID) && (
                          <span className="synthetic-demo-pill">DEMO DATA — Synthetic learner profile</span>
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
            {/* Synthetic Demo Learner Notice */}
            {(isDemoParent || selectedChild.student_id === DEMO_STUDENT_ID) && (
              <div className="synthetic-demo-notice-banner">
                <span className="synthetic-badge-icon">ℹ️</span>
                <div className="synthetic-notice-text">
                  <span className="synthetic-notice-title">DEMO DATA — Synthetic learner profile</span>
                  <p>Sample learning trajectory, Common Core mastery radar, and inactivity alerts shown for demonstration. No actual children are being monitored.</p>
                </div>
              </div>
            )}

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
    </div>
  )
}
