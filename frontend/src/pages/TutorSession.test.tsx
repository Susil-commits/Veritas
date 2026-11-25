import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../context/ThemeContext'

const mockAuthState = {
  user: { id: 'stu-test-1', email: 'stu@veritas.dev' },
  role: 'student',
  loading: false,
  avatar: null,
  updateAvatar: vi.fn(),
  signOut: vi.fn(),
}

vi.mock('../context/AuthContext', () => ({
  useAuth: () => mockAuthState,
}))

vi.mock('../hooks/useVoice', () => ({
  useTTS: () => ({ isSpeaking: false, speak: vi.fn(), stop: vi.fn() }),
  useSpeechInput: () => ({
    isListening: false,
    interimText: '',
    startListening: vi.fn(),
    stopListening: vi.fn(),
    isSupported: false,
  }),
}))

const mockGenerateCode = vi.fn().mockResolvedValue({
  status: 'ok',
  pairing_code: '482910',
  expires_in: 900,
  expires_at: 9999999999,
})

const mockApproveParent = vi.fn().mockResolvedValue({
  status: 'ok',
  message: 'Approved',
})

vi.mock('../lib/api', () => ({
  startSession: vi.fn().mockResolvedValue({
    session_id: 'sess-1',
    student_id: 'stu-test-1',
    student_name: 'Maya',
    welcome_message: 'Welcome back! Ready to solve equal groups?',
    current_problem: {
      id: 'prob-1',
      title: 'Equal Groups',
      text: 'Calculate 3 × 4.',
      skill_id: '3.OA.A.1',
      skill_name: 'Understanding Multiplication',
      difficulty: 1,
    },
    mastery_state: { '3.OA.A.1': 0.3 },
    conversation_history: [],
    thinking_steps: [],
  }),
  streamMessage: vi.fn(),
  fetchNextProblem: vi.fn(),
  resetSession: vi.fn(),
  generateStudentPairingCode: (...args: unknown[]) => mockGenerateCode(...args),
  getPendingParents: vi.fn().mockResolvedValue({
    pending_parents: [{ parent_id: 'parent-9999-aaaa', created_at: '2026-11-25T10:00:00Z' }],
  }),
  approveParentLink: (...args: unknown[]) => mockApproveParent(...args),
}))

import TutorSession from './TutorSession'

describe('TutorSession Parent Link modal', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('opens Parent Link modal, generates pairing code, and approves pending parent request', async () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <TutorSession />
        </MemoryRouter>
      </ThemeProvider>,
    )

    const parentLinkBtns = await screen.findAllByRole('button', { name: /Parent Link/i })
    fireEvent.click(parentLinkBtns[0])

    expect(await screen.findByText(/Parent Account Linking/i)).toBeTruthy()
    expect(await screen.findByText(/Pending Parent Link Requests \(1\)/i)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Generate 6-Digit Pairing Code/i }))
    await waitFor(() => {
      expect(mockGenerateCode).toHaveBeenCalledWith('stu-test-1')
      expect(screen.getByText('482910')).toBeTruthy()
    })

    fireEvent.click(screen.getByRole('button', { name: /^Approve$/i }))
    await waitFor(() => {
      expect(mockApproveParent).toHaveBeenCalledWith('stu-test-1', 'parent-9999-aaaa')
    })
  })
})
