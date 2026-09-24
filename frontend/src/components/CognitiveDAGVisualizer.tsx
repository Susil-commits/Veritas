import React, { useState, useMemo, useEffect } from 'react';
import {
  COGNITIVE_DAG_LIST,
  COGNITIVE_DAG_NODES,
  getDetailedDeficitDiagnosis,
  applyTimeDecay,
} from '../lib/skillsData';
import type { SkillDAGNode } from '../lib/skillsData';
import './CognitiveDAGVisualizer.css';

interface CognitiveDAGVisualizerProps {
  skills?: { skill_id: string; mastery_prob: number; name?: string }[];
  activeSkillId?: string | null;
  onSelectSkill?: (skillId: string) => void;
  showDecayControls?: boolean;
  compact?: boolean;
}

// Fixed SVG layout coordinates for 800x410 viewport
const NODE_COORDINATES: Record<string, { x: number; y: number }> = {
  '3.OA.A.1': { x: 160, y: 70 },
  '3.OA.A.2': { x: 400, y: 70 },
  '3.OA.D.8': { x: 640, y: 70 },

  '4.NF.A.1': { x: 130, y: 195 },
  '4.NF.B.3': { x: 310, y: 195 },
  '4.NF.B.4': { x: 490, y: 195 },
  '5.NF.B.7': { x: 670, y: 195 },

  '6.EE.A.2': { x: 180, y: 320 },
  '6.EE.B.7': { x: 400, y: 320 },
  '7.EE.B.4': { x: 640, y: 320 },
};

// Curriculum Milestones organized by Grade Tiers for high-value sidebar navigation
const GRADE_TIERS = [
  {
    tierId: 'foundations',
    name: 'Grade 3 · Foundations',
    subtitle: 'Multiplication, Division & Word Problems',
    icon: '📘',
    skillIds: ['3.OA.A.1', '3.OA.A.2', '3.OA.D.8'],
  },
  {
    tierId: 'fractions',
    name: 'Grade 4–5 · Fractions & Decimals',
    subtitle: 'Equivalence, Addition/Subtraction & Fraction Division',
    icon: '📙',
    skillIds: ['4.NF.A.1', '4.NF.B.3', '4.NF.B.4', '5.NF.B.7'],
  },
  {
    tierId: 'equations',
    name: 'Grade 6–7 · Algebraic Equations',
    subtitle: 'Expressions, One-Step & Multi-Step Linear Equations',
    icon: '📐',
    skillIds: ['6.EE.A.2', '6.EE.B.7', '7.EE.B.4'],
  },
];

export const CognitiveDAGVisualizer: React.FC<CognitiveDAGVisualizerProps> = ({
  skills = [],
  activeSkillId: propActiveSkillId,
  onSelectSkill,
  showDecayControls = true,
  compact = false,
}) => {
  // Default to 'path' view when compact (e.g. in the session sidebar) so text is 100% visible and readable!
  const [viewMode, setViewMode] = useState<'path' | 'graph'>(compact ? 'path' : 'graph');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [selectedSkillId, setSelectedSkillId] = useState<string>(
    propActiveSkillId || '3.OA.A.2'
  );
  const [decayDays, setDecayDays] = useState<number>(0);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Sync prop changes if provided
  useEffect(() => {
    if (propActiveSkillId) {
      setSelectedSkillId(propActiveSkillId);
    }
  }, [propActiveSkillId]);

  // Close modal on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isModalOpen) {
        setIsModalOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isModalOpen]);

  const currentActiveId = propActiveSkillId || selectedSkillId;

  // Build live mastery map from passed-in skills (or fallback to prior defaults)
  const baseMasteryMap = useMemo(() => {
    const map: Record<string, number> = {};
    COGNITIVE_DAG_LIST.forEach((n) => {
      const match = skills.find((s) => s.skill_id === n.id);
      map[n.id] = match ? (Number(match.mastery_prob) || n.prior) : n.prior;
    });
    return map;
  }, [skills]);

  // Apply Ebbinghaus time decay to mastery map
  const activeMasteryMap = useMemo(() => {
    if (decayDays === 0) return baseMasteryMap;
    const decayed: Record<string, number> = {};
    COGNITIVE_DAG_LIST.forEach((n) => {
      const base = baseMasteryMap[n.id] ?? n.prior;
      decayed[n.id] = applyTimeDecay(base, decayDays, n.id);
    });
    return decayed;
  }, [baseMasteryMap, decayDays]);

  // Active root deficit diagnosis for the currently selected skill
  const deficitAnalysis = useMemo(() => {
    if (!currentActiveId) return null;
    return getDetailedDeficitDiagnosis(activeMasteryMap, currentActiveId, 0.70);
  }, [currentActiveId, activeMasteryMap]);

  // Node selection handler
  const handleNodeClick = (skillId: string) => {
    setSelectedSkillId(skillId);
    if (onSelectSkill) {
      onSelectSkill(skillId);
    }
  };

  const selectedNode = COGNITIVE_DAG_NODES[currentActiveId] || COGNITIVE_DAG_LIST[0];
  const selectedPct = Math.round((activeMasteryMap[selectedNode.id] ?? 0.5) * 100);

  // Helper to determine node colors based on mastery level
  const getNodeColor = (prob: number) => {
    if (prob >= 0.85) return { stroke: '#10B981', fill: 'rgba(16, 185, 129, 0.22)', label: 'Mastered', tier: 'mastered' };
    if (prob >= 0.70) return { stroke: '#3B82F6', fill: 'rgba(59, 130, 246, 0.22)', label: 'Proficient', tier: 'proficient' };
    if (prob >= 0.50) return { stroke: '#F59E0B', fill: 'rgba(245, 158, 11, 0.22)', label: 'Practicing', tier: 'practicing' };
    return { stroke: '#EF4444', fill: 'rgba(239, 68, 68, 0.22)', label: 'Needs Work', tier: 'deficit' };
  };

  // Compile list of edges for SVG
  const edges = useMemo(() => {
    const list: { from: string; to: string; isDeficit: boolean; isActive: boolean }[] = [];
    COGNITIVE_DAG_LIST.forEach((node) => {
      node.prerequisites.forEach((preId) => {
        const isDeficit =
          deficitAnalysis?.deficitPath?.includes(preId) &&
          deficitAnalysis?.deficitPath?.includes(node.id);
        const isActive =
          (currentActiveId === node.id && node.prerequisites.includes(preId)) ||
          hoveredNodeId === node.id ||
          hoveredNodeId === preId;

        list.push({
          from: preId,
          to: node.id,
          isDeficit: Boolean(isDeficit),
          isActive: Boolean(isActive),
        });
      });
    });
    return list;
  }, [deficitAnalysis, currentActiveId, hoveredNodeId]);

  // Reusable SVG graph component with enhanced high-contrast text and crisp nodes
  const renderSVGGraph = (isModal: boolean = false) => (
    <div className={`dag-svg-wrapper ${isModal ? 'dag-svg-wrapper--modal' : ''}`}>
      <svg
        className={`dag-svg ${isModal ? 'dag-svg--modal' : ''}`}
        viewBox="0 0 800 400"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <marker
            id="dag-arrow"
            viewBox="0 0 10 10"
            refX="18"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 10 5 L 0 9 z" fill="rgba(148, 163, 184, 0.6)" />
          </marker>
          <marker
            id="dag-arrow-active"
            viewBox="0 0 10 10"
            refX="18"
            refY="5"
            markerWidth="8"
            markerHeight="8"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#818CF8" />
          </marker>
          <marker
            id="dag-arrow-deficit"
            viewBox="0 0 10 10"
            refX="18"
            refY="5"
            markerWidth="8"
            markerHeight="8"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#F87171" />
          </marker>
        </defs>

        {/* Background Level Guides with High-Contrast Typography */}
        <g className="dag-level-guides">
          <line x1="30" y1="70" x2="770" y2="70" className="dag-level-line" />
          <text x="35" y="62" className="dag-level-text">
            GRADE 3 · FOUNDATIONS
          </text>

          <line x1="30" y1="195" x2="770" y2="195" className="dag-level-line" />
          <text x="35" y="187" className="dag-level-text">
            GRADE 4-5 · FRACTIONS &amp; DECIMALS
          </text>

          <line x1="30" y1="320" x2="770" y2="320" className="dag-level-line" />
          <text x="35" y="312" className="dag-level-text">
            GRADE 6-7 · ALGEBRAIC EQUATIONS
          </text>
        </g>

        {/* Directed Edges */}
        <g className="dag-edges">
          {edges.map((edge, idx) => {
            const p = NODE_COORDINATES[edge.from];
            const t = NODE_COORDINATES[edge.to];
            if (!p || !t) return null;

            const midY = (p.y + t.y) / 2;
            const d = `M ${p.x} ${p.y + 27} C ${p.x} ${midY}, ${t.x} ${midY}, ${t.x} ${t.y - 27}`;

            let edgeClass = 'dag-edge';
            let marker = 'url(#dag-arrow)';
            if (edge.isDeficit) {
              edgeClass += ' dag-edge--deficit';
              marker = 'url(#dag-arrow-deficit)';
            } else if (edge.isActive) {
              edgeClass += ' dag-edge--active';
              marker = 'url(#dag-arrow-active)';
            }

            return (
              <path
                key={`edge-${edge.from}-${edge.to}-${idx}`}
                d={d}
                className={edgeClass}
                markerEnd={marker}
              />
            );
          })}
        </g>

        {/* Nodes with High Contrast Labels */}
        <g className="dag-nodes">
          {COGNITIVE_DAG_LIST.map((node: SkillDAGNode) => {
            const coords = NODE_COORDINATES[node.id];
            if (!coords) return null;

            const prob = activeMasteryMap[node.id] ?? node.prior;
            const pct = Math.round(prob * 100);
            const { stroke, fill } = getNodeColor(prob);
            const isSelected = currentActiveId === node.id;
            const isDeficit = deficitAnalysis?.rootDeficitId === node.id;
            const isCurrentFocus = propActiveSkillId === node.id;

            return (
              <g
                key={node.id}
                className={`dag-node ${isSelected ? 'dag-node--selected' : ''} ${isCurrentFocus ? 'dag-node--current' : ''}`}
                transform={`translate(${coords.x}, ${coords.y})`}
                onClick={() => handleNodeClick(node.id)}
                onMouseEnter={() => setHoveredNodeId(node.id)}
                onMouseLeave={() => setHoveredNodeId(null)}
                role="button"
                tabIndex={0}
                aria-label={`${node.id}: ${node.title}, Mastery ${pct}%`}
              >
                {/* Deficit Halo */}
                {isDeficit && (
                  <circle
                    r="34"
                    fill="none"
                    stroke="#EF4444"
                    strokeWidth="2.5"
                    strokeDasharray="4 2"
                    opacity="0.9"
                  >
                    <animateTransform
                      attributeName="transform"
                      type="rotate"
                      from="0"
                      to="360"
                      dur="8s"
                      repeatCount="indefinite"
                    />
                  </circle>
                )}

                {/* Current Active Focus Pulse Ring */}
                {isCurrentFocus && (
                  <circle
                    r="32"
                    fill="none"
                    stroke="#818CF8"
                    strokeWidth="2"
                    opacity="0.8"
                    className="dag-current-pulse-ring"
                  />
                )}

                {/* Main Node Circle */}
                <circle
                  className="dag-node-circle"
                  r="27"
                  fill={fill}
                  stroke={isSelected ? '#FFFFFF' : (isCurrentFocus ? '#818CF8' : stroke)}
                  strokeWidth={isSelected ? '3.5' : (isCurrentFocus ? '3' : '2.2')}
                />

                {/* CCSS Short Code */}
                <text className="dag-node-text-code" y="-5">
                  {node.id}
                </text>

                {/* Percentage */}
                <text
                  className="dag-node-text-pct"
                  y="13"
                  fill={stroke}
                >
                  {pct}%
                </text>

                {/* Label below circle */}
                <text className="dag-node-text-label" y="42">
                  {node.shortTitle}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );

  return (
    <div className={`dag-container ${compact ? 'dag-container--compact' : ''}`}>
      {/* Header with Title, Mode Switcher & Expand button */}
      <div className="dag-header">
        <div className="dag-header-title">
          <h3>
            <span>🧠</span> Math Learning Journey
          </h3>
          <p className="dag-header-sub">
            {compact
              ? 'Foundations to middle school algebra'
              : 'See how elementary math foundations connect directly to middle school algebra'}
          </p>
        </div>

        <div className="dag-header-actions">
          {/* Segmented View Mode Switcher (Journey Path vs Network Graph) */}
          <div className="dag-view-toggle">
            <button
              type="button"
              className={`dag-view-btn ${viewMode === 'path' ? 'dag-view-btn--active' : ''}`}
              onClick={() => setViewMode('path')}
              title="View as structured learning milestones"
            >
              🛤️ Path
            </button>
            <button
              type="button"
              className={`dag-view-btn ${viewMode === 'graph' ? 'dag-view-btn--active' : ''}`}
              onClick={() => setViewMode('graph')}
              title="View full cognitive network graph"
            >
              🕸️ Graph
            </button>
          </div>

          {/* Fullscreen / Expand Modal Button */}
          <button
            type="button"
            className="dag-expand-btn"
            onClick={() => setIsModalOpen(true)}
            title="Expand into full-screen interactive skill graph"
          >
            🔍 Expand
          </button>
        </div>
      </div>

      {/* Forgetting curve controls (shown on graph mode or non-compact) */}
      {showDecayControls && viewMode === 'graph' && (
        <div className="dag-decay-controls" title="Project retention using the Ebbinghaus forgetting curve">
          <span className="dag-decay-label">Forgetting Curve:</span>
          {[
            { days: 0, label: 'Live' },
            { days: 7, label: '+7d' },
            { days: 14, label: '+14d' },
            { days: 30, label: '+30d' },
          ].map((horizon) => (
            <button
              key={horizon.days}
              type="button"
              className={`dag-decay-btn ${decayDays === horizon.days ? 'dag-decay-btn--active' : ''}`}
              onClick={() => setDecayDays(horizon.days)}
            >
              {horizon.label}
            </button>
          ))}
        </div>
      )}

      {/* VIEW 1: High-Value, 100% Readable Journey Path View (Sidebar-Optimized) */}
      {viewMode === 'path' && (
        <div className="dag-path-wrapper">
          {GRADE_TIERS.map((tier) => (
            <div key={tier.tierId} className="dag-tier-section">
              <div className="dag-tier-header">
                <span className="dag-tier-icon">{tier.icon}</span>
                <div className="dag-tier-meta">
                  <span className="dag-tier-name">{tier.name}</span>
                  <span className="dag-tier-sub">{tier.subtitle}</span>
                </div>
              </div>

              <div className="dag-tier-skills">
                {tier.skillIds.map((skillId) => {
                  const node = COGNITIVE_DAG_NODES[skillId];
                  if (!node) return null;
                  const prob = activeMasteryMap[node.id] ?? node.prior;
                  const pct = Math.round(prob * 100);
                  const badge = getNodeColor(prob);
                  const isSelected = currentActiveId === node.id;
                  const isCurrentFocus = propActiveSkillId === node.id;
                  const isDeficit = deficitAnalysis?.rootDeficitId === node.id;

                  return (
                    <div
                      key={node.id}
                      className={`dag-skill-item ${isSelected ? 'dag-skill-item--selected' : ''} ${isCurrentFocus ? 'dag-skill-item--active-focus' : ''}`}
                      onClick={() => handleNodeClick(node.id)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="dag-skill-top">
                        <div className="dag-skill-id-title">
                          <span className="dag-skill-badge">{node.id}</span>
                          <span className="dag-skill-title">{node.title}</span>
                        </div>
                        <div className="dag-skill-stat">
                          <span className="dag-skill-pct" style={{ color: badge.stroke }}>
                            {pct}%
                          </span>
                          <span className={`dag-status-pill dag-status-pill--${badge.tier}`}>
                            {badge.label}
                          </span>
                        </div>
                      </div>

                      {/* Visual Mastery Progress Bar */}
                      <div className="dag-progress-bar-bg">
                        <div
                          className="dag-progress-bar-fill"
                          style={{
                            width: `${pct}%`,
                            background: badge.stroke,
                          }}
                        />
                      </div>

                      {/* Badges for active problem focus or foundational gap alerts */}
                      {(isCurrentFocus || isDeficit) && (
                        <div className="dag-skill-tags">
                          {isCurrentFocus && (
                            <span className="dag-tag dag-tag--focus">
                              🎯 Current Problem Topic
                            </span>
                          )}
                          {isDeficit && (
                            <span className="dag-tag dag-tag--deficit">
                              ⚠️ Foundational Gap
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* VIEW 2: Interactive SVG Network Graph View */}
      {viewMode === 'graph' && renderSVGGraph(false)}

      {/* Selected Node Details & Root-Cause Diagnosis */}
      <div className="dag-detail-card">
        <div className="dag-detail-header">
          <div className="dag-detail-title-group">
            <span
              className="dag-detail-badge"
              style={{
                background: getNodeColor(activeMasteryMap[selectedNode.id] ?? 0.5).fill,
                color: getNodeColor(activeMasteryMap[selectedNode.id] ?? 0.5).stroke,
                border: `1px solid ${getNodeColor(activeMasteryMap[selectedNode.id] ?? 0.5).stroke}`,
              }}
            >
              {selectedNode.id} · {selectedNode.cluster}
            </span>
            <h4 className="dag-detail-name">{selectedNode.title}</h4>
          </div>

          <div className="dag-detail-metrics">
            <span
              className="dag-detail-pct"
              style={{ color: getNodeColor(activeMasteryMap[selectedNode.id] ?? 0.5).stroke }}
            >
              {selectedPct}% Mastery
            </span>
          </div>
        </div>

        <p className="dag-detail-desc">{selectedNode.description}</p>

        {/* Foundational Gap Alert Banner if prerequisite support needed */}
        {deficitAnalysis && (
          <div className="dag-deficit-banner">
            <div className="dag-deficit-text">
              <span>🎯 <strong>Foundational Concept Focus:</strong> Mastery in <em>{selectedNode.title}</em> builds directly upon <strong>{deficitAnalysis.rootDeficitName}</strong> ({Math.round((activeMasteryMap[deficitAnalysis.rootDeficitId] ?? 0.5) * 100)}%). Strengthening this prerequisite first will make this topic much easier!</span>
            </div>
            <button
              type="button"
              className="dag-deficit-action-btn"
              onClick={() => handleNodeClick(deficitAnalysis.rootDeficitId)}
            >
              Practice Foundational Skill →
            </button>
          </div>
        )}
      </div>

      {/* FULL-SCREEN EXPAND MODAL */}
      {isModalOpen && (
        <div className="dag-modal-overlay" onClick={() => setIsModalOpen(false)}>
          <div
            className="dag-modal-container"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <div className="dag-modal-header">
              <div>
                <h2 className="dag-modal-title">
                  <span>🧠</span> Veritas Cognitive Skill Map — Grade 3–7 Knowledge Graph
                </h2>
                <p className="dag-modal-sub">
                  Full prerequisite dependency topology and live student mastery flow
                </p>
              </div>

              <div className="dag-modal-header-actions">
                <div className="dag-decay-controls" title="Project retention using the Ebbinghaus forgetting curve">
                  <span className="dag-decay-label">Forgetting Curve:</span>
                  {[
                    { days: 0, label: 'Today (Live)' },
                    { days: 7, label: '+7d' },
                    { days: 14, label: '+14d' },
                    { days: 30, label: '+30d' },
                  ].map((horizon) => (
                    <button
                      key={horizon.days}
                      type="button"
                      className={`dag-decay-btn ${decayDays === horizon.days ? 'dag-decay-btn--active' : ''}`}
                      onClick={() => setDecayDays(horizon.days)}
                    >
                      {horizon.label}
                    </button>
                  ))}
                </div>

                <button
                  type="button"
                  className="dag-modal-close-btn"
                  onClick={() => setIsModalOpen(false)}
                  title="Close Map (Esc)"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="dag-modal-body">
              {renderSVGGraph(true)}

              <div className="dag-detail-card dag-detail-card--modal">
                <div className="dag-detail-header">
                  <div className="dag-detail-title-group">
                    <span
                      className="dag-detail-badge"
                      style={{
                        background: getNodeColor(activeMasteryMap[selectedNode.id] ?? 0.5).fill,
                        color: getNodeColor(activeMasteryMap[selectedNode.id] ?? 0.5).stroke,
                        border: `1px solid ${getNodeColor(activeMasteryMap[selectedNode.id] ?? 0.5).stroke}`,
                      }}
                    >
                      {selectedNode.id} · {selectedNode.cluster}
                    </span>
                    <h3 className="dag-detail-name">{selectedNode.title}</h3>
                  </div>

                  <div className="dag-detail-metrics">
                    <span
                      className="dag-detail-pct"
                      style={{ color: getNodeColor(activeMasteryMap[selectedNode.id] ?? 0.5).stroke }}
                    >
                      {selectedPct}% Mastery
                    </span>
                  </div>
                </div>

                <p className="dag-detail-desc">{selectedNode.description}</p>

                {deficitAnalysis && (
                  <div className="dag-deficit-banner">
                    <div className="dag-deficit-text">
                      <span>🎯 <strong>Foundational Concept Focus:</strong> Mastery in <em>{selectedNode.title}</em> builds directly upon <strong>{deficitAnalysis.rootDeficitName}</strong> ({Math.round((activeMasteryMap[deficitAnalysis.rootDeficitId] ?? 0.5) * 100)}%). Strengthening this prerequisite first will make this topic much easier!</span>
                    </div>
                    <button
                      type="button"
                      className="dag-deficit-action-btn"
                      onClick={() => handleNodeClick(deficitAnalysis.rootDeficitId)}
                    >
                      Practice Foundational Skill →
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
