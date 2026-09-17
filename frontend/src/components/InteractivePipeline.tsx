import { useState, useRef, useCallback, useEffect } from 'react'
import {
  FileText,
  Mic,
  Target,
  History,
  Eye,
  Search,
  Cpu,
  MessageSquare,
  BarChart3,
  Lightbulb,
  PenTool,
  Activity,
  Compass,
  Bell,
  Pause,
  Play,
  RotateCcw,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import './InteractivePipeline.css'

export interface PipelineNode {
  id: string
  title: string
  subtitle: string
  category: 'input' | 'core' | 'output'
  icon: LucideIcon
  x: number
  y: number
  color: string
  badge: string
  description: string
  sampleData: string
}

export interface Connection {
  from: string
  to: string
  label?: string
  color?: string
}

const DEFAULT_NODES: PipelineNode[] = [
  // ── LEFT: STUDENT & CONTEXT INPUTS (Width = 250) ──
  {
    id: 'paper-work',
    title: 'Student Paper Work',
    subtitle: 'Handwritten math steps & photos',
    category: 'input',
    icon: FileText,
    x: 142,
    y: 85,
    color: '#38BDF8',
    badge: 'PHOTO SCAN',
    description: 'The student snaps a quick camera photo of their handwritten pencil work on paper.',
    sampleData: 'Line 1: 1/3 + 1/6\nLine 2: = 2/9  (Handwritten pencil)',
  },
  {
    id: 'student-voice',
    title: 'Student Voice & Chat',
    subtitle: 'Spoken questions & thoughts',
    category: 'input',
    icon: Mic,
    x: 142,
    y: 235,
    color: '#818CF8',
    badge: 'AUDIO & TEXT',
    description: 'The student can speak out loud or type their ideas, questions, and points of confusion.',
    sampleData: '"I added 1+1 and 3+6, but I am not sure if that is right."',
  },
  {
    id: 'math-problem',
    title: 'Target Math Problem',
    subtitle: 'Target concept & difficulty',
    category: 'input',
    icon: Target,
    x: 142,
    y: 405,
    color: '#F472B6',
    badge: 'PRACTICE GOAL',
    description: 'The math problem currently on the chalkboard (fractions, multiplication, or algebra).',
    sampleData: 'Topic: Adding Fractions\nDifficulty: Level 2 of 5\nGoal: Solve 1/3 + 1/6',
  },
  {
    id: 'student-history',
    title: 'Past Practice History',
    subtitle: 'Known strengths & struggles',
    category: 'input',
    icon: History,
    x: 142,
    y: 575,
    color: '#FB923C',
    badge: 'SKILL PROFILE',
    description: 'Records past problem attempts so the tutor knows what concepts need extra encouragement.',
    sampleData: 'Equivalent Fractions: 68% (Proficient)\nUnlike Denominators: 35% (Needs Practice)',
  },

  // ── CENTER: PROCESSING SATELLITES & CORE HUB ──
  {
    id: 'hub-reader',
    title: 'Read Handwriting',
    subtitle: 'Understands pencil lines & signs',
    category: 'core',
    icon: Eye,
    x: 425,
    y: 160,
    color: '#34D399',
    badge: 'VISION STAGE 1',
    description: 'Inspects each line of handwritten math to understand what the student wrote.',
    sampleData: 'Detected: Student wrote "2/9" on line 2.\nNumerator: 2, Denominator: 9',
  },
  {
    id: 'hub-misconception',
    title: 'Spot Misconception',
    subtitle: 'Finds exact point of confusion',
    category: 'core',
    icon: Search,
    x: 425,
    y: 520,
    color: '#FBBF24',
    badge: 'ANALYSIS STAGE 2',
    description: 'Identifies the root thinking error rather than just marking the problem right or wrong.',
    sampleData: 'Root Cause: Added denominators directly (3 + 6 = 9) instead of finding common slice sizes.',
  },
  {
    id: 'hub-center',
    title: 'Veritas Thinking Core',
    subtitle: 'Socratic reasoning engine',
    category: 'core',
    icon: Cpu,
    x: 610,
    y: 340,
    color: '#A78BFA',
    badge: 'AI REASONING CORE',
    description: 'Coordinates the learning cycle: never blurts out answers, always guides with questions.',
    sampleData: 'Decision: Do not reveal 1/2.\nAction: Ask a slice-comparison visual question.',
  },
  {
    id: 'hub-socratic',
    title: 'Craft Socratic Clue',
    subtitle: 'Helpful guiding question',
    category: 'core',
    icon: MessageSquare,
    x: 795,
    y: 160,
    color: '#C084FC',
    badge: 'GUIDANCE STAGE 3',
    description: 'Formulates an encouraging question that prompts the student to discover their own error.',
    sampleData: '"If you have a 3-slice pizza and a 6-slice pizza, are the slices equal sizes?"',
  },
  {
    id: 'hub-mastery',
    title: 'Update Skill Level',
    subtitle: 'Calculates real understanding',
    category: 'core',
    icon: BarChart3,
    x: 795,
    y: 520,
    color: '#2DD4BF',
    badge: 'EVALUATION STAGE 4',
    description: 'Scientifically measures skill progress as the student works through steps.',
    sampleData: 'Fractions Mastery: 35% → 42% (Reflecting self-correction engagement)',
  },

  // ── RIGHT: LIVE LEARNING OUTPUTS (Width = 250) ──
  {
    id: 'out-hint',
    title: 'Socratic Guiding Clue',
    subtitle: 'Audio speech & chat bubble',
    category: 'output',
    icon: Lightbulb,
    x: 1078,
    y: 75,
    color: '#FBBF24',
    badge: 'SOCRATIC HINT',
    description: 'Spoken gently through voice and shown in chat so the student experiences a "lightbulb moment".',
    sampleData: 'Tutor says: "What size slices would make both pizzas easy to compare together?"',
  },
  {
    id: 'out-box',
    title: 'Paper Step Highlight',
    subtitle: 'Visual box drawn on student work',
    category: 'output',
    icon: PenTool,
    x: 1078,
    y: 195,
    color: '#F87171',
    badge: 'PAPER BOX',
    description: 'Draws a color-coded guidance box over the handwritten step that needs another look.',
    sampleData: 'Highlighted: Step 2 denominator "9" in warm amber with hint label.',
  },
  {
    id: 'out-radar',
    title: 'Live Skill Radar Update',
    subtitle: 'Real-time mastery growth',
    category: 'output',
    icon: Activity,
    x: 1078,
    y: 320,
    color: '#34D399',
    badge: 'SKILL RADAR',
    description: 'Student and parent dashboards immediately reflect newly solidified math understanding.',
    sampleData: 'Understanding Fractions: +7% mastery gained this session.',
  },
  {
    id: 'out-next-problem',
    title: 'Next Practice Problem',
    subtitle: 'Calibrated to ability level',
    category: 'output',
    icon: Compass,
    x: 1078,
    y: 445,
    color: '#60A5FA',
    badge: 'NEXT PROBLEM',
    description: 'Selects a tailored follow-up question so the student can practice the new realization.',
    sampleData: 'Next: "Walking Trails: Adding 1/4 + 1/2" (reinforces common denominators).',
  },
  {
    id: 'out-parent-alert',
    title: 'Parent Progress Notice',
    subtitle: 'Celebration or friendly reminder',
    category: 'output',
    icon: Bell,
    x: 1078,
    y: 575,
    color: '#C084FC',
    badge: 'PARENT UPDATE',
    description: 'Parents see daily milestones or get a friendly reminder if a skill has not been practiced in 3 days.',
    sampleData: 'Alert sent: "Alex mastered unlike denominators today with 3 self-corrections!"',
  },
]

const CONNECTIONS: Connection[] = [
  // Inputs to Reader / Core / Misconception
  { from: 'paper-work', to: 'hub-reader', label: 'SCAN', color: '#38BDF8' },
  { from: 'student-voice', to: 'hub-center', label: 'AUDIO', color: '#818CF8' },
  { from: 'math-problem', to: 'hub-misconception', label: 'CONTEXT', color: '#F472B6' },
  { from: 'student-history', to: 'hub-misconception', label: 'HISTORY', color: '#FB923C' },

  // Internal Core flow
  { from: 'hub-reader', to: 'hub-center', label: 'LINES', color: '#34D399' },
  { from: 'hub-misconception', to: 'hub-center', label: 'ERROR', color: '#FBBF24' },
  { from: 'hub-center', to: 'hub-socratic', label: 'REASON', color: '#A78BFA' },
  { from: 'hub-center', to: 'hub-mastery', label: 'EVAL', color: '#A78BFA' },

  // Core to Outputs
  { from: 'hub-socratic', to: 'out-hint', label: 'HINT', color: '#FBBF24' },
  { from: 'hub-socratic', to: 'out-box', label: 'BOX', color: '#F87171' },
  { from: 'hub-mastery', to: 'out-radar', label: 'GROWTH', color: '#34D399' },
  { from: 'hub-mastery', to: 'out-next-problem', label: 'NEXT', color: '#60A5FA' },
  { from: 'hub-mastery', to: 'out-parent-alert', label: 'NOTICE', color: '#C084FC' },
]

export default function InteractivePipeline() {
  const [nodes, setNodes] = useState<PipelineNode[]>(DEFAULT_NODES)
  const [selectedNodeId, setSelectedNodeId] = useState<string>('hub-center')
  const [isPaused, setIsPaused] = useState(false)
  const [isSimulating, setIsSimulating] = useState(false)
  const [simulationMessage, setSimulationMessage] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'canvas' | 'cards'>('canvas')

  // Dragging state
  const svgRef = useRef<SVGSVGElement | null>(null)
  const draggingNodeRef = useRef<{ id: string; startX: number; startY: number; mouseStartX: number; mouseStartY: number } | null>(null)


  const simulationTimersRef = useRef<number[]>([])

  useEffect(() => {
    return () => {
      simulationTimersRef.current.forEach(clearTimeout)
    }
  }, [])

  // Reset to default positions
  const handleResetLayout = () => {
    setNodes(DEFAULT_NODES)
  }

  // Trigger interactive practice step simulation
  const handleSimulateStep = () => {
    if (isSimulating) return
    setIsSimulating(true)
    setSimulationMessage('Step 1: Student uploaded handwritten work (1/3 + 1/6 = 2/9)...')
    setSelectedNodeId('paper-work')

    simulationTimersRef.current.forEach(clearTimeout)
    simulationTimersRef.current = []

    const t1 = window.setTimeout(() => {
      setSimulationMessage('Step 2: Handwriting Reader spotted denominator addition...')
      setSelectedNodeId('hub-misconception')
    }, 1100)

    const t2 = window.setTimeout(() => {
      setSimulationMessage('Step 3: Veritas crafted a visual pizza-slice Socratic clue...')
      setSelectedNodeId('hub-socratic')
    }, 2200)

    const t3 = window.setTimeout(() => {
      setSimulationMessage('Step 4: Sent Socratic hint to chat & updated skill mastery radar!')
      setSelectedNodeId('out-hint')
    }, 3300)

    const t4 = window.setTimeout(() => {
      setIsSimulating(false)
      setSimulationMessage(null)
    }, 4800)

    simulationTimersRef.current.push(t1, t2, t3, t4)
  }

  // Pointer drag handlers
  const handlePointerDown = (id: string, e: React.PointerEvent) => {
    e.stopPropagation()
    const targetNode = nodes.find(n => n.id === id)
    if (!targetNode) return

    setSelectedNodeId(id)

    // Capture pointer
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)

    draggingNodeRef.current = {
      id,
      startX: targetNode.x,
      startY: targetNode.y,
      mouseStartX: e.clientX,
      mouseStartY: e.clientY,
    }
  }

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!draggingNodeRef.current || !svgRef.current) return

    const rect = svgRef.current.getBoundingClientRect()
    // Convert client delta to SVG coordinate delta
    const scaleX = 1220 / rect.width
    const scaleY = 680 / rect.height

    const dx = (e.clientX - draggingNodeRef.current.mouseStartX) * scaleX
    const dy = (e.clientY - draggingNodeRef.current.mouseStartY) * scaleY

    const newX = Math.max(100, Math.min(1120, draggingNodeRef.current.startX + dx))
    const newY = Math.max(50, Math.min(630, draggingNodeRef.current.startY + dy))

    setNodes(prev =>
      prev.map(node =>
        node.id === draggingNodeRef.current?.id ? { ...node, x: newX, y: newY } : node
      )
    )
  }, [])

  const handlePointerUp = useCallback(() => {
    draggingNodeRef.current = null
  }, [])

  // Calculate clean anchor endpoints on boundary of capsules
  const getEndpoints = (source: PipelineNode, target: PipelineNode) => {
    let x1 = source.x
    let y1 = source.y
    if (source.id === 'hub-center') {
      x1 = source.x + 60
    } else if (source.category === 'input') {
      x1 = source.x + 125
    } else if (source.category === 'core') {
      x1 = source.x + 110
    }

    let x2 = target.x
    let y2 = target.y
    if (target.id === 'hub-center') {
      x2 = target.x - 60
    } else if (target.category === 'output') {
      x2 = target.x - 125
    } else if (target.category === 'core') {
      x2 = target.x - 110
    }

    return { x1, y1, x2, y2 }
  }

  // Calculate smooth cubic bezier path between two nodes
  const getPath = (source: PipelineNode, target: PipelineNode) => {
    const { x1, y1, x2, y2 } = getEndpoints(source, target)
    const dx = Math.abs(x2 - x1) * 0.55
    const cx1 = x1 + dx
    const cy1 = y1
    const cx2 = x2 - dx
    const cy2 = y2

    return `M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`
  }

  return (
    <div className="pipeline-wrapper">
      {/* ── Top Bar with Controls ── */}
      <div className="pipeline-topbar">
        <div className="pipeline-status">
          <span className={`pipeline-live-dot ${isPaused ? 'paused' : ''}`} />
          <span className="pipeline-title-text">
            LIVE LEARNING FLOW {isPaused ? '(PAUSED)' : '(REAL-TIME)'}
          </span>
          {simulationMessage && (
            <span className="pipeline-sim-banner animate-fadein">
              {simulationMessage}
            </span>
          )}
        </div>

        <div className="pipeline-controls">
          <button
            type="button"
            className="pipeline-btn pipeline-btn--primary"
            onClick={handleSimulateStep}
            disabled={isSimulating}
            title="Watch a sample practice problem flow through the pipeline"
          >
            <Sparkles size={16} />
            <span>{isSimulating ? 'Simulating…' : 'Send Practice Step'}</span>
          </button>

          <button
            type="button"
            className="pipeline-btn"
            onClick={() => setIsPaused(prev => !prev)}
            title={isPaused ? 'Resume animated flow' : 'Pause animation'}
          >
            {isPaused ? <Play size={15} /> : <Pause size={15} />}
            <span>{isPaused ? 'Resume Flow' : 'Pause Flow'}</span>
          </button>

          <button
            type="button"
            className="pipeline-btn"
            onClick={handleResetLayout}
            title="Reset dragged nodes to initial positions"
          >
            <RotateCcw size={15} />
            <span>Reset Nodes</span>
          </button>

          <div className="pipeline-view-toggle">
            <button
              type="button"
              className={`toggle-btn ${viewMode === 'canvas' ? 'active' : ''}`}
              onClick={() => setViewMode('canvas')}
              title="Interactive draggable canvas"
            >
              Interactive Map
            </button>
            <button
              type="button"
              className={`toggle-btn ${viewMode === 'cards' ? 'active' : ''}`}
              onClick={() => setViewMode('cards')}
              title="Sequential step-by-step list"
            >
              Step Cards
            </button>
          </div>
        </div>
      </div>

      {/* ── Interactive SVG Canvas ── */}
      {viewMode === 'canvas' ? (
        <div className="pipeline-stage-container">
          <div className="pipeline-hint-bar">
            <Lightbulb size={16} style={{ color: '#FBBF24', flexShrink: 0 }} />
            <span>Click or <strong>drag nodes freely</strong> to flex live cables — or click <strong>Send Practice Step</strong> to watch real-time data flow!</span>
          </div>

          <div className="pipeline-svg-wrapper">
            <svg
              ref={svgRef}
              viewBox="0 0 1220 680"
              className="pipeline-svg"
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
            >
              <defs>
                {/* Radial background glow */}
                <radialGradient id="centerGlow" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="#818CF8" stopOpacity="0.22" />
                  <stop offset="100%" stopColor="#818CF8" stopOpacity="0" />
                </radialGradient>
              </defs>

              {/* Background Glow */}
              <circle cx="610" cy="340" r="300" fill="url(#centerGlow)" />

              {/* Central Radar Rings */}
              <circle
                cx="610"
                cy="340"
                r="115"
                fill="none"
                stroke="var(--pipeline-grid-line, rgba(129, 140, 248, 0.22))"
                strokeWidth="1.2"
                strokeDasharray="5 5"
                className={`radar-ring ${isPaused ? 'paused' : ''}`}
              />
              <circle
                cx="610"
                cy="340"
                r="195"
                fill="none"
                stroke="var(--pipeline-grid-line, rgba(129, 140, 248, 0.12))"
                strokeWidth="1"
                strokeDasharray="7 7"
                className="radar-outer-ring"
              />

              {/* ── Dynamic Connecting Curved Paths ── */}
              {CONNECTIONS.map((conn, idx) => {
                const src = nodes.find(n => n.id === conn.from)
                const tgt = nodes.find(n => n.id === conn.to)
                if (!src || !tgt) return null

                const pathD = getPath(src, tgt)
                const isSelectedConn = selectedNodeId === src.id || selectedNodeId === tgt.id
                const { x1, y1, x2, y2 } = getEndpoints(src, tgt)
                const midX = (x1 + x2) / 2
                const midY = (y1 + y2) / 2

                return (
                  <g key={`conn-${idx}`} className="pipeline-cable-group">
                    {/* Base cable */}
                    <path
                      d={pathD}
                      className={`pipeline-cable ${isSelectedConn ? 'pipeline-cable--selected' : ''}`}
                      stroke={conn.color || 'var(--text-muted)'}
                      strokeWidth={isSelectedConn ? 2.8 : 1.8}
                      strokeDasharray="5 4"
                      fill="none"
                    />

                    {/* Animated moving pulse packet */}
                    {!isPaused && (
                      <circle r={isSelectedConn ? 5.2 : 3.8} fill={conn.color || '#38BDF8'} className="pulse-particle">
                        <animateMotion
                          dur={isSelectedConn ? '2s' : '3.5s'}
                          repeatCount="indefinite"
                          path={pathD}
                          keyPoints="0;1"
                          keyTimes="0;1"
                        />
                      </circle>
                    )}

                    {/* Cybernetic Floating Cable Badge */}
                    {conn.label && (
                      <g transform={`translate(${midX}, ${midY})`} className="cable-badge-group">
                        <rect
                          x="-28"
                          y="-10"
                          width="56"
                          height="20"
                          rx="10"
                          className="cable-badge-rect"
                          stroke={conn.color || 'var(--border)'}
                          strokeWidth="1.2"
                          data-label={conn.label}
                        />
                        <text
                          x="0"
                          y="4"
                          textAnchor="middle"
                          fontSize="8.5"
                          fontWeight="800"
                          letterSpacing="0.08em"
                          fill={conn.color || '#94a3b8'}
                          className="cable-badge-text"
                          data-label={conn.label}
                        >
                          {conn.label}
                        </text>
                      </g>
                    )}
                  </g>
                )
              })}

              {/* ── Draggable Pipeline Nodes ── */}
              {nodes.map(node => {
                const isSelected = selectedNodeId === node.id
                const isCenterCore = node.id === 'hub-center'
                const isSatellite = node.category === 'core' && !isCenterCore
                const NodeIcon = node.icon

                // Widths: 250 for inputs/outputs, 220 for satellites
                const rectW = isSatellite ? 220 : 250
                const rectH = 58
                const halfW = rectW / 2
                const halfH = rectH / 2

                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    className={`pipeline-node-item ${isSelected ? 'selected' : ''} ${isCenterCore ? 'center-core' : ''}`}
                    onPointerDown={e => handlePointerDown(node.id, e)}
                    onClick={() => setSelectedNodeId(node.id)}
                    style={{ cursor: 'grab' }}
                  >
                    {/* Clip path ensuring no text or child element ever overflows outside the capsule */}
                    {!isCenterCore && (
                      <defs>
                        <clipPath id={`clip-${node.id}`}>
                          <rect
                            x={-halfW + 1}
                            y={-halfH + 1}
                            width={rectW - 2}
                            height={rectH - 2}
                            rx="12"
                          />
                        </clipPath>
                      </defs>
                    )}

                    {/* Outer glow aura for selected node */}
                    {isSelected && (
                      <circle
                        cx="0"
                        cy="0"
                        r={isCenterCore ? 72 : 62}
                        fill="none"
                        stroke={node.color}
                        strokeWidth="2.5"
                        strokeOpacity="0.45"
                        className="node-aura-pulse"
                      />
                    )}

                    {isCenterCore ? (
                      // ── Center Core Hub (HUD Style) ──
                      <g className="center-core-group">
                        <circle
                          cx="0"
                          cy="0"
                          r="60"
                          className="node-core-circle"
                          stroke={node.color}
                          strokeWidth={isSelected ? 3.5 : 2.5}
                        />

                        {/* Inner rotating orbit of radar dots */}
                        <g className={`core-dot-orbit ${isPaused ? 'paused' : ''}`}>
                          {[0, 45, 90, 135, 180, 225, 270, 315].map((deg, i) => {
                            const rad = (deg * Math.PI) / 180
                            const dx = Math.cos(rad) * 44
                            const dy = Math.sin(rad) * 44
                            return (
                              <circle
                                key={i}
                                cx={dx}
                                cy={dy}
                                r="2.5"
                                fill={node.color}
                                opacity="0.65"
                                className="core-orbit-dot"
                              />
                            )
                          })}
                        </g>

                        {/* Large Vector CPU icon */}
                        <NodeIcon
                          x="-18"
                          y="-35"
                          size={36}
                          color={node.color}
                          strokeWidth={2.2}
                          className="node-core-icon"
                        />

                        {/* Core Title */}
                        <text
                          x="0"
                          y="14"
                          textAnchor="middle"
                          className="node-core-title"
                          fontSize="12"
                          fontWeight="800"
                        >
                          VERITAS CORE
                        </text>

                        {/* Core Subtitle */}
                        <text
                          x="0"
                          y="28"
                          textAnchor="middle"
                          className="node-core-sub"
                          fontSize="9.5"
                          fontWeight="700"
                          letterSpacing="0.08em"
                        >
                          SOCRATIC AI
                        </text>
                      </g>
                    ) : (
                      // ── Standard Pill Capsule ──
                      <g clipPath={`url(#clip-${node.id})`}>
                        {/* Main Capsule Body */}
                        <rect
                          x={-halfW}
                          y={-halfH}
                          width={rectW}
                          height={rectH}
                          rx="13"
                          className="node-pill-rect"
                          stroke={isSelected ? node.color : 'var(--pipeline-border, rgba(255,255,255,0.14))'}
                          strokeWidth={isSelected ? 2.5 : 1.2}
                        />

                        {/* Large Circular Vector Icon Badge Container */}
                        <circle
                          cx={-halfW + 34}
                          cy="0"
                          r="19"
                          className="node-icon-bg"
                          fill={`${node.color}18`}
                          stroke={`${node.color}45`}
                          strokeWidth="1.2"
                        />

                        {/* High-visibility Vector Lucide Icon */}
                        <NodeIcon
                          x={-halfW + 22}
                          y="-12"
                          size={24}
                          color={node.color}
                          strokeWidth={2.2}
                        />

                        {/* Text Group - Clear, Large, Readable Typography */}
                        <text
                          x={-halfW + 62}
                          y="-5"
                          className="node-title"
                          fontSize="13.5"
                          fontWeight="700"
                          textLength={node.title.length > 20 ? (isSatellite ? 142 : 166) : undefined}
                          lengthAdjust="spacing"
                        >
                          {node.title}
                        </text>

                        <text
                          x={-halfW + 62}
                          y="14"
                          className="node-sub"
                          fontSize="9.8"
                          fontWeight="700"
                          letterSpacing="0.07em"
                        >
                          {node.badge}
                        </text>
                      </g>
                    )}

                    {/* Connection Anchor Port Dots */}
                    {!isCenterCore && node.category === 'input' && (
                      <circle cx={halfW} cy="0" r="4.5" fill={node.color} className="anchor-port" />
                    )}
                    {!isCenterCore && node.category === 'output' && (
                      <circle cx={-halfW} cy="0" r="4.5" fill={node.color} className="anchor-port" />
                    )}
                    {!isCenterCore && node.category === 'core' && (
                      <>
                        <circle cx={-halfW} cy="0" r="4.5" fill={node.color} className="anchor-port" />
                        <circle cx={halfW} cy="0" r="4.5" fill={node.color} className="anchor-port" />
                      </>
                    )}
                  </g>
                )
              })}
            </svg>
          </div>
        </div>
      ) : (
        /* ── Mobile Step-by-Step Cards View ── */
        <div className="pipeline-cards-view">
          <div className="cards-column">
            <h4>1. Student & Problem Inputs</h4>
            <div className="cards-grid">
              {nodes.filter(n => n.category === 'input').map(n => {
                const CardIcon = n.icon
                return (
                  <div
                    key={n.id}
                    className={`pipeline-card-item ${selectedNodeId === n.id ? 'active' : ''}`}
                    onClick={() => setSelectedNodeId(n.id)}
                  >
                    <div
                      className="card-icon-badge"
                      style={{
                        background: `${n.color}18`,
                        borderColor: `${n.color}45`,
                        color: n.color,
                      }}
                    >
                      <CardIcon size={22} strokeWidth={2.2} />
                    </div>
                    <div>
                      <strong>{n.title}</strong>
                      <p>{n.subtitle}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="cards-column">
            <h4>2. Socratic Reasoning Core</h4>
            <div className="cards-grid">
              {nodes.filter(n => n.category === 'core').map(n => {
                const CardIcon = n.icon
                return (
                  <div
                    key={n.id}
                    className={`pipeline-card-item ${selectedNodeId === n.id ? 'active' : ''}`}
                    onClick={() => setSelectedNodeId(n.id)}
                  >
                    <div
                      className="card-icon-badge"
                      style={{
                        background: `${n.color}18`,
                        borderColor: `${n.color}45`,
                        color: n.color,
                      }}
                    >
                      <CardIcon size={22} strokeWidth={2.2} />
                    </div>
                    <div>
                      <strong>{n.title}</strong>
                      <p>{n.subtitle}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="cards-column">
            <h4>3. Student & Parent Outcomes</h4>
            <div className="cards-grid">
              {nodes.filter(n => n.category === 'output').map(n => {
                const CardIcon = n.icon
                return (
                  <div
                    key={n.id}
                    className={`pipeline-card-item ${selectedNodeId === n.id ? 'active' : ''}`}
                    onClick={() => setSelectedNodeId(n.id)}
                  >
                    <div
                      className="card-icon-badge"
                      style={{
                        background: `${n.color}18`,
                        borderColor: `${n.color}45`,
                        color: n.color,
                      }}
                    >
                      <CardIcon size={22} strokeWidth={2.2} />
                    </div>
                    <div>
                      <strong>{n.title}</strong>
                      <p>{n.subtitle}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
