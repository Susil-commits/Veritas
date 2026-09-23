-- ── Migration Day 6: Cognitive DAG & BKT Hyperparameters in PostgreSQL ──────
-- Migrates BKT cognitive parameters and DAG prerequisite edges from static JSON
-- into the authoritative PostgreSQL `skills` table.

-- 1. Extend `skills` table schema with BKT hyperparameters and DAG topology
ALTER TABLE skills ADD COLUMN IF NOT EXISTS prior FLOAT DEFAULT 0.3;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS learn FLOAT DEFAULT 0.15;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS guess FLOAT DEFAULT 0.2;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS slip FLOAT DEFAULT 0.1;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS prerequisites TEXT[] DEFAULT '{}';
ALTER TABLE skills ADD COLUMN IF NOT EXISTS retention_half_life_days FLOAT DEFAULT 21.0;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS decay_rate FLOAT DEFAULT 0.0385;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS calibrated BOOLEAN DEFAULT FALSE;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS calibration_source TEXT;

-- 2. Upsert Common Core skills with full cognitive parameters & DAG prerequisites
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

COMMENT ON TABLE skills IS
    'Authoritative Common Core skill taxonomy, BKT cognitive parameters, and prerequisite DAG edges.';
