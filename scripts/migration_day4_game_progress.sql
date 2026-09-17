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
-- Clean up any legacy or overly permissive policies
DROP POLICY IF EXISTS "Students can view own game progress" ON public.student_game_progress;
DROP POLICY IF EXISTS "Students can upsert own game progress" ON public.student_game_progress;
DROP POLICY IF EXISTS "Students can insert own game progress" ON public.student_game_progress;
DROP POLICY IF EXISTS "Students can update own game progress" ON public.student_game_progress;
DROP POLICY IF EXISTS "Students can delete own game progress" ON public.student_game_progress;

-- Strict student-level & parent-level access:
-- Authenticated students can view only their own game progress.
-- Authenticated parents can view their linked children's game progress.
CREATE POLICY "Students can view own game progress"
    ON public.student_game_progress
    FOR SELECT
    TO authenticated
    USING (
        student_id = auth.uid() OR
        EXISTS (
            SELECT 1 FROM public.children c
            WHERE c.student_id = public.student_game_progress.student_id
              AND c.parent_id = auth.uid()
        )
    );

-- Authenticated students can insert only their own game progress
CREATE POLICY "Students can insert own game progress"
    ON public.student_game_progress
    FOR INSERT
    TO authenticated
    WITH CHECK (student_id = auth.uid());

-- Authenticated students can update only their own game progress
CREATE POLICY "Students can update own game progress"
    ON public.student_game_progress
    FOR UPDATE
    TO authenticated
    USING (student_id = auth.uid())
    WITH CHECK (student_id = auth.uid());

-- Authenticated students can delete only their own game progress
CREATE POLICY "Students can delete own game progress"
    ON public.student_game_progress
    FOR DELETE
    TO authenticated
    USING (student_id = auth.uid());

-- 5. Comment explaining production architecture & service role
-- Note: The FastAPI backend accesses this table using SUPABASE_SERVICE_ROLE_KEY which bypasses RLS cleanly.
COMMENT ON TABLE public.student_game_progress IS 
    'Distributed game progression, stars, and high score persistence across horizontal container instances with strict student/parent RLS';

