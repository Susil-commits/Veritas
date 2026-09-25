import { useState, useCallback, useRef, useEffect } from 'react'
import { synthesizeSpeech } from '../lib/api'

declare global {
  interface Window {
    SpeechRecognition: any
    webkitSpeechRecognition: any
  }
}

// Web Speech API hook for STT (speech-to-text)
export function useSpeechInput(onResult: (text: string) => void) {
  const isSupported = typeof window !== 'undefined' && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
  const [isListening, setIsListening] = useState(false)
  const [interimText, setInterimText] = useState('')
  const recognitionRef = useRef<any | null>(null)

  const startListening = useCallback(() => {
    const SpeechRecognition = typeof window !== 'undefined'
      ? (window.SpeechRecognition || window.webkitSpeechRecognition)
      : null

    if (!SpeechRecognition) {
      console.warn('SpeechRecognition is not supported on this browser.')
      return
    }

    try {
      const recognition = new SpeechRecognition()
      recognition.continuous = false
      recognition.interimResults = true
      recognition.lang = 'en-US'

      recognition.onstart = () => setIsListening(true)
      recognition.onend = () => {
        setIsListening(false)
        setInterimText('')
      }

      recognition.onresult = (event: any) => {
        let final = ''
        let interim = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const t = event.results[i][0].transcript
          if (event.results[i].isFinal) final += t
          else interim += t
        }
        setInterimText(interim)
        if (final) {
          onResult(final.trim())
          setInterimText('')
        }
      }

      recognition.onerror = (event: any) => {
        setIsListening(false)
        if (event?.error === 'not-allowed') {
          console.warn('Microphone permission denied.')
        }
      }

      recognitionRef.current = recognition
      recognition.start()
    } catch (e) {
      console.warn('Failed to start SpeechRecognition:', e)
      setIsListening(false)
    }
  }, [onResult])

  const stopListening = useCallback(() => {
    try {
      recognitionRef.current?.stop()
    } catch {}
    setIsListening(false)
  }, [])

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop()
      } catch {}
    }
  }, [])

  return { isListening, interimText, startListening, stopListening, isSupported }
}

/**
 * Strips markdown markup, LaTeX tags, and formatting characters so speech synthesis
 * sounds human and natural instead of reading out symbols like backslashes, asterisks, or dollar signs.
 */
export function cleanTextForSpeech(raw: string): string {
  if (!raw) return ''
  let text = raw

  // 0. Normalize overescaping and HTML entities first
  text = text.replace(/\\{2,}([a-zA-Z()[\]{}])/g, '\\$1')
  text = text.replace(/\\"/g, '"').replace(/\\'/g, "'")
  text = text.replace(/&amp;/g, ' and ').replace(/&lt;/g, ' less than ').replace(/&gt;/g, ' greater than ')

  // Fractions: \frac{a}{b} -> a over b
  text = text.replace(/\\*frac\{([^}]+)\}\{([^}]+)\}/g, '$1 over $2')

  // LaTeX math blocks and inline math delimiters $...$ or $$...$$, \(...\), \[...\]
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, '$1')
  text = text.replace(/\$([^$]+)\$/g, '$1')
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, '$1')
  text = text.replace(/\\\(([\s\S]*?)\\\)/g, '$1')

  // Strip stray parentheses or brackets from LaTeX delimiters
  text = text.replace(/\\+[()[\]]/g, ' ')

  // Common math symbols
  text = text.replace(/\\*(?:cdot|times)/g, ' times ')
  text = text.replace(/\\*div/g, ' divided by ')
  text = text.replace(/\\*leq?/g, ' is less than or equal to ')
  text = text.replace(/\\*geq?/g, ' is greater than or equal to ')
  text = text.replace(/\\*neq/g, ' is not equal to ')
  text = text.replace(/\\*pm/g, ' plus or minus ')
  text = text.replace(/\\*sqrt\{([^}]+)\}/g, 'square root of $1')

  // Exponents, percentages, and degrees
  text = text.replace(/([a-zA-Z0-9]+)\^2\b/g, '$1 squared')
  text = text.replace(/([a-zA-Z0-9]+)\^3\b/g, '$1 cubed')
  text = text.replace(/([a-zA-Z0-9]+)\^([a-zA-Z0-9]+)/g, '$1 to the power of $2')
  text = text.replace(/(\d+)%/g, '$1 percent')
  text = text.replace(/(\d+)\s*(?:°|\^\\circ)/g, '$1 degrees')
  text = text.replace(/(\d+)\s*\*\s*(\d+)/g, '$1 times $2')

  // Strip other LaTeX commands: \text{abc} -> abc, \pi -> pi
  text = text.replace(/\\*text\{([^}]+)\}/g, '$1')
  text = text.replace(/\\[a-zA-Z]+/g, ' ')

  // Strip markdown formatting: bold **text**, italics *text* or _text_
  text = text.replace(/\*\*([^*]+)\*\*/g, '$1')
  text = text.replace(/\*([^*]+)\*/g, '$1')
  text = text.replace(/__([^_]+)__/g, '$1')
  text = text.replace(/_([^_]+)_/g, '$1')

  // Strip markdown headers # Heading
  text = text.replace(/^#+\s+/gm, '')

  // Strip markdown bullet points and list markers
  text = text.replace(/^[\s*•-]+\s+/gm, '')

  // Strip backticks `code`
  text = text.replace(/`([^`]+)`/g, '$1')

  // Strip markdown links [label](url) -> label
  text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')

  // Clean excessive spaces and newlines
  text = text.replace(/\s+/g, ' ').trim()

  return text
}

// Cache cloud TTS quota state in memory and localStorage to prevent spamming failed requests
let cloudTtsExhausted = typeof window !== 'undefined' && (
  sessionStorage.getItem('veritas_cloud_tts_disabled') === 'true' ||
  localStorage.getItem('veritas_cloud_tts_disabled') === 'true'
)

// Global registry for currently playing AudioContext to ensure immediate cancellation on logout or route changes
let activeAudioContext: AudioContext | null = null
let globalSpeechGeneration = 0

export function stopAllSpeech() {
  globalSpeechGeneration += 1
  try {
    if (activeAudioContext && activeAudioContext.state !== 'closed') {
      activeAudioContext.close()
    }
  } catch {}
  activeAudioContext = null
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    try {
      window.speechSynthesis.cancel()
    } catch {}
  }
}

// ElevenLabs TTS hook (via backend proxy) with seamless browser fallback
export function useTTS() {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const audioContextRef = useRef<AudioContext | null>(null)
  const isSpeakingRef = useRef(false)
  const currentTokenRef = useRef(0)
  const isMountedRef = useRef(true)

  // Keep ref in sync with state so callbacks always read current value
  const setSpeaking = useCallback((val: boolean) => {
    isSpeakingRef.current = val
    setIsSpeaking(val)
  }, [])

  const stop = useCallback(() => {
    currentTokenRef.current += 1
    try {
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close()
      }
      audioContextRef.current = null
    } catch {}
    try {
      if (activeAudioContext && activeAudioContext.state !== 'closed') {
        activeAudioContext.close()
      }
      activeAudioContext = null
    } catch {}
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
      } catch {}
    }
    setSpeaking(false)
  }, [setSpeaking])

  // Stop any ongoing speech and invalidate tokens when the component unmounts
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      currentTokenRef.current += 1
      stop()
    }
  }, [stop])

  const speak = useCallback(async (text: string) => {
    if (!text) return
    const speechText = cleanTextForSpeech(text)
    if (!speechText) return

    // Cancel any previous speech before starting a new one (prevents audio queue pile-up)
    stop()
    const token = ++currentTokenRef.current
    const localGen = globalSpeechGeneration
    setSpeaking(true)

    // 1. Try ElevenLabs cloud TTS only if quota hasn't previously failed
    if (!cloudTtsExhausted) {
      try {
        const buffer = await synthesizeSpeech(speechText)
        if (currentTokenRef.current !== token || !isMountedRef.current || localGen !== globalSpeechGeneration) {
          return
        }
        if (buffer) {
          const ctx = new AudioContext()
          audioContextRef.current = ctx
          activeAudioContext = ctx
          const decoded = await ctx.decodeAudioData(buffer)
          if (currentTokenRef.current !== token || !isMountedRef.current || localGen !== globalSpeechGeneration) {
            try { ctx.close() } catch {}
            return
          }
          const source = ctx.createBufferSource()
          source.buffer = decoded
          source.connect(ctx.destination)
          source.onended = () => {
            if (currentTokenRef.current === token) {
              setSpeaking(false)
              try { ctx.close() } catch {}
              if (audioContextRef.current === ctx) {
                audioContextRef.current = null
              }
              if (activeAudioContext === ctx) {
                activeAudioContext = null
              }
            }
          }
          source.start()
          return
        } else {
          // synthesizeSpeech returned null (quota exceeded or 204 fallback)
          cloudTtsExhausted = true
          try {
            localStorage.setItem('veritas_cloud_tts_disabled', 'true')
            sessionStorage.setItem('veritas_cloud_tts_disabled', 'true')
          } catch {}
        }
      } catch {
        if (currentTokenRef.current !== token || !isMountedRef.current || localGen !== globalSpeechGeneration) {
          return
        }
        cloudTtsExhausted = true
        try {
          localStorage.setItem('veritas_cloud_tts_disabled', 'true')
          sessionStorage.setItem('veritas_cloud_tts_disabled', 'true')
        } catch {}
      }
    }

    if (currentTokenRef.current !== token || !isMountedRef.current || localGen !== globalSpeechGeneration) {
      return
    }

    // 2. Clean browser TTS fallback with safety timeout
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
        const utterance = new SpeechSynthesisUtterance(speechText)
        utterance.rate = 1.0
        utterance.pitch = 1.0

        const voices = window.speechSynthesis.getVoices?.() || []
        const naturalVoice = voices.find(v => v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Samantha') || v.name.includes('Daniel')))
        if (naturalVoice) {
          utterance.voice = naturalVoice
        }

        // Safety timeout in case browser policy blocks unprompted autoplay
        const safetyTimer = setTimeout(() => {
          if (currentTokenRef.current === token) {
            setSpeaking(false)
          }
        }, 10000)

        utterance.onend = () => {
          clearTimeout(safetyTimer)
          if (currentTokenRef.current === token) {
            setSpeaking(false)
          }
        }
        utterance.onerror = () => {
          clearTimeout(safetyTimer)
          if (currentTokenRef.current === token) {
            setSpeaking(false)
          }
        }
        window.speechSynthesis.speak(utterance)
      } catch {
        if (currentTokenRef.current === token) {
          setSpeaking(false)
        }
      }
    } else {
      if (currentTokenRef.current === token) {
        setSpeaking(false)
      }
    }
  }, [setSpeaking, stop])

  return { isSpeaking, speak, stop }
}
