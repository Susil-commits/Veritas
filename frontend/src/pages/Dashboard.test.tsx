import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from '../context/ThemeContext'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'student-123', email: 'student@veritas.dev' },
    role: 'student',
    avatar: null,
    updateAvatar: vi.fn(),
    signOut: vi.fn(),
  }),
}))

vi.mock('../lib/api', () => ({
  getMastery: vi.fn().mockResolvedValue({
    student_id: 'student-123',
    mastery: [{ skill_id: '3.OA.A.1', mastery_prob: 0.85 }],
    all_skills: [{ id: '3.OA.A.1', name: 'Understanding Multiplication' }],
  }),
  getSummary: vi.fn().mockResolvedValue({ summary: 'Strong multiplication fluency.' }),
  getGamesProgress: vi.fn().mockResolvedValue({
    student_id: 'student-123',
    levels: [],
    total_stars: 6,
    total_score: 1450,
    games_unlocked: 3,
    total_games: 7,
  }),
  getStudentActivity: vi.fn().mockResolvedValue({
    student_id: 'student-123',
    current_streak_days: 4,
    longest_streak_days: 7,
    active_days_last_7: 5,
    last_active_at: '2026-11-25T15:00:00Z',
  }),
}))

import Dashboard from './Dashboard'

describe('Dashboard page integration', () => {
  it('renders live student streak telemetry and arcade stars from backend endpoints', async () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={['/dashboard/student-123']}>
          <Routes>
            <Route path="/dashboard/:studentId" element={<Dashboard />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    )

    await waitFor(() => {
      expect(screen.getByText(/4 Days/i)).toBeTruthy()
    })
    expect(screen.getByText(/5 active days this week/i)).toBeTruthy()
    expect(screen.getByText(/6 ⭐/)).toBeTruthy()
    expect(screen.getByText(/3 \/ 7 tiers unlocked/i)).toBeTruthy()
  })
})
