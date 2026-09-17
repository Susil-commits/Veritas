import React, { useState, useMemo } from 'react'
import { getColorfulGradient, getInitial, isImageAvatar, isPersonSilhouette } from '../lib/avatars'
import './UserAvatar.css'

export interface UserAvatarProps {
  avatar?: string | null
  name?: string
  role?: 'student' | 'parent'
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  onClick?: () => void
  showEditBadge?: boolean
  alt?: string
}

const SIZE_MAP: Record<string, { px: number; font: string }> = {
  xs: { px: 24, font: '0.7rem' },
  sm: { px: 32, font: '0.85rem' },
  md: { px: 40, font: '1rem' },
  lg: { px: 56, font: '1.4rem' },
  xl: { px: 84, font: '2.1rem' },
}

export default function UserAvatar({
  avatar,
  name,
  role,
  size = 'md',
  className = '',
  onClick,
  showEditBadge = false,
  alt,
}: UserAvatarProps) {
  const [imgError, setImgError] = useState(false)
  const dim = SIZE_MAP[size] || SIZE_MAP.md

  const resolvedAvatar = useMemo(() => {
    if (avatar && avatar !== 'initials') return avatar
    // Try localStorage lookups for this student/user
    if (name) {
      const lower = localStorage.getItem(`veritas_avatar_${name.toLowerCase()}`)
      if (lower && lower !== 'initials') return lower
      const direct = localStorage.getItem(`veritas_avatar_${name}`)
      if (direct && direct !== 'initials') return direct
    }
    const globalAv = localStorage.getItem('veritas_avatar')
    if (globalAv && globalAv !== 'initials') return globalAv
    try {
      const rem = localStorage.getItem('veritas_remembered_profile')
      if (rem) {
        const parsed = JSON.parse(rem)
        if (parsed?.avatar && parsed.avatar !== 'initials') return parsed.avatar
      }
    } catch {}
    return avatar || null
  }, [avatar, name])

  const isImg = !imgError && isImageAvatar(resolvedAvatar)
  const isSilhouette = isPersonSilhouette(resolvedAvatar)
  const initial = getInitial(name, role)
  const gradient = getColorfulGradient(name || role || 'User')

  const containerStyle: React.CSSProperties = {
    width: `${dim.px}px`,
    height: `${dim.px}px`,
    minWidth: `${dim.px}px`,
    minHeight: `${dim.px}px`,
    borderRadius: '50%',
    cursor: onClick ? 'pointer' : 'default',
  }

  return (
    <div
      className={`user-avatar-wrapper ${onClick ? 'user-avatar--interactive' : ''} ${className}`}
      style={containerStyle}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (onClick && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onClick()
        }
      }}
      title={onClick ? 'Click to change profile picture' : (name || 'User Profile')}
    >
      {isImg ? (
        <img
          src={resolvedAvatar!}
          alt={alt || name || 'Profile Avatar'}
          className="user-avatar-img"
          onError={() => setImgError(true)}
        />
      ) : isSilhouette ? (
        <div className="user-avatar-silhouette" style={{ width: '100%', height: '100%' }}>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="user-avatar-silhouette-icon"
          >
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </div>
      ) : (
        <div
          className="user-avatar-initials"
          style={{
            background: gradient.bg,
            color: gradient.text,
            fontSize: dim.font,
            boxShadow: `0 2px 10px ${gradient.shadow}`,
          }}
        >
          {initial}
        </div>
      )}

      {showEditBadge && (
        <div className="user-avatar-edit-badge" title="Edit avatar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
          </svg>
        </div>
      )}
    </div>
  )
}
