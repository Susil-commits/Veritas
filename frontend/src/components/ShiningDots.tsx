import { useEffect, useRef } from 'react'

interface Dot {
  x: number
  y: number
  baseOpacity: number
  maxOpacity: number
  phase: number
  speed: number
  isShiningStar: boolean
  radius: number
  glowColor: string
}

export default function ShiningDots() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationFrameId: number
    let dots: Dot[] = []
    const spacing = 38 // Optimized grid spacing for high performance & clean aesthetic

    let mouseX = -1000
    let mouseY = -1000

    const setupCanvas = () => {
      const dpr = window.devicePixelRatio || 1
      const width = window.innerWidth
      const height = window.innerHeight

      canvas.width = width * dpr
      canvas.height = height * dpr
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`

      ctx.resetTransform?.()
      ctx.scale(dpr, dpr)

      const cols = Math.ceil(width / spacing) + 1
      const rows = Math.ceil(height / spacing) + 1

      dots = []
      for (let c = 0; c < cols; c++) {
        for (let r = 0; r < rows; r++) {
          // ~22% of dots continuously shine and twinkle
          const isShiningStar = Math.random() < 0.22
          const isViolet = Math.random() < 0.7
          dots.push({
            x: c * spacing,
            y: r * spacing,
            baseOpacity: isShiningStar ? 0.20 : 0.10,
            maxOpacity: isShiningStar ? 0.90 : 0.30,
            phase: Math.random() * Math.PI * 2,
            speed: 0.015 + Math.random() * 0.03,
            isShiningStar,
            radius: isShiningStar ? 1.4 : 1.0,
            glowColor: isViolet ? 'rgba(167, 139, 250, 0.85)' : 'rgba(96, 165, 250, 0.8)',
          })
        }
      }
    }

    setupCanvas()

    let time = 0
    const render = () => {
      time += 0.04
      const width = window.innerWidth
      const height = window.innerHeight

      ctx.clearRect(0, 0, width, height)

      // Fast batched rendering
      for (let i = 0; i < dots.length; i++) {
        const dot = dots[i]

        const naturalPulse = (Math.sin(time * dot.speed * 30 + dot.phase) + 1) / 2
        let currentOpacity = dot.baseOpacity + (dot.maxOpacity - dot.baseOpacity) * naturalPulse

        // Mouse hover shine
        const dx = dot.x - mouseX
        const dy = dot.y - mouseY
        const distSq = dx * dx + dy * dy
        if (distSq < 19600) { // 140^2 precalculated
          const dist = Math.sqrt(distSq)
          const mouseFactor = (1 - dist / 140) * 0.4
          currentOpacity = Math.min(1, currentOpacity + mouseFactor)
        }

        ctx.beginPath()
        ctx.arc(dot.x, dot.y, dot.radius, 0, Math.PI * 2)

        if (dot.isShiningStar && currentOpacity > 0.4) {
          ctx.fillStyle = `rgba(230, 225, 255, ${currentOpacity})`
        } else {
          ctx.fillStyle = `rgba(145, 160, 220, ${currentOpacity})`
        }
        ctx.fill()
      }

      if (isRunning) {
        animationFrameId = requestAnimationFrame(render)
      }
    }

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReducedMotion) {
      render()
      return
    }

    let isRunning = true
    render()

    let resizeTimeout: number | undefined
    const handleResize = () => {
      if (resizeTimeout) clearTimeout(resizeTimeout)
      resizeTimeout = window.setTimeout(() => {
        setupCanvas()
      }, 100)
    }

    const handleVisibilityChange = () => {
      if (document.hidden) {
        isRunning = false
        cancelAnimationFrame(animationFrameId)
      } else if (!isRunning) {
        isRunning = true
        animationFrameId = requestAnimationFrame(render)
      }
    }

    const handleMouseMove = (e: MouseEvent) => {
      mouseX = e.clientX
      mouseY = e.clientY
    }

    const handleMouseLeave = () => {
      mouseX = -1000
      mouseY = -1000
    }

    window.addEventListener('resize', handleResize)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('mousemove', handleMouseMove, { passive: true })
    window.addEventListener('mouseleave', handleMouseLeave)

    return () => {
      isRunning = false
      cancelAnimationFrame(animationFrameId)
      if (resizeTimeout) clearTimeout(resizeTimeout)
      window.removeEventListener('resize', handleResize)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseleave', handleMouseLeave)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 0,
      }}
    />
  )
}
