import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getGamesProgress, recordGameScore, type GameLevel, type GamesProgressResponse } from '../lib/api'
import ThemeToggle from '../components/ThemeToggle'
import UserAvatar from '../components/UserAvatar'
import './MathArcade.css'

interface GameQuestion {
  question: string
  options: number[]
  answer: number
}

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

function generateFractionQuestion(): GameQuestion {
  // Equivalent fraction matching: e.g. 2/4 = ?/8 -> answer 4
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
}

export default function MathArcade() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const studentId = user?.id || '24e836e3-3b42-41a0-8a27-222f883eaa10'
  const studentName = user?.user_metadata?.name || user?.email?.split('@')[0] || 'Alex'

  const [loading, setLoading] = useState(true)
  const [progress, setProgress] = useState<GamesProgressResponse | null>(null)
  const [activeGameId, setActiveGameId] = useState<string | null>(null)

  // Active Game State
  const [gameTimeLeft, setGameTimeLeft] = useState(45)
  const [gameScore, setGameScore] = useState(0)
  const [gameStreak, setGameStreak] = useState(0)
  const [currentQuestion, setCurrentQuestion] = useState<GameQuestion | null>(null)
  const [questionFeedback, setQuestionFeedback] = useState<'correct' | 'wrong' | null>(null)
  const [gameOver, setGameOver] = useState(false)
  const [starsEarned, setStarsEarned] = useState(0)
  const [isNewHighScore, setIsNewHighScore] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

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
    if (gameId === 'multiplier_matrix') {
      setCurrentQuestion(generateMultiplicationQuestion())
    } else if (gameId === 'division_dungeons') {
      setCurrentQuestion(generateDivisionQuestion())
    } else {
      setCurrentQuestion(generateFractionQuestion())
    }
  }, [])

  const startGame = (game: GameLevel) => {
    if (!game.is_unlocked) return
    setActiveGameId(game.id)
    setGameScore(0)
    setGameStreak(0)
    setGameTimeLeft(45)
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
    if (!activeGameId) return

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
      const updated = await recordGameScore(studentId, activeGameId, gameScore, earned)
      setProgress(updated)
    } catch (err) {
      console.error('Failed to record game score:', err)
    }
  }, [activeGameId, gameScore, progress?.levels, studentId])

  // Game Countdown Timer
  useEffect(() => {
    if (!activeGameId || gameOver) return

    timerRef.current = setInterval(() => {
      setGameTimeLeft((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current)
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [activeGameId, gameOver])

  // Trigger game over when countdown reaches zero
  useEffect(() => {
    if (activeGameId && !gameOver && gameTimeLeft === 0) {
      handleGameOver()
    }
  }, [activeGameId, gameOver, gameTimeLeft, handleGameOver])

  const handleOptionSelect = (selected: number) => {
    if (!currentQuestion || gameOver || questionFeedback) return

    if (selected === currentQuestion.answer) {
      // Correct answer!
      setQuestionFeedback('correct')
      const multiplier = Math.min(5, Math.floor(gameStreak / 3) + 1)
      const pointsAdded = 100 * multiplier
      setGameScore((s) => s + pointsAdded)
      setGameStreak((st) => st + 1)

      setTimeout(() => {
        setQuestionFeedback(null)
        if (activeGameId) nextQuestionForGame(activeGameId)
      }, 350)
    } else {
      // Wrong answer
      setQuestionFeedback('wrong')
      setGameStreak(0)
      setGameScore((s) => Math.max(0, s - 25))

      setTimeout(() => {
        setQuestionFeedback(null)
        if (activeGameId) nextQuestionForGame(activeGameId)
      }, 500)
    }
  }

  const activeLevel = progress?.levels.find((l) => l.id === activeGameId)

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
                {progress?.games_unlocked || 1} / {progress?.total_games || 5}
              </span>
              <span className="stat-label">Unlocked</span>
            </div>
          </div>
        </div>

        <div className="arcade-nav-right">
          <ThemeToggle />
          <div className="arcade-user-badge">
            <UserAvatar name={studentName} size="sm" />
            <span className="arcade-user-name">{studentName}</span>
          </div>
        </div>
      </header>

      {/* Main Content: Level Hierarchy Roadmap or Active Game Arena */}
      {!activeGameId ? (
        <main className="arcade-roadmap-view">
          {/* Motivation & Eagerness Header */}
          <section className="arcade-hero-section">
            <div className="arcade-hero-badge">LEVEL PROGRESSION ROADMAP</div>
            <h1 className="arcade-hero-title">
              Complete Math Practice to <span className="neon-text">Unlock New Games</span>
            </h1>
            <p className="arcade-hero-desc">
              Solve problems and master curriculum standards in your practice sessions to unlock higher
              tiers. Every game you unlock, score you earn, and star you collect is permanently tied to
              your account and saved across logins!
            </p>
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
                        </div>

                        <div className="level-actions">
                          {isUnlocked ? (
                            <button
                              type="button"
                              className="btn-play-game"
                              onClick={() => startGame(lvl)}
                            >
                              Play Game 🎮
                            </button>
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
              <span className="arena-game-mode">Curriculum Challenge Blitz</span>
            </div>

            <div className="arena-stats-bar">
              <div className="arena-stat-item">
                <span className="label">TIME</span>
                <span className={`value time ${gameTimeLeft <= 10 ? 'urgent' : ''}`}>
                  {gameTimeLeft}s
                </span>
              </div>
              <div className="arena-stat-item">
                <span className="label">SCORE</span>
                <span className="value score">{gameScore}</span>
              </div>
              <div className="arena-stat-item">
                <span className="label">STREAK</span>
                <span className="value streak">
                  {gameStreak}x {gameStreak >= 3 && '🔥'}
                </span>
              </div>
            </div>
          </div>

          {!gameOver ? (
            <div className="arena-playfield">
              {/* Question Plasma Display */}
              <div className={`question-plasma-orb ${questionFeedback || ''}`}>
                <div className="plasma-core">
                  <span className="question-text">{currentQuestion?.question} = ?</span>
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
                    <span className="bubble-val">{opt}</span>
                  </button>
                ))}
              </div>

              {/* Feedback Flash */}
              {questionFeedback === 'correct' && (
                <div className="feedback-badge correct">💥 CRITICAL HIT! +100 PTS</div>
              )}
              {questionFeedback === 'wrong' && (
                <div className="feedback-badge wrong">⚠️ MISSED! STREAK RESET</div>
              )}
            </div>
          ) : (
            /* Game Over / Victory Modal */
            <div className="game-over-modal-backdrop">
              <div className="game-over-modal">
                <div className="modal-badge">ROUND COMPLETED</div>
                <h2 className="modal-title">
                  {gameScore >= 500 ? '🎉 Stellar Performance!' : '⚡ Challenge Finished!'}
                </h2>
                <p className="modal-subtitle">
                  Your score and stars have been permanently synced to your Veritas account.
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
                    <span className="sum-label">FINAL SCORE</span>
                    <span className="sum-val">{gameScore} PTS</span>
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
                      if (activeLevel) startGame(activeLevel)
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
    </div>
  )
}
