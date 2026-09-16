// API client for the FastAPI backend
import axios from 'axios'

const rawUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const BASE_URL = rawUrl.replace(/\/+$/, '')

export const api = axios.create({ baseURL: BASE_URL })

api.interceptors.request.use((config) => {
  const authHeaders = getAuthHeaders()
  for (const [key, value] of Object.entries(authHeaders)) {
    if (!config.headers.has(key)) {
      config.headers.set(key, value)
    }
  }
  return config
})

export interface Problem {
  id: string
  title: string
  text: string
  skill_id: string
  difficulty: number
  expected_steps: string[]
}

export interface SessionData {
  session_id: string
  student_id: string
  student_name: string
  session_token?: string
  current_problem: Problem
  mastery_state: Record<string, number>
  welcome_message: string
}

let cachedSupabaseKey: string | null = null

function getSupabaseAuthToken(): string | null {
  try {
    if (cachedSupabaseKey) {
      const raw = localStorage.getItem(cachedSupabaseKey)
      if (raw) {
        const parsed = JSON.parse(raw)
        const token = parsed?.access_token || parsed?.session?.access_token
        if (token && typeof token === 'string') return token
      }
      cachedSupabaseKey = null
    }

    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key && key.startsWith('sb-') && key.endsWith('-auth-token')) {
        const raw = localStorage.getItem(key)
        if (raw) {
          const parsed = JSON.parse(raw)
          const token = parsed?.access_token || parsed?.session?.access_token
          if (token && typeof token === 'string') {
            cachedSupabaseKey = key
            return token
          }
        }
      }
    }
  } catch {}
  return null
}

export function getAuthHeaders(): Record<string, string> {
  const currentRole = localStorage.getItem('veritas_user_role') || localStorage.getItem('ainerd_user_role')

  // 1. Prioritize active student practice session token ONLY when role is not explicitly parent
  if (currentRole !== 'parent') {
    try {
      const raw = sessionStorage.getItem('session')
      if (raw) {
        const session = JSON.parse(raw)
        if (session.session_token && typeof session.session_token === 'string') {
          const parts = session.session_token.split('.')
          if (parts.length === 2) {
            try {
              let b64 = parts[0].replace(/-/g, '+').replace(/_/g, '/')
              while (b64.length % 4 !== 0) {
                b64 += '='
              }
              const payloadJson = atob(b64)
              const payload = JSON.parse(payloadJson)
              if (payload.exp && payload.exp * 1000 >= Date.now()) {
                return {
                  'Authorization': `Bearer ${session.session_token}`,
                  'X-Session-Token': session.session_token,
                }
              }
            } catch {}
          }
        }
      }
    } catch {}
  }

  // 2. Check localStorage for Supabase authenticated session token
  const supabaseToken = getSupabaseAuthToken()
  if (supabaseToken) {
    return {
      'Authorization': `Bearer ${supabaseToken}`,
      'X-Session-Token': supabaseToken,
    }
  }

  // 3. Check demo user profile
  try {
    const role = localStorage.getItem('veritas_user_role') || localStorage.getItem('ainerd_user_role')
    const storedDemo = localStorage.getItem('veritas_demo_user') || localStorage.getItem('ainerd_demo_user')
    if (storedDemo) {
      const parsed = JSON.parse(storedDemo)
      if (parsed?.id) {
        if (role === 'parent' || parsed.user_metadata?.user_role === 'parent') {
          return {
            'X-Parent-Id': parsed.id,
            'Authorization': `Bearer demo_parent_${parsed.id}`,
            'X-Session-Token': `demo_parent_${parsed.id}`,
          }
        }
        return {
          'Authorization': `Bearer demo_${parsed.id}`,
          'X-Session-Token': `demo_${parsed.id}`,
        }
      }
    }
  } catch {}

  return {}
}

export interface BoundingBox {
  x: number
  y: number
  width: number
  height: number
  top?: number
  left?: number
}

export interface Diagnosis {
  ocr_text: string
  is_correct: boolean
  step_number: number
  misconception_type: string
  description: string
  skill_gap: string
  skill_gap_name: string
  corrective_question: string
  bounding_hint: BoundingBox | null
  bounding_box?: BoundingBox | null
}

export interface HealthStatus {
  status: string
  version?: string
  uptime_seconds?: number
  services?: {
    supabase: boolean
    gemini: boolean
  }
  db?: boolean
  active_cached_sessions?: number
}

export async function checkHealth(): Promise<HealthStatus> {
  const { data } = await api.get('/health', { timeout: 12000 })
  return data
}

export async function startSession(studentName: string, studentId?: string, studentEmail?: string): Promise<SessionData> {
  const { data } = await api.post('/session/start', {
    student_name: studentName,
    student_id: studentId,
    student_email: studentEmail,
  })
  return data
}

export async function getMastery(studentId: string) {
  const { data } = await api.get(`/student/${studentId}/mastery`, {
    headers: getAuthHeaders(),
  })
  return data
}

export async function getSummary(studentId: string, sessionId: string) {
  const { data } = await api.get(`/student/${studentId}/summary`, {
    params: { session_id: sessionId },
    headers: getAuthHeaders(),
  })
  return data
}

export interface ChildItem {
  student_id: string
  student_name: string
  student_email: string
  last_session_at: string | null
  days_since_practice: number
  has_fraction_gap: boolean
  fraction_alert_message: string
  fraction_mastery: number
  session_count: number
}

export async function getParentChildren(parentId: string): Promise<{ children: ChildItem[] }> {
  const { data } = await api.get(`/parent/${parentId}/children`, {
    headers: getAuthHeaders(),
  })
  return data
}

export async function addChild(
  parentId: string,
  childEmail: string,
  childName?: string,
  parentEmail?: string,
): Promise<{ status: string; child: { student_id: string; student_name: string; student_email: string } }> {
  const { data } = await api.post(
    '/parent/add-child',
    {
      parent_id: parentId,
      child_email: childEmail,
      child_name: childName,
      parent_email: parentEmail,
    },
    {
      headers: getAuthHeaders(),
    },
  )
  return data
}

export async function getChildDetails(parentId: string, childId: string) {
  const { data } = await api.get(`/parent/${parentId}/child/${childId}/details`, {
    headers: getAuthHeaders(),
  })
  return data
}

export async function deleteParentData(parentId: string): Promise<{
  status: string
  message: string
  purged_records?: {
    children_unlinked: number
    sessions_deleted: number
    events_deleted: number
  }
}> {
  const { data } = await api.delete(`/parent/${parentId}/data`, {
    headers: getAuthHeaders(),
  })
  return data
}


export async function fetchNextProblem(
  sessionId: string,
  markPreviousCorrect: boolean = false,
): Promise<{
  status: string
  current_problem: Problem
  mastery_state: Record<string, number>
  tutor_message: string
}> {
  const { data } = await api.post(
    '/session/next-problem',
    {
      session_id: sessionId,
      mark_previous_correct: markPreviousCorrect,
    },
    { headers: getAuthHeaders() },
  )
  return data
}

export async function resetSession(
  studentId: string,
  sessionId?: string,
): Promise<SessionData> {
  const { data } = await api.post<SessionData>(
    '/session/reset',
    {
      student_id: studentId,
      session_id: sessionId,
    },
    { headers: getAuthHeaders() },
  )
  return data
}


export function streamMessage(
  sessionId: string,
  message: string,
  onThinking: (step: string) => void,
  onResponse: (text: string, done: boolean) => void,
  onDone: (masteryState: Record<string, number>, problemSolved?: boolean) => void,
  onError?: (err: any) => void,
) {
  const url = `${BASE_URL}/session/message`
  fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ session_id: sessionId, message }),
  }).then(async (res) => {
    if (!res.ok) {
      if (res.status === 429) {
        onThinking('Tutor catching breath...')
        onResponse("You're thinking super fast! Please wait a couple of seconds before sending your next message.", true)
        onDone({}, false)
        return
      }
      throw new Error(`HTTP ${res.status}: ${res.statusText}`)
    }

    if (!res.body) return
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const payload = JSON.parse(line.slice(6))
          if (payload.type === 'thinking') onThinking(payload.content)
          if (payload.type === 'response') onResponse(payload.content, payload.done)
          if (payload.type === 'done') onDone(payload.mastery_state ?? {}, Boolean(payload.problem_solved))
        } catch {}
      }
    }
  }).catch((err) => {
    console.warn('streamMessage error:', err)
    onError?.(err)
  })
}

export function streamDiagnosis(
  sessionId: string,
  file: File,
  onThinking: (step: string) => void,
  onDiagnosis: (diagnosis: Diagnosis, masteryState: Record<string, number>, nextProblem: Problem | null) => void,
  onError?: (err: any) => void,
) {
  const formData = new FormData()
  formData.append('file', file)

  fetch(`${BASE_URL}/session/upload-work?session_id=${sessionId}`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData,
  }).then(async (res) => {
    if (!res.ok) {
      if (res.status === 429) {
        onThinking('Vision analyzer cooldown — please wait a few seconds before re-uploading.')
        throw new Error('Rate limit: please wait a few seconds before uploading another photo.')
      }
      if (res.status === 413) {
        throw new Error('Image exceeds 10MB limit. Please upload a smaller photo.')
      }
      throw new Error(`HTTP ${res.status}: ${res.statusText}`)
    }

    if (!res.body) return
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const payload = JSON.parse(line.slice(6))
          if (payload.type === 'thinking') onThinking(payload.content)
          if (payload.type === 'diagnosis') {
            onDiagnosis(payload.diagnosis, payload.mastery_state, payload.next_problem)
          }
        } catch {}
      }
    }
  }).catch((err) => {
    console.warn('streamDiagnosis error:', err)
    onError?.(err)
  })
}

export async function synthesizeSpeech(text: string): Promise<ArrayBuffer | null> {
  const trimmed = text.trim().slice(0, 500) // match backend's ElevenLabs free tier limit
  if (!trimmed) return null

  // If cloud TTS has previously failed or quota exhausted, skip network call entirely
  try {
    if (localStorage.getItem('veritas_cloud_tts_disabled') === 'true') {
      return null
    }
  } catch {}

  try {
    const res = await fetch(`${BASE_URL}/tts?text=${encodeURIComponent(trimmed)}`, {
      method: 'POST',
      headers: getAuthHeaders(),
    })

    // Status 204 or fallback header means backend gracefully signals to use browser speech
    if (res.status === 204 || res.headers.get('x-tts-fallback') === 'browser') {
      try {
        localStorage.setItem('veritas_cloud_tts_disabled', 'true')
      } catch {}
      return null
    }

    if (!res.ok) {
      if (res.status === 402 || res.status === 429 || res.status === 503) {
        try {
          localStorage.setItem('veritas_cloud_tts_disabled', 'true')
        } catch {}
      }
      return null
    }

    return await res.arrayBuffer()
  } catch {
    return null
  }
}

export interface NeoChatResponse {
  status: string
  reply: string
  guardrailed: boolean
  guardrail_reason?: string | null
  suggested_actions: string[]
  user_role: string
}

export async function sendNeoChat(
  message: string,
  history: Array<{ role: string; content: string }>,
  visitorId?: string,
): Promise<NeoChatResponse> {
  const headers: Record<string, string> = {
    ...getAuthHeaders(),
  }
  if (visitorId) {
    headers['X-Visitor-Id'] = visitorId
  }

  const { data } = await api.post<NeoChatResponse>(
    '/neo/chat',
    {
      message,
      history,
      visitor_id: visitorId,
    },
    { headers },
  )
  return data
}

export async function getNeoSuggestions(): Promise<string[]> {
  try {
    const { data } = await api.get<{ suggestions: string[] }>('/neo/suggestions')
    return data.suggestions || []
  } catch {
    return [
      'How does the Socratic tutor work?',
      'What math topics are covered?',
      'How do I upload handwritten work?',
      'How do parent progress alerts work?',
    ]
  }
}

export interface GameLevel {
  id: string
  level: number
  name: string
  subtitle: string
  theme: string
  skill_required: string
  skill_name: string
  unlock_requirement: string
  description: string
  is_unlocked: boolean
  progress_percent: number
  high_score: number
  stars: number
  times_played: number
}

export interface GamesProgressResponse {
  student_id: string
  levels: GameLevel[]
  total_stars: number
  total_score: number
  games_unlocked: number
  total_games: number
}

export async function getGamesProgress(studentId: string): Promise<GamesProgressResponse> {
  const { data } = await api.get<GamesProgressResponse>(`/games/progress`, {
    params: { student_id: studentId },
  })
  return data
}

export async function recordGameScore(
  studentId: string,
  gameId: string,
  score: number,
  stars: number,
): Promise<GamesProgressResponse> {
  const { data } = await api.post<GamesProgressResponse>(`/games/score`, {
    student_id: studentId,
    game_id: gameId,
    score,
    stars,
  })
  return data
}

