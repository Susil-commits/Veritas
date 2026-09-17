import { useState } from 'react'
import './SocraticPreview.css'

interface Scenario {
  id: string
  title: string
  topic: string
  problem: string
  studentWork: string
  misconception: string
  tutorThought: string
  socraticQuestion: string
  whyItWorks: string
}

const SCENARIOS: Scenario[] = [
  {
    id: 'fractions',
    title: 'Adding Fractions',
    topic: 'Fractions · Visual Slice Models',
    problem: 'Solve:  1/3 + 1/6',
    studentWork: '1/3 + 1/6 = 2/9  (I added 1+1 and 3+6)',
    misconception: 'Added denominators directly instead of finding a common denominator.',
    tutorThought: 'Spotted denominator addition misconception. Don\'t give 1/2. Guide student to visualize slice sizes.',
    socraticQuestion: '“Imagine you eat 1 piece of a 3-slice pizza, and 1 piece of a 6-slice pizza. Are those slices the same size? What size slices would make them easy to compare?”',
    whyItWorks: 'Instead of memorizing LCD formulas, the student visualizes equal parts and understands the reasoning.',
  },
  {
    id: 'algebra',
    title: 'Negative Coefficients',
    topic: 'Equations · Negative Coefficients',
    problem: 'Solve for x:  -3x = 12',
    studentWork: '-3x = 12  →  x = 12 / 3  →  x = 4',
    misconception: 'Dropped the negative sign when dividing both sides.',
    tutorThought: 'Sign error on division. Prompt student to check their sign rule.',
    socraticQuestion: '“You divided both sides by 3, but the original number with x is -3. When you divide a positive number by a negative number, what sign does your answer have?”',
    whyItWorks: 'The student catches their own sign flip, building confidence for test day.',
  },
  {
    id: 'geometry',
    title: 'Perimeter vs. Area',
    topic: 'Geometry · Perimeter vs. Area',
    problem: 'A garden is 6m long and 4m wide. Find the fence needed to surround it.',
    studentWork: '6 × 4 = 24 meters of fence',
    misconception: 'Calculated area instead of perimeter.',
    tutorThought: 'Student multiplied dimensions (Area) instead of walking around the boundary (Perimeter).',
    socraticQuestion: '“If you walk all the way around the garden to put up the fence, how many sides do you walk along? Let’s trace each side together!”',
    whyItWorks: 'Grounds abstract geometry formulas in physical, intuitive real-world movement.',
  },
]

export default function SocraticPreview() {
  const [activeId, setActiveId] = useState<string>('fractions')
  const activeScenario = SCENARIOS.find(s => s.id === activeId) || SCENARIOS[0]

  return (
    <div className="socratic-preview-card card">
      <div className="preview-header">
        <div className="preview-header-left">
          <span className="badge badge-amber">Interactive Demo</span>
          <h2>See How The Socratic Method Works</h2>
          <p className="preview-sub">
            Notice the difference: A standard app just spits out the answer. Veritas diagnoses where thinking went off track and asks the exact guiding question to help you discover the rule yourself.
          </p>
        </div>
      </div>

      {/* Scenario Selector Tabs */}
      <div className="scenario-tabs" role="tablist">
        {SCENARIOS.map(s => (
          <button
            key={s.id}
            role="tab"
            aria-selected={activeId === s.id}
            className={`scenario-tab ${activeId === s.id ? 'active' : ''}`}
            onClick={() => setActiveId(s.id)}
          >
            <span className="tab-topic">{s.topic}</span>
            <span className="tab-title">{s.title}</span>
          </button>
        ))}
      </div>

      {/* Interactive Demonstration Body */}
      <div className="preview-body">
        {/* Left Column: Problem & Student Work */}
        <div className="preview-col student-col">
          <div className="col-label">
            <span>Problem & Student Attempt</span>
          </div>

          <div className="problem-box">
            <span className="box-tag">Problem</span>
            <p className="problem-text">{activeScenario.problem}</p>
          </div>

          <div className="student-attempt-box">
            <span className="box-tag box-tag--attempt">Student's Handwritten Work</span>
            <p className="attempt-text font-handwriting">{activeScenario.studentWork}</p>
            <div className="attempt-diagnosis">
              <span className="diagnosis-pill">Tricky Spot Detected</span>
              <p>{activeScenario.misconception}</p>
            </div>
          </div>
        </div>

        {/* Middle Connector */}
        <div className="preview-connector" aria-hidden="true">
          <span className="connector-arrow">→</span>
        </div>

        {/* Right Column: AI Tutor Reasoning & Guiding Question */}
        <div className="preview-col tutor-col">
          <div className="col-label">
            <span>Tutor Guidance & Question</span>
          </div>

          <div className="tutor-thought-box">
            <span className="thought-tag">Behind the Scenes · Tutor Status</span>
            <p className="thought-text">{activeScenario.tutorThought}</p>
          </div>

          <div className="socratic-prompt-box">
            <span className="prompt-tag">What The Tutor Asks Next</span>
            <p className="prompt-text">{activeScenario.socraticQuestion}</p>
          </div>

          <div className="why-box">
            <p><strong>The Takeaway:</strong> {activeScenario.whyItWorks}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
