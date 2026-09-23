import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  getGamesProgress,
  recordGameScore,
  resetGameScore,
  type GameLevel,
  type GamesProgressResponse,
} from '../lib/api'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import AvatarModal from '../components/AvatarModal'
import MathText from '../components/MathText'
import { Volume2, VolumeX } from 'lucide-react'
import './MathArcade.css'

export type GameMode = 'blitz' | 'zen'

// ── Zero-Dependency Web Audio Sound Effects Synthesizer ───────────────
class SoundFX {
  private ctx: AudioContext | null = null
  public enabled: boolean = true

  private getContext(): AudioContext | null {
    if (!this.enabled) return null
    if (!this.ctx && typeof window !== 'undefined') {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      if (AudioCtx) this.ctx = new AudioCtx()
    }
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume()
    }
    return this.ctx
  }

  playCorrect(streak: number = 0) {
    const ctx = this.getContext()
    if (!ctx) return
    const now = ctx.currentTime
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)

    const baseFreq = Math.min(880, 523.25 + streak * 35)
    osc.type = 'triangle'
    osc.frequency.setValueAtTime(baseFreq, now)
    osc.frequency.exponentialRampToValueAtTime(baseFreq * 1.5, now + 0.12)

    gain.gain.setValueAtTime(0.2, now)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22)

    osc.start(now)
    osc.stop(now + 0.23)
  }

  playStreak() {
    const ctx = this.getContext()
    if (!ctx) return
    const now = ctx.currentTime
    const freqs = [587.33, 739.99, 880.0, 1174.66]
    freqs.forEach((f, idx) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.type = 'sine'
      osc.frequency.setValueAtTime(f, now + idx * 0.05)
      gain.gain.setValueAtTime(0.18, now + idx * 0.05)
      gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.05 + 0.18)
      osc.start(now + idx * 0.05)
      osc.stop(now + idx * 0.05 + 0.2)
    })
  }

  playIncorrect() {
    const ctx = this.getContext()
    if (!ctx) return
    const now = ctx.currentTime
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)

    osc.type = 'sawtooth'
    osc.frequency.setValueAtTime(220, now)
    osc.frequency.exponentialRampToValueAtTime(174.61, now + 0.18)

    gain.gain.setValueAtTime(0.15, now)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2)

    osc.start(now)
    osc.stop(now + 0.22)
  }

  playLevelComplete() {
    const ctx = this.getContext()
    if (!ctx) return
    const now = ctx.currentTime
    const chord = [523.25, 659.25, 783.99, 1046.5]
    chord.forEach((f) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.type = 'sine'
      osc.frequency.setValueAtTime(f, now)
      gain.gain.setValueAtTime(0.12, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.5)
      osc.start(now)
      osc.stop(now + 0.55)
    })
  }
}

export const soundFX = new SoundFX()

interface GameQuestion {
  question: string
  options: (number | string)[]
  answer: number | string
  hint?: string
}

/* ── Procedural Question Generators for all 7 Levels ─────────── */

function generateMultiplicationQuestion(): GameQuestion {
  const a = Math.floor(Math.random() * 9) + 2 // 2 to 10
  const b = Math.floor(Math.random() * 9) + 2 // 2 to 10
  const answer = a * b
  const optionsSet = new Set<number>([answer])
  while (optionsSet.size < 4) {
    const delta = (Math.floor(Math.random() * 7) - 3) * (Math.random() > 0.5 ? a : b)
    const fake = Math.max(2, answer + (delta === 0 ? (Math.random() > 0.5 ? 4 : -4) : delta))
    optionsSet.add(fake)
  }
  const options = Array.from(optionsSet).sort(() => Math.random() - 0.5)
  return {
    question: `${a} × ${b}`,
    options,
    answer,
  }
}

function generateDivisionQuestion(): GameQuestion {
  const b = Math.floor(Math.random() * 8) + 2 // divisor: 2 to 9
  const quotient = Math.floor(Math.random() * 9) + 2 // 2 to 10
  const a = b * quotient // dividend
  const answer = quotient
  const optionsSet = new Set<number>([answer])
  while (optionsSet.size < 4) {
    const delta = Math.floor(Math.random() * 5) - 2
    const fake = Math.max(1, answer + (delta === 0 ? 3 : delta))
    optionsSet.add(fake)
  }
  const options = Array.from(optionsSet).sort(() => Math.random() - 0.5)
  return {
    question: `${a} ÷ ${b}`,
    options,
    answer,
  }
}

function generateTwoStepQuestion(): GameQuestion {
  const types = ['mult_add', 'mult_sub', 'paren_mult', 'add_div']
  const type = types[Math.floor(Math.random() * types.length)]
  let question = ''
  let answer = 0

  if (type === 'mult_add') {
    const a = Math.floor(Math.random() * 6) + 3 // 3 to 8
    const b = Math.floor(Math.random() * 6) + 2 // 2 to 7
    const c = Math.floor(Math.random() * 15) + 3 // 3 to 17
    answer = a * b + c
    question = `(${a} × ${b}) + ${c}`
  } else if (type === 'mult_sub') {
    const a = Math.floor(Math.random() * 6) + 4 // 4 to 9
    const b = Math.floor(Math.random() * 6) + 3 // 3 to 8
    const c = Math.floor(Math.random() * 10) + 2 // 2 to 11
    answer = a * b - c
    question = `(${a} × ${b}) - ${c}`
  } else if (type === 'paren_mult') {
    const a = Math.floor(Math.random() * 6) + 2 // 2 to 7
    const b = Math.floor(Math.random() * 5) + 2 // 2 to 6
    const c = Math.floor(Math.random() * 4) + 2 // 2 to 5
    answer = (a + b) * c
    question = `(${a} + ${b}) × ${c}`
  } else {
    const b = Math.floor(Math.random() * 4) + 2 // 2 to 5
    const q = Math.floor(Math.random() * 7) + 3 // 3 to 9
    const total = b * q
    const a = Math.floor(Math.random() * (total - 3)) + 2
    const c = total - a
    answer = q
    question = `(${a} + ${c}) ÷ ${b}`
  }

  const optionsSet = new Set<number>([answer])
  while (optionsSet.size < 4) {
    const delta = Math.floor(Math.random() * 7) - 3
    const fake = Math.max(1, answer + (delta === 0 ? 4 : delta))
    optionsSet.add(fake)
  }
  const options = Array.from(optionsSet).sort(() => Math.random() - 0.5)
  return {
    question,
    options,
    answer,
  }
}

function generateFractionQuestion(): GameQuestion {
  const isEquivalent = Math.random() > 0.4
  if (isEquivalent) {
    const numerators = [1, 2, 3, 4]
    const denominators = [2, 3, 4, 5]
    const den = denominators[Math.floor(Math.random() * denominators.length)]
    const num = numerators[Math.floor(Math.random() * Math.min(den - 1, numerators.length))] || 1
    const multiplier = Math.floor(Math.random() * 2) + 2 // 2 or 3
    const targetDen = den * multiplier
    const answer = num * multiplier

    const optionsSet = new Set<number>([answer])
    while (optionsSet.size < 4) {
      const fake = Math.max(1, answer + (Math.floor(Math.random() * 7) - 3))
      optionsSet.add(fake)
    }
    const options = Array.from(optionsSet).sort(() => Math.random() - 0.5)
    return {
      question: `${num}/${den} = ?/${targetDen}`,
      options,
      answer,
    }
  } else {
    // Fraction Addition with common denominator
    const den = [4, 5, 6, 8, 10][Math.floor(Math.random() * 5)]
    const a = Math.floor(Math.random() * (den - 2)) + 1
    const b = Math.floor(Math.random() * (den - a - 1)) + 1
    const answer = a + b

    const optionsSet = new Set<number>([answer])
    while (optionsSet.size < 4) {
      const fake = Math.max(1, Math.min(den, answer + (Math.floor(Math.random() * 5) - 2)))
      optionsSet.add(fake)
    }
    const options = Array.from(optionsSet).sort(() => Math.random() - 0.5)
    return {
      question: `${a}/${den} + ${b}/${den} = ?/${den}`,
      options,
      answer,
    }
  }
}

function generateEquationQuestion(): GameQuestion {
  const op = ['add', 'sub', 'mult', 'div'][Math.floor(Math.random() * 4)]
  let question = ''
  let answer = 0

  if (op === 'add') {
    const x = Math.floor(Math.random() * 20) + 3
    const c = Math.floor(Math.random() * 15) + 2
    const total = x + c
    answer = x
    question = `x + ${c} = ${total}`
  } else if (op === 'sub') {
    const x = Math.floor(Math.random() * 25) + 8
    const c = Math.floor(Math.random() * (x - 2)) + 1
    const diff = x - c
    answer = x
    question = `x - ${c} = ${diff}`
  } else if (op === 'mult') {
    const x = Math.floor(Math.random() * 9) + 2
    const a = Math.floor(Math.random() * 7) + 2
    const prod = a * x
    answer = x
    question = `${a}x = ${prod}`
  } else {
    const quotient = Math.floor(Math.random() * 8) + 2
    const d = Math.floor(Math.random() * 5) + 2
    const dividend = quotient * d
    answer = dividend
    question = `x ÷ ${d} = ${quotient}`
  }

  const optionsSet = new Set<number>([answer])
  while (optionsSet.size < 4) {
    const delta = Math.floor(Math.random() * 7) - 3
    const fake = Math.max(1, answer + (delta === 0 ? 3 : delta))
    optionsSet.add(fake)
  }
  const options = Array.from(optionsSet).sort(() => Math.random() - 0.5)
  return {
    question: `Solve for x: ${question}`,
    options,
    answer,
  }
}

function generateDecimalQuestion(): GameQuestion {
  const type = ['add', 'sub', 'mult'][Math.floor(Math.random() * 3)]
  let question = ''
  let answerStr = ''
  let numAnswer = 0

  if (type === 'add') {
    const a = (Math.floor(Math.random() * 8) + 1) * 0.25
    const b = (Math.floor(Math.random() * 6) + 1) * 0.25
    numAnswer = Math.round((a + b) * 100) / 100
    answerStr = numAnswer.toFixed(2).replace(/\.?0+$/, '')
    question = `${a} + ${b}`
  } else if (type === 'sub') {
    const b = (Math.floor(Math.random() * 5) + 1) * 0.25
    const numAns = (Math.floor(Math.random() * 6) + 2) * 0.25
    const a = Math.round((numAns + b) * 100) / 100
    numAnswer = numAns
    answerStr = numAnswer.toFixed(2).replace(/\.?0+$/, '')
    question = `${a} - ${b}`
  } else {
    const a = (Math.floor(Math.random() * 8) + 2) * 0.1
    const b = Math.floor(Math.random() * 7) + 2
    numAnswer = Math.round(a * b * 10) / 10
    answerStr = numAnswer.toFixed(1)
    question = `${a.toFixed(1)} × ${b}`
  }

  const optionsSet = new Set<string>([answerStr])
  while (optionsSet.size < 4) {
    const delta = (Math.floor(Math.random() * 5) - 2) * 0.25
    const fakeNum = Math.max(0.25, Math.round((numAnswer + (delta === 0 ? 0.5 : delta)) * 100) / 100)
    optionsSet.add(fakeNum.toFixed(2).replace(/\.?0+$/, ''))
  }
  const options = Array.from(optionsSet).sort(() => Math.random() - 0.5)
  return {
    question,
    options,
    answer: answerStr,
  }
}

function generateGeometryQuestion(): GameQuestion {
  const type = ['rect_area', 'rect_perim', 'square_area', 'square_perim'][Math.floor(Math.random() * 4)]
  let question = ''
  let answer = 0

  if (type === 'rect_area') {
    const l = Math.floor(Math.random() * 8) + 3
    const w = Math.floor(Math.random() * 6) + 2
    answer = l * w
    question = `Area: Rect with length ${l}m, width ${w}m`
  } else if (type === 'rect_perim') {
    const l = Math.floor(Math.random() * 8) + 4
    const w = Math.floor(Math.random() * 6) + 2
    answer = 2 * (l + w)
    question = `Perimeter: Rect with length ${l}m, width ${w}m`
  } else if (type === 'square_area') {
    const s = Math.floor(Math.random() * 8) + 3
    answer = s * s
    question = `Area: Square with side ${s}m`
  } else {
    const s = Math.floor(Math.random() * 9) + 4
    answer = 4 * s
    question = `Perimeter: Square with side ${s}m`
  }

  const optionsSet = new Set<number>([answer])
  while (optionsSet.size < 4) {
    const delta = Math.floor(Math.random() * 9) - 4
    const fake = Math.max(4, answer + (delta === 0 ? 6 : delta))
    optionsSet.add(fake)
  }
  const options = Array.from(optionsSet).sort(() => Math.random() - 0.5)
  return {
    question,
    options,
    answer,
  }
}

export default function MathArcade() {
  const navigate = useNavigate()
  const { user, avatar, updateAvatar, role } = useAuth()
  const cachedSession = (() => {
    try {
      const raw = sessionStorage.getItem('session')
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  })()
  const studentId = user?.id || cachedSession?.student_id || '24e836e3-3b42-41a0-8a27-222f883eaa10'
  const studentName = user?.user_metadata?.name || cachedSession?.student_name || user?.email?.split('@')[0] || 'Student'
  const [showAvatarModal, setShowAvatarModal] = useState(false)

  const [loading, setLoading] = useState(true)
  const [progress, setProgress] = useState<GamesProgressResponse | null>(null)
  const [activeGameId, setActiveGameId] = useState<string | null>(null)

  // Game Mode Selection
  const [selectedMode, setSelectedMode] = useState<GameMode>('blitz')

  // Active Game State
  const [gameTimeLeft, setGameTimeLeft] = useState(45)
  const [zenElapsed, setZenElapsed] = useState(0)
  const [gameScore, setGameScore] = useState(0)
  const [gameStreak, setGameStreak] = useState(0)
  const [maxStreak, setMaxStreak] = useState(0)
  const [currentQuestion, setCurrentQuestion] = useState<GameQuestion | null>(null)
  const [questionFeedback, setQuestionFeedback] = useState<'correct' | 'wrong' | null>(null)
  const [gameOver, setGameOver] = useState(false)
  const [starsEarned, setStarsEarned] = useState(0)
  const [isNewHighScore, setIsNewHighScore] = useState(false)
  const [soundEnabled, setSoundEnabled] = useState(true)
  const [floatingXP, setFloatingXP] = useState<{ id: number; text: string } | null>(null)
  const floatingIdRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Reset Score Modal State
  const [showResetModal, setShowResetModal] = useState(false)
  const [targetResetGame, setTargetResetGame] = useState<GameLevel | null>(null)
  const [isResetting, setIsResetting] = useState(false)

  const loadProgress = useCallback(async () => {
    if (!studentId) return
    try {
      setLoading(true)
      const data = await getGamesProgress(studentId)
      setProgress(data)
    } catch (err) {
      console.error('Failed to load arcade progress:', err)
    } finally {
      setLoading(false)
    }
  }, [studentId])

  useEffect(() => {
    loadProgress()
  }, [loadProgress])

  const nextQuestionForGame = useCallback((gameId: string) => {
    switch (gameId) {
      case 'multiplier_matrix':
        setCurrentQuestion(generateMultiplicationQuestion())
        break
      case 'division_dungeons':
        setCurrentQuestion(generateDivisionQuestion())
        break
      case 'two_step_runner':
        setCurrentQuestion(generateTwoStepQuestion())
        break
      case 'fraction_fusion':
        setCurrentQuestion(generateFractionQuestion())
        break
      case 'equation_alchemist':
        setCurrentQuestion(generateEquationQuestion())
        break
      case 'decimal_dash':
        setCurrentQuestion(generateDecimalQuestion())
        break
      case 'geometry_odyssey':
        setCurrentQuestion(generateGeometryQuestion())
        break
      default:
        setCurrentQuestion(generateMultiplicationQuestion())
        break
    }
  }, [])

  const startGame = (game: GameLevel, mode: GameMode = selectedMode) => {
    if (!game.is_unlocked) return
    setSelectedMode(mode)
    setActiveGameId(game.id)
    setGameScore(0)
    setGameStreak(0)
    setMaxStreak(0)
    setGameTimeLeft(45)
    setZenElapsed(0)
    setGameOver(false)
    setStarsEarned(0)
    setIsNewHighScore(false)
    setQuestionFeedback(null)
    nextQuestionForGame(game.id)
  }

  const exitActiveGame = () => {
    if (timerRef.current) clearInterval(timerRef.current)
    setActiveGameId(null)
    setGameOver(false)
    loadProgress()
  }

  const handleGameOver = useCallback(async () => {
    setGameOver(true)
    if (timerRef.current) clearInterval(timerRef.current)
    if (!activeGameId) return

    soundFX.playLevelComplete()

    // Calculate stars: >= 800: 3 stars, >= 450: 2 stars, >= 150: 1 star
    let earned = 1
    if (gameScore >= 800) earned = 3
    else if (gameScore >= 450) earned = 2

    setStarsEarned(earned)

    const currentGame = progress?.levels.find((l) => l.id === activeGameId)
    const prevHigh = currentGame?.high_score || 0
    if (gameScore > prevHigh) {
      setIsNewHighScore(true)
    }

    try {
      const updated = await recordGameScore(
        studentId,
        activeGameId,
        gameScore,
        earned,
        selectedMode,
        maxStreak,
      )
      setProgress(updated)
    } catch (err) {
      console.error('Failed to record game score:', err)
    }
  }, [activeGameId, gameScore, progress?.levels, studentId, selectedMode, maxStreak])

  // Game Countdown Timer (Blitz) or Count-Up Timer (Zen)
  useEffect(() => {
    if (!activeGameId || gameOver) return

    if (selectedMode === 'blitz') {
      timerRef.current = setInterval(() => {
        setGameTimeLeft((prev) => {
          if (prev <= 1) {
            if (timerRef.current) clearInterval(timerRef.current)
            return 0
          }
          return prev - 1
        })
      }, 1000)
    } else {
      // Zen mode count-up
      timerRef.current = setInterval(() => {
        setZenElapsed((prev) => prev + 1)
      }, 1000)
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [activeGameId, gameOver, selectedMode])

  // Trigger game over when blitz countdown reaches zero
  useEffect(() => {
    if (activeGameId && !gameOver && selectedMode === 'blitz' && gameTimeLeft === 0) {
      handleGameOver()
    }
  }, [activeGameId, gameOver, selectedMode, gameTimeLeft, handleGameOver])

  const handleOptionSelect = (selected: number | string) => {
    if (!currentQuestion || gameOver || questionFeedback) return

    // Normalize comparison for number or string matches
    const isCorrect = String(selected).trim() === String(currentQuestion.answer).trim()

    if (isCorrect) {
      // Correct answer!
      setQuestionFeedback('correct')
      soundFX.playCorrect(gameStreak)
      const nextStreak = gameStreak + 1
      if (nextStreak === 3 || nextStreak === 5 || nextStreak === 8) {
        soundFX.playStreak()
      }

      const multiplier = Math.min(5, Math.floor(gameStreak / 3) + 1)
      const pointsAdded = 100 * multiplier
      setGameScore((s) => s + pointsAdded)
      floatingIdRef.current += 1
      setFloatingXP({ id: floatingIdRef.current, text: `+${pointsAdded} XP` })
      setGameStreak(() => {
        setMaxStreak((m) => Math.max(m, nextStreak))
        return nextStreak
      })

      setTimeout(() => {
        setQuestionFeedback(null)
        setFloatingXP(null)
        if (activeGameId) nextQuestionForGame(activeGameId)
      }, 350)
    } else {
      // Wrong answer
      setQuestionFeedback('wrong')
      soundFX.playIncorrect()
      setGameStreak(0)
      setFloatingXP(null)
      setGameScore((s) => Math.max(0, s - 25))

      setTimeout(() => {
        setQuestionFeedback(null)
        if (activeGameId) nextQuestionForGame(activeGameId)
      }, 500)
    }
  }

  const handleConfirmReset = async () => {
    try {
      setIsResetting(true)
      const updated = await resetGameScore(studentId, targetResetGame?.id)
      setProgress(updated)
      setShowResetModal(false)
      setTargetResetGame(null)
    } catch (err) {
      console.error('Failed to reset score:', err)
      alert('Could not reset game score. Please try again.')
    } finally {
      setIsResetting(false)
    }
  }

  const activeLevel = progress?.levels.find((l) => l.id === activeGameId)
  const currentMultiplier = Math.min(5, Math.floor(gameStreak / 3) + 1)

  return (
    <div className="math-arcade-container">
      {/* Top Glass Navigation Bar */}
      <header className="arcade-navbar">
        <div className="arcade-nav-left">
          <button
            type="button"
            className="arcade-back-btn"
            onClick={() => navigate('/student-session')}
            title="Return to Socratic practice workspace"
          >
            ← Back to Practice
          </button>
          <div className="arcade-brand">
            <span className="arcade-brand-icon">🎮</span>
            <div className="arcade-brand-text">
              <span className="arcade-brand-title">Veritas Math Arcade</span>
              <span className="arcade-brand-subtitle">Curriculum Challenge Zone</span>
            </div>
          </div>
        </div>

        <div className="arcade-nav-stats">
          <div className="arcade-stat-pill stars">
            <span className="stat-icon">⭐</span>
            <div className="stat-meta">
              <span className="stat-value">{progress?.total_stars || 0}</span>
              <span className="stat-label">Stars</span>
            </div>
          </div>

          <div className="arcade-stat-pill score">
            <span className="stat-icon">🏆</span>
            <div className="stat-meta">
              <span className="stat-value">{progress?.total_score || 0}</span>
              <span className="stat-label">Total Score</span>
            </div>
          </div>

          <div className="arcade-stat-pill unlocked">
            <span className="stat-icon">🔓</span>
            <div className="stat-meta">
              <span className="stat-value">
                {progress?.games_unlocked || 1} / {progress?.total_games || 7}
              </span>
              <span className="stat-label">Unlocked</span>
            </div>
          </div>

          {/* Quick Reset All High Scores Trigger */}
          <button
            type="button"
            className="arcade-reset-scores-btn"
            onClick={() => {
              setTargetResetGame(null)
              setShowResetModal(true)
            }}
            title="Reset high scores and start fresh"
          >
            Reset Scores 🔄
          </button>
        </div>

        <div className="arcade-nav-right">
          <button
            type="button"
            className="sound-toggle-btn"
            onClick={() => {
              const next = !soundEnabled
              soundFX.enabled = next
              setSoundEnabled(next)
            }}
            title={soundEnabled ? 'Mute arcade sound effects' : 'Enable arcade sound effects'}
            aria-label={soundEnabled ? 'Mute arcade sound' : 'Enable arcade sound'}
          >
            {soundEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
          </button>
          <ThemeToggle />
          <div
            className="arcade-user-badge"
            onClick={() => setShowAvatarModal(true)}
            style={{ cursor: 'pointer' }}
            title="Click to change profile picture"
          >
            <UserAvatar
              avatar={avatar}
              name={studentName}
              role={role}
              size="sm"
              showEditBadge={true}
            />
            <span className="arcade-user-name">{studentName}</span>
          </div>
        </div>
      </header>

      {/* Main Content: Level Hierarchy Roadmap or Active Game Arena */}
      {!activeGameId ? (
        <main className="arcade-roadmap-view">
          {/* Motivation & Eagerness Header */}
          <section className="arcade-hero-section">
            <div className="arcade-hero-badge">7-TIER LEVEL PROGRESSION ROADMAP</div>
            <h1 className="arcade-hero-title">
              Master Math Practice to <span className="neon-text">Unlock New Games</span>
            </h1>
            <p className="arcade-hero-desc">
              Solve problems and master curriculum standards in your practice sessions to unlock higher
              tiers. Every game you unlock, score you earn, and star you collect is permanently tied to
              your account and saved across logins!
            </p>

            {/* Mode Pre-selector */}
            <div className="hero-mode-selector">
              <span className="mode-selector-label">Preferred Game Mode:</span>
              <div className="mode-toggle-group">
                <button
                  type="button"
                  className={`mode-toggle-btn ${selectedMode === 'blitz' ? 'active' : ''}`}
                  onClick={() => setSelectedMode('blitz')}
                >
                  ⚡ Speed Blitz (45s Timer)
                </button>
                <button
                  type="button"
                  className={`mode-toggle-btn ${selectedMode === 'zen' ? 'active' : ''}`}
                  onClick={() => setSelectedMode('zen')}
                >
                  🧘 Zen Practice (Untimed)
                </button>
              </div>
            </div>
          </section>

          {loading ? (
            <div className="arcade-loading-state">
              <div className="arcade-spinner" />
              <span>Hydrating your game levels and high scores…</span>
            </div>
          ) : (
            <div className="arcade-hierarchy-timeline">
              {progress?.levels.map((lvl, index) => {
                const isUnlocked = lvl.is_unlocked
                const isNextUnlock = !isUnlocked && index > 0 && progress.levels[index - 1].is_unlocked

                return (
                  <div
                    key={lvl.id}
                    className={`arcade-level-node ${isUnlocked ? 'unlocked' : 'locked'} ${
                      isNextUnlock ? 'next-target' : ''
                    } theme-${lvl.theme}`}
                  >
                    {/* Connecting Conduit Line */}
                    {index < progress.levels.length - 1 && (
                      <div
                        className={`arcade-conduit ${
                          isUnlocked && progress.levels[index + 1].is_unlocked ? 'powered' : ''
                        }`}
                      />
                    )}

                    {/* Level Number Orb */}
                    <div className="level-orb">
                      {isUnlocked ? (
                        <span className="orb-num">0{lvl.level}</span>
                      ) : (
                        <span className="orb-lock">🔒</span>
                      )}
                    </div>

                    {/* Level Card Details */}
                    <div className="level-card">
                      <div className="level-card-top">
                        <div className="level-identity">
                          <span className="level-tag">LEVEL {lvl.level}</span>
                          <h3 className="level-name">
                            {lvl.name}{' '}
                            <span className="level-icon">
                              {lvl.theme === 'space' && '🛸'}
                              {lvl.theme === 'dungeon' && '💎'}
                              {lvl.theme === 'castle' && '🏰'}
                              {lvl.theme === 'kitchen' && '🍕'}
                              {lvl.theme === 'alchemy' && '⚖️'}
                              {lvl.theme === 'cyber' && '⚡'}
                              {lvl.theme === 'galaxy' && '🌌'}
                            </span>
                          </h3>
                          <span className="level-subtitle">{lvl.subtitle}</span>
                        </div>

                        <div className="level-status-badge">
                          {isUnlocked ? (
                            <span className="badge-unlocked">
                              <span className="pulse-dot" /> READY TO PLAY
                            </span>
                          ) : (
                            <span className="badge-locked">🔒 LOCKED</span>
                          )}
                        </div>
                      </div>

                      <p className="level-description">{lvl.description}</p>

                      {/* Requirement & Mastery Progress */}
                      <div className="level-requirement-box">
                        <div className="req-header">
                          <span className="req-label">
                            {isUnlocked ? 'Topic Mastered:' : 'Required Assignment:'}
                          </span>
                          <span className="req-skill-code">{lvl.skill_required}</span>
                        </div>
                        <div className="req-title">{lvl.skill_name}</div>

                        {/* Progress Bar towards unlock */}
                        <div className="req-progress-track">
                          <div
                            className={`req-progress-fill ${isUnlocked ? 'completed' : ''}`}
                            style={{ width: `${lvl.progress_percent}%` }}
                          />
                        </div>
                        <div className="req-progress-meta">
                          <span>{lvl.unlock_requirement}</span>
                          <span className="progress-pct">{lvl.progress_percent}%</span>
                        </div>
                      </div>

                      {/* Performance Stats & Actions */}
                      <div className="level-card-footer">
                        <div className="level-metrics">
                          <div className="metric-stars">
                            {[1, 2, 3].map((s) => (
                              <span
                                key={s}
                                className={`star-slot ${s <= lvl.stars ? 'active' : 'inactive'}`}
                              >
                                ★
                              </span>
                            ))}
                          </div>
                          <div className="metric-score">
                            <span className="score-label">BEST:</span>
                            <span className="score-num">{lvl.high_score} PTS</span>
                          </div>
                          {lvl.times_played > 0 && (
                            <span className="metric-played">
                              🎮 {lvl.times_played} {lvl.times_played === 1 ? 'play' : 'plays'}
                            </span>
                          )}
                        </div>

                        <div className="level-actions">
                          {isUnlocked ? (
                            <>
                              <button
                                type="button"
                                className="btn-play-game"
                                onClick={() => startGame(lvl, selectedMode)}
                              >
                                Play Game 🎮
                              </button>
                              {lvl.high_score > 0 && (
                                <button
                                  type="button"
                                  className="btn-reset-single"
                                  onClick={() => {
                                    setTargetResetGame(lvl)
                                    setShowResetModal(true)
                                  }}
                                  title={`Reset high score for ${lvl.name}`}
                                >
                                  Reset 🔄
                                </button>
                              )}
                            </>
                          ) : (
                            <button
                              type="button"
                              className="btn-practice-unlock"
                              onClick={() => navigate('/student-session')}
                              title="Go to tutoring session to solve problems and unlock this game!"
                            >
                              Practice to Unlock ✏️
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </main>
      ) : (
        /* ── Active Game Arena ────────────────────────────────── */
        <main className={`arcade-arena-view theme-${activeLevel?.theme || 'space'}`}>
          <div className="arena-header">
            <button type="button" className="arena-exit-btn" onClick={exitActiveGame}>
              ← Leave Game
            </button>

            <div className="arena-title-group">
              <span className="arena-game-name">{activeLevel?.name}</span>
              <span className="arena-game-mode">
                {selectedMode === 'blitz' ? '⚡ Speed Blitz (45s)' : '🧘 Zen Practice Mode'}
              </span>
            </div>

            <div className="arena-stats-bar">
              <div className="arena-stat-item">
                <span className="label">
                  {selectedMode === 'blitz' ? 'TIME LEFT' : 'ELAPSED'}
                </span>
                <span className={`value time ${selectedMode === 'blitz' && gameTimeLeft <= 10 ? 'urgent' : ''}`}>
                  {selectedMode === 'blitz' ? `${gameTimeLeft}s` : `${zenElapsed}s`}
                </span>
              </div>
              <div className="arena-stat-item">
                <span className="label">SCORE</span>
                <span className="value score">{gameScore}</span>
              </div>
              <div className="arena-stat-item">
                <span className="label">STREAK</span>
                <span className="value streak">
                  {gameStreak}x {currentMultiplier > 1 && <span className="streak-multiplier">({currentMultiplier}x PTS 🔥)</span>}
                </span>
              </div>
              <button
                type="button"
                className="sound-toggle-btn"
                style={{ width: '32px', height: '32px' }}
                onClick={() => {
                  const next = !soundEnabled
                  soundFX.enabled = next
                  setSoundEnabled(next)
                }}
                title={soundEnabled ? 'Mute sound' : 'Enable sound'}
              >
                {soundEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}
              </button>
              {selectedMode === 'zen' && (
                <button
                  type="button"
                  className="arena-finish-btn"
                  onClick={handleGameOver}
                >
                  Finish Round ✅
                </button>
              )}
            </div>
          </div>

          {!gameOver ? (
            <div className="arena-playfield">
              {/* Combo Multiplier Alert */}
              {currentMultiplier > 1 && (
                <div className="streak-banner">
                  <span>🔥 {currentMultiplier}x COMBO MULTIPLIER ACTIVE! (+{100 * currentMultiplier} PTS PER HIT)</span>
                </div>
              )}

              {/* Question Plasma Display */}
              <div className={`question-plasma-orb ${questionFeedback || ''}`}>
                <div className="plasma-core">
                  <span className="question-text">
                    <MathText
                      content={
                        currentQuestion?.question.includes('=') || currentQuestion?.question.startsWith('Solve')
                          ? currentQuestion?.question
                          : `${currentQuestion?.question} = ?`
                      }
                      inline
                    />
                  </span>
                  {floatingXP && (
                    <div key={floatingXP.id} className="floating-xp-indicator">
                      {floatingXP.text}
                    </div>
                  )}
                </div>
                <div className="plasma-ring ring-1" />
                <div className="plasma-ring ring-2" />
              </div>

              {/* 4 Plasma Answer Bubbles */}
              <div className="plasma-options-grid">
                {currentQuestion?.options.map((opt, i) => (
                  <button
                    key={`${opt}-${i}`}
                    type="button"
                    className="plasma-bubble-btn"
                    onClick={() => handleOptionSelect(opt)}
                    disabled={Boolean(questionFeedback)}
                  >
                    <span className="bubble-val">
                      <MathText content={String(opt)} inline />
                    </span>
                  </button>
                ))}
              </div>

              {/* Feedback Flash */}
              {questionFeedback === 'correct' && (
                <div className="feedback-badge correct">
                  💥 CRITICAL HIT! +{100 * currentMultiplier} PTS
                </div>
              )}
              {questionFeedback === 'wrong' && (
                <div className="feedback-badge wrong">⚠️ MISSED! STREAK RESET</div>
              )}
            </div>
          ) : (
            /* Game Over / Victory Modal */
            <div className="game-over-modal-backdrop">
              <div className="game-over-modal">
                <div className="modal-badge">
                  {selectedMode === 'blitz' ? 'BLITZ ROUND COMPLETED' : 'ZEN PRACTICE FINISHED'}
                </div>
                <h2 className="modal-title">
                  {gameScore >= 500 ? '🎉 Stellar Performance!' : '⚡ Challenge Finished!'}
                </h2>
                <p className="modal-subtitle">
                  Your score and stars have been permanently saved to your Veritas account and Parent Portal.
                </p>

                {/* Stars Display */}
                <div className="modal-stars-container">
                  {[1, 2, 3].map((s) => (
                    <span
                      key={s}
                      className={`modal-star ${s <= starsEarned ? 'lit' : 'unlit'}`}
                      style={{ animationDelay: `${s * 0.2}s` }}
                    >
                      ★
                    </span>
                  ))}
                </div>

                <div className="modal-score-summary">
                  <div className="summary-item">
                    <span className="sum-label">FINAL ROUND SCORE</span>
                    <span className="sum-val">{gameScore} PTS</span>
                  </div>
                  <div className="summary-item">
                    <span className="sum-label">MAX STREAK</span>
                    <span className="sum-val">{maxStreak}x 🔥</span>
                  </div>
                  <div className="summary-item">
                    <span className="sum-label">BEST ALL-TIME</span>
                    <span className="sum-val">
                      {Math.max(gameScore, activeLevel?.high_score || 0)} PTS
                    </span>
                  </div>
                  {isNewHighScore && (
                    <div className="new-high-badge">🏆 NEW ALL-TIME HIGH SCORE!</div>
                  )}
                </div>

                <div className="modal-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => {
                      if (activeLevel) startGame(activeLevel, selectedMode)
                    }}
                  >
                    Play Again 🔄
                  </button>
                  <button type="button" className="btn btn-secondary" onClick={exitActiveGame}>
                    Back to Level Roadmap 🗺️
                  </button>
                </div>
              </div>
            </div>
          )}
        </main>
      )}

      {/* Reset Confirmation Modal */}
      {showResetModal && (
        <div className="modal-backdrop" onClick={() => setShowResetModal(false)}>
          <div className="reset-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="reset-modal-icon">🔄</div>
            <h3 className="reset-modal-title">
              {targetResetGame
                ? `Reset ${targetResetGame.name} Scores?`
                : 'Reset All Arcade High Scores?'}
            </h3>
            <p className="reset-modal-desc">
              {targetResetGame
                ? `This will clear your high score (${targetResetGame.high_score} pts), stars, and times played for ${targetResetGame.name} so you can practice from a clean slate.`
                : 'This will reset your high scores, stars, and play logs across all games. Your curriculum skill mastery and practice problems will remain completely intact.'}
            </p>
            <div className="reset-modal-actions">
              <button
                type="button"
                className="btn-cancel"
                onClick={() => setShowResetModal(false)}
                disabled={isResetting}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-confirm-danger"
                onClick={handleConfirmReset}
                disabled={isResetting}
              >
                {isResetting ? 'Resetting…' : 'Confirm Reset'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Avatar Modal */}
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
    </div>
  )
}
