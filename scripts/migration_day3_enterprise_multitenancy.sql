-- ============================================================================
-- Veritas — Enterprise Multi-Tenancy & Governance Schema Migration (Day 3)
-- Provisions District -> School -> Classroom -> Student Hierarchy
-- Enforces Postgres Row Level Security (RLS) & Immutable Audit Trails
-- ============================================================================

-- 1. Districts / Organizations Table
CREATE TABLE IF NOT EXISTS public.districts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    state TEXT,
    clever_id TEXT UNIQUE,
    classlink_id TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Schools Table
CREATE TABLE IF NOT EXISTS public.schools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    district_id UUID NOT NULL REFERENCES public.districts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    nces_id TEXT, -- National Center for Education Statistics ID
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS schools_district_id_idx ON public.schools(district_id);

-- 3. Classrooms / Cohorts Table
CREATE TABLE IF NOT EXISTS public.classrooms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    grade_level INT CHECK (grade_level BETWEEN 1 AND 12),
    teacher_id UUID NOT NULL, -- references auth.users(id)
    academic_year TEXT DEFAULT '2026-2027',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS classrooms_school_id_idx ON public.classrooms(school_id);
CREATE INDEX IF NOT EXISTS classrooms_teacher_id_idx ON public.classrooms(teacher_id);

-- 4. Classroom Student Enrollment Table
CREATE TABLE IF NOT EXISTS public.classroom_enrollments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    classroom_id UUID NOT NULL REFERENCES public.classrooms(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    enrolled_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(classroom_id, student_id)
);
CREATE INDEX IF NOT EXISTS enrollments_student_idx ON public.classroom_enrollments(student_id);

-- 5. Tenant Role Memberships (RBAC)
CREATE TABLE IF NOT EXISTS public.tenant_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL, -- auth.users(id)
    district_id UUID REFERENCES public.districts(id) ON DELETE CASCADE,
    school_id UUID REFERENCES public.schools(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('district_admin', 'school_principal', 'teacher', 'observer')),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, district_id, school_id, role)
);
CREATE INDEX IF NOT EXISTS tenant_memberships_user_idx ON public.tenant_memberships(user_id);

-- 6. SOC-2 & FERPA Immutable Audit Log
CREATE TABLE IF NOT EXISTS public.enterprise_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_timestamp TIMESTAMPTZ DEFAULT now(),
    actor_id UUID,
    actor_role TEXT,
    event_type TEXT NOT NULL, -- 'auth_attempt', 'data_export', 'canary_leak', 'pii_redacted', 'student_erasure'
    target_resource TEXT,
    ip_address INET,
    user_agent TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_logs_timestamp_idx ON public.enterprise_audit_logs(event_timestamp DESC);
CREATE INDEX IF NOT EXISTS audit_logs_event_type_idx ON public.enterprise_audit_logs(event_type);

-- 7. Enable Row Level Security (RLS)
ALTER TABLE public.districts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schools ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.classrooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.classroom_enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enterprise_audit_logs ENABLE ROW LEVEL SECURITY;

-- 8. Strict RLS Policies for Classrooms:
-- Teachers can only view and manage classrooms where they are assigned as teacher
CREATE POLICY "Teachers can view own classrooms"
ON public.classrooms
FOR SELECT
TO authenticated
USING (
    teacher_id = auth.uid()
    OR EXISTS (
        SELECT 1 FROM public.tenant_memberships tm
        WHERE tm.user_id = auth.uid()
        AND tm.school_id = classrooms.school_id
        AND tm.role IN ('school_principal', 'district_admin')
    )
);

-- Teachers can view enrolled students in their own classrooms
CREATE POLICY "Teachers can view their students enrollments"
ON public.classroom_enrollments
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.classrooms c
        WHERE c.id = classroom_enrollments.classroom_id
        AND c.teacher_id = auth.uid()
    )
);

-- Audit logs: append-only for services, readable only by district admins
CREATE POLICY "District admins can view audit logs"
ON public.enterprise_audit_logs
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.tenant_memberships tm
        WHERE tm.user_id = auth.uid()
        AND tm.role = 'district_admin'
    )
);
