import { useState } from 'react'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer, Tooltip
} from 'recharts'
import { getSkillMeta, getMasteryTierInfo, getBarGradient } from '../lib/skillsData'
import './MasteryRadar.css'

interface SkillMastery {
  skill_id: string
  name: string
  mastery_prob: number
}

interface Props {
  skills: SkillMastery[]
  /** If false, only the radar chart is shown without the card breakdown below */
  showBars?: boolean
}

type FilterTier = 'all' | 'needs-work' | 'developing' | 'proficient' | 'mastered'

export default function MasteryRadar({ skills = [], showBars = true }: Props) {
  const [filter, setFilter] = useState<FilterTier>('all')
  const safeSkills = skills || []

  // Enrich skills with metadata
  const enriched = safeSkills.map(s => {
    const rawVal = Number(s.mastery_prob)
    const probVal = isNaN(rawVal) ? 0 : rawVal
    return {
      ...s,
      meta: getSkillMeta(s.skill_id),
      tierInfo: getMasteryTierInfo(probVal),
      pct: Math.round(probVal * 100),
    }
  })

  // Radar data
  const radarData = enriched.map(s => ({
    subject: s.meta.shortTitle,
    mastery: s.pct,
    fullMark: 100,
    fullTitle: s.meta.title,
  }))

  // Tier counts for filter badges
  const counts = {
    all: enriched.length,
    'needs-work': enriched.filter(s => s.tierInfo.tier === 'needs-work').length,
    developing: enriched.filter(s => s.tierInfo.tier === 'developing').length,
    proficient: enriched.filter(s => s.tierInfo.tier === 'proficient').length,
    mastered: enriched.filter(s => s.tierInfo.tier === 'mastered').length,
  }

  const filtered = filter === 'all' ? enriched : enriched.filter(s => s.tierInfo.tier === filter)

  const FILTER_TABS: { key: FilterTier; label: string; color: string }[] = [
    { key: 'all', label: 'All', color: 'var(--text-secondary)' },
    { key: 'needs-work', label: 'Needs Practice', color: '#F87171' },
    { key: 'developing', label: 'Developing', color: '#F5A623' },
    { key: 'proficient', label: 'Proficient', color: '#A78BFA' },
    { key: 'mastered', label: 'Mastered', color: '#34D399' },
  ]

  return (
    <div className="mastery-container">
      {/* Header */}
      <div className="mastery-header-bar">
        <h3 className="mastery-title">Skill Progress</h3>
        <span className="badge badge-emerald mastery-live-badge">Live</span>
      </div>

      {/* Radar Chart */}
      <ResponsiveContainer width="100%" height={240}>
        <RadarChart data={radarData} margin={{ top: 8, right: 24, bottom: 8, left: 24 }}>
          <PolarGrid stroke="rgba(255,255,255,0.07)" />
          <PolarAngleAxis
            dataKey="subject"
            tick={{ fill: 'var(--text-secondary)', fontSize: 10.5, fontFamily: 'Inter, system-ui' }}
          />
          <Radar
            name="Progress"
            dataKey="mastery"
            stroke="var(--violet)"
            fill="var(--violet)"
            fillOpacity={0.22}
            strokeWidth={2}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: '10px',
              color: 'var(--text-primary)',
              fontSize: '0.82rem',
              padding: '8px 12px',
            }}
            formatter={(value: any, _name: any, payload: any) => [
              `${value ?? 0}% — ${payload?.payload?.fullTitle ?? ''}`,
              'Mastery',
            ] as [string, string]}
          />
        </RadarChart>
      </ResponsiveContainer>

      {/* Skill Breakdown Cards */}
      {showBars && enriched.length > 0 && (
        <>
          {/* Filter Pills */}
          <div className="mastery-filter-row">
            {FILTER_TABS.filter(t => t.key === 'all' || counts[t.key] > 0).map(tab => (
              <button
                key={tab.key}
                className={`mastery-filter-pill ${filter === tab.key ? 'mastery-filter-pill--active' : ''}`}
                style={{ '--pill-color': tab.color } as React.CSSProperties}
                onClick={() => setFilter(tab.key)}
              >
                {tab.label}
                {counts[tab.key] > 0 && (
                  <span className="mastery-filter-count">{counts[tab.key]}</span>
                )}
              </button>
            ))}
          </div>

          {/* Skill Cards */}
          <div className="mastery-skill-list">
            {filtered.map(s => (
              <div
                key={s.skill_id}
                className="mastery-skill-card"
                style={{ borderColor: s.tierInfo.borderColor }}
              >
                {/* Card Top: Domain + Tier Badge */}
                <div className="mastery-skill-top">
                  <div className="mastery-skill-badges">
                    <span
                      className="mastery-domain-badge"
                      style={{ color: s.meta.domainColor, background: `${s.meta.domainColor}18`, border: `1px solid ${s.meta.domainColor}35` }}
                    >
                      {s.meta.grade} · {s.meta.domainAbbr}
                    </span>
                    <span className="mastery-std-code">{s.meta.shortTitle || s.meta.title}</span>
                  </div>
                  <span
                    className="mastery-tier-badge"
                    style={{
                      color: s.tierInfo.color,
                      background: s.tierInfo.bgColor,
                      border: `1px solid ${s.tierInfo.borderColor}`,
                    }}
                  >
                    <span className="mastery-tier-icon">{s.tierInfo.icon}</span>
                    {s.tierInfo.label}
                  </span>
                </div>

                {/* Title + Percent */}
                <div className="mastery-skill-main">
                  <span className="mastery-skill-title">{s.meta.title}</span>
                  <span className="mastery-skill-pct" style={{ color: s.tierInfo.color }}>{s.pct}%</span>
                </div>

                {/* Progress Bar */}
                <div className="mastery-bar-track">
                  <div
                    className="mastery-bar-fill"
                    style={{
                      width: `${Math.min(Math.max(s.pct, 0), 100)}%`,
                      background: getBarGradient(s.tierInfo.tier),
                    }}
                  />
                </div>

                {/* Description */}
                <p className="mastery-skill-desc">{s.meta.description}</p>
              </div>
            ))}

            {filtered.length === 0 && (
              <p className="mastery-empty-state">No skills in this category yet.</p>
            )}
          </div>
        </>
      )}

      {showBars && enriched.length === 0 && (
        <p className="mastery-empty-state">No skill data recorded yet. Start solving problems!</p>
      )}
    </div>
  )
}
