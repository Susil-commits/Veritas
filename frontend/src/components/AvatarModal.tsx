import React, { useState, useRef, useEffect } from 'react'
import { SUGGESTED_AVATARS, isPersonSilhouette } from '../lib/avatars'
import { uploadAvatar } from '../lib/api'
import UserAvatar from './UserAvatar'
import './AvatarModal.css'

export interface AvatarModalProps {
  isOpen: boolean
  onClose: () => void
  onSave: (avatarVal: string) => Promise<void> | void
  currentAvatar?: string | null
  name?: string
  role?: 'student' | 'parent'
  isRegistration?: boolean
  onSkip?: () => void
}

export default function AvatarModal({
  isOpen,
  onClose,
  onSave,
  currentAvatar,
  name,
  role = 'student',
  isRegistration = false,
  onSkip,
}: AvatarModalProps) {
  const [selectedAvatar, setSelectedAvatar] = useState<string>(currentAvatar || 'initials')
  const [isSaving, setIsSaving] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (isOpen) {
      setSelectedAvatar(currentAvatar || 'initials')
      setUploadError(null)
    }
  }, [isOpen, currentAvatar])

  if (!isOpen) return null

  // Handle client-side file upload and lightweight compression (max 256x256)
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    if (!file.type.startsWith('image/')) {
      setUploadError('Please select a valid image file (PNG, JPG, WEBP).')
      return
    }

    if (file.size > 8 * 1024 * 1024) {
      setUploadError('Image size is too large (max 8MB). Please choose a smaller photo.')
      return
    }

    setUploadError(null)
    const reader = new FileReader()
    reader.onload = (event) => {
      const img = new Image()
      img.onload = () => {
        const canvas = document.createElement('canvas')
        const MAX_DIM = 256
        let { width, height } = img

        // Crop to square centered
        const minDim = Math.min(width, height)
        const sx = (width - minDim) / 2
        const sy = (height - minDim) / 2

        canvas.width = MAX_DIM
        canvas.height = MAX_DIM
        const ctx = canvas.getContext('2d')
        if (ctx) {
          ctx.drawImage(img, sx, sy, minDim, minDim, 0, 0, MAX_DIM, MAX_DIM)
          const compressedDataUrl = canvas.toDataURL('image/jpeg', 0.88)
          setSelectedAvatar(compressedDataUrl)
        }
      }
      img.onerror = () => {
        setUploadError('Could not process image file. Please try another one.')
      }
      img.src = event.target?.result as string
    }
    reader.readAsDataURL(file)
    // Reset file input so same file can be re-selected if needed
    e.target.value = ''
  }

  const handleSave = async () => {
    setIsSaving(true)
    try {
      let finalAvatar = selectedAvatar
      if (selectedAvatar && selectedAvatar.startsWith('data:image/')) {
        finalAvatar = await uploadAvatar(selectedAvatar, name || role || 'user')
      }
      await onSave(finalAvatar)
      onClose()
    } catch (err: any) {
      console.error('Save avatar failed:', err)
      setUploadError('Failed to save avatar. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  const handleSkip = () => {
    if (onSkip) {
      onSkip()
    } else {
      onSave('initials')
      onClose()
    }
  }

  const handleDeletePhoto = () => {
    // Delete photo resets avatar to neutral person icon, which cannot be deleted further
    setSelectedAvatar('person')
  }

  const isSilhouetteActive = isPersonSilhouette(selectedAvatar)
  const isInitialsActive = selectedAvatar === 'initials' || (!selectedAvatar && !isSilhouetteActive)

  return (
    <div className="avatar-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="avatar-modal-card animate-fadein" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="avatar-modal-header">
          <div>
            <h2 className="avatar-modal-title">
              {isRegistration ? 'Choose Your Avatar' : 'Update Profile Picture'}
            </h2>
            <p className="avatar-modal-subtitle">
              {isRegistration
                ? 'Select a suggested character, upload your own photo, or skip to use your colorful name initial.'
                : 'Personalize your learning workspace identity.'}
            </p>
          </div>
          {!isRegistration && (
            <button
              type="button"
              className="avatar-modal-close-btn"
              onClick={onClose}
              aria-label="Close dialog"
            >
              ✕
            </button>
          )}
        </div>

        {/* Live Preview Bar */}
        <div className="avatar-preview-section">
          <div className="avatar-preview-ring">
            <UserAvatar
              avatar={selectedAvatar}
              name={name}
              role={role}
              size="xl"
            />
          </div>
          <div className="avatar-preview-meta">
            <span className="avatar-preview-badge">Active Selection</span>
            <div className="avatar-preview-name">
              {isSilhouetteActive
                ? 'Neutral Person Icon'
                : isInitialsActive
                ? `Colorful Initial "${name ? name.charAt(0).toUpperCase() : (role === 'parent' ? 'P' : 'S')}"`
                : selectedAvatar.startsWith('data:')
                ? 'Custom Uploaded Photo'
                : (SUGGESTED_AVATARS.find((a) => a.src === selectedAvatar)?.label || 'Selected Avatar')}
            </div>
            <span className="avatar-preview-hint">
              {isSilhouetteActive
                ? 'Neutral fallback silhouette (cannot be deleted further)'
                : 'Will appear across practice sessions and dashboards'}
            </span>
          </div>
        </div>

        {/* Upload & Quick Action Bar */}
        <div className="avatar-quick-actions">
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            accept="image/png,image/jpeg,image/webp,image/avif"
            onChange={handleFileChange}
          />
          <button
            type="button"
            className="btn-avatar-action btn-avatar-upload"
            onClick={() => fileInputRef.current?.click()}
          >
            <span>📁</span>
            <span>Upload from Device</span>
          </button>

          <button
            type="button"
            className={`btn-avatar-action ${isInitialsActive ? 'btn-avatar-action--active' : ''}`}
            onClick={() => setSelectedAvatar('initials')}
            title="Use vibrant colorful name initial"
          >
            <span>🎨</span>
            <span>Colorful Initial</span>
          </button>

          <button
            type="button"
            className="btn-avatar-action btn-avatar-delete"
            onClick={handleDeletePhoto}
            disabled={isSilhouetteActive}
            title={
              isSilhouetteActive
                ? 'Neutral person icon is already active and cannot be deleted'
                : 'Delete current picture and use neutral person icon'
            }
          >
            <span>🗑️</span>
            <span>{isSilhouetteActive ? 'Person Icon Active' : 'Delete Picture'}</span>
          </button>
        </div>

        {uploadError && <div className="avatar-error-banner">{uploadError}</div>}

        {/* Suggested Avatars Grid */}
        <div className="avatar-grid-container">
          <label className="avatar-grid-label">Suggested Avatars ({SUGGESTED_AVATARS.length})</label>
          <div className="avatar-grid">
            {SUGGESTED_AVATARS.map((item) => {
              const isSelected = selectedAvatar === item.src
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`avatar-grid-item ${isSelected ? 'avatar-grid-item--selected' : ''}`}
                  onClick={() => setSelectedAvatar(item.src)}
                  title={item.label}
                >
                  <img src={item.src} alt={item.label} className="avatar-grid-img" />
                  <span className="avatar-grid-tag">{item.label}</span>
                  {isSelected && <span className="avatar-grid-check">✓</span>}
                </button>
              )
            })}
          </div>
        </div>

        {/* Footer Actions */}
        <div className="avatar-modal-footer">
          {isRegistration ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={handleSkip}
              disabled={isSaving}
            >
              Skip for Now (Use Default)
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onClose}
              disabled={isSaving}
            >
              Cancel
            </button>
          )}

          <button
            type="button"
            className="btn-signin-gradient"
            style={{ margin: 0, padding: '10px 22px' }}
            onClick={handleSave}
            disabled={isSaving}
          >
            {isSaving ? 'Saving…' : isRegistration ? 'Set Avatar & Launch →' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
