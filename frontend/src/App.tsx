import { useState, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Landing from './pages/Landing'
import ShiningDots from './components/ShiningDots'
import NeoChat from './components/NeoChat'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import { isLocalhostInProduction } from './lib/api'
import './index.css'

const TutorSession = lazy(() => import('./pages/TutorSession'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const ParentDashboard = lazy(() => import('./pages/ParentDashboard'))
const MathArcade = lazy(() => import('./pages/MathArcade'))
const Scratchpad = lazy(() => import('./pages/Scratchpad'))

function ConfigWarningBanner() {
  const [dismissed, setDismissed] = useState(false)
  if (!isLocalhostInProduction || dismissed) return null

  return (
    <div
      role="alert"
      style={{
        background: 'linear-gradient(90deg, #991b1b, #dc2626)',
        color: '#ffffff',
        padding: '10px 16px',
        fontSize: '0.85rem',
        fontWeight: 500,
        position: 'sticky',
        top: 0,
        zIndex: 999999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.25)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, justifyContent: 'center' }}>
        <span style={{ fontSize: '1rem' }}>⚠️</span>
        <span>
          <strong>Configuration Warning:</strong> Frontend is deployed over HTTPS, but <code style={{ background: 'rgba(0,0,0,0.2)', padding: '2px 6px', borderRadius: '4px' }}>VITE_API_URL</code> is pointing to localhost. API requests will fail. Please add your live backend URL in Vercel Project Settings &gt; Environment Variables.
        </span>
      </div>
      <button
        onClick={() => setDismissed(true)}
        style={{
          background: 'none',
          border: 'none',
          color: '#ffffff',
          fontSize: '1rem',
          cursor: 'pointer',
          padding: '2px 8px',
          opacity: 0.8,
        }}
        aria-label="Dismiss banner"
      >
        ✕
      </button>
    </div>
  )
}

function HomeOnlyNeoChat() {
  const location = useLocation()
  if (location.pathname !== '/') return null
  return <NeoChat />
}

function PageFallback() {
  return (
    <div style={{
      minHeight: '80vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '1rem',
      color: 'var(--text-secondary)',
      fontSize: '0.95rem'
    }}>
      <div style={{
        width: '36px',
        height: '36px',
        border: '3px solid rgba(124, 93, 250, 0.2)',
        borderTopColor: 'var(--violet-light)',
        borderRadius: '50%',
        animation: 'spin 0.8s linear infinite'
      }} />
      <span>Loading practice session…</span>
    </div>
  )
}

function DashboardRedirect() {
  const { user } = useAuth()
  let studentId = user?.id
  if (!studentId) {
    try {
      const raw = sessionStorage.getItem('session')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (parsed.student_id) studentId = parsed.student_id
      }
    } catch {}
  }
  if (!studentId) {
    studentId = '24e836e3-3b42-41a0-8a27-222f883eaa10'
  }
  return <Navigate to={`/dashboard/${studentId}`} replace />
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <ConfigWarningBanner />
          <ShiningDots />
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/demo" element={<Navigate to="/#demo" replace />} />
              <Route path="/how-it-works" element={<Navigate to="/#how-it-works" replace />} />
              <Route path="/pipeline" element={<Navigate to="/#pipeline" replace />} />
              <Route path="/live-pipeline" element={<Navigate to="/#pipeline" replace />} />
              <Route path="/topics" element={<Navigate to="/#topics" replace />} />
              <Route path="/features" element={<Navigate to="/#features" replace />} />
              <Route
                path="/student-session"
                element={
                  <ProtectedRoute>
                    <TutorSession />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/session"
                element={
                  <ProtectedRoute>
                    <TutorSession />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/parent-dashboard"
                element={
                  <ProtectedRoute allowedRoles={['parent']}>
                    <ParentDashboard />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/arcade"
                element={
                  <ProtectedRoute>
                    <MathArcade />
                  </ProtectedRoute>
                }
              />
              <Route path="/games" element={<Navigate to="/arcade" replace />} />
              <Route
                path="/scratchpad"
                element={
                  <ProtectedRoute>
                    <Scratchpad />
                  </ProtectedRoute>
                }
              />
              <Route path="/session/scratchpad" element={<Navigate to="/scratchpad" replace />} />
              <Route
                path="/dashboard"
                element={
                  <ProtectedRoute>
                    <DashboardRedirect />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/dashboard/:studentId"
                element={
                  <ProtectedRoute>
                    <Dashboard />
                  </ProtectedRoute>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
          <HomeOnlyNeoChat />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  )
}
