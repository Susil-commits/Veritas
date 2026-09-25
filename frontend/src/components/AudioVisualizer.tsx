import { memo } from 'react'
import { Volume2, Mic } from 'lucide-react'
import './AudioVisualizer.css'

interface AudioVisualizerProps {
  active: boolean
  mode: 'speaking' | 'listening' | 'idle'
  onStop?: () => void
  label?: string
}

export const AudioVisualizer = memo(function AudioVisualizer({
  active,
  mode,
  onStop,
  label,
}: AudioVisualizerProps) {
  if (!active && mode === 'idle') return null

  const isSpeaking = mode === 'speaking'
  const isListening = mode === 'listening'
  const defaultLabel = isSpeaking ? 'Tutor speaking…' : isListening ? 'Listening to your voice…' : ''
  const displayLabel = label || defaultLabel

  return (
    <div
      className={`audio-visualizer-container ${mode} animate-fadein`}
      role="status"
      aria-live="polite"
      title={displayLabel}
    >
      <div className="audio-visualizer-icon">
        {isSpeaking && <Volume2 size={16} className="pulse-icon" />}
        {isListening && <Mic size={16} className="mic-pulse-icon" />}
      </div>

      <div className="visualizer-bars" aria-hidden="true">
        <span className="v-bar bar-1" />
        <span className="v-bar bar-2" />
        <span className="v-bar bar-3" />
        <span className="v-bar bar-4" />
        <span className="v-bar bar-5" />
        <span className="v-bar bar-6" />
        <span className="v-bar bar-7" />
      </div>

      <span className="visualizer-label">{displayLabel}</span>

      {isSpeaking && onStop && (
        <button
          type="button"
          className="audio-stop-btn"
          onClick={onStop}
          title="Stop reading out loud"
          aria-label="Stop audio"
        >
          Stop
        </button>
      )}
    </div>
  )
})

export default AudioVisualizer
