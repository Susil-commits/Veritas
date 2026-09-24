import React, { useState, useMemo } from 'react';
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

export const CognitiveDAGVisualizer: React.FC<CognitiveDAGVisualizerProps> = ({
  skills = [],
  activeSkillId: propActiveSkillId,
  onSelectSkill,
  showDecayControls = true,
}) => {
  const [selectedSkillId, setSelectedSkillId] = useState<string>(
    propActiveSkillId || '7.EE.B.4'
  );
  const [decayDays, setDecayDays] = useState<number>(0);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Sync prop changes if provided
  const currentActiveId = propActiveSkillId || selectedSkillId;

  // Build live mastery map from passed-in skills (or fallback to prior defaults)
  const baseMasteryMap = useMemo(() => {
    const map: Record<string, number> = {};
    COGNITIVE_DAG_LIST.forEach((n) => {
      const match = skills.find((s) => s.skill_id === n.id);
      map[n.id] = match ? match.mastery_prob : n.prior;
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
    if (prob >= 0.85) return { stroke: '#10B981', fill: 'rgba(16, 185, 129, 0.22)', label: 'Mastered' };
    if (prob >= 0.70) return { stroke: '#3B82F6', fill: 'rgba(59, 130, 246, 0.22)', label: 'Proficient' };
    if (prob >= 0.50) return { stroke: '#F59E0B', fill: 'rgba(245, 158, 11, 0.22)', label: 'Practicing' };
    return { stroke: '#EF4444', fill: 'rgba(239, 68, 68, 0.22)', label: 'Deficit Risk' };
  };

  // Compile list of edges
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

  return (
    <div className="dag-container">
      {/* Header with Title & Ebbinghaus Time-Decay horizon controls */}
      <div className="dag-header">
        <div className="dag-header-title">
          <h3>
            <span>🧠</span> Cognitive Knowledge Graph (DAG)
          </h3>
          <p className="dag-header-sub">
            Common Core prerequisite relationships &amp; Bayesian deficit flow
          </p>
        </div>

        {showDecayControls && (
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
        )}
      </div>

      {/* SVG DAG Visualizer */}
      <div className="dag-svg-wrapper">
        <svg
          className="dag-svg"
          viewBox="0 0 800 400"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <marker
              id="dag-arrow"
              viewBox="0 0 10 10"
              refX="18"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="rgba(255, 255, 255, 0.35)" />
            </marker>
            <marker
              id="dag-arrow-active"
              viewBox="0 0 10 10"
              refX="18"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#818CF8" />
            </marker>
            <marker
              id="dag-arrow-deficit"
              viewBox="0 0 10 10"
              refX="18"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#F87171" />
            </marker>
          </defs>

          {/* Background Level Guides */}
          <g className="dag-level-guides" opacity="0.4">
            <line x1="40" y1="70" x2="760" y2="70" stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
            <text x="45" y="65" fill="var(--text-muted)" fontSize="10" fontWeight="600">
              GRADE 3 · FOUNDATIONS
            </text>

            <line x1="40" y1="195" x2="760" y2="195" stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
            <text x="45" y="190" fill="var(--text-muted)" fontSize="10" fontWeight="600">
              GRADE 4-5 · FRACTIONS &amp; DECIMALS
            </text>

            <line x1="40" y1="320" x2="760" y2="320" stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
            <text x="45" y="315" fill="var(--text-muted)" fontSize="10" fontWeight="600">
              GRADE 6-7 · ALGEBRAIC EQUATIONS
            </text>
          </g>

          {/* Directed Edges */}
          <g className="dag-edges">
            {edges.map((edge, idx) => {
              const p = NODE_COORDINATES[edge.from];
              const t = NODE_COORDINATES[edge.to];
              if (!p || !t) return null;

              // Cubic Bezier curve
              const midY = (p.y + t.y) / 2;
              const d = `M ${p.x} ${p.y + 26} C ${p.x} ${midY}, ${t.x} ${midY}, ${t.x} ${t.y - 26}`;

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

          {/* Nodes */}
          <g className="dag-nodes">
            {COGNITIVE_DAG_LIST.map((node: SkillDAGNode) => {
              const coords = NODE_COORDINATES[node.id];
              if (!coords) return null;

              const prob = activeMasteryMap[node.id] ?? node.prior;
              const pct = Math.round(prob * 100);
              const { stroke, fill } = getNodeColor(prob);
              const isSelected = currentActiveId === node.id;
              const isDeficit = deficitAnalysis?.rootDeficitId === node.id;

              return (
                <g
                  key={node.id}
                  className={`dag-node ${isSelected ? 'dag-node--selected' : ''}`}
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
                      r="33"
                      fill="none"
                      stroke="#EF4444"
                      strokeWidth="2"
                      strokeDasharray="4 2"
                      opacity="0.8"
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

                  {/* Main Node Circle */}
                  <circle
                    className="dag-node-circle"
                    r="25"
                    fill={fill}
                    stroke={isSelected ? '#FFFFFF' : stroke}
                    strokeWidth={isSelected ? '3.5' : '2'}
                  />

                  {/* CCSS Short Code */}
                  <text className="dag-node-text-code" y="-4">
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
                  <text className="dag-node-text-label" y="40">
                    {node.shortTitle}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>

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

        {/* Root Deficit Alert Banner if prerequisite gap detected */}
        {deficitAnalysis && (
          <div className="dag-deficit-banner">
            <div className="dag-deficit-text">
              <span>⚠️ <strong>Root Deficit Detected:</strong> Mastery in <em>{selectedNode.title}</em> is bottlenecked by unmet prerequisite <strong>{deficitAnalysis.rootDeficitName}</strong> ({Math.round((activeMasteryMap[deficitAnalysis.rootDeficitId] ?? 0.5) * 100)}%).</span>
            </div>
            <button
              type="button"
              className="dag-deficit-action-btn"
              onClick={() => handleNodeClick(deficitAnalysis.rootDeficitId)}
            >
              Jump to Root Prerequisite →
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
