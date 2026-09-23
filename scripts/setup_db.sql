-- AI Socratic Tutor — Supabase Schema
-- Run this in your Supabase SQL Editor

-- Enable pgvector extension for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Students ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS students (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);
-- Migration: Allow distinct students with identical first names (drops legacy unique constraint)
ALTER TABLE students DROP CONSTRAINT IF EXISTS students_name_key;

-- ── Sessions ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY,
    student_id  UUID REFERENCES students(id) ON DELETE CASCADE,
    student_name TEXT,
    started_at  TIMESTAMPTZ DEFAULT now(),
    ended_at    TIMESTAMPTZ
);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS state JSONB DEFAULT '{}'::jsonb;

-- ── Skills (Common Core taxonomy + BKT Parameters & Cognitive DAG) ─────────
CREATE TABLE IF NOT EXISTS skills (
    id                      TEXT PRIMARY KEY,   -- e.g. '4.NF.B.3'
    name                    TEXT NOT NULL,
    cc_standard             TEXT,
    sequence_order          INTEGER NOT NULL DEFAULT 0,
    prior                   FLOAT NOT NULL DEFAULT 0.3,
    learn                   FLOAT NOT NULL DEFAULT 0.15,
    guess                   FLOAT NOT NULL DEFAULT 0.2,
    slip                    FLOAT NOT NULL DEFAULT 0.1,
    prerequisites           TEXT[] NOT NULL DEFAULT '{}',
    retention_half_life_days FLOAT NOT NULL DEFAULT 21.0,
    decay_rate              FLOAT NOT NULL DEFAULT 0.0385,
    calibrated              BOOLEAN NOT NULL DEFAULT FALSE,
    calibration_source      TEXT
);

-- Seed skills with authoritative cognitive parameters and prerequisite DAG edges
INSERT INTO skills (
    id, name, cc_standard, sequence_order, prior, learn, guess, slip,
    prerequisites, retention_half_life_days, decay_rate, calibrated, calibration_source
) VALUES
    ('3.OA.A.1', 'Understanding multiplication', '3.OA.A.1', 1, 0.30, 0.15, 0.20, 0.10,
     ARRAY[]::TEXT[], 21.0, 0.0330, FALSE, 'Corbett & Anderson Baseline'),
    ('3.OA.A.2', 'Understanding division', '3.OA.A.2', 2, 0.25, 0.15, 0.20, 0.10,
     ARRAY['3.OA.A.1']::TEXT[], 18.0, 0.0385, FALSE, 'Corbett & Anderson Baseline'),
    ('3.OA.D.8', 'Solving two-step word problems', '3.OA.D.8', 3, 0.20, 0.12, 0.18, 0.12,
     ARRAY['3.OA.A.1', '3.OA.A.2']::TEXT[], 14.0, 0.0495, FALSE, 'Corbett & Anderson Baseline'),
    ('4.NF.A.1', 'Equivalent fractions', '4.NF.A.1', 4, 0.40, 0.08, 0.22, 0.14,
     ARRAY['3.OA.A.1', '3.OA.A.2']::TEXT[], 16.0, 0.0433, TRUE, 'ASSISTments 2009-2010 (Equivalent Fractions)'),
    ('4.NF.B.3', 'Adding and subtracting fractions', '4.NF.B.3', 5, 0.40, 0.20, 0.18, 0.14,
     ARRAY['4.NF.A.1']::TEXT[], 16.0, 0.0433, TRUE, 'ASSISTments 2009-2010 (Addition and Subtraction Fractions)'),
    ('4.NF.B.4', 'Multiplying fractions by whole numbers', '4.NF.B.4', 6, 0.40, 0.12, 0.26, 0.14,
     ARRAY['3.OA.A.1', '4.NF.A.1']::TEXT[], 18.0, 0.0385, TRUE, 'ASSISTments 2009-2010 (Multiplication Fractions)'),
    ('5.NF.B.7', 'Dividing fractions', '5.NF.B.7', 7, 0.40, 0.24, 0.26, 0.14,
     ARRAY['4.NF.B.4', '3.OA.A.2']::TEXT[], 15.0, 0.0462, TRUE, 'ASSISTments 2009-2010 (Division Fractions)'),
    ('6.EE.A.2', 'Writing and reading algebraic expressions', '6.EE.A.2', 8, 0.20, 0.13, 0.20, 0.10,
     ARRAY['3.OA.D.8']::TEXT[], 20.0, 0.0347, FALSE, 'Corbett & Anderson Baseline'),
    ('6.EE.B.7', 'Solving one-step equations', '6.EE.B.7', 9, 0.35, 0.08, 0.26, 0.14,
     ARRAY['6.EE.A.2']::TEXT[], 18.0, 0.0385, TRUE, 'ASSISTments 2009-2010 (Equation Solving Two or Fewer Steps)'),
    ('7.EE.B.4', 'Solving multi-step equations', '7.EE.B.4', 10, 0.40, 0.24, 0.26, 0.14,
     ARRAY['6.EE.B.7', '4.NF.B.3']::TEXT[], 14.0, 0.0495, TRUE, 'ASSISTments 2009-2010 (Equation Solving More Than Two Steps)')
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    cc_standard = EXCLUDED.cc_standard,
    sequence_order = EXCLUDED.sequence_order,
    prior = EXCLUDED.prior,
    learn = EXCLUDED.learn,
    guess = EXCLUDED.guess,
    slip = EXCLUDED.slip,
    prerequisites = EXCLUDED.prerequisites,
    retention_half_life_days = EXCLUDED.retention_half_life_days,
    decay_rate = EXCLUDED.decay_rate,
    calibrated = EXCLUDED.calibrated,
    calibration_source = EXCLUDED.calibration_source;

-- ── Problems (with pgvector embedding) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS problems (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    text            TEXT NOT NULL,
    skill_id        TEXT REFERENCES skills(id),
    difficulty      INTEGER CHECK (difficulty BETWEEN 1 AND 5) DEFAULT 1,
    expected_steps  JSONB DEFAULT '[]',
    source          TEXT DEFAULT 'hand_curated',  -- 'hand_curated' | 'gsm8k' | 'openstax'
    embedding       vector(768),                   -- Gemini gemini-embedding-001 dimension (768-dim)
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Vector similarity search index
CREATE INDEX IF NOT EXISTS problems_embedding_idx
    ON problems USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- ── Student Mastery (BKT state per student per skill) ───────────────────────
CREATE TABLE IF NOT EXISTS student_skill_mastery (
    student_id   UUID REFERENCES students(id) ON DELETE CASCADE,
    skill_id     TEXT REFERENCES skills(id) ON DELETE CASCADE,
    mastery_prob FLOAT NOT NULL DEFAULT 0.3,
    updated_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (student_id, skill_id)
);

-- ── Session Events (audit log + mastery data) ────────────────────────────────
CREATE TABLE IF NOT EXISTS session_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES sessions(id),
    student_id      UUID REFERENCES students(id),
    problem_id      UUID REFERENCES problems(id),
    attempt_text    TEXT,
    is_correct      BOOLEAN,
    agent_response  TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Performance indices for student history queries, alerts, and state rehydration
CREATE INDEX IF NOT EXISTS session_events_student_created_idx
    ON session_events(student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS session_events_session_id_idx
    ON session_events(session_id);

-- ── Arcade Progress ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS student_game_progress (
    student_id   UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    game_id      TEXT NOT NULL,
    high_score   INTEGER NOT NULL DEFAULT 0,
    stars        INTEGER NOT NULL DEFAULT 0,
    times_played INTEGER NOT NULL DEFAULT 0,
    last_played  TIMESTAMPTZ,
    history      JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, game_id)
);

-- ── RLS Policies (Row Level Security for anon key safety) ───────────────────
ALTER TABLE students ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_skill_mastery ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_game_progress ENABLE ROW LEVEL SECURITY;

-- Allow backend (service role) to bypass RLS — no policy needed
-- Problem rows contain expected solution steps and must remain server-only.
-- The backend exposes a safe student projection after authorization.
CREATE POLICY "Public read skills" ON skills FOR SELECT USING (true);

-- ── Similarity Search Function (used by content agent) ───────────────────────
CREATE OR REPLACE FUNCTION match_problems(
    query_embedding vector(768),
    skill_filter    TEXT DEFAULT NULL,
    match_count     INT DEFAULT 5
)
RETURNS TABLE (
    id          UUID,
    title       TEXT,
    text        TEXT,
    skill_id    TEXT,
    difficulty  INTEGER,
    expected_steps JSONB,
    similarity  FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id, p.title, p.text, p.skill_id, p.difficulty, p.expected_steps,
        1 - (p.embedding <=> query_embedding) AS similarity
    FROM problems p
    WHERE (skill_filter IS NULL OR skill_filter = '' OR p.skill_id = skill_filter)
    ORDER BY p.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
