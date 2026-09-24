import { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Diagnosis, Problem } from '../lib/api'
import { streamDiagnosis } from '../lib/api'
import { PenTool, Upload, Camera } from 'lucide-react'
import './WorkUpload.css'

interface Props {
  sessionId: string
  onThinking: (step: string) => void
  onDiagnosis: (d: Diagnosis, mastery: Record<string, number>, next: Problem | null) => void
  disabled?: boolean
}

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024 // 10MB cap matching backend safety boundary

type UploadMode = 'upload' | 'camera'

export default function WorkUpload({ sessionId, onThinking, onDiagnosis, disabled = false }: Props) {
  const navigate = useNavigate()
  const [mode, setMode] = useState<UploadMode>('upload')
  const [preview, setPreview] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [cameraOpen, setCameraOpen] = useState(false)

  const stopCameraStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }, [])

  const closeCamera = useCallback(() => {
    stopCameraStream()
    setCameraOpen(false)
  }, [stopCameraStream])

  useEffect(() => {
    return () => {
      stopCameraStream()
    }
  }, [stopCameraStream])

  const handleFile = (f: File) => {
    // 1. Client-side file-size check matching backend's 10MB cap
    if (f.size > MAX_FILE_SIZE_BYTES) {
      const sizeMb = (f.size / (1024 * 1024)).toFixed(1)
      setUploadError(`Image is ${sizeMb}MB — please use one under 10MB.`)
      setFile(null)
      setPreview(null)
      setDiagnosis(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
      return
    }

    // 2. Validate MIME type
    if (f.type && !f.type.startsWith('image/')) {
      setUploadError('Please select a valid photo file (PNG, JPEG, or WebP).')
      setFile(null)
      setPreview(null)
      setDiagnosis(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
      return
    }

    setFile(f)
    setDiagnosis(null)
    setUploadError(null)
    const reader = new FileReader()
    reader.onload = (e) => setPreview(e.target?.result as string)
    reader.readAsDataURL(f)
  }

  const openCamera = async () => {
    setUploadError(null)
    try {
      if (!navigator?.mediaDevices?.getUserMedia) {
        throw new Error('Camera is not supported in this browser environment')
      }
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      streamRef.current = stream
      setCameraOpen(true)
      setMode('camera')
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
    } catch (err) {
      console.error('Camera access failed:', err)
      setUploadError('Could not access camera — check your browser permissions, or upload a photo instead.')
    }
  }

  const capturePhoto = () => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || video.videoWidth === 0 || video.videoHeight === 0) return
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')!.drawImage(video, 0, 0)
    canvas.toBlob((blob) => {
      if (!blob) return
      const f = new File([blob], 'work.jpg', { type: 'image/jpeg' })
      handleFile(f)
      closeCamera()
    }, 'image/jpeg', 0.9)
  }

async function compressImageFile(f: File, maxDimension = 1600, quality = 0.85): Promise<File> {
  if (!f.type.startsWith('image/') || f.size < 200 * 1024) {
    return f
  }

  return new Promise((resolve) => {
    const img = new Image()
    const url = URL.createObjectURL(f)
    img.onload = () => {
      URL.revokeObjectURL(url)
      let { width, height } = img
      if (width <= maxDimension && height <= maxDimension && f.size < 1024 * 1024) {
        resolve(f)
        return
      }

      if (width > maxDimension || height > maxDimension) {
        if (width > height) {
          height = Math.round((height * maxDimension) / width)
          width = maxDimension
        } else {
          width = Math.round((width * maxDimension) / height)
          height = maxDimension
        }
      }

      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        resolve(f)
        return
      }
      ctx.fillStyle = '#FFFFFF'
      ctx.fillRect(0, 0, width, height)
      ctx.drawImage(img, 0, 0, width, height)
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            resolve(f)
            return
          }
          const compressed = new File([blob], f.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' })
          resolve(compressed)
        },
        'image/jpeg',
        quality,
      )
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(f)
    }
    img.src = url
  })
}

  const analyzeFile = useCallback(async (targetFile: File) => {
    if (!targetFile || !sessionId) return
    setUploading(true)
    setUploadError(null)

    const uploadPayload = await compressImageFile(targetFile)

    streamDiagnosis(
      sessionId,
      uploadPayload,
      onThinking,
      (d, mastery, next) => {
        setDiagnosis(d)
        setUploading(false)
        onDiagnosis(d, mastery, next)
      },
      (err) => {
        console.error('Handwriting diagnosis error:', err)
        setUploading(false)
        const errMsg = err?.message || ''
        if (errMsg.includes('10MB') || errMsg.includes('413')) {
          setUploadError('Image exceeds 10MB limit. Please upload a smaller photo.')
        } else if (errMsg.includes('Rate limit') || errMsg.includes('429')) {
          setUploadError('Tutor is catching its breath. Please wait a few seconds before uploading again.')
        } else {
          setUploadError('Could not analyze handwritten work. Please try again.')
        }
      },
    )
  }, [sessionId, onThinking, onDiagnosis])

  return (
    <div className="work-upload">
      <div className="upload-header">
        <h3 className="upload-title">Show Your Work</h3>
        {!preview && !cameraOpen && (
          <div className="work-mode-tabs">
            <button
              type="button"
              className="mode-tab-btn"
              onClick={() => navigate('/scratchpad')}
              disabled={disabled || uploading}
              title="Open full-screen digital scratchpad workspace"
            >
              <PenTool size={13} />
              <span>Scratchpad ↗</span>
            </button>
            <button
              type="button"
              className={`mode-tab-btn ${mode === 'upload' ? 'active' : ''}`}
              onClick={() => setMode('upload')}
              disabled={disabled || uploading}
            >
              <Upload size={13} />
              <span>Upload</span>
            </button>
            <button
              type="button"
              className={`mode-tab-btn ${mode === 'camera' ? 'active' : ''}`}
              onClick={openCamera}
              disabled={disabled || uploading}
            >
              <Camera size={13} />
              <span>Camera</span>
            </button>
          </div>
        )}
      </div>

      {cameraOpen ? (
        <div className="camera-view">
          <video
            ref={(el) => {
              videoRef.current = el
              if (el && streamRef.current && el.srcObject !== streamRef.current) {
                el.srcObject = streamRef.current
              }
            }}
            autoPlay
            playsInline
            className="camera-video"
          />
          <canvas ref={canvasRef} style={{ display: 'none' }} />
          <div className="camera-actions">
            <button className="btn btn-primary" onClick={capturePhoto} aria-label="Take photo of handwritten work">
              Capture
            </button>
            <button className="btn btn-ghost" onClick={closeCamera} aria-label="Cancel camera capture">
              Cancel
            </button>
          </div>
        </div>
      ) : preview ? (
        <div className="preview-container">
          <img src={preview} alt="Your work" className="work-preview" />

          {/* Visual mistake-highlight overlay directly on top of handwritten work */}
          {diagnosis && !diagnosis.is_correct && Boolean(diagnosis.bounding_hint || diagnosis.bounding_box) && (() => {
            const b = diagnosis.bounding_hint || diagnosis.bounding_box
            if (!b) return null
            const x = 'x' in b && b.x !== undefined ? b.x : (b.left ?? 10)
            const y = 'y' in b && b.y !== undefined ? b.y : (b.top ?? 35)
            const w = b.width ?? 80
            const h = b.height ?? 22

            return (
              <div
                className="error-bounding-box"
                style={{
                  top: `${y}%`,
                  left: `${x}%`,
                  width: `${w}%`,
                  height: `${h}%`,
                }}
              >
                <div className="box-reticle-corner top-left" />
                <div className="box-reticle-corner top-right" />
                <div className="box-reticle-corner bottom-left" />
                <div className="box-reticle-corner bottom-right" />
                <div className="box-badge">
                  <span>Step {diagnosis.step_number}: {diagnosis.misconception_type.replace(/_/g, ' ')}</span>
                </div>
              </div>
            )
          })()}

          {diagnosis && diagnosis.is_correct && (
            <div
              className="success-bounding-box"
              style={{
                top: '12%',
                left: '8%',
                width: '84%',
                height: '74%',
              }}
            >
              <div className="box-badge success">
                <span>Verified correct reasoning</span>
              </div>
            </div>
          )}

          {diagnosis && (
            <div className={`diagnosis-overlay ${diagnosis.is_correct ? 'correct' : 'incorrect'}`}>
              {diagnosis.is_correct ? (
                <div className="diagnosis-result correct">
                  <span>Correct! Well done.</span>
                </div>
              ) : (
                <div className="diagnosis-result incorrect">
                  <div>
                    <strong>{diagnosis.misconception_type.replace(/_/g, ' ')}</strong>
                    <p>at Step {diagnosis.step_number}</p>
                  </div>
                </div>
              )}
            </div>
          )}
          <button
            className="clear-btn"
            onClick={() => {
              if (disabled || uploading) return
              setPreview(null)
              setFile(null)
              setDiagnosis(null)
              setUploadError(null)
              if (fileInputRef.current) {
                fileInputRef.current.value = ''
              }
            }}
            disabled={disabled || uploading}
            aria-label="Remove uploaded image"
            title="Remove image"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      ) : (
        <div className="upload-options-stack">
          <button
            type="button"
            className="scratchpad-launch-card"
            onClick={() => navigate('/scratchpad')}
            disabled={disabled || uploading}
            title="Open full-screen digital scratchpad workspace"
          >
            <div className="scratchpad-card-icon">✍️</div>
            <div className="scratchpad-card-text">
              <span className="scratchpad-card-title">Digital Scratchpad ↗</span>
              <span className="scratchpad-card-desc">Work out steps with pen, graph paper & AI checks</span>
            </div>
          </button>

          <div
            className={`upload-zone ${disabled ? 'upload-zone--disabled' : ''}`}
            role="button"
            tabIndex={disabled ? -1 : 0}
            aria-label="Upload photo of handwritten work. Click to browse or drag and drop."
            onClick={() => !disabled && fileInputRef.current?.click()}
            onKeyDown={(e) => !disabled && (e.key === 'Enter' || e.key === ' ') && fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); if (!disabled) { const f = e.dataTransfer.files[0]; if (f) handleFile(f) } }}
          >
            <span className="upload-prompt-badge">Upload Work</span>
            <p>Drop your photo here<br /><span>or click to browse</span></p>
          </div>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        disabled={disabled}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
      />

      {uploadError && (
        <div className="upload-error-banner" role="alert">
          ⚠️ {uploadError}
        </div>
      )}

      {file && !diagnosis && !cameraOpen && (
        <div className="upload-actions">
          <button
            className="btn btn-primary"
            onClick={() => file && analyzeFile(file)}
            disabled={uploading || disabled}
            aria-label="Check handwritten work photo"
          >
            {uploading ? 'Checking steps…' : 'Check My Work'}
          </button>
        </div>
      )}

      {diagnosis && !diagnosis.is_correct && (
        <div className="diagnosis-detail animate-fadein">
          <p className="diagnosis-desc">{diagnosis.description}</p>
          <p className="corrective-q">{diagnosis.corrective_question}</p>
        </div>
      )}
    </div>
  )
}
