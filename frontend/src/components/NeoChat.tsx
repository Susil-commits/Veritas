import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { sendNeoChat, getNeoSuggestions, type NeoChatResponse } from '../lib/api'
import './NeoChat.css'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  guardrailed?: boolean
  guardrailReason?: string | null
  suggestedActions?: string[]
  timestamp: string
}

const VISITOR_ID_KEY = 'neo_visitor_id'
const CHAT_HISTORY_KEY = 'neo_chat_history_v1'

function getOrCreateVisitorId(): string {
  let vid = localStorage.getItem(VISITOR_ID_KEY)
  if (!vid) {
    vid = 'visitor_' + Math.random().toString(36).substring(2, 11)
    localStorage.setItem(VISITOR_ID_KEY, vid)
  }
  return vid
}

function createMessageId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
}

export default function NeoChat() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, role } = useAuth()
  const [isOpen, setIsOpen] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const saved = localStorage.getItem(CHAT_HISTORY_KEY)
      if (saved) return JSON.parse(saved)
    } catch {}
    return []
  })
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [hasUnread, setHasUnread] = useState(false)
  const [showTooltip, setShowTooltip] = useState(false)

  // Detect if user is on a live tutor session page where sidebar takes right edge
  const isSessionPage = location.pathname === '/session' || location.pathname === '/student-session'

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleOpenChat = () => {
    setIsOpen(true)
    setHasUnread(false)
    setShowTooltip(false)
  }

  // Load contextual suggestions on mount
  useEffect(() => {
    getNeoSuggestions().then(setSuggestions).catch(() => {})
  }, [])

  // Save chat history to localStorage (capped at 50 messages to prevent quota overflow)
  const isInitialMessagesMount = useRef(true)
  useEffect(() => {
    if (isInitialMessagesMount.current) {
      isInitialMessagesMount.current = false
      return
    }
    try {
      const toSave = messages.length > 50 ? messages.slice(-50) : messages
      localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(toSave))
    } catch {}
  }, [messages])

  // Scroll to bottom when messages update or chat opens
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      setTimeout(() => inputRef.current?.focus(), 150)
    }
  }, [isOpen, messages, isLoading])

  // Show a gentle helper tooltip once if user has not interacted
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!isOpen && messages.length === 0) {
        setShowTooltip(true)
      }
    }, 4000)
    return () => clearTimeout(timer)
  }, [isOpen, messages.length])

  const handleSend = async (textToSend?: string) => {
    const query = (textToSend || inputValue).trim()
    if (!query || isLoading) return

    const userMsgId = createMessageId('usr')
    const nowIso = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

    const userMessage: ChatMessage = {
      id: userMsgId,
      role: 'user',
      content: query,
      timestamp: nowIso,
    }

    const updatedHistory = [...messages, userMessage]
    setMessages(updatedHistory)
    setInputValue('')
    setIsLoading(true)

    const visitorId = getOrCreateVisitorId()

    try {
      const historyPayload = updatedHistory.slice(-8).map((m) => ({
        role: m.role,
        content: m.content,
      }))

      const response: NeoChatResponse = await sendNeoChat(query, historyPayload, visitorId)

      const assistantMessage: ChatMessage = {
        id: createMessageId('neo'),
        role: 'assistant',
        content: response.reply,
        guardrailed: response.guardrailed,
        guardrailReason: response.guardrail_reason,
        suggestedActions: response.suggested_actions || [],
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }

      setMessages((prev) => [...prev, assistantMessage])
      if (!isOpen) setHasUnread(true)
    } catch (err: any) {
      const errMsg = err?.response?.data?.detail || 'Neo is temporarily catching its breath. Please try again in a few moments.'
      const errorMessage: ChatMessage = {
        id: createMessageId('err'),
        role: 'assistant',
        content: errMsg,
        guardrailed: false,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const handleClearHistory = () => {
    setMessages([])
    try {
      localStorage.removeItem(CHAT_HISTORY_KEY)
    } catch {}
  }

  const handleActionClick = (action: string) => {
    const actLower = action.toLowerCase()
    if (actLower.includes('start a practice session') || actLower === 'start a practice' || actLower === 'start practice') {
      setIsOpen(false)
      if (user) {
        navigate('/student-session')
      } else {
        const authSection = document.getElementById('auth-card') || document.getElementById('auth-section') || document.querySelector('.auth-card-container') || document.querySelector('.auth-card')
        if (authSection) {
          authSection.scrollIntoView({ behavior: 'smooth' })
        } else {
          navigate('/')
        }
      }
    } else if (actLower.includes('parent dashboard') || actLower === 'view parent dashboard') {
      setIsOpen(false)
      if (user && role === 'parent') {
        navigate('/parent-dashboard')
      } else {
        const authSection = document.getElementById('auth-card') || document.getElementById('auth-section') || document.querySelector('.auth-card-container') || document.querySelector('.auth-card')
        if (authSection) {
          authSection.scrollIntoView({ behavior: 'smooth' })
        } else {
          navigate('/')
        }
      }
    } else {
      handleSend(action)
    }
  }

  const renderFormattedText = (text: string) => {
    const lines = text.split('\n')
    return lines.map((line, idx) => {
      const parts = line.split(/(\*\*.*?\*\*)/g)
      return (
        <div key={idx} className="neo-text-line">
          {parts.map((part, pIdx) => {
            if (part.startsWith('**') && part.endsWith('**')) {
              return <strong key={pIdx}>{part.slice(2, -2)}</strong>
            }
            return <span key={pIdx}>{part}</span>
          })}
        </div>
      )
    })
  }

  const userDisplayName = user?.user_metadata?.name || (role === 'parent' ? 'Parent' : 'Student')
  const userTag = user ? (role === 'parent' ? 'Parent' : 'Student') : 'Visitor'

  return (
    <div className={`neo-chatbot-container${isSessionPage ? ' neo-chatbot-container--session' : ''}`}>
      {/* Floating Launcher Button */}
      {!isOpen && (
        <div className="neo-launcher-wrapper">
          {showTooltip && !isMinimized && (
            <div className="neo-tooltip" onClick={() => setIsOpen(true)}>
              <span>Have questions about Veritas? <strong>Ask Neo</strong></span>
              <button
                className="neo-tooltip-close"
                onClick={(e) => {
                  e.stopPropagation()
                  setShowTooltip(false)
                }}
                title="Dismiss"
                aria-label="Dismiss tooltip"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          )}

          {isMinimized ? (
            /* Minimized circular avatar */
            <button
              className="neo-launcher-mini"
              onClick={() => setIsMinimized(false)}
              aria-label="Expand Neo AI assistant"
              title="Ask Neo"
            >
              <div className="neo-launcher-glow" />
              <span className="neo-launcher-mini-text">N</span>
              {hasUnread && <span className="neo-unread-dot" />}
            </button>
          ) : (
            <div className="neo-launcher-row">
              <button
                className={`neo-launcher-btn ${hasUnread ? 'has-unread' : ''}`}
                onClick={handleOpenChat}
                aria-label="Open Neo AI Assistant"
              >
                <div className="neo-launcher-glow" />
                <span className="neo-launcher-text">Ask Neo</span>
                {hasUnread && <span className="neo-unread-badge">New</span>}
              </button>
              {isSessionPage && (
                <button
                  className="neo-minimize-btn"
                  onClick={() => setIsMinimized(true)}
                  aria-label="Minimize Neo"
                  title="Minimize"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <line x1="5" y1="12" x2="19" y2="12" />
                  </svg>
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Expanded Clean Typography Window */}
      {isOpen && (
        <div className="neo-window" role="dialog" aria-modal="true">
          {/* Header */}
          <div className="neo-header">
            <div className="neo-header-left">
              <div className="neo-avatar">
                <span className="neo-avatar-text">NEO</span>
              </div>
              <div className="neo-title-group">
                <div className="neo-title-row">
                  <h3 className="neo-title">Neo</h3>
                  <span className="neo-tag">AI Guide</span>
                </div>
                <div className="neo-subtitle-row">
                  <span className="neo-subtitle">Veritas Platform Scope Only</span>
                </div>
              </div>
            </div>

            <div className="neo-header-right">
              <span className="neo-user-pill" title={`Session: ${userDisplayName}`}>
                {userTag}
              </span>
              <button
                className="neo-text-btn"
                onClick={handleClearHistory}
                title="Clear conversation"
              >
                Clear
              </button>
              <button
                className="neo-text-btn neo-close-btn"
                onClick={() => setIsOpen(false)}
                title="Close chat"
                aria-label="Close chat"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          {/* Messages Area */}
          <div className="neo-messages-scroll">
            {/* Welcome banner if no messages */}
            {messages.length === 0 && (
              <div className="neo-welcome-card">
                <div className="neo-welcome-glow" />
                <div className="neo-welcome-header">
                  <span className="neo-welcome-badge">Guide</span>
                  <h4>Welcome to Veritas</h4>
                </div>
                <p className="neo-welcome-desc">
                  I am your dedicated platform guide. I can answer questions about our{' '}
                  <strong>Socratic math tutor</strong>, <strong>Grade 3–7 curriculum</strong>,{' '}
                  <strong>Paper Work Reader</strong>, and <strong>Parent Dashboard</strong>.
                </p>

                <div className="neo-guardrail-notice">
                  <span>
                    <strong>Math & Veritas Guide:</strong> I specialize in answering questions about
                    Veritas and math learning.
                  </span>
                </div>

                <div className="neo-suggestions-section">
                  <span className="neo-suggestions-label">Try asking:</span>
                  <div className="neo-suggestion-pills">
                    {suggestions.map((sug, i) => (
                      <button
                        key={i}
                        className="neo-suggestion-chip"
                        onClick={() => handleSend(sug)}
                      >
                        {sug}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Message Stream */}
            {messages.map((msg) => (
              <div key={msg.id} className={`neo-msg-row ${msg.role === 'user' ? 'user-row' : 'neo-row'}`}>
                {msg.role === 'assistant' && (
                  <div className="neo-msg-avatar">
                    <span>N</span>
                  </div>
                )}

                <div className={`neo-msg-bubble ${msg.role === 'user' ? 'user-bubble' : 'neo-bubble'} ${msg.guardrailed ? 'guardrailed-bubble' : ''}`}>
                  {msg.guardrailed && (
                    <div className="neo-guardrail-alert">
                      <span>Veritas Domain Guardrail Active</span>
                    </div>
                  )}

                  <div className="neo-bubble-text">{renderFormattedText(msg.content)}</div>

                  {msg.suggestedActions && msg.suggestedActions.length > 0 && (
                    <div className="neo-action-chips">
                      {msg.suggestedActions.map((act, aIdx) => (
                        <button
                          key={aIdx}
                          className="neo-action-chip"
                          onClick={() => handleActionClick(act)}
                        >
                          <span>{act}</span>
                        </button>
                      ))}
                    </div>
                  )}

                  <span className="neo-msg-time">{msg.timestamp}</span>
                </div>

                {msg.role === 'user' && (
                  <div className="neo-user-avatar">
                    <span>You</span>
                  </div>
                )}
              </div>
            ))}

            {/* Loading / Typing Indicator */}
            {isLoading && (
              <div className="neo-msg-row neo-row">
                <div className="neo-msg-avatar">
                  <span>N</span>
                </div>
                <div className="neo-msg-bubble neo-bubble neo-typing-bubble">
                  <span className="neo-typing-text">Neo is thinking...</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Footer Input */}
          <div className="neo-footer">
            <form
              className="neo-input-form"
              onSubmit={(e) => {
                e.preventDefault()
                handleSend()
              }}
            >
              <input
                ref={inputRef}
                type="text"
                className="neo-input"
                placeholder="Ask Neo about Veritas, math topics, or features..."
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                maxLength={600}
                disabled={isLoading}
              />
              <button
                type="submit"
                className="neo-send-btn"
                disabled={!inputValue.trim() || isLoading}
              >
                Send
              </button>
            </form>

            <div className="neo-footer-disclaimer">
              <span>Personalized Socratic Math Guide</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
