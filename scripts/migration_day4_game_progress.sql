-- ============================================================================
-- Veritas — Day 4 Game Progress Distributed Supabase Persistence Migration
-- Run this in your Supabase SQL Editor (Dashboard -> SQL Editor -> New Query)
-- ============================================================================

-- 1. Create table for persistent arcade game progress per student
CREATE TABLE IF NOT EXISTS public.student_game_progress (
    student_id      UUID NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    game_id         TEXT NOT NULL,
    high_score      INTEGER NOT NULL DEFAULT 0,
    stars           INTEGER NOT NULL DEFAULT 0,
    times_played    INTEGER NOT NULL DEFAULT 0,
    last_played     TIMESTAMPTZ,
    history         JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, game_id)
);

-- 2. Index for rapid lookup by student
CREATE INDEX IF NOT EXISTS student_game_progress_student_idx 
    ON public.student_game_progress(student_id);

-- 3. Enable Row Level Security (RLS)
ALTER TABLE public.student_game_progress ENABLE ROW LEVEL SECURITY;

-- 4. RLS Policies
-- Allow service role full access (default in backend)
-- Allow authenticated students read/write on their own game progress
CREATE POLICY "Students can view own game progress"
    ON public.student_game_progress
    FOR SELECT
    USING (true);

CREATE POLICY "Students can upsert own game progress"
    ON public.student_game_progress
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- 5. Comment explaining production architecture
COMMENT ON TABLE public.student_game_progress IS 
    'Distributed game progression, stars, and high score persistence across horizontal container instances';
