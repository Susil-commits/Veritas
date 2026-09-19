-- Veritas Day 5 security hardening.
-- Run after setup_db.sql and earlier migrations.

-- Remove the legacy policy that exposed expected_steps through the anon key.
DROP POLICY IF EXISTS "Public read problems" ON public.problems;

-- Keep problem content server-only. The backend uses the service role key.
ALTER TABLE public.problems ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.problems IS
    'Server-only curriculum content; expected_steps and answer metadata must not be exposed to browser clients.';