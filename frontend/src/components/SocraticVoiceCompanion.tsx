import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useSpeechInput, useTTS } from '../hooks/useVoice';
import MathText from './MathText';
import './SocraticVoiceCompanion.css';

interface SocraticVoiceCompanionProps {
  isOpen: boolean;
  onClose: () => void;
  problem?: {
    title?: string;
    question?: string;
    skill_id?: string;
  } | null;
  latestTutorMessage?: string;
  onSendMessage: (text: string) => void;
  isStreaming?: boolean;
  onNextProblem?: () => void;
}

export const SocraticVoiceCompanion: React.FC<SocraticVoiceCompanionProps> = ({
  isOpen,
  onClose,
  problem,
  latestTutorMessage,
  onSendMessage,
  isStreaming = false,
  onNextProblem,
}) => {
  const [typedFallback, setTypedFallback] = useState('');
  const [autoListen, setAutoListen] = useState(true);
  const lastSpokenMsgRef = useRef<string>('');

  const { speak, stop: stopTTS, isSpeaking } = useTTS();

  const handleVoiceInputResult = useCallback(
    (text: string) => {
      if (text.trim()) {
        onSendMessage(text.trim());
      }
    },
    [onSendMessage]
  );

  const { isListening, interimText, startListening, stopListening, isSupported } =
    useSpeechInput(handleVoiceInputResult);

  // Automatically speak tutor messages when voice mode is open
  useEffect(() => {
    if (!isOpen || !latestTutorMessage) return;
    if (latestTutorMessage !== lastSpokenMsgRef.current && !isStreaming) {
      lastSpokenMsgRef.current = latestTutorMessage;
      speak(latestTutorMessage);
    }
  }, [isOpen, latestTutorMessage, isStreaming, speak]);

  // When tutor finishes speaking and autoListen is on, automatically engage microphone
  useEffect(() => {
    if (!isOpen || !autoListen) return;
    if (!isSpeaking && !isStreaming && !isListening) {
      const timer = setTimeout(() => {
        startListening();
      }, 400);
      return () => clearTimeout(timer);
    }
  }, [isOpen, isSpeaking, isStreaming, isListening, autoListen, startListening]);

  // Handle safe exit
  const handleExit = useCallback(() => {
    stopListening();
    stopTTS();
    onClose();
  }, [stopListening, stopTTS, onClose]);

  // Handle manual mic toggle
  const toggleListening = () => {
    if (isListening) {
      stopListening();
      setAutoListen(false);
    } else {
      stopTTS();
      startListening();
      setAutoListen(true);
    }
  };

  const handleSendTyped = (e: React.FormEvent) => {
    e.preventDefault();
    if (typedFallback.trim()) {
      onSendMessage(typedFallback.trim());
      setTypedFallback('');
    }
  };

  if (!isOpen) return null;

  // Compute visualizer orb mode
  const currentMode = isSpeaking
    ? 'speaking'
    : isListening
    ? 'listening'
    : isStreaming
    ? 'thinking'
    : 'idle';

  return (
    <div className="voice-companion-overlay" role="dialog" aria-modal="true">
      {/* Top Bar */}
      <div className="voice-topbar">
        <div className="voice-status-pill">
          <span className={`voice-status-dot voice-status-dot--${currentMode}`} />
          <span>
            {isSpeaking
              ? 'Veritas Tutor Speaking…'
              : isListening
              ? 'Listening to your voice…'
              : isStreaming
              ? 'Thinking Socratic Scaffold…'
              : 'Voice Companion Active'}
          </span>
        </div>

        <button
          type="button"
          className="voice-exit-btn"
          onClick={handleExit}
          title="Exit voice mode back to chat"
        >
          ✕ Exit Voice Mode
        </button>
      </div>

      {/* Main Interactive Arena */}
      <div className="voice-arena">
        {/* Math Blackboard */}
        {problem && (
          <div className="voice-blackboard">
            <div className="voice-blackboard-label">
              {problem.title || 'Current Math Challenge'}
            </div>
            <div className="voice-blackboard-math">
              <MathText content={problem.question || 'Loading problem formulation…'} />
            </div>
          </div>
        )}

        {/* Neural Orb Visualizer */}
        <div className="voice-orb-wrapper">
          <div className={`voice-orb-glow voice-orb-glow--${currentMode}`} />
          <div
            className={`voice-orb-core voice-orb-core--${currentMode}`}
            onClick={toggleListening}
            title={isListening ? 'Click to stop listening' : 'Click to speak'}
          >
            <span className="voice-orb-icon">
              {isSpeaking ? '🔊' : isListening ? '🎙️' : isStreaming ? '✨' : '💬'}
            </span>
          </div>
        </div>

        {/* Dialogue Captions Feed */}
        <div className="voice-captions-box">
          <div className="voice-caption-text">
            {latestTutorMessage ? (
              <MathText content={latestTutorMessage} />
            ) : (
              <span>&ldquo;Hey! I&rsquo;m ready when you are. Tell me what you notice first!&rdquo;</span>
            )}
          </div>
          {interimText && (
            <div className="voice-caption-interim">
              &ldquo;{interimText}&hellip;&rdquo;
            </div>
          )}
        </div>

        {/* Quick Socratic Prompt Chips */}
        <div className="voice-chips-row">
          <button
            type="button"
            className="voice-chip-btn"
            onClick={() => onSendMessage('Can you give me a small hint to start?')}
          >
            💡 Give me a hint
          </button>
          <button
            type="button"
            className="voice-chip-btn"
            onClick={() => onSendMessage('What concept is this problem testing?')}
          >
            🔍 Explain the concept
          </button>
          <button
            type="button"
            className="voice-chip-btn"
            onClick={() => latestTutorMessage && speak(latestTutorMessage)}
          >
            🔄 Repeat that
          </button>
          {onNextProblem && (
            <button
              type="button"
              className="voice-chip-btn"
              onClick={onNextProblem}
            >
              ⏭️ Next Problem
            </button>
          )}
        </div>
      </div>

      {/* Bottom Controls */}
      <div className="voice-bottom-controls">
        <button
          type="button"
          className={`voice-mic-main-btn ${isListening ? 'voice-mic-main-btn--active' : ''}`}
          onClick={toggleListening}
          aria-label={isListening ? 'Mute microphone' : 'Start talking'}
          title={isListening ? 'Mute' : 'Speak'}
        >
          {isListening ? '🛑' : '🎙️'}
        </button>

        <form onSubmit={handleSendTyped} style={{ display: 'contents' }}>
          <input
            type="text"
            className="voice-text-fallback-input"
            value={typedFallback}
            onChange={(e) => setTypedFallback(e.target.value)}
            placeholder={
              !isSupported
                ? 'Speech recognition not supported in this browser. Type here...'
                : 'Or type your answer if noisy...'
            }
          />
          {typedFallback.trim() && (
            <button
              type="submit"
              className="btn btn-sm btn-violet"
              style={{ borderRadius: '10px', height: '42px', padding: '0 14px' }}
            >
              Send
            </button>
          )}
        </form>
      </div>
    </div>
  );
};
