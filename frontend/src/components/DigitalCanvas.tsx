import React, { useRef, useState, useEffect, useCallback, useImperativeHandle, forwardRef } from 'react'
import { Pen, Eraser, RotateCcw, Trash2, Grid, Sparkles, AlignJustify } from 'lucide-react'
import './DigitalCanvas.css'

export interface DigitalCanvasRef {
  getBlob: () => Promise<Blob | null>
  hasDrawing: () => boolean
  clear: () => void
}

interface DigitalCanvasProps {
  onStrokeDrawn?: () => void
  disabled?: boolean
  height?: number | string
}

type ToolMode = 'pen' | 'eraser'
type PaperStyle = 'graph' | 'lined' | 'blank'

const PEN_COLORS = [
  { name: 'Pencil', value: '#1e293b' },
  { name: 'Royal Ink', value: '#1d4ed8' },
  { name: 'Emerald', value: '#047857' },
  { name: 'Purple', value: '#7c3aed' },
  { name: 'Crimson', value: '#e11d48' },
  { name: 'Highlighter', value: '#facc15' },
]

export const DigitalCanvas = forwardRef<DigitalCanvasRef, DigitalCanvasProps>(function DigitalCanvas(
  { onStrokeDrawn, disabled = false, height },
  ref
) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const isDrawingRef = useRef(false)
  const lastPointRef = useRef<{ x: number; y: number } | null>(null)
  const historyRef = useRef<ImageData[]>([])
  const [hasContent, setHasContent] = useState(false)

  const [tool, setTool] = useState<ToolMode>('pen')
  const [strokeColor, setStrokeColor] = useState('#1e293b')
  const [strokeWidth, setStrokeWidth] = useState(3)
  const [paperStyle, setPaperStyle] = useState<PaperStyle>('graph')

  // Redraw paper background pattern
  const drawPaperBackground = useCallback((ctx: CanvasRenderingContext2D, width: number, height: number, style: PaperStyle) => {
    // Fill base off-white paper tone
    ctx.fillStyle = '#FFFFFF'
    ctx.fillRect(0, 0, width, height)

    if (style === 'graph') {
      ctx.save()
      ctx.strokeStyle = 'rgba(59, 130, 246, 0.14)' // faint blue grid
      ctx.lineWidth = 1
      const gridSize = 24

      for (let x = 0; x <= width; x += gridSize) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, height)
        ctx.stroke()
      }
      for (let y = 0; y <= height; y += gridSize) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(width, y)
        ctx.stroke()
      }
      ctx.restore()
    } else if (style === 'lined') {
      ctx.save()
      ctx.strokeStyle = 'rgba(59, 130, 246, 0.2)'
      ctx.lineWidth = 1
      const lineSpacing = 30

      // Pink left margin
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.25)'
      ctx.beginPath()
      ctx.moveTo(48, 0)
      ctx.lineTo(48, height)
      ctx.stroke()

      // Blue horizontal lines
      ctx.strokeStyle = 'rgba(59, 130, 246, 0.16)'
      for (let y = 40; y <= height; y += lineSpacing) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(width, y)
        ctx.stroke()
      }
      ctx.restore()
    }
  }, [])

  // Initialize Canvas
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return

    // Set physical resolution
    const rect = canvas.getBoundingClientRect()
    const width = Math.max(300, rect.width || 560)
    const height = Math.max(200, rect.height || 360)

    canvas.width = width
    canvas.height = height

    drawPaperBackground(ctx, width, height, paperStyle)
    historyRef.current = [ctx.getImageData(0, 0, width, height)]
  }, [paperStyle, drawPaperBackground])

  // Save state for undo
  const saveSnapshot = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return

    const snapshot = ctx.getImageData(0, 0, canvas.width, canvas.height)
    if (historyRef.current.length > 20) {
      historyRef.current.shift()
    }
    historyRef.current.push(snapshot)
    setHasContent(true)
    onStrokeDrawn?.()
  }, [onStrokeDrawn])

  // Undo last action
  const handleUndo = useCallback(() => {
    if (disabled || historyRef.current.length <= 1) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return

    historyRef.current.pop() // remove current
    const prev = historyRef.current[historyRef.current.length - 1]
    if (prev) {
      ctx.putImageData(prev, 0, 0)
      if (historyRef.current.length <= 1) {
        setHasContent(false)
      }
    }
  }, [disabled])

  // Global undo keyboard shortcut (Ctrl+Z / Cmd+Z)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        const target = e.target as HTMLElement | null
        if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
          return
        }
        if (!e.shiftKey) {
          e.preventDefault()
          handleUndo()
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleUndo])

  // Clear Canvas
  const handleClear = useCallback(() => {
    if (disabled) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return

    drawPaperBackground(ctx, canvas.width, canvas.height, paperStyle)
    historyRef.current = [ctx.getImageData(0, 0, canvas.width, canvas.height)]
    setHasContent(false)
  }, [disabled, paperStyle, drawPaperBackground])

  // Load 1-Click Demo Misconception
  const handleLoadDemoMisconception = useCallback(() => {
    if (disabled) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return

    drawPaperBackground(ctx, canvas.width, canvas.height, paperStyle)

    ctx.save()
    // Simulated realistic handwriting
    ctx.strokeStyle = '#1e293b'
    ctx.fillStyle = '#1e293b'
    ctx.font = 'bold 22px "Comic Sans MS", "Caveat", "Indie Flower", cursive, sans-serif'
    ctx.lineWidth = 2.5
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'

    // Step 1: 1/3 + 1/4
    ctx.fillText('1/3 + 1/4', 50, 70)

    // Arrow or equals
    ctx.fillText('= (1 + 1) / (3 + 4)', 50, 140)

    // Erroneous answer: = 2/7
    ctx.font = 'bold 26px "Comic Sans MS", "Caveat", cursive, sans-serif'
    ctx.fillStyle = '#0f172a'
    ctx.fillText('= 2/7', 50, 210)

    // Add student scratch note
    ctx.font = 'italic 16px "Comic Sans MS", cursive, sans-serif'
    ctx.fillStyle = '#475569'
    ctx.fillText('(Added across top and bottom)', 130, 210)

    ctx.restore()

    saveSnapshot()
  }, [disabled, paperStyle, drawPaperBackground, saveSnapshot])

  // Pointer event handlers for drawing
  const getCoordinates = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const scaleY = canvas.height / rect.height
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    }
  }

  const startDrawing = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (disabled) return
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.setPointerCapture(e.pointerId)
    isDrawingRef.current = true
    const pt = getCoordinates(e)
    lastPointRef.current = pt

    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return
    ctx.beginPath()
    ctx.moveTo(pt.x, pt.y)
  }

  const draw = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawingRef.current || disabled) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return

    const currentPt = getCoordinates(e)
    const lastPt = lastPointRef.current || currentPt

    ctx.save()
    if (tool === 'eraser') {
      ctx.globalCompositeOperation = 'destination-out'
      ctx.lineWidth = strokeWidth * 6
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.beginPath()
      ctx.moveTo(lastPt.x, lastPt.y)
      ctx.lineTo(currentPt.x, currentPt.y)
      ctx.stroke()
    } else {
      ctx.globalCompositeOperation = 'source-over'
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = strokeWidth
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      if (strokeColor === '#facc15') {
        ctx.globalAlpha = 0.4
        ctx.lineWidth = strokeWidth * 4
      }

      // Smooth stroke interpolation using midpoint quadratic curve
      const midX = (lastPt.x + currentPt.x) / 2
      const midY = (lastPt.y + currentPt.y) / 2
      ctx.beginPath()
      ctx.moveTo(lastPt.x, lastPt.y)
      ctx.quadraticCurveTo(lastPt.x, lastPt.y, midX, midY)
      ctx.lineTo(currentPt.x, currentPt.y)
      ctx.stroke()
    }
    ctx.restore()

    lastPointRef.current = currentPt
  }

  const stopDrawing = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawingRef.current) return
    const canvas = canvasRef.current
    if (canvas) {
      try {
        canvas.releasePointerCapture(e.pointerId)
      } catch {}
    }
    isDrawingRef.current = false
    lastPointRef.current = null
    saveSnapshot()
  }

  // Expose imperative handle for parent component
  useImperativeHandle(ref, () => ({
    getBlob: async () => {
      const canvas = canvasRef.current
      if (!canvas) return null
      return new Promise<Blob | null>((resolve) => {
        canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.92)
      })
    },
    hasDrawing: () => hasContent,
    clear: handleClear,
  }))

  return (
    <div className="digital-canvas-wrapper">
      {/* Canvas Toolbar */}
      <div className="canvas-toolbar">
        <div className="tool-group">
          <button
            type="button"
            className={`canvas-tool-btn ${tool === 'pen' ? 'active' : ''}`}
            onClick={() => setTool('pen')}
            title="Pencil / Pen"
            aria-label="Pen tool"
          >
            <Pen size={15} />
            <span>Draw</span>
          </button>
          <button
            type="button"
            className={`canvas-tool-btn ${tool === 'eraser' ? 'active' : ''}`}
            onClick={() => setTool('eraser')}
            title="Eraser"
            aria-label="Eraser tool"
          >
            <Eraser size={15} />
            <span>Eraser</span>
          </button>
        </div>

        {tool === 'pen' && (
          <div className="color-palette">
            {PEN_COLORS.map((c) => (
              <button
                key={c.value}
                type="button"
                className={`color-dot ${strokeColor === c.value ? 'selected' : ''}`}
                style={{ backgroundColor: c.value }}
                onClick={() => setStrokeColor(c.value)}
                title={c.name}
                aria-label={`Select ${c.name} color`}
              />
            ))}
          </div>
        )}

        <div className="width-selectors">
          {[2, 4, 7].map((w) => (
            <button
              key={w}
              type="button"
              className={`width-btn ${strokeWidth === w ? 'selected' : ''}`}
              onClick={() => setStrokeWidth(w)}
              title={`${w}px stroke`}
            >
              <div
                style={{
                  width: `${w * 2}px`,
                  height: `${w * 2}px`,
                  borderRadius: '50%',
                  background: 'currentColor',
                }}
              />
            </button>
          ))}
        </div>

        <div className="paper-style-group">
          <button
            type="button"
            className={`canvas-tool-btn ${paperStyle === 'graph' ? 'active' : ''}`}
            onClick={() => setPaperStyle('graph')}
            title="Graph Paper"
            aria-label="Graph paper background"
          >
            <Grid size={14} />
            <span>Grid</span>
          </button>
          <button
            type="button"
            className={`canvas-tool-btn ${paperStyle === 'lined' ? 'active' : ''}`}
            onClick={() => setPaperStyle('lined')}
            title="Lined Paper"
            aria-label="Lined paper background"
          >
            <AlignJustify size={14} />
            <span>Lined</span>
          </button>
        </div>

        <div className="action-group">
          <button
            type="button"
            className="canvas-tool-btn demo-btn"
            onClick={handleLoadDemoMisconception}
            title="Load demo math problem to test error detection"
            aria-label="Load demo math work"
          >
            <Sparkles size={14} />
            <span>Demo Error</span>
          </button>
          <button
            type="button"
            className="canvas-tool-btn"
            onClick={handleUndo}
            disabled={!hasContent || disabled}
            title="Undo stroke"
            aria-label="Undo"
          >
            <RotateCcw size={14} />
          </button>
          <button
            type="button"
            className="canvas-tool-btn danger"
            onClick={handleClear}
            disabled={!hasContent || disabled}
            title="Clear canvas"
            aria-label="Clear canvas"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Canvas Drawing Surface */}
      <div className="canvas-surface-container" style={height ? { height: typeof height === 'number' ? `${height}px` : height } : undefined}>
        <canvas
          ref={canvasRef}
          className="scratchpad-canvas"
          onPointerDown={startDrawing}
          onPointerMove={draw}
          onPointerUp={stopDrawing}
          onPointerCancel={stopDrawing}
        />
        {!hasContent && (
          <div className="canvas-watermark">
            <p>Write your math steps here using mouse, finger, or stylus...</p>
            <small>Or click <strong>"Demo Error"</strong> above to test instantly</small>
          </div>
        )}
      </div>
    </div>
  )
})

export default DigitalCanvas
