"""
FastAPI Enterprise Management Router — Veritas.
Provides B2B APIs for:
1. School Districts (/enterprise/districts)
2. Schools (/enterprise/schools)
3. Classrooms & Cohorts (/enterprise/classrooms)
4. Student Enrollments (/enterprise/classrooms/{classroom_id}/enroll)
5. SOC-2 / FERPA Audit Logs (/enterprise/audit-logs)
"""
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth import verify_parent_caller
from db.supabase_client import get_supabase
from routes.common import db_exec

logger = logging.getLogger("veritas-backend.enterprise")

router = APIRouter(prefix="/enterprise", tags=["Enterprise & School Districts"])


# ── Pydantic Models ──────────────────────────────────────────────────────────

class DistrictCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    state: Optional[str] = Field(None, max_length=50)
    clever_id: Optional[str] = None
    classlink_id: Optional[str] = None


class SchoolCreateRequest(BaseModel):
    district_id: str
    name: str = Field(..., min_length=2, max_length=120)
    nces_id: Optional[str] = None


class ClassroomCreateRequest(BaseModel):
    school_id: str
    name: str = Field(..., min_length=2, max_length=100)
    grade_level: int = Field(..., ge=1, le=12)
    teacher_id: str
    academic_year: Optional[str] = "2026-2027"


class EnrollmentRequest(BaseModel):
    student_id: str


# ── Enterprise Endpoints ─────────────────────────────────────────────────────

@router.post("/districts")
async def create_district(
    req: DistrictCreateRequest,
    auth: dict = Depends(verify_parent_caller),
):
    """Provisions a new School District / Educational Organization."""
    supabase = get_supabase()
    payload = {
        "name": req.name.strip(),
        "state": req.state.strip() if req.state else None,
        "clever_id": req.clever_id,
        "classlink_id": req.classlink_id,
    }
    res = await db_exec(supabase.table("districts").insert(payload))
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create district.")
    return {"status": "ok", "district": res.data[0]}


@router.get("/districts")
async def list_districts(
    auth: dict = Depends(verify_parent_caller),
):
    """Lists districts accessible to the authenticated administrator."""
    supabase = get_supabase()
    res = await db_exec(supabase.table("districts").select("*").order("name"))
    return {"status": "ok", "districts": res.data or []}


@router.post("/schools")
async def create_school(
    req: SchoolCreateRequest,
    auth: dict = Depends(verify_parent_caller),
):
    """Provisions a new school scoped to a district."""
    supabase = get_supabase()
    payload = {
        "district_id": req.district_id,
        "name": req.name.strip(),
        "nces_id": req.nces_id,
    }
    res = await db_exec(supabase.table("schools").insert(payload))
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create school.")
    return {"status": "ok", "school": res.data[0]}


@router.get("/districts/{district_id}/schools")
async def list_district_schools(
    district_id: str,
    auth: dict = Depends(verify_parent_caller),
):
    """Lists schools within a designated district."""
    supabase = get_supabase()
    res = await db_exec(supabase.table("schools").select("*").eq("district_id", district_id).order("name"))
    return {"status": "ok", "schools": res.data or []}


@router.post("/classrooms")
async def create_classroom(
    req: ClassroomCreateRequest,
    auth: dict = Depends(verify_parent_caller),
):
    """Provisions a classroom cohort assigned to a specific teacher."""
    supabase = get_supabase()
    payload = {
        "school_id": req.school_id,
        "name": req.name.strip(),
        "grade_level": req.grade_level,
        "teacher_id": req.teacher_id,
        "academic_year": req.academic_year,
    }
    res = await db_exec(supabase.table("classrooms").insert(payload))
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create classroom.")
    return {"status": "ok", "classroom": res.data[0]}


@router.get("/schools/{school_id}/classrooms")
async def list_school_classrooms(
    school_id: str,
    auth: dict = Depends(verify_parent_caller),
):
    """Lists classrooms within a designated school."""
    supabase = get_supabase()
    res = await db_exec(supabase.table("classrooms").select("*").eq("school_id", school_id).order("name"))
    return {"status": "ok", "classrooms": res.data or []}


@router.post("/classrooms/{classroom_id}/enroll")
async def enroll_student_in_classroom(
    classroom_id: str,
    req: EnrollmentRequest,
    auth: dict = Depends(verify_parent_caller),
):
    """Enrolls a student in a classroom cohort."""
    supabase = get_supabase()
    payload = {
        "classroom_id": classroom_id,
        "student_id": req.student_id,
    }
    res = await db_exec(supabase.table("classroom_enrollments").upsert(payload))
    return {"status": "ok", "enrollment": res.data[0] if res.data else {}}


@router.get("/classrooms/{classroom_id}/students")
async def list_classroom_students(
    classroom_id: str,
    auth: dict = Depends(verify_parent_caller),
):
    """Lists students enrolled in a classroom cohort."""
    supabase = get_supabase()
    res = await db_exec(
        supabase.table("classroom_enrollments")
        .select("student_id, enrolled_at, students(id, name, email)")
        .eq("classroom_id", classroom_id)
    )
    return {"status": "ok", "enrollments": res.data or []}


@router.get("/audit-logs")
async def get_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    auth: dict = Depends(verify_parent_caller),
):
    """Returns immutable enterprise security and compliance audit logs."""
    supabase = get_supabase()
    res = await db_exec(
        supabase.table("enterprise_audit_logs")
        .select("*")
        .order("event_timestamp", desc=True)
        .limit(limit)
    )
    return {"status": "ok", "audit_logs": res.data or []}
