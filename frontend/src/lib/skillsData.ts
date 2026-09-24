/**
 * Centralized Skill Metadata Registry for Veritas
 * Maps Common Core standard IDs to human-readable information shown to students and parents.
 */

export type MasteryTier = 'needs-work' | 'developing' | 'proficient' | 'mastered'

export interface SkillMeta {
  /** Raw Common Core standard ID */
  id: string
  /** Full human-readable topic title */
  title: string
  /** Short title used on radar chart axes */
  shortTitle: string
  /** Grade level string e.g. "Grade 3" */
  grade: string
  /** Domain e.g. "Operations & Algebraic Thinking" */
  domain: string
  /** Short domain abbreviation for badges e.g. "OA" */
  domainAbbr: string
  /** One-sentence educational summary */
  description: string
  /** CSS color token variable for this domain */
  domainColor: string
}

const SKILLS_REGISTRY: Record<string, SkillMeta> = {
  '3.OA.A.1': {
    id: '3.OA.A.1',
    title: 'Understanding Multiplication',
    shortTitle: 'Multiply',
    grade: 'Grade 3',
    domain: 'Operations & Algebraic Thinking',
    domainAbbr: 'OA',
    description: 'Interpreting products of whole numbers as equal groups, arrays, and repeated addition.',
    domainColor: 'var(--violet)',
  },
  '3.OA.A.2': {
    id: '3.OA.A.2',
    title: 'Understanding Division',
    shortTitle: 'Divide',
    grade: 'Grade 3',
    domain: 'Operations & Algebraic Thinking',
    domainAbbr: 'OA',
    description: 'Interpreting whole-number quotients by partitioning a set equally or finding missing factors.',
    domainColor: 'var(--violet)',
  },
  '3.OA.D.8': {
    id: '3.OA.D.8',
    title: 'Two-Step Word Problems',
    shortTitle: '2-Step WP',
    grade: 'Grade 3',
    domain: 'Operations & Algebraic Thinking',
    domainAbbr: 'OA',
    description: 'Solving two-step word problems using all four operations, and assessing reasonableness of answers.',
    domainColor: 'var(--violet)',
  },
  '4.NF.A.1': {
    id: '4.NF.A.1',
    title: 'Equivalent Fractions',
    shortTitle: 'Equiv. Frac',
    grade: 'Grade 4',
    domain: 'Number & Fractions',
    domainAbbr: 'NF',
    description: 'Explaining why fractions are equivalent using visual models and generating equivalent forms.',
    domainColor: 'var(--amber)',
  },
  '4.NF.B.3': {
    id: '4.NF.B.3',
    title: 'Adding & Subtracting Fractions',
    shortTitle: 'Add Frac',
    grade: 'Grade 4',
    domain: 'Number & Fractions',
    domainAbbr: 'NF',
    description: 'Adding and subtracting fractions and mixed numbers with the same denominator.',
    domainColor: 'var(--amber)',
  },
  '4.NF.B.4': {
    id: '4.NF.B.4',
    title: 'Fractions × Whole Numbers',
    shortTitle: 'Frac × Whole',
    grade: 'Grade 4',
    domain: 'Number & Fractions',
    domainAbbr: 'NF',
    description: 'Multiplying a fraction by a whole number using visual models and repeated addition.',
    domainColor: 'var(--amber)',
  },
  '5.NF.B.7': {
    id: '5.NF.B.7',
    title: 'Dividing Fractions',
    shortTitle: 'Div. Frac',
    grade: 'Grade 5',
    domain: 'Number & Fractions',
    domainAbbr: 'NF',
    description: 'Dividing unit fractions by whole numbers and whole numbers by unit fractions.',
    domainColor: 'var(--amber)',
  },
  '6.EE.A.2': {
    id: '6.EE.A.2',
    title: 'Algebraic Expressions',
    shortTitle: 'Expressions',
    grade: 'Grade 6',
    domain: 'Expressions & Equations',
    domainAbbr: 'EE',
    description: 'Writing, reading, and evaluating algebraic expressions with variables and real-world contexts.',
    domainColor: 'var(--emerald)',
  },
  '6.EE.B.7': {
    id: '6.EE.B.7',
    title: 'Solving One-Step Equations',
    shortTitle: '1-Step Eq',
    grade: 'Grade 6',
    domain: 'Expressions & Equations',
    domainAbbr: 'EE',
    description: 'Solving real-world problems by writing and solving one-step equations of the form px = q.',
    domainColor: 'var(--emerald)',
  },
  '7.EE.B.4': {
    id: '7.EE.B.4',
    title: 'Multi-Step Equations',
    shortTitle: 'Multi-Step Eq',
    grade: 'Grade 7',
    domain: 'Expressions & Equations',
    domainAbbr: 'EE',
    description: 'Solving multi-step real-life problems with positive and negative rational numbers in equations.',
    domainColor: 'var(--emerald)',
  },
}

/** Resolve skill metadata from a standard ID, falling back gracefully */
export function getSkillMeta(skillId: string): SkillMeta {
  if (SKILLS_REGISTRY[skillId]) return SKILLS_REGISTRY[skillId]
  // Graceful fallback for unknown skills
  return {
    id: skillId,
    title: skillId.replace(/_/g, ' '),
    shortTitle: skillId,
    grade: 'Unknown',
    domain: 'Math',
    domainAbbr: '?',
    description: 'Practice this math skill to improve your mastery.',
    domainColor: 'var(--text-muted)',
  }
}

/** Classify a mastery probability (0–1) into a named tier */
export function getMasteryTier(prob: number): MasteryTier {
  if (prob >= 0.85) return 'mastered'
  if (prob >= 0.70) return 'proficient'
  if (prob >= 0.40) return 'developing'
  return 'needs-work'
}

export interface MasteryTierInfo {
  tier: MasteryTier
  label: string
  color: string
  bgColor: string
  borderColor: string
  icon: string
}

export function getMasteryTierInfo(prob: number): MasteryTierInfo {
  const tier = getMasteryTier(prob)
  switch (tier) {
    case 'mastered':
      return {
        tier,
        label: 'Mastered',
        color: '#34D399',
        bgColor: 'rgba(52, 211, 153, 0.12)',
        borderColor: 'rgba(52, 211, 153, 0.35)',
        icon: '⭐',
      }
    case 'proficient':
      return {
        tier,
        label: 'Proficient',
        color: '#A78BFA',
        bgColor: 'rgba(167, 139, 250, 0.12)',
        borderColor: 'rgba(167, 139, 250, 0.35)',
        icon: '✓',
      }
    case 'developing':
      return {
        tier,
        label: 'Developing',
        color: '#F5A623',
        bgColor: 'rgba(245, 166, 35, 0.12)',
        borderColor: 'rgba(245, 166, 35, 0.35)',
        icon: '↗',
      }
    case 'needs-work':
    default:
      return {
        tier,
        label: 'Needs Practice',
        color: '#F87171',
        bgColor: 'rgba(248, 113, 113, 0.12)',
        borderColor: 'rgba(248, 113, 113, 0.35)',
        icon: '!',
      }
  }
}

export function getBarGradient(tier: MasteryTier): string {
  switch (tier) {
    case 'mastered':   return 'linear-gradient(90deg, #10B981, #34D399)'
    case 'proficient': return 'linear-gradient(90deg, #7C5DFA, #A78BFA)'
    case 'developing': return 'linear-gradient(90deg, #D97706, #F5A623)'
    case 'needs-work':
    default:           return 'linear-gradient(90deg, #DC2626, #F87171)'
  }
}

export type DAGCluster = 'foundations' | 'fractions' | 'equations'

export interface SkillDAGNode extends SkillMeta {
  prerequisites: string[]
  prior: number
  learn: number
  guess: number
  slip: number
  retentionHalfLifeDays: number
  decayRate: number
  cluster: DAGCluster
  level: number // 1: Foundations, 2: Fractions, 3: Equations
  colIndex: number // Layout positioning for SVG DAG
}

export const COGNITIVE_DAG_NODES: Record<string, SkillDAGNode> = {
  '3.OA.A.1': {
    ...SKILLS_REGISTRY['3.OA.A.1'],
    prerequisites: [],
    prior: 0.30,
    learn: 0.15,
    guess: 0.20,
    slip: 0.10,
    retentionHalfLifeDays: 21.0,
    decayRate: 0.0330,
    cluster: 'foundations',
    level: 1,
    colIndex: 0,
  },
  '3.OA.A.2': {
    ...SKILLS_REGISTRY['3.OA.A.2'],
    prerequisites: ['3.OA.A.1'],
    prior: 0.25,
    learn: 0.15,
    guess: 0.20,
    slip: 0.10,
    retentionHalfLifeDays: 18.0,
    decayRate: 0.0385,
    cluster: 'foundations',
    level: 1,
    colIndex: 1,
  },
  '3.OA.D.8': {
    ...SKILLS_REGISTRY['3.OA.D.8'],
    prerequisites: ['3.OA.A.1', '3.OA.A.2'],
    prior: 0.20,
    learn: 0.12,
    guess: 0.18,
    slip: 0.12,
    retentionHalfLifeDays: 14.0,
    decayRate: 0.0495,
    cluster: 'foundations',
    level: 1,
    colIndex: 2,
  },
  '4.NF.A.1': {
    ...SKILLS_REGISTRY['4.NF.A.1'],
    prerequisites: ['3.OA.A.1', '3.OA.A.2'],
    prior: 0.40,
    learn: 0.08,
    guess: 0.22,
    slip: 0.14,
    retentionHalfLifeDays: 16.0,
    decayRate: 0.0433,
    cluster: 'fractions',
    level: 2,
    colIndex: 0,
  },
  '4.NF.B.3': {
    ...SKILLS_REGISTRY['4.NF.B.3'],
    prerequisites: ['4.NF.A.1'],
    prior: 0.40,
    learn: 0.20,
    guess: 0.18,
    slip: 0.14,
    retentionHalfLifeDays: 16.0,
    decayRate: 0.0433,
    cluster: 'fractions',
    level: 2,
    colIndex: 1,
  },
  '4.NF.B.4': {
    ...SKILLS_REGISTRY['4.NF.B.4'],
    prerequisites: ['3.OA.A.1', '4.NF.A.1'],
    prior: 0.40,
    learn: 0.12,
    guess: 0.26,
    slip: 0.14,
    retentionHalfLifeDays: 18.0,
    decayRate: 0.0385,
    cluster: 'fractions',
    level: 2,
    colIndex: 2,
  },
  '5.NF.B.7': {
    ...SKILLS_REGISTRY['5.NF.B.7'],
    prerequisites: ['4.NF.B.4', '3.OA.A.2'],
    prior: 0.40,
    learn: 0.24,
    guess: 0.26,
    slip: 0.14,
    retentionHalfLifeDays: 15.0,
    decayRate: 0.0462,
    cluster: 'fractions',
    level: 2,
    colIndex: 3,
  },
  '6.EE.A.2': {
    ...SKILLS_REGISTRY['6.EE.A.2'],
    prerequisites: ['3.OA.D.8'],
    prior: 0.20,
    learn: 0.13,
    guess: 0.20,
    slip: 0.10,
    retentionHalfLifeDays: 20.0,
    decayRate: 0.0347,
    cluster: 'equations',
    level: 3,
    colIndex: 0,
  },
  '6.EE.B.7': {
    ...SKILLS_REGISTRY['6.EE.B.7'],
    prerequisites: ['6.EE.A.2'],
    prior: 0.35,
    learn: 0.08,
    guess: 0.26,
    slip: 0.14,
    retentionHalfLifeDays: 18.0,
    decayRate: 0.0385,
    cluster: 'equations',
    level: 3,
    colIndex: 1,
  },
  '7.EE.B.4': {
    ...SKILLS_REGISTRY['7.EE.B.4'],
    prerequisites: ['6.EE.B.7', '4.NF.B.3'],
    prior: 0.40,
    learn: 0.24,
    guess: 0.26,
    slip: 0.14,
    retentionHalfLifeDays: 14.0,
    decayRate: 0.0495,
    cluster: 'equations',
    level: 3,
    colIndex: 2,
  },
}

/** Get list of prerequisites for a given skill */
export function getSkillPrerequisites(skillId: string): string[] {
  return COGNITIVE_DAG_NODES[skillId]?.prerequisites || []
}

/**
 * Ebbinghaus Exponential Memory Forgetting Decay:
 * Predicts mastery probability after `elapsedDays` without practice:
 * P(L_{t+dt}) = P_prior + (P(L_t) - P_prior) * exp(-lambda * dt)
 */
export function applyTimeDecay(
  currentMastery: number,
  elapsedDays: number,
  skillId: string,
): number {
  if (elapsedDays <= 0) return currentMastery
  const node = COGNITIVE_DAG_NODES[skillId]
  if (!node) return currentMastery
  const pPrior = node.prior
  const decayRate = node.decayRate

  if (currentMastery <= pPrior) return currentMastery
  const decayed = pPrior + (currentMastery - pPrior) * Math.exp(-decayRate * elapsedDays)
  return Math.round(Math.min(Math.max(decayed, pPrior), 1.0) * 100) / 100
}

/**
 * Recursive root-deficit diagnosis:
 * Traverses upstream prerequisite DAG from a failing skill (mastery < threshold)
 * to locate the deepest unmastered ancestor.
 */
export function diagnoseRootSkillDeficit(
  masteryMap: Record<string, number>,
  failingSkillId: string,
  threshold: number = 0.65,
): string | null {
  const visited = new Set<string>()
  const queue = [...getSkillPrerequisites(failingSkillId)]
  const unmasteredRoots: { id: string; score: number }[] = []

  while (queue.length > 0) {
    const curr = queue.shift()!
    if (visited.has(curr)) continue
    visited.add(curr)

    const currMastery = masteryMap[curr] ?? (COGNITIVE_DAG_NODES[curr]?.prior ?? 0.3)
    if (currMastery < threshold) {
      unmasteredRoots.push({ id: curr, score: currMastery })
      queue.push(...getSkillPrerequisites(curr))
    }
  }

  if (unmasteredRoots.length > 0) {
    unmasteredRoots.sort((a, b) => a.score - b.score)
    return unmasteredRoots[0].id
  }
  return null
}

export interface DeficitDiagnosis {
  targetSkillId: string
  rootDeficitId: string
  rootDeficitName: string
  deficitPath: string[]
}

export function getDetailedDeficitDiagnosis(
  masteryMap: Record<string, number>,
  failingSkillId: string,
  threshold: number = 0.70,
): DeficitDiagnosis | null {
  const rootId = diagnoseRootSkillDeficit(masteryMap, failingSkillId, threshold)
  if (!rootId || rootId === failingSkillId) return null
  const rootMeta = getSkillMeta(rootId)
  return {
    targetSkillId: failingSkillId,
    rootDeficitId: rootId,
    rootDeficitName: rootMeta.title || rootId,
    deficitPath: [rootId, failingSkillId],
  }
}

export const COGNITIVE_DAG_LIST: SkillDAGNode[] = Object.values(COGNITIVE_DAG_NODES)

export { SKILLS_REGISTRY }


