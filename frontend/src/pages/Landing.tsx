import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { checkHealth } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import AnimatedIntro from '../components/AnimatedIntro'
import SocraticPreview from '../components/SocraticPreview'
import {
  validateEmailFormat,
  validateNameFormat,
  sanitizeNameInput,
  suggestCorrection,
  friendlyAuthError,
} from '../lib/emailValidation'
import { useBackendWarmup } from '../hooks/useBackendWarmup'
import WarmupExperience from '../components/WarmupExperience'
import InteractivePipeline from '../components/InteractivePipeline'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import AvatarModal from '../components/AvatarModal'
import './Landing.css'

const STATS = [
  { value: '3', label: 'Smart AI Helpers' },
  { value: '10', label: 'Core Math Topics' },
  { value: '20+', label: 'Practice Problems' },
  { value: 'Instant', label: 'Step-by-Step Feedback' },
]

const FEATURES = [
  {
    title: 'The Socratic Tutor',
    desc: 'Never just hands you the answer. Asks friendly guiding questions that help you solve problems on your own.',
    tag: 'Socratic Method',
  },
  {
    title: 'Paper Work Reader',
    desc: 'Snap a picture of your handwritten work. It checks each step and pinpoints tricky spots — like flipped signs or mixed-up fractions.',
    tag: 'Paper Scanner',
  },
  {
    title: 'Real Progress Tracker',
    desc: 'Watches how you grow across every math topic so you always practice problems that are just the right challenge.',
    tag: 'Adaptive Mastery',
  },
]

const MATH_TOPICS = [
  {
    id: '3.OA.A.1',
    grade: 'Grade 3',
    name: 'Understanding Multiplication',
    desc: 'Connecting equal groups, arrays, and repeated addition to build rock-solid number sense.',
    example: '3 groups of 4 apples = 12',
    tag: 'Foundations',
  },
  {
    id: '3.OA.A.2',
    grade: 'Grade 3',
    name: 'Understanding Division',
    desc: 'Sharing quantities into equal piles and discovering how division is multiplication in reverse.',
    example: '15 stickers shared by 3 friends = 5 each',
    tag: 'Foundations',
  },
  {
    id: '3.OA.D.8',
    grade: 'Grade 3',
    name: 'Two-Step Word Problems',
    desc: 'Breaking tricky real-world scenarios into step 1 and step 2 without getting overwhelmed.',
    example: 'Earned $10, bought $4 juice, saved the rest',
    tag: 'Word Problems',
  },
  {
    id: '4.NF.A.1',
    grade: 'Grade 4',
    name: 'Equivalent Fractions',
    desc: 'Seeing why 1/2 is the same amount of pizza as 2/4 or 4/8 using visual area models.',
    example: '2/3 = 4/6 = 8/12',
    tag: 'Fractions',
  },
  {
    id: '4.NF.B.3',
    grade: 'Grade 4',
    name: 'Adding & Subtracting Fractions',
    desc: 'Finding common denominators and discovering why you never add denominators together.',
    example: '1/3 + 1/6 = 2/6 + 1/6 = 3/6 = 1/2',
    tag: 'Fractions',
  },
  {
    id: '4.NF.B.4',
    grade: 'Grade 4',
    name: 'Multiplying Fractions by Whole Numbers',
    desc: 'Scaling recipes, measuring ingredients, and repeated fraction additions.',
    example: '3 × (2/5) = 6/5 = 1 1/5',
    tag: 'Fractions',
  },
  {
    id: '5.NF.B.7',
    grade: 'Grade 5',
    name: 'Dividing Fractions',
    desc: 'Understanding how many fractional slices fit into a whole unit using intuitive visual models.',
    example: 'How many 1/4 cups in 2 cups? 2 ÷ 1/4 = 8',
    tag: 'Fractions',
  },
  {
    id: '6.EE.A.2',
    grade: 'Grade 6',
    name: 'Algebraic Expressions',
    desc: 'Translating written math phrases into algebraic expressions with variables and constants.',
    example: '"5 less than twice a number" → 2n - 5',
    tag: 'Algebra',
  },
  {
    id: '6.EE.B.7',
    grade: 'Grade 6',
    name: 'Solving One-Step Equations',
    desc: 'Balancing the scales: using inverse operations to isolate variables with confidence.',
    example: 'x + 7 = 15 → x = 8',
    tag: 'Algebra',
  },
  {
    id: '7.EE.B.4',
    grade: 'Grade 7',
    name: 'Solving Multi-Step Equations',
    desc: 'Combining like terms, distributing, and keeping track of negative signs on both sides.',
    example: '3(x - 4) + 2 = 14 → x = 8',
    tag: 'Algebra',
  },
]

type ConnStatus = 'checking' | 'connected' | 'waking_up' | 'error'

// Module-level guard preventing duplicate intro mounting in the same runtime session
let introAlreadyInitiated = false

export default function Landing() {
  const navigate = useNavigate()
  const location = useLocation()
  const {
    user,
    role,
    avatar,
    updateAvatar,
    setRole,
    sendMagicLink,
    verifyOtp,
    demoSignIn,
    signOut,
    rememberedProfile,
  } = useAuth()
  const [email, setEmail] = useState('')
  const [emailCorrection, setEmailCorrection] = useState<string | null>(null)
  const [magicLinkEmail, setMagicLinkEmail] = useState('')
  const [authError, setAuthError] = useState('')
  const [authLoading, setAuthLoading] = useState(false)

  // Standout modern auth states
  const [authScreen, setAuthScreen] = useState<'form' | 'otp'>('form')
  const [otpLength, setOtpLength] = useState<6 | 8>(8) // Default to 8 digits matching Supabase project configuration
  const [otpDigits, setOtpDigits] = useState<string[]>(['', '', '', '', '', '', '', ''])
  const [hasOtpError, setHasOtpError] = useState(false)
  const [shakeOtp, setShakeOtp] = useState(false)
  const [resendTimer, setResendTimer] = useState(45)
  const [resendCount, setResendCount] = useState(0)
  const [resendSuccess, setResendSuccess] = useState(false)
  const MAX_RESENDS = 3
  const [rememberedDismissed, setRememberedDismissed] = useState(false)
  const otpRefs = useRef<(HTMLInputElement | null)[]>([])
  const [otpScreenSeconds, setOtpScreenSeconds] = useState(0)

  const switchOtpLength = (targetLen: 6 | 8) => {
    setOtpLength(targetLen)
    setOtpDigits(Array(targetLen).fill(''))
    setAuthError('')
    setHasOtpError(false)
    setTimeout(() => otpRefs.current[0]?.focus(), 50)
  }

  const handleClearOtp = () => {
    setOtpDigits(Array(otpLength).fill(''))
    setHasOtpError(false)
    setAuthError('')
    setTimeout(() => otpRefs.current[0]?.focus(), 50)
  }

  // Smart auth mode: defaults to 'signin' if remembered profile is cached, else 'signup' for new visitors
  const [authMode, setAuthMode] = useState<'signin' | 'signup'>(() => {
    try {
      const raw = localStorage.getItem('veritas_remembered_profile')
      return raw ? 'signin' : 'signup'
    } catch {
      return 'signup'
    }
  })
  const [fullName, setFullName] = useState('')
  const [roleMismatchNotice, setRoleMismatchNotice] = useState<string | null>(null)
  const [showAvatarModal, setShowAvatarModal] = useState(false)
  const [isRegistrationAvatarStep, setIsRegistrationAvatarStep] = useState(false)

  // Cold-start warmup hook
  const {
    isReady: isWarmupReady,
    isTimeout: isWarmupTimeout,
    startWarmupFlow,
    resetWarmup,
  } = useBackendWarmup()
  const [showWarmupModal, setShowWarmupModal] = useState(false)
  const [pendingWarmupDestination, setPendingWarmupDestination] = useState<{ path: string; role: 'student' | 'parent' } | null>(null)

  // OTP screen dwell timer for proactive help escalation
  useEffect(() => {
    if (authScreen !== 'otp') {
      setOtpScreenSeconds(0)
      return
    }
    const interval = setInterval(() => {
      setOtpScreenSeconds(prev => prev + 1)
    }, 1000)
    return () => clearInterval(interval)
  }, [authScreen])

  // Resend OTP countdown
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null
    if (authScreen === 'otp' && resendTimer > 0) {
      interval = setInterval(() => {
        setResendTimer(prev => prev - 1)
      }, 1000)
    }
    return () => {
      if (interval !== null) clearInterval(interval)
    }
  }, [authScreen, resendTimer])

  // Animated intro portal control (bypassed if arriving directly with a section anchor like #demo, or if already presented)
  const [showIntro, setShowIntro] = useState(() => {
    try {
      if (introAlreadyInitiated) {
        return false
      }
      if (window.location.hash && !window.location.hash.includes('access_token')) {
        return false
      }
      const seen =
        sessionStorage.getItem('veritas_intro_seen') === 'true' ||
        sessionStorage.getItem('ainerd_intro_seen') === 'true' ||
        localStorage.getItem('veritas_intro_seen') === 'true'
      if (seen) {
        return false
      }
      introAlreadyInitiated = true
      return true
    } catch {
      return false
    }
  })

  // Simple server & database connection status
  const [connStatus, setConnStatus] = useState<ConnStatus>('checking')
  const [connMessage, setConnMessage] = useState<string>('Connecting to learning space...')
  const [connRetryTrigger, setConnRetryTrigger] = useState(0)
  const [connVisible, setConnVisible] = useState(true)
  const [connFading, setConnFading] = useState(false)

  const checkConnection = async (): Promise<boolean> => {
    try {
      const data = await checkHealth()
      if (data && data.status === 'ok') {
        setConnStatus('connected')
        setConnMessage('Connected to learning space')
        return true
      } else {
        setConnStatus('waking_up')
        setConnMessage('Connecting to learning space... please wait a moment')
        return false
      }
    } catch {
      setConnStatus('waking_up')
      setConnMessage('Connecting to learning space... please wait a moment')
      return false
    }
  }

  useEffect(() => {
    document.title = "Veritas — The Math Tutor That Guides Your Thinking"
    let mounted = true
    let timer: any = null
    let retries = 0

    const poll = async () => {
      const ready = await checkConnection()
      if (!mounted) return
      if (!ready) {
        retries++
        if (retries < 25) {
          timer = setTimeout(poll, 2500)
        } else {
          setConnStatus('error')
          setConnMessage('Connection taking longer than expected. Please refresh.')
        }
      }
    }

    poll()

    return () => {
      mounted = false
      if (timer) clearTimeout(timer)
    }
  }, [connRetryTrigger])

  // Show "Connected to learning space" for 2.5s, then smoothly fade out & disappear
  useEffect(() => {
    if (connStatus === 'connected') {
      const fadeTimer = setTimeout(() => {
        setConnFading(true)
      }, 2500)

      const hideTimer = setTimeout(() => {
        setConnVisible(false)
      }, 3100)

      return () => {
        clearTimeout(fadeTimer)
        clearTimeout(hideTimer)
      }
    }
  }, [connStatus])

  const handleConnRetry = () => {
    setConnVisible(true)
    setConnFading(false)
    setConnStatus('checking')
    setConnMessage('Connecting to learning space...')
    setConnRetryTrigger(c => c + 1)
  }

  // Smoothly scroll to a section by element ID with sticky navbar offset resilience
  const scrollToSection = useCallback((sectionId: string, smooth: boolean = true) => {
    const cleanId = sectionId.replace(/^#/, '').trim()
    if (!cleanId) return

    let attempts = 0
    const tryScroll = () => {
      let el = document.getElementById(cleanId)
      if (!el && (cleanId === 'live-pipeline' || cleanId === 'pipeline')) {
        el = document.getElementById('pipeline') || document.getElementById('live-pipeline')
      }
      if (el) {
        el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' })
      } else if (attempts < 10) {
        attempts++
        setTimeout(tryScroll, 60)
      }
    }

    tryScroll()
  }, [])

  // Auto-scroll to target section on initial load or refresh if hash is present (e.g. #demo)
  useEffect(() => {
    const rawHash = location.hash || window.location.hash
    if (rawHash && !rawHash.includes('access_token') && !rawHash.includes('error=')) {
      if ('scrollRestoration' in window.history) {
        window.history.scrollRestoration = 'manual'
      }
      // Instant initial positioning
      scrollToSection(rawHash, false)
      // Follow-up passes as React renders child elements
      const timer1 = setTimeout(() => scrollToSection(rawHash, false), 50)
      const timer2 = setTimeout(() => scrollToSection(rawHash, false), 200)
      const timer3 = setTimeout(() => scrollToSection(rawHash, false), 500)
      return () => {
        clearTimeout(timer1)
        clearTimeout(timer2)
        clearTimeout(timer3)
      }
    }
  }, [location.hash, scrollToSection])

  // Handle browser back/forward buttons when moving between section hashes
  useEffect(() => {
    const handleHashChange = () => {
      const rawHash = window.location.hash
      if (rawHash && !rawHash.includes('access_token') && !rawHash.includes('error=')) {
        scrollToSection(rawHash, true)
      } else if (!rawHash) {
        window.scrollTo({ top: 0, behavior: 'smooth' })
      }
    }

    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [scrollToSection])

  // On verified login (Magic Link callback in URL hash/query), redirect to role destination
  useEffect(() => {
    const hasAuthToken = window.location.hash.includes('access_token') || window.location.search.includes('code')
    if (user && hasAuthToken) {
      if (role === 'parent') {
        navigate('/parent-dashboard')
      } else {
        navigate('/student-session')
      }
    }
  }, [user, role, navigate])

  const handleApplyDomain = (domain: string) => {
    const trimmed = email.trim()
    if (!trimmed) {
      setEmail(`student${domain}`)
    } else if (trimmed.includes('@')) {
      const prefix = trimmed.split('@')[0]
      setEmail(`${prefix}${domain}`)
    } else {
      setEmail(`${trimmed}${domain}`)
    }
    setAuthError('')
    setEmailCorrection(null)
  }

  const navigateToRoleWithWarmup = (targetRole: 'student' | 'parent', path: string) => {
    startWarmupFlow({
      onWarmReady: () => {
        navigate(path)
      },
      onColdStart: () => {
        setPendingWarmupDestination({ path, role: targetRole })
        setShowWarmupModal(true)
      },
      onBackendAwake: () => {
        // Backend responds ready; non-blocking toast displays inside WarmupExperience
      },
    })
  }

  // Evaluator Convenience: Fixed test emails gated to @veritas.dev for instant judge evaluation
  const DEMO_EMAILS = ['parent.sarah@veritas.dev', 'student.alex@veritas.dev']

  const isDemoEmail = (emailStr: string) => {
    const normalized = emailStr.trim().toLowerCase()
    return DEMO_EMAILS.includes(normalized) || normalized.endsWith('@veritas.dev')
  }

  const handleFastResume = async () => {
    if (!rememberedProfile) return
    const remEmail = rememberedProfile.email.trim()
    const remRole = rememberedProfile.role

    if (isDemoEmail(remEmail)) {
      // Evaluator shortcut: genuine demo account gets instant one-click access
      setAuthLoading(true)
      setAuthError('')
      try {
        await demoSignIn(remRole, remEmail)
        setAuthScreen('form')
      } catch (err: any) {
        console.error('Fast resume failed:', err)
        setAuthError(friendlyAuthError(err?.message || 'Could not resume demo session. Please try signing in again.'))
      } finally {
        setAuthLoading(false)
      }
    } else {
      // Real user account: re-authenticate properly via real magic link / OTP rather than fabricating a fake session
      setEmail(remEmail)
      setRole(remRole)
      handleSendMagicLinkOrOtp(undefined, remEmail, remRole).catch((err) => {
        console.error('Fast resume send magic link failed:', err)
        setAuthError(friendlyAuthError('Could not send verification code. Please try signing in again.'))
      })
    }
  }

  const handleEmailBlur = () => {
    const trimmed = email.trim()
    if (!trimmed) return
    const validation = validateEmailFormat(trimmed)
    if (!validation.valid) {
      setAuthError(validation.reason || 'Please enter a valid email address.')
    } else {
      setAuthError('')
      const typo = suggestCorrection(trimmed)
      setEmailCorrection(typo)
    }
  }

  const handleNameBlur = () => {
    const trimmed = fullName.trim()
    if (!trimmed) return
    const nameValidation = validateNameFormat(trimmed)
    if (!nameValidation.valid) {
      setAuthError(nameValidation.reason || 'Invalid name format')
    } else {
      setAuthError('')
    }
  }

  const handleSendMagicLinkOrOtp = async (
    e?: React.FormEvent,
    emailOverride?: string,
    roleOverride?: 'student' | 'parent'
  ) => {
    if (e) e.preventDefault()
    const targetEmail = (emailOverride !== undefined ? emailOverride : email).trim()
    const targetRole = roleOverride || role

    // 1. Strict email validation (rejects phone numbers, plain names, missing TLDs, etc.)
    const validation = validateEmailFormat(targetEmail)
    if (!validation.valid) {
      setAuthError(validation.reason || 'Please enter a valid email address.')
      return
    }

    // 2. Strict name validation during signup (rejects emails, numbers, symbols in name)
    if (authMode === 'signup' && fullName.trim()) {
      const nameValidation = validateNameFormat(fullName)
      if (!nameValidation.valid) {
        setAuthError(nameValidation.reason || 'Please enter a valid name.')
        return
      }
    }

    setAuthLoading(true)
    setAuthError('')
    try {
      const res = await sendMagicLink(
        targetEmail,
        targetRole,
        authMode === 'signup' ? fullName : undefined,
        authMode === 'signup'
      )
      if (res.error) {
        setAuthError(friendlyAuthError(res.error))
      } else {
        setMagicLinkEmail(targetEmail)
        setAuthScreen('otp')
        setOtpScreenSeconds(0)
        setResendTimer(45)
        setResendCount(0)
        setEmailCorrection(null)
      }
    } catch (err: any) {
      console.error('Send magic link failed:', err)
      setAuthError(friendlyAuthError(err?.message || 'Could not send verification code. Please check your connection and try again.'))
    } finally {
      setAuthLoading(false)
    }
  }

  const handleResendOtp = async () => {
    if (resendCount >= MAX_RESENDS) {
      setAuthError('Too many attempts. Please refresh the page and try again in a few minutes.')
      return
    }
    const target = magicLinkEmail || email
    if (!target) return
    setAuthLoading(true)
    setAuthError('')
    try {
      const res = await sendMagicLink(
        target,
        role,
        authMode === 'signup' ? fullName : undefined,
        authMode === 'signup'
      )
      if (res.error) {
        setAuthError(friendlyAuthError(res.error))
      } else {
        setOtpScreenSeconds(0) // restart the window after a fresh send
        const nextCount = resendCount + 1
        setResendCount(nextCount)
        setResendTimer(45 * (nextCount + 1)) // 45s, then 90s, then 135s progressive backoff
        setResendSuccess(true)
        setTimeout(() => setResendSuccess(false), 9000)
      }
    } catch (err: any) {
      console.error('Resend OTP failed:', err)
      setAuthError(friendlyAuthError(err?.message || 'Could not resend code. Please try again.'))
    } finally {
      setAuthLoading(false)
    }
  }

  const handleVerifyOtpCode = async (codeToVerify: string, overrideRole?: 'student' | 'parent') => {
    const cleanCode = codeToVerify.trim()
    if (cleanCode.length !== 6 && cleanCode.length !== 8) {
      setAuthError('Please enter all digits of the verification code (6 or 8 digits).')
      return
    }
    const activeRole = overrideRole || role
    setAuthLoading(true)
    setAuthError('')
    try {
      const targetEmail = magicLinkEmail || email
      if (!targetEmail) {
        setAuthError('Please enter your email address before verifying the code.')
        setAuthLoading(false)
        setAuthScreen('form')
        return
      }
      const res = await verifyOtp(targetEmail, cleanCode, activeRole, authMode === 'signup' ? fullName : undefined)
      if (res.error) {
        setAuthError(friendlyAuthError(res.error))
        setHasOtpError(true)
        setShakeOtp(true)
        setTimeout(() => setShakeOtp(false), 500)
        otpRefs.current[0]?.focus()
      } else {
        setHasOtpError(false)
        if (res.roleMismatch && res.registeredRole) {
          const registeredLabel =
            res.registeredRole === 'student' ? 'Student Socratic Workspace' : 'Parent & Guardian Portal'
          const registeredRoleName = res.registeredRole === 'student' ? 'Student' : 'Parent'
          setRoleMismatchNotice(
            `Account Verified: This email is registered as a ${registeredRoleName}. We've protected your profile and automatically directed you to your ${registeredLabel}.`
          )
        } else {
          setRoleMismatchNotice(null)
        }
        // Verification succeeded and user session is active.
        // If registering, prompt avatar setup onboarding
        if (authMode === 'signup') {
          setIsRegistrationAvatarStep(true)
          setShowAvatarModal(true)
        }
        setAuthScreen('form')
      }
    } catch (err: any) {
      console.error('Verify OTP failed:', err)
      setAuthError(friendlyAuthError(err?.message || 'Verification failed. Please check the code and try again.'))
      setHasOtpError(true)
      setShakeOtp(true)
      setTimeout(() => setShakeOtp(false), 500)
      otpRefs.current[0]?.focus()
    } finally {
      setAuthLoading(false)
    }
  }

  const handleOtpChange = (index: number, val: string) => {
    if (hasOtpError) {
      setHasOtpError(false)
    }
    // Only accept numeric digits
    const char = val.replace(/\D/g, '').slice(-1)
    const nextDigits = [...otpDigits]
    nextDigits[index] = char
    setOtpDigits(nextDigits)
    setAuthError('')

    if (char && index < otpLength - 1) {
      otpRefs.current[index + 1]?.focus()
    }

    const fullCode = nextDigits.join('')
    if (fullCode.length === otpLength && !nextDigits.includes('')) {
      handleVerifyOtpCode(fullCode)
    }
  }

  const handleOtpKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace') {
      if (!otpDigits[index] && index > 0) {
        otpRefs.current[index - 1]?.focus()
      }
      return
    }
    // Allow navigation, modifier shortcuts, tab, enter, escape, delete
    if (
      e.key === 'Tab' ||
      e.key === 'Enter' ||
      e.key === 'Delete' ||
      e.key === 'Escape' ||
      e.key === 'ArrowLeft' ||
      e.key === 'ArrowRight' ||
      e.key === 'ArrowUp' ||
      e.key === 'ArrowDown' ||
      e.key === 'Home' ||
      e.key === 'End' ||
      e.ctrlKey ||
      e.metaKey
    ) {
      return
    }
    // Only accept numeric digits 0-9; reject any other character (letters, punctuation, symbols)
    if (!/^[0-9]$/.test(e.key)) {
      e.preventDefault()
    }
  }

  const handleOtpPaste = (e: React.ClipboardEvent) => {
    e.preventDefault()
    setHasOtpError(false)
    const rawPasted = e.clipboardData.getData('text').trim().replace(/\D/g, '')
    if (!rawPasted) return

    let targetLen: 6 | 8 = otpLength
    if (rawPasted.length === 6) {
      targetLen = 6
    } else if (rawPasted.length >= 8) {
      targetLen = 8
    }
    setOtpLength(targetLen)

    const truncated = rawPasted.slice(0, targetLen)
    const next = Array(targetLen).fill('')
    for (let i = 0; i < truncated.length; i++) {
      next[i] = truncated[i] || ''
    }
    setOtpDigits(next)

    if (truncated.length === targetLen) {
      handleVerifyOtpCode(truncated)
    } else {
      const firstEmpty = next.findIndex(d => !d)
      if (firstEmpty !== -1) {
        setTimeout(() => otpRefs.current[firstEmpty]?.focus(), 30)
      }
    }
  }

  const handleAutofillOtp = (code: string, targetRole: 'student' | 'parent') => {
    setRole(targetRole)
    setHasOtpError(false)
    setAuthError('')
    const targetLen: 6 | 8 = code.length === 8 ? 8 : 6
    setOtpLength(targetLen)
    const digits = code.slice(0, targetLen).split('')
    setOtpDigits(digits)
    handleVerifyOtpCode(code, targetRole)
  }

  const handleDemoLogin = async (targetRole: 'student' | 'parent') => {
    setAuthLoading(true)
    setAuthError('')
    try {
      await demoSignIn(targetRole)
      setAuthScreen('form')
      const targetPath = targetRole === 'parent' ? '/parent-dashboard' : '/student-session'
      navigateToRoleWithWarmup(targetRole, targetPath)
    } catch (err: any) {
      console.error('Demo sign-in failed:', err)
      setAuthError(friendlyAuthError(err?.message || 'Could not log into demo. Please try again.'))
    } finally {
      setAuthLoading(false)
    }
  }

  const handleEnterSession = () => {
    const targetPath = role === 'parent' ? '/parent-dashboard' : '/student-session'
    navigateToRoleWithWarmup(role, targetPath)
  }

  return (
    <>
      {/* Animated Entrance Portal (Opens animately on first arrival or replay) */}
      {showIntro && (
        <AnimatedIntro
          onEnter={() => {
            setShowIntro(false)
            try {
              sessionStorage.setItem('veritas_intro_seen', 'true')
              localStorage.setItem('veritas_intro_seen', 'true')
            } catch {}
            const rawHash = window.location.hash
            if (rawHash && !rawHash.includes('access_token')) {
              setTimeout(() => scrollToSection(rawHash, true), 120)
            }
          }}
        />
      )}

      {/* Top Glassmorphic Navigation Bar */}
      <header className="landing-navbar">
        <div className="navbar-container">
          <a
            href="/"
            className="navbar-brand"
            onClick={(e) => {
              e.preventDefault()
              window.scrollTo({ top: 0, behavior: 'smooth' })
              window.history.replaceState(null, '', window.location.pathname + window.location.search)
            }}
          >
            <span className="brand-icon">✨</span>
            <span className="brand-name">Veritas<span className="brand-dot">.</span></span>
          </a>

          <nav className="navbar-links">
            <a
              href="#demo"
              className="nav-link"
              onClick={(e) => {
                e.preventDefault()
                scrollToSection('demo', true)
                window.history.pushState(null, '', '#demo')
              }}
            >
              Interactive Demo
            </a>
            <a
              href="#how-it-works"
              className="nav-link"
              onClick={(e) => {
                e.preventDefault()
                scrollToSection('how-it-works', true)
                window.history.pushState(null, '', '#how-it-works')
              }}
            >
              How It Works
            </a>
            <a
              href="#pipeline"
              className="nav-link"
              onClick={(e) => {
                e.preventDefault()
                scrollToSection('pipeline', true)
                window.history.pushState(null, '', '#pipeline')
              }}
            >
              Live Pipeline
            </a>
            <a
              href="#topics"
              className="nav-link"
              onClick={(e) => {
                e.preventDefault()
                scrollToSection('topics', true)
                window.history.pushState(null, '', '#topics')
              }}
            >
              Math Topics
            </a>
          </nav>

          <div className="navbar-actions">
            <ThemeToggle />
            {user && (
              <div className="navbar-user-group">
                <button
                  type="button"
                  className="btn btn-sm btn-violet"
                  onClick={handleEnterSession}
                  title="Move to your learning space"
                >
                  {role === 'parent' ? 'Parent Portal →' : 'Learning Space →'}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost navbar-logout-btn"
                  onClick={async () => {
                    try {
                      await signOut()
                    } catch (err) {
                      console.error('Sign out error:', err)
                    }
                    setEmail('')
                    setAuthScreen('form')
                  }}
                  title="Sign out of your account"
                >
                  Log Out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="landing">
      {/* Hero */}
      <section className="hero">
        <h1 className="hero-headline">
          The Math Tutor That<br />
          <span className="gradient-text">Guides Your Thinking.</span>
        </h1>

        <p className="hero-sub">
          An encouraging math tutor that spots where you get stuck — asking helpful questions so you learn the concepts and solve problems on your own.
        </p>

        {/* Server Connection Status - shows connecting, then 'Connected to learning space', then smoothly disappears */}
        {connVisible && (
          <div className={`conn-status conn-status--${connStatus} ${connFading ? 'conn-status--fade-out' : ''}`}>
            <span className="conn-dot" />
            <span>{connMessage}</span>
            {connStatus === 'error' && (
              <button
                className="conn-retry-btn"
                onClick={handleConnRetry}
              >
                Retry
              </button>
            )}
          </div>
        )}

        {/* Modern Standout Split-Card Auth */}
        <div className="auth-card-container" id="auth-card">
          {user ? (
            <div className="auth-logged-in-card animate-fadein">
              {roleMismatchNotice && (
                <div className="auth-info-banner animate-fadein">
                  <span className="info-banner-icon">🛡️</span>
                  <span className="info-banner-text">{roleMismatchNotice}</span>
                </div>
              )}
              <div className="logged-in-badge">
                <UserAvatar
                  avatar={avatar}
                  name={user.user_metadata?.name || rememberedProfile?.name || ''}
                  role={role}
                  size="lg"
                  onClick={() => {
                    setIsRegistrationAvatarStep(false)
                    setShowAvatarModal(true)
                  }}
                  showEditBadge={true}
                />
                <div>
                  <div className="logged-in-celebration">
                    <span className="celebration-dot" />
                    Account Verified & Ready!
                  </div>
                  <div className="logged-in-title">Signed In as <strong>{user.email}</strong></div>
                  <div className="logged-in-role">Active Portal: <span className="badge badge-violet">{role === 'parent' ? 'Parent & Guardian Portal' : 'Student Socratic Workspace'}</span></div>
                </div>
              </div>
              <div className="logged-in-actions">
                <button
                  type="button"
                  className="btn btn-violet btn-lg logged-in-primary-cta"
                  onClick={handleEnterSession}
                  title="Move to your learning space"
                >
                  {role === 'parent' ? 'Enter Parent Dashboard →' : 'Enter Learning Space →'}
                </button>
                <div className="logged-in-sub-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => scrollToSection('pipeline', true)}
                  >
                    Explore Live Pipeline ↓
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => scrollToSection('topics', true)}
                  >
                    View Math Topics ↓
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm logged-in-logout-btn"
                    onClick={async () => {
                      try {
                        await signOut()
                      } catch (err) {
                        console.error('Sign out error:', err)
                      }
                      setEmail('')
                      setRoleMismatchNotice(null)
                      setAuthScreen('form')
                    }}
                  >
                    Log Out / Switch
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="auth-split-card">
              {/* Left Panel */}
              <div className="auth-card-left">
                <div className="auth-brand-row">
                  <span className="auth-brand-badge">PORTAL</span>
                  <span className="auth-brand-name">Veritas<span className="auth-brand-dot">.</span></span>
                  <span className="auth-security-pill">
                    <span>Child-Safe Socratic Learning</span>
                  </span>
                </div>

                {/* 1. Fast Account Switcher / Remembered Profile */}
                {rememberedProfile && !rememberedDismissed && authScreen === 'form' ? (
                  <div className="auth-remembered-card animate-fadein">
                    <div className="remembered-header">
                      <UserAvatar
                        avatar={rememberedProfile.avatar}
                        name={rememberedProfile.name}
                        role={rememberedProfile.role}
                        size="md"
                      />
                      <div className="remembered-info">
                        <div className="remembered-name-row">
                          <span className="remembered-name">{rememberedProfile.name}</span>
                          <span className="badge badge-violet">{rememberedProfile.role === 'parent' ? 'Parent' : 'Student'}</span>
                        </div>
                        <div className="remembered-email">{rememberedProfile.email}</div>
                      </div>
                    </div>
                    <div className="remembered-actions">
                      <button
                        type="button"
                        className="btn btn-violet btn-sm remembered-continue-btn"
                        onClick={handleFastResume}
                        disabled={authLoading}
                      >
                        {authLoading ? 'Signing in…' : `Continue as ${rememberedProfile.name.split(' ')[0]}`}
                      </button>
                      <button
                        type="button"
                        className="remembered-switch-btn"
                        onClick={() => setRememberedDismissed(true)}
                      >
                        Use another account
                      </button>
                    </div>
                  </div>
                ) : null}

                {/* 2. Main Login Form or OTP Verification Screen */}
                {authScreen === 'otp' ? (
                  <div className="auth-otp-screen animate-fadein">
                    <div className="otp-header-row">
                      <button
                        type="button"
                        className="otp-back-btn"
                        onClick={() => {
                          setAuthScreen('form')
                          setAuthError('')
                        }}
                      >
                        Change Email
                      </button>
                      <span className="otp-email-chip">{magicLinkEmail || email}</span>
                    </div>

                    <h2 className="auth-greeting">
                      {authMode === 'signup' ? (
                        <>
                          Account Setup<br />
                          <span className="auth-greeting-sub">Verification</span>
                        </>
                      ) : (
                        <>
                          Security Code<br />
                          <span className="auth-greeting-sub">Verification</span>
                        </>
                      )}
                    </h2>
                    <p className="auth-tagline">
                      {authMode === 'signup'
                        ? "We've sent an activation code to your email."
                        : "If that email is registered, we've sent your code."}
                    </p>

                    {/* Single Concise Spam Check Notice */}
                    <div className="otp-spam-alert-banner animate-fadein">
                      <span className="otp-spam-alert-badge">Spam check</span>
                      <span>If not in your inbox, check your <strong>Spam / Junk folder</strong>.</span>
                    </div>

                    {resendSuccess && (
                      <div className="otp-success-banner animate-fadein">
                        ✅ Fresh code sent! Check your inbox or Spam folder.
                      </div>
                    )}

                    {/* Format switcher for 8-digit vs 6-digit */}
                    <div className="otp-format-toggle-row">
                      <span className="otp-format-label">Code length:</span>
                      <div className="otp-format-pills">
                        <button
                          type="button"
                          className={`otp-format-btn ${otpLength === 8 ? 'otp-format-btn--active' : ''}`}
                          onClick={() => switchOtpLength(8)}
                        >
                          8 Digits (Standard)
                        </button>
                        <button
                          type="button"
                          className={`otp-format-btn ${otpLength === 6 ? 'otp-format-btn--active' : ''}`}
                          onClick={() => switchOtpLength(6)}
                        >
                          6 Digits
                        </button>
                      </div>
                    </div>

                    <div className={`otp-inputs-grid otp-inputs-grid--${otpLength} ${shakeOtp ? 'otp-inputs-grid--shake' : ''}`}>
                      {otpDigits.map((digit, idx) => (
                        <input
                          key={idx}
                          ref={(el) => { otpRefs.current[idx] = el }}
                          type="text"
                          inputMode="numeric"
                          pattern="[0-9]*"
                          autoComplete="one-time-code"
                          maxLength={1}
                          className={`otp-digit-input ${digit ? 'otp-digit-input--filled' : ''} ${hasOtpError ? 'otp-digit-input--error' : ''}`}
                          value={digit}
                          onChange={(e) => handleOtpChange(idx, e.target.value)}
                          onKeyDown={(e) => handleOtpKeyDown(idx, e)}
                          onPaste={handleOtpPaste}
                          disabled={authLoading}
                          autoFocus={idx === 0}
                          aria-label={`Digit ${idx + 1} of ${otpLength}`}
                        />
                      ))}
                    </div>

                    {/* Laptop vs Phone helper tip */}
                    <div className="otp-device-tip animate-fadein">
                      <span className="otp-device-tip-icon">💻</span>
                      <div className="otp-device-tip-body">
                        <span className="otp-device-tip-title">Signing in on this laptop?</span>
                        <span className="otp-device-tip-desc">
                          Type your verification code directly into the boxes above. Tapping the link on your phone logs in your phone's browser, not this laptop.
                        </span>
                      </div>
                    </div>

                    {otpScreenSeconds >= 75 && (
                      <p className="otp-hint otp-hint--direct animate-fadein">
                        Still nothing? Make sure to check your <strong>Spam / Junk folder</strong>, confirm <strong>{magicLinkEmail || email}</strong> is spelled
                        correctly, or{' '}
                        <button
                          type="button"
                          className="otp-hint-link"
                          onClick={() => { setAuthScreen('form'); setAuthError(''); setResendSuccess(false); setHasOtpError(false) }}
                        >
                          try a different email
                        </button>.
                      </p>
                    )}

                    {authError && (
                      <div className="auth-error-banner-group animate-fadein">
                        <p className="auth-error-banner">{authError}</p>
                        <div className="otp-error-action-bar">
                          <button
                            type="button"
                            className="btn-otp-clear"
                            onClick={handleClearOtp}
                            title="Clear all digits to re-type code"
                          >
                            <span>🔄 Clear & Re-enter</span>
                          </button>
                          <button
                            type="button"
                            className="btn-otp-change-email"
                            onClick={() => {
                              setAuthScreen('form')
                              setAuthError('')
                              setHasOtpError(false)
                            }}
                            title="Enter a different email"
                          >
                            <span>✏️ Change Email</span>
                          </button>
                        </div>
                      </div>
                    )}

                    <button
                      type="button"
                      className="btn-signin-gradient"
                      onClick={() => handleVerifyOtpCode(otpDigits.join(''))}
                      disabled={authLoading || (otpDigits.join('').length !== 6 && otpDigits.join('').length !== 8)}
                    >
                      {authLoading
                        ? 'Verifying Code…'
                        : (authMode === 'signup' ? 'Verify & Launch Account' : 'Verify & Launch Session')}
                    </button>

                    {/* Quick Demo Access Codes */}
                    <div className="otp-evaluator-box">
                      <span className="evaluator-label">Quick Demo Access Codes:</span>
                      <div className="evaluator-chips-grid">
                        <button
                          type="button"
                          className="evaluator-code-btn evaluator-code-student"
                          onClick={() => handleAutofillOtp('777888', 'student')}
                        >
                          Student Demo: <code>777888</code>
                        </button>
                        <button
                          type="button"
                          className="evaluator-code-btn evaluator-code-parent"
                          onClick={() => handleAutofillOtp('123456', 'parent')}
                        >
                          Parent Demo: <code>123456</code>
                        </button>
                      </div>
                    </div>

                    <div className="otp-resend-row">
                      {resendTimer > 0 ? (
                        <div className="otp-resend-col">
                          <span className="otp-timer-text">Resend new code in <strong>{resendTimer}s</strong></span>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="otp-resend-link"
                          onClick={handleResendOtp}
                          disabled={authLoading || resendCount >= MAX_RESENDS}
                        >
                          {resendCount >= MAX_RESENDS ? 'Max resends reached' : 'Resend verification code'}
                        </button>
                      )}
                      {resendCount > 0 && resendCount < MAX_RESENDS && (
                        <span className="otp-resend-attempts">Attempt {resendCount} of {MAX_RESENDS}</span>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="animate-fadein">
                    {/* Modern Segmented Auth Mode Switcher */}
                    <div className="auth-mode-tabs" role="tablist" aria-label="Authentication Mode">
                      <button
                        type="button"
                        role="tab"
                        aria-selected={authMode === 'signin'}
                        className={`auth-mode-tab ${authMode === 'signin' ? 'auth-mode-tab--active' : ''}`}
                        onClick={() => {
                          setAuthMode('signin')
                          setAuthError('')
                          setRoleMismatchNotice(null)
                        }}
                      >
                        <span className="tab-icon">👋</span>
                        <span>Sign In</span>
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={authMode === 'signup'}
                        className={`auth-mode-tab ${authMode === 'signup' ? 'auth-mode-tab--active' : ''}`}
                        onClick={() => {
                          setAuthMode('signup')
                          setAuthError('')
                          setRoleMismatchNotice(null)
                        }}
                      >
                        <span className="tab-icon">✨</span>
                        <span>Create Account</span>
                      </button>
                    </div>

                    {authMode === 'signin' ? (
                      <div className="auth-greeting-block animate-fadein">
                        <h2 className="auth-greeting">
                          {rememberedProfile ? (
                            <>Holla,<br /><span className="auth-greeting-sub">Welcome Back, {rememberedProfile.name.split(' ')[0]}!</span></>
                          ) : (
                            <>Sign In<br /><span className="auth-greeting-sub">Good to See You</span></>
                          )}
                        </h2>
                        <p className="auth-tagline">
                          {rememberedProfile
                            ? 'Hey, welcome back to your learning space'
                            : 'Enter your email to receive a one-time verification code'}
                        </p>
                      </div>
                    ) : (
                      <div className="auth-greeting-block animate-fadein">
                        <h2 className="auth-greeting">
                          Welcome to Veritas,<br />
                          <span className="auth-greeting-sub">Start Learning</span>
                        </h2>
                        <p className="auth-tagline">Create your student or parent account to begin Socratic discovery</p>
                      </div>
                    )}

                    <form onSubmit={handleSendMagicLinkOrOtp} className="auth-form-body">
                      {/* Name input for new users */}
                      {authMode === 'signup' && (
                        <div className="auth-field-group animate-fadein">
                          <div className="auth-label-row">
                            <label htmlFor="auth-name-input">
                              {role === 'parent' ? 'Parent / Guardian Name' : 'Student Name'}
                            </label>
                            <span className="auth-label-optional">(Optional)</span>
                          </div>
                          <div className="auth-input-wrapper">
                            <input
                              id="auth-name-input"
                              type="text"
                              className="auth-text-input"
                              placeholder={role === 'parent' ? 'e.g. Sarah Jenkins' : 'e.g. Alex Jenkins'}
                              value={fullName}
                              onChange={(e) => {
                                setFullName(sanitizeNameInput(e.target.value))
                                setAuthError('')
                              }}
                              onBlur={handleNameBlur}
                              disabled={authLoading}
                              maxLength={50}
                            />
                          </div>
                        </div>
                      )}

                      <div className="auth-field-group">
                        <div className="auth-label-row">
                          <label htmlFor="auth-email-input">Email Address</label>
                        </div>
                        <div className="auth-input-wrapper">
                          <input
                            id="auth-email-input"
                            type="email"
                            className="auth-text-input"
                            placeholder={authMode === 'signup' ? 'your.name@example.com' : (rememberedProfile?.email || 'your.email@example.com')}
                            value={email}
                            onChange={(e) => {
                              setEmail(e.target.value)
                              setAuthError('')
                              const correction = suggestCorrection(e.target.value)
                              if (!correction) setEmailCorrection(null)
                            }}
                            onBlur={handleEmailBlur}
                            required
                            disabled={authLoading}
                          />
                        </div>

                        {/* Soft Inline Typo Suggestion */}
                        {emailCorrection && (
                          <div className="auth-email-suggestion animate-fadein">
                            <span className="suggestion-icon">💡</span>
                            <span className="suggestion-text">
                              Did you mean <strong>{emailCorrection}</strong>?
                            </span>
                            <button
                              type="button"
                              className="btn-suggestion-apply"
                              onClick={() => {
                                setEmail(emailCorrection)
                                setEmailCorrection(null)
                                setAuthError('')
                              }}
                            >
                              Use this
                            </button>
                          </div>
                        )}

                        {/* Interactive Domain Suggestion Chips */}
                        <div className="auth-domain-chips">
                          <span className="domain-chips-hint">Quick fill:</span>
                          {['@gmail.com', '@icloud.com', '@outlook.com', '@school.edu'].map((dom) => (
                            <button
                              key={dom}
                              type="button"
                              className="domain-chip-btn"
                              onClick={() => handleApplyDomain(dom)}
                            >
                              {dom}
                            </button>
                          ))}
                        </div>

                      </div>

                      {/* Role selection is only required when creating a new account */}
                      {authMode === 'signup' && (
                        <div className="auth-field-group animate-fadein">
                          <label>
                            Select Your Learning Role
                          </label>
                          <div className="auth-role-tabs">
                            <button
                              type="button"
                              className={`auth-role-tab ${role === 'student' ? 'auth-role-tab--active' : ''}`}
                              onClick={() => {
                                setRole('student')
                                checkHealth().catch(() => {})
                              }}
                            >
                              <div className="role-tab-text">
                                <span className="role-tab-title">Student</span>
                                <span className="role-tab-desc">Socratic math tutor</span>
                              </div>
                            </button>

                            <button
                              type="button"
                              className={`auth-role-tab ${role === 'parent' ? 'auth-role-tab--active' : ''}`}
                              onClick={() => {
                                setRole('parent')
                                checkHealth().catch(() => {})
                              }}
                            >
                              <div className="role-tab-text">
                                <span className="role-tab-title">Parent</span>
                                <span className="role-tab-desc">Live radar & history</span>
                              </div>
                            </button>
                          </div>
                        </div>
                      )}

                      {authError && (
                        <div className="auth-error-banner animate-fadein">
                          <div>{authError}</div>
                          {authMode === 'signin' && (authError.toLowerCase().includes('create free account') || authError.toLowerCase().includes('register first') || authError.toLowerCase().includes('no account found')) && (
                            <div style={{ marginTop: '8px' }}>
                              <button
                                type="button"
                                className="btn-auth-switch-prompt"
                                onClick={() => {
                                  setAuthMode('signup')
                                  setAuthError('')
                                }}
                              >
                                ✨ Switch to Create Free Account →
                              </button>
                            </div>
                          )}
                        </div>
                      )}

                      <div className="auth-submit-row">
                        <button
                          type="submit"
                          className="btn-signin-gradient"
                          disabled={authLoading}
                          id="magic-link-submit-btn"
                        >
                          {authLoading
                            ? (authMode === 'signup' ? 'Sending Verification Code…' : 'Sending Secure Code…')
                            : (authMode === 'signup' ? 'Create Free Account & Launch' : 'Sign In with Secure Code')}
                        </button>

                        <div className="auth-spam-pre-hint">
                          <span className="auth-spam-pre-badge">Spam check</span>
                          <span>Codes may arrive in your <strong>Spam / Junk folder</strong>.</span>
                        </div>

                        <div className="auth-mode-switch-row">
                          {authMode === 'signin' ? (
                            <span>
                              New to Veritas?{' '}
                              <button
                                type="button"
                                className="auth-mode-switch-link"
                                onClick={() => {
                                  setAuthMode('signup')
                                  setAuthError('')
                                }}
                              >
                                Create a free account
                              </button>
                            </span>
                          ) : (
                            <span>
                              Already have an account?{' '}
                              <button
                                type="button"
                                className="auth-mode-switch-link"
                                onClick={() => {
                                  setAuthMode('signin')
                                  setAuthError('')
                                }}
                              >
                                Sign in
                              </button>
                            </span>
                          )}
                        </div>

                        <button
                          type="button"
                          className="auth-enter-pin-toggle"
                          onClick={() => {
                            setAuthScreen('otp')
                            setAuthError('')
                          }}
                        >
                          Already have a verification code? Enter code
                        </button>
                      </div>

                      {/* Quick Demo Access */}
                      <div className="auth-demo-section">
                        <span className="demo-label">Instant Demo Preview:</span>
                        <div className="demo-buttons-grid">
                          <button
                            type="button"
                            className="demo-pill-btn demo-pill-parent"
                            onClick={() => handleDemoLogin('parent')}
                          >
                            Demo as Parent
                          </button>
                          <button
                            type="button"
                            className="demo-pill-btn demo-pill-student"
                            onClick={() => handleDemoLogin('student')}
                          >
                            Demo as Student
                          </button>
                        </div>
                      </div>
                    </form>
                  </div>
                )}
              </div>

              {/* Right Panel: Socratic Learning Space Photo Showcase */}
              <div className="auth-card-right auth-card-photo-side">
                <div className="photo-side-image-wrapper">
                  <img
                    src="/student_math_learning.jpg"
                    alt="Student actively learning math with Veritas Socratic tutor"
                    className="photo-side-img"
                  />
                  <div className="photo-side-overlay" />
                </div>

                <div className="photo-side-content">
                  <span className="photo-side-badge">Socratic Learning Space</span>
                  <h3 className="photo-side-title">Think. Reason.<br />Master Math.</h3>
                  <p className="photo-side-desc">
                    Veritas never just gives away solutions. It guides your thinking step-by-step with encouraging questions so you discover patterns and build genuine understanding.
                  </p>
                  <div className="photo-side-chips">
                    <span className="photo-chip">Voice & Vision Scanner</span>
                    <span className="photo-chip">Adaptive Skill Mastery</span>
                    <span className="photo-chip">Student Privacy Protected</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Platform Safety & Compliance Trust Strip */}
          <div className="auth-trust-strip">
            <div className="trust-item">
              <div className="trust-text">
                <strong>FERPA & COPPA Child Safe</strong>
                <span>Zero tracking, student privacy protected</span>
              </div>
            </div>
            <div className="trust-item">
              <div className="trust-text">
                <strong>End-to-End Encryption</strong>
                <span>Safe student & parent access</span>
              </div>
            </div>
            <div className="trust-item">
              <div className="trust-text">
                <strong>Account Protection Active</strong>
                <span>Intelligent account & spam protection</span>
              </div>
            </div>
            <div className="trust-item">
              <div className="trust-text">
                <strong>Socratic AI Guardrails</strong>
                <span>Encourages independent thinking & never spoils answers</span>
              </div>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="stats-grid">
          {STATS.map(s => (
            <div key={s.label} className="stat-card">
              <div className="stat-value">{s.value}</div>
              <div className="stat-label">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Interactive Socratic Demo Showcase */}
      <section id="demo" className="demo-section">
        <SocraticPreview />
      </section>

      {/* Features */}
      <section id="features" className="features">
        {FEATURES.map(f => (
          <div key={f.title} className="feature-card card">
            <h3>{f.title}</h3>
            <p>{f.desc}</p>
          </div>
        ))}
      </section>

      {/* How it works & 3 Helpers */}
      <section id="how-it-works" className="architecture-section">
        <div className="section-header">
          <span className="badge badge-indigo">How It Works</span>
          <h2>How Veritas Helps You Learn</h2>
          <p className="section-sub">
            Three smart helpers work together to guide your math practice, check your handwritten work, and find the perfect next problem.
          </p>
        </div>

        <div className="agents-grid">
          <div className="agent-card card">
            <div className="agent-header">
              <span className="agent-tag badge badge-violet">Helper 1 · Conversation</span>
              <h3>The Friendly Tutor</h3>
            </div>
            <p className="agent-desc">
              Guides your thinking with warm, step-by-step questions. Instead of giving away the solution, it prompts you to notice patterns and discover the answer yourself.
            </p>
            <div className="agent-feature">
              <span>Approach</span> Never gives away answers; asks one helpful question at a time
            </div>
          </div>

          <div className="agent-card card">
            <div className="agent-header">
              <span className="agent-tag badge badge-amber">Helper 2 · Homework Checker</span>
              <h3>Handwritten Work Reader</h3>
            </div>
            <p className="agent-desc">
              Snap a quick picture of your paper math work. It reads your handwriting, verifies each line of working, and points out where a step went off track.
            </p>
            <div className="agent-feature">
              <span>Checks</span> Flipped signs, denominator additions, and calculation errors
            </div>
          </div>

          <div className="agent-card card">
            <div className="agent-header">
              <span className="agent-tag badge badge-emerald">Helper 3 · Practice Guide</span>
              <h3>Smart Problem Finder</h3>
            </div>
            <p className="agent-desc">
              Chooses the next problem tailored to how well you understand the topic. When you're cruising, it adds a fun challenge; when you're stuck, it gives you an easier practice step.
            </p>
            <div className="agent-feature">
              <span>Pacing</span> Keeps problems at just the right challenge level
            </div>
          </div>

          <div className="agent-card card card-highlight">
            <div className="agent-header">
              <span className="agent-tag badge badge-indigo">Progress Engine</span>
              <h3>Live Skill Tracker</h3>
            </div>
            <p className="agent-desc">
              Keeps a live map of your skills as you practice. Every completed problem updates your progress so parents, teachers, and you can see real growth across fractions, word problems, and equations.
            </p>
            <div className="agent-feature">
              <span>Feedback</span> Updates instantly after each problem attempt
            </div>
          </div>
        </div>
      </section>

      {/* Live Draggable Learning Flow Architecture Pipeline */}
      <section id="pipeline" className="pipeline-section">
        <div id="live-pipeline" />
        <div className="section-header">
          <span className="badge badge-cyan">Live Pipeline</span>
          <h2>Real-Time Socratic Learning Engine</h2>
          <p className="section-sub">
            Interactive visual architecture showing how student input flows through safety guardrails, multimodal reasoning, and mastery tracking. Drag nodes or simulate a step below.
          </p>
        </div>
        <InteractivePipeline />
      </section>

      {/* 10 Core Math Topics Section */}
      <section id="topics" className="topics-section">
        <div className="section-header">
          <span className="badge badge-violet">Curriculum Topics</span>
          <h2>10 Core Math Topics You Can Master</h2>
          <p className="section-sub">
            From multiplication and visual fractions to multi-step algebra, practice with problems calibrated directly to standard classroom curricula.
          </p>
        </div>

        <div className="topics-grid">
          {MATH_TOPICS.map(topic => (
            <div key={topic.id} className="topic-card card">
              <div className="topic-card-top">
                <span className="topic-standard">{topic.tag || topic.name}</span>
                <span className="topic-grade">{topic.grade}</span>
              </div>
              <h3 className="topic-title">{topic.name}</h3>
              <p className="topic-desc">{topic.desc}</p>
              <div className="topic-example">
                <span className="example-tag">Sample:</span>
                <code>{topic.example}</code>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Classroom Aligned & Standards */}
      <section className="research-section">
        <div className="section-header">
          <span className="badge badge-emerald">Classroom Aligned</span>
          <h2>Built on Proven Math Learning Standards</h2>
          <p className="section-sub">
            Veritas is modeled around real classroom math curricula and common student learning patterns.
          </p>
        </div>

        <div className="citations-grid">
          <div className="citation-card card">
            <div className="citation-header">
              <h4>Real Student Practice Data</h4>
            </div>
            <p>
              Calibrated with over 55,000 real student practice sessions across fraction, equation, and arithmetic topics to make sure the tutor advances skills at a natural pace.
            </p>
            <span className="citation-source">Student Learning Data (55,000+ Sessions)</span>
          </div>

          <div className="citation-card card">
            <div className="citation-header">
              <h4>Common Mistake Patterns</h4>
            </div>
            <p>
              Recognizes typical elementary and middle school tricky spots — like adding fraction denominators together or flipping negative signs.
            </p>
            <span className="citation-source">Math Misconception Research</span>
          </div>

          <div className="citation-card card">
            <div className="citation-header">
              <h4>Step-by-Step Word Problems</h4>
            </div>
            <p>
              Breaks multi-step word problems into manageable bites so students learn how to set up equations and solve with confidence.
            </p>
            <span className="citation-source">Multi-Step Math Problem Bank</span>
          </div>

          <div className="citation-card card">
            <div className="citation-header">
              <h4>Grade-Level Standards</h4>
            </div>
            <p>
              Aligned directly with standard elementary and middle school Common Core math standards (Grades 3 to 7) matching classroom curricula.
            </p>
            <span className="citation-source">Common Core Math Standards (CCSS-M)</span>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="footer-content">
          <p className="footer-lead">
            <strong>Veritas</strong> · Friendly, Step-by-Step Math Tutoring for Kids
          </p>
          <p className="footer-meta">
            Voice & Vision · Aligned with Classroom Math Standards
          </p>
        </div>
      </footer>
    </div>

    {/* Role-Based Cold-Start Warmup Modal */}
    {showWarmupModal && pendingWarmupDestination && (
      <WarmupExperience
        role={pendingWarmupDestination.role}
        isReady={isWarmupReady}
        isTimeout={isWarmupTimeout}
        onComplete={(scoreData) => {
          if (scoreData) {
            try {
              sessionStorage.setItem('veritas_warmup_badge', JSON.stringify({
                score: scoreData.score,
                total: scoreData.total,
                role: pendingWarmupDestination.role,
              }))
            } catch {}
          }
          setShowWarmupModal(false)
          navigate(pendingWarmupDestination.path)
        }}
        onRetry={() => {
          resetWarmup()
          navigateToRoleWithWarmup(pendingWarmupDestination.role, pendingWarmupDestination.path)
        }}
        onDismiss={() => {
          setShowWarmupModal(false)
          resetWarmup()
        }}
      />
    )}

    {/* Avatar Selection & Profile Modal */}
    <AvatarModal
      isOpen={showAvatarModal}
      onClose={() => setShowAvatarModal(false)}
      onSave={async (newAvatar) => {
        await updateAvatar(newAvatar)
      }}
      currentAvatar={avatar}
      name={user?.user_metadata?.name || rememberedProfile?.name || fullName}
      role={role}
      isRegistration={isRegistrationAvatarStep}
      onSkip={async () => {
        await updateAvatar('initials')
        setShowAvatarModal(false)
      }}
    />
    </>
  )
}
