import { useEffect, useState } from 'react'
import './ConfirmLogoutModal.css'

export interface ConfirmLogoutModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => Promise<void> | void
  title?: string
  message?: string
  confirmText?: string
  cancelText?: string
}

export default function ConfirmLogoutModal({
  isOpen,
  onClose,
  onConfirm,
  title = 'Confirm Log Out',
  message = 'Are you sure you want to log out? Your progress, skill mastery, and learning history are safely saved.',
  confirmText = 'Log Out',
  cancelText = 'Cancel',
}: ConfirmLogoutModalProps) {
  const [isLoggingOut, setIsLoggingOut] = useState(false)

  useEffect(() => {
    if (!isOpen) {
      setIsLoggingOut(false)
      return
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isLoggingOut) {
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, isLoggingOut, onClose])

  if (!isOpen) return null

  const handleConfirm = async () => {
    setIsLoggingOut(true)
    try {
      await onConfirm()
    } finally {
      setIsLoggingOut(false)
    }
  }

  return (
    <div
      className="logout-modal-overlay"
      onClick={() => {
        if (!isLoggingOut) onClose()
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="logout-modal-title"
    >
      <div
        className="logout-modal-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="logout-modal-header">
          <div className="logout-icon-box">
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          </div>
          <button
            type="button"
            className="logout-modal-close"
            onClick={onClose}
            disabled={isLoggingOut}
            aria-label="Cancel and close dialog"
          >
            ✕
          </button>
        </div>

        <div className="logout-modal-body">
          <h3 id="logout-modal-title" className="logout-modal-title">
            {title}
          </h3>
          <p className="logout-modal-desc">
            {message}
          </p>
        </div>

        <div className="logout-modal-actions">
          <button
            type="button"
            className="logout-btn-cancel"
            onClick={onClose}
            disabled={isLoggingOut}
          >
            {cancelText}
          </button>
          <button
            type="button"
            className="logout-btn-confirm"
            onClick={handleConfirm}
            disabled={isLoggingOut}
          >
            {isLoggingOut ? 'Logging out…' : confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
