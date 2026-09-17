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

-- ── Skills (Common Core taxonomy) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS skills (
    id              TEXT PRIMARY KEY,   -- e.g. '4.NF.B.3'
    name            TEXT NOT NULL,
    cc_standard     TEXT,
    sequence_order  INTEGER NOT NULL DEFAULT 0
);

-- Seed skills (matches bkt/parameters.json)
INSERT INTO skills (id, name, cc_standard, sequence_order) VALUES
    ('3.OA.A.1', 'Understanding multiplication', '3.OA.A.1', 1),
    ('3.OA.A.2', 'Understanding division', '3.OA.A.2', 2),
    ('3.OA.D.8', 'Solving two-step word problems', '3.OA.D.8', 3),
    ('4.NF.A.1', 'Equivalent fractions', '4.NF.A.1', 4),
    ('4.NF.B.3', 'Adding and subtracting fractions', '4.NF.B.3', 5),
    ('4.NF.B.4', 'Multiplying fractions by whole numbers', '4.NF.B.4', 6),
    ('5.NF.B.7', 'Dividing fractions', '5.NF.B.7', 7),
    ('6.EE.A.2', 'Writing and reading algebraic expressions', '6.EE.A.2', 8),
    ('6.EE.B.7', 'Solving one-step equations', '6.EE.B.7', 9),
    ('7.EE.B.4', 'Solving multi-step equations', '7.EE.B.4', 10)
ON CONFLICT (id) DO NOTHING;

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

-- ── RLS Policies (Row Level Security for anon key safety) ───────────────────
ALTER TABLE students ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_skill_mastery ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_events ENABLE ROW LEVEL SECURITY;

-- Allow backend (service role) to bypass RLS — no policy needed
-- Allow frontend (anon key) read-only on problems and skills
CREATE POLICY "Public read problems" ON problems FOR SELECT USING (true);
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
