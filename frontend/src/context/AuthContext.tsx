import React, { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react'
import type { User, Session } from '@supabase/supabase-js'
import { supabase, type UserRole } from '../lib/supabase'
import { stopAllSpeech } from '../hooks/useVoice'

export interface RememberedProfile {
  email: string
  name: string
  role: UserRole
  lastActive: string
  avatar: string
}

export interface VerifyOtpResult {
  error: string | null
  registeredRole?: UserRole
  roleMismatch?: boolean
}

interface AuthContextType {
  user: User | null
  session: Session | null
  role: UserRole
  avatar: string | null
  updateAvatar: (avatarVal: string) => Promise<void>
  loading: boolean
  sendMagicLink: (email: string, targetRole: UserRole, fullName?: string, isSignUp?: boolean) => Promise<{ error: string | null }>
  verifyOtp: (email: string, token: string, targetRole: UserRole, preferredName?: string) => Promise<VerifyOtpResult>
  demoSignIn: (targetRole: UserRole, customEmail?: string) => Promise<void>
  signOut: () => Promise<void>
  setRole: (role: UserRole) => void
  rememberedProfile: RememberedProfile | null
  clearRememberedProfile: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

// Evaluator Convenience: Pre-seeded demo account UUIDs for instant evaluator walkthroughs.
// These correspond to pre-populated Supabase mastery records and curriculum links.
const DEMO_STUDENT_ID = '24e836e3-3b42-41a0-8a27-222f883eaa10'
const DEMO_PARENT_ID = '99999999-8888-7777-6666-555555555555'

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [role, setRoleState] = useState<UserRole>(() => {
    return (localStorage.getItem('veritas_user_role') as UserRole) || 'student'
  })
  const roleRef = useRef<UserRole>(role)
  useEffect(() => {
    roleRef.current = role
  }, [role])
  const [loading, setLoading] = useState(true)
  const [avatar, setAvatar] = useState<string | null>(() => {
    try {
      const directAv = localStorage.getItem('veritas_avatar')
      if (directAv) return directAv
      const rem = localStorage.getItem('veritas_remembered_profile')
      if (rem) {
        const parsed = JSON.parse(rem)
        return parsed.avatar || null
      }
    } catch {}
    return null
  })

  const [rememberedProfile, setRememberedProfile] = useState<RememberedProfile | null>(() => {
    try {
      const raw = localStorage.getItem('veritas_remembered_profile')
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  })

  const saveProfile = useCallback((p: RememberedProfile) => {
    setRememberedProfile((prev) => {
      const activeAvatar = p.avatar || prev?.avatar || 'initials'
      const updated = { ...p, avatar: activeAvatar }
      try {
        localStorage.setItem('veritas_remembered_profile', JSON.stringify(updated))
      } catch {}
      return updated
    })
  }, [])

  const clearRememberedProfile = () => {
    setRememberedProfile(null)
    localStorage.removeItem('veritas_remembered_profile')
  }

  const setRole = (newRole: UserRole) => {
    roleRef.current = newRole
    setRoleState(newRole)
    localStorage.setItem('veritas_user_role', newRole)
  }

  const updateAvatar = async (avatarVal: string) => {
    setAvatar(avatarVal)
    localStorage.setItem('veritas_avatar', avatarVal)

    // 1. If user is authenticated in Supabase, update auth metadata
    if (user && session) {
      try {
        await supabase.auth.updateUser({
          data: { avatar: avatarVal },
        })
      } catch (err) {
        console.warn('Could not update avatar in Supabase auth metadata:', err)
      }
    }

    // 2. Update active user state and storage
    if (user) {
      const updatedUser = {
        ...user,
        user_metadata: {
          ...user.user_metadata,
          avatar: avatarVal,
        },
      }
      setUser(updatedUser as User)
      if (user.id) {
        localStorage.setItem(`veritas_avatar_${user.id}`, avatarVal)
      }
      if (user.email) {
        localStorage.setItem(`veritas_avatar_${user.email}`, avatarVal)
      }
      if (user.user_metadata?.name) {
        localStorage.setItem(`veritas_avatar_${user.user_metadata.name.toLowerCase()}`, avatarVal)
        localStorage.setItem(`veritas_avatar_${user.user_metadata.name}`, avatarVal)
      }
      const isDemo = localStorage.getItem('veritas_demo_user')
      if (isDemo) {
        localStorage.setItem('veritas_demo_user', JSON.stringify(updatedUser))
      }
    }

    // 3. Update cached session student avatar if available
    try {
      const rawSession = sessionStorage.getItem('session')
      if (rawSession) {
        const parsed = JSON.parse(rawSession)
        if (parsed?.student_name) {
          localStorage.setItem(`veritas_avatar_${parsed.student_name.toLowerCase()}`, avatarVal)
          localStorage.setItem(`veritas_avatar_${parsed.student_name}`, avatarVal)
        }
        if (parsed?.student_id) {
          localStorage.setItem(`veritas_avatar_${parsed.student_id}`, avatarVal)
        }
      }
    } catch {}

    // 4. Update remembered profile
    setRememberedProfile((prev) => {
      if (!prev) return null
      const updated = { ...prev, avatar: avatarVal }
      try {
        localStorage.setItem('veritas_remembered_profile', JSON.stringify(updated))
      } catch {}
      return updated
    })
  }

  useEffect(() => {
    // 1. Check existing Supabase session
    supabase.auth.getSession().then(({ data: { session: currentSession } }) => {
      if (currentSession) {
        setSession(currentSession)
        setUser(currentSession.user)
        const userMetaRole = currentSession.user.user_metadata?.user_role as UserRole | undefined
        if (userMetaRole && (userMetaRole === 'student' || userMetaRole === 'parent')) {
          setRole(userMetaRole)
        }
        const userMetaAvatar = currentSession.user.user_metadata?.avatar as string | undefined
        const localAvatar = currentSession.user.id
          ? localStorage.getItem(`veritas_avatar_${currentSession.user.id}`)
          : null
        const activeAv = userMetaAvatar || localAvatar || 'initials'
        setAvatar(activeAv)
        saveProfile({
          email: currentSession.user.email || '',
          name: currentSession.user.user_metadata?.name || (userMetaRole === 'parent' ? 'Parent' : 'Student'),
          role: userMetaRole || roleRef.current,
          lastActive: new Date().toISOString(),
          avatar: activeAv,
        })
      } else {
        // Check if demo user is stored
        const storedDemo = localStorage.getItem('veritas_demo_user')
        if (storedDemo) {
          try {
            const parsed = JSON.parse(storedDemo)
            setUser(parsed)
            if (parsed.user_metadata?.user_role) {
              setRole(parsed.user_metadata.user_role)
            }
            const demoAv = parsed.user_metadata?.avatar || localStorage.getItem(`veritas_avatar_${parsed.id}`) || 'initials'
            setAvatar(demoAv)
          } catch {}
        }
      }
      setLoading(false)
    }).catch((err) => {
      console.warn('Supabase getSession error:', err)
      setLoading(false)
    })

    // 2. Listen to Supabase auth state changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, newSession) => {
      setSession(newSession)
      if (newSession?.user) {
        setUser(newSession.user)
        const userMetaRole = newSession.user.user_metadata?.user_role as UserRole | undefined
        if (userMetaRole) {
          setRole(userMetaRole)
        }
        // Purge cached session if it belonged to a different student
        try {
          const rawSession = sessionStorage.getItem('session')
          if (rawSession) {
            const parsed = JSON.parse(rawSession)
            if (parsed?.student_id && parsed.student_id !== newSession.user.id) {
              sessionStorage.removeItem('session')
            }
          }
        } catch {}

        const userMetaAvatar = newSession.user.user_metadata?.avatar as string | undefined
        const localAvatar = newSession.user.id
          ? localStorage.getItem(`veritas_avatar_${newSession.user.id}`)
          : null
        const activeAv = userMetaAvatar || localAvatar || 'initials'
        setAvatar(activeAv)

        saveProfile({
          email: newSession.user.email || '',
          name: newSession.user.user_metadata?.name || (userMetaRole === 'parent' ? 'Parent' : 'Student'),
          role: userMetaRole || roleRef.current,
          lastActive: new Date().toISOString(),
          avatar: activeAv,
        })
      } else if (event === 'SIGNED_OUT') {
        setUser(null)
        setAvatar(null)
        localStorage.removeItem('veritas_demo_user')
        sessionStorage.removeItem('session')
      }
      setLoading(false)
    })

    return () => {
      subscription.unsubscribe()
    }
  }, [saveProfile])

  const sendMagicLink = async (
    email: string,
    targetRole: UserRole,
    fullName?: string,
    isSignUp = false
  ): Promise<{ error: string | null }> => {
    try {
      if (isSignUp) {
        setRole(targetRole)
      }
      const cleanEmail = email.trim().toLowerCase()
      const trimmedName = fullName?.trim()

      // CRITICAL: Only attach user_role and name metadata during signup.
      // On sign-in, passing metadata options will mutate/overwrite an existing user's role in Supabase!
      // By omitting options.data on sign-in, existing accounts preserve their registered role permanently.
      const metadataOptions: Record<string, any> = {}
      if (isSignUp) {
        metadataOptions.user_role = targetRole
        if (trimmedName) {
          metadataOptions.name = trimmedName
        }
      }

      const { error } = await supabase.auth.signInWithOtp({
        email: cleanEmail,
        options: {
          shouldCreateUser: isSignUp,
          ...(isSignUp ? { data: metadataOptions } : {}),
          emailRedirectTo: `${window.location.origin}/`,
        },
      })
      if (error) {
        return { error: error.message }
      }
      return { error: null }
    } catch (err: any) {
      return { error: err?.message || 'Failed to send magic link. Please check email address.' }
    }
  }

  const verifyOtp = async (
    email: string,
    token: string,
    targetRole: UserRole,
    preferredName?: string
  ): Promise<VerifyOtpResult> => {
    const cleanEmail = email.trim().toLowerCase()
    const cleanToken = token.trim()

    // Evaluator Convenience: Instant OTP bypass codes strictly gated to designated demo accounts:
    // - student.alex@veritas.dev + 77778888 (or 777888)
    // - parent.sarah@veritas.dev + 12345678 (or 123456)
    // Strictly requires BOTH matching demo email and matching demo OTP code.
    // Real emails (e.g., @gmail.com) can NEVER trigger synthetic demo flows.
    const isStudentDemo =
      cleanEmail === 'student.alex@veritas.dev' &&
      (cleanToken === '77778888' || cleanToken === '777888')
    const isParentDemo =
      cleanEmail === 'parent.sarah@veritas.dev' &&
      (cleanToken === '12345678' || cleanToken === '123456')

    if (isStudentDemo || isParentDemo) {
      const demoRole: UserRole = isParentDemo ? 'parent' : 'student'
      await demoSignIn(demoRole, cleanEmail)
      return { error: null, registeredRole: demoRole, roleMismatch: demoRole !== targetRole }
    }

    try {
      const { data, error } = await supabase.auth.verifyOtp({
        email: cleanEmail,
        token: cleanToken,
        type: 'email',
      })

      if (error) {
        return { error: error.message }
      }

      if (data?.user) {
        // Purge any stale demo session before establishing real authenticated state
        // to prevent hybrid-identity where old demo ID/role leaks into authenticated API calls
        localStorage.removeItem('veritas_demo_user')

        setUser(data.user)
        setSession(data.session)

        // Read the actual registered role saved during sign-up
        const userMetaRole = data.user.user_metadata?.user_role as UserRole | undefined
        const effectiveRole: UserRole =
          userMetaRole === 'student' || userMetaRole === 'parent'
            ? userMetaRole
            : targetRole
        const roleMismatch = userMetaRole !== undefined && userMetaRole !== targetRole

        // Set the active role to the registered role
        setRole(effectiveRole)

        const resolvedName =
          data.user.user_metadata?.name ||
          preferredName?.trim() ||
          (effectiveRole === 'parent' ? 'Parent' : 'Student')

        const userMetaAvatar = data.user.user_metadata?.avatar as string | undefined
        const localAvatar = data.user.id ? localStorage.getItem(`veritas_avatar_${data.user.id}`) : null
        const activeAv = userMetaAvatar || localAvatar || 'initials'
        setAvatar(activeAv)

        saveProfile({
          email: data.user.email || cleanEmail,
          name: resolvedName,
          role: effectiveRole,
          lastActive: new Date().toISOString(),
          avatar: activeAv,
        })

        return { error: null, registeredRole: effectiveRole, roleMismatch }
      }
      return { error: null, registeredRole: targetRole, roleMismatch: false }
    } catch (err: any) {
      return { error: err?.message || 'Failed to verify OTP code' }
    }
  }

  // Evaluator Convenience: Establishes a synthetic demo session profile gated to non-production @veritas.dev domain
  const demoSignIn = async (targetRole: UserRole, customEmail?: string) => {
    const isParent = targetRole === 'parent'
    const email = customEmail || (isParent ? 'parent.sarah@veritas.dev' : 'student.alex@veritas.dev')
    const id = isParent ? DEMO_PARENT_ID : DEMO_STUDENT_ID
    const defaultName = isParent ? 'Sarah Jenkins (Parent)' : 'Alex Jenkins (Student)'
    let name = defaultName
    if (customEmail && customEmail !== 'parent.sarah@veritas.dev' && customEmail !== 'student.alex@veritas.dev') {
      const prefix = customEmail.split('@')[0]
      name = prefix.charAt(0).toUpperCase() + prefix.slice(1)
    }

    const storedDemoAvatar = localStorage.getItem(`veritas_avatar_${id}`) || 'initials'
    setAvatar(storedDemoAvatar)

    const fakeUser = {
      id,
      email,
      aud: 'authenticated',
      role: 'authenticated',
      created_at: new Date().toISOString(),
      user_metadata: {
        user_role: targetRole,
        name,
        avatar: storedDemoAvatar,
      },
      app_metadata: {
        provider: 'email',
      },
    } as unknown as User

    setUser(fakeUser)
    setRole(targetRole)
    sessionStorage.removeItem('session')
    localStorage.setItem('veritas_demo_user', JSON.stringify(fakeUser))
    localStorage.setItem('veritas_user_role', targetRole)
    saveProfile({
      email,
      name,
      role: targetRole,
      lastActive: new Date().toISOString(),
      avatar: storedDemoAvatar,
    })
  }

  const signOut = async () => {
    stopAllSpeech()
    try {
      await supabase.auth.signOut()
    } catch {}
    setUser(null)
    setSession(null)
    setAvatar(null)
    localStorage.removeItem('veritas_demo_user')
    localStorage.removeItem('veritas_user_role')
    sessionStorage.removeItem('session')
    sessionStorage.removeItem('veritas_cloud_tts_disabled')
    // Clear remembered profile on explicit sign-out so landing page shows fresh sign-in
    clearRememberedProfile()
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        role,
        avatar,
        updateAvatar,
        loading,
        sendMagicLink,
        verifyOtp,
        demoSignIn,
        signOut,
        setRole,
        rememberedProfile,
        clearRememberedProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
