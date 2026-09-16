import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Landing from './pages/Landing'
import ShiningDots from './components/ShiningDots'
import NeoChat from './components/NeoChat'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import './index.css'

const TutorSession = lazy(() => import('./pages/TutorSession'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const ParentDashboard = lazy(() => import('./pages/ParentDashboard'))
const MathArcade = lazy(() => import('./pages/MathArcade'))

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

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
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
