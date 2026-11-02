"""
Automated Test Suite for Enterprise District, School, and Classroom API Endpoints:
1. Validates authentication enforcement (HTTP 401) on /enterprise/districts
2. Validates admin access and district querying
3. Validates audit log retrieval and query scoping
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

os.environ.setdefault("VERITAS_TEST_MODE", "true")
os.environ.setdefault("VERITAS_MOCK_LLM", "true")

from fastapi.testclient import TestClient
from main import app
from auth import create_session_token

client = TestClient(app)

def test_enterprise_auth_enforcement():
    print("🛡️ [ENTERPRISE ROUTE TEST 1] Verifying Unauthenticated Access Blocked...")
    # 1. Unauthenticated request to list districts
    res = client.get("/enterprise/districts")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"
    print("   ✓ /enterprise/districts correctly rejects unauthenticated calls (HTTP 401)")

    # 2. Unauthenticated request to create district
    res2 = client.post("/enterprise/districts", json={"name": "Metropolitan School District"})
    assert res2.status_code == 401, f"Expected 401, got {res2.status_code}: {res2.text}"
    print("   ✓ POST /enterprise/districts correctly rejects unauthenticated calls (HTTP 401)")

    # 3. Unauthenticated request to view audit logs
    res3 = client.get("/enterprise/audit-logs")
    assert res3.status_code == 401, f"Expected 401, got {res3.status_code}: {res3.text}"
    print("   ✓ /enterprise/audit-logs correctly rejects unauthenticated calls (HTTP 401)")

    # 4. Parent role and demo tokens must be rejected with 403 Forbidden
    parent_token = create_session_token(
        student_id="parent-user-001",
        session_id="parent-session-001",
        student_name="Standard Parent",
        role="parent",
    )
    res_parent = client.get("/enterprise/districts", headers={"Authorization": f"Bearer {parent_token}"})
    assert res_parent.status_code == 403, f"Expected 403 for parent role, got {res_parent.status_code}"
    res_demo = client.get("/enterprise/districts", headers={"Authorization": "Bearer demo_parent"})
    assert res_demo.status_code == 403, f"Expected 403 for demo_parent, got {res_demo.status_code}"
    print("   ✓ /enterprise/districts correctly rejects parent role and demo_parent token (HTTP 403)")
    print("✅ [ENTERPRISE ROUTE TEST 1 PASSED]\n")


def test_enterprise_admin_endpoints():
    print("🔑 [ENTERPRISE ROUTE TEST 2] Verifying Authenticated Admin Access...")
    # Generate admin token
    admin_token = create_session_token(
        student_id="admin-user-001",
        session_id="admin-session-001",
        student_name="District Admin",
        role="district_admin",
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. List districts
    res = client.get("/enterprise/districts", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "districts" in data
    print(f"   ✓ Successfully queried /enterprise/districts (found {len(data['districts'])} districts)")

    # 2. Query audit logs
    res_logs = client.get("/enterprise/audit-logs?limit=10", headers=headers)
    assert res_logs.status_code == 200, f"Expected 200, got {res_logs.status_code}: {res_logs.text}"
    logs_data = res_logs.json()
    assert "audit_logs" in logs_data
    print(f"   ✓ Successfully queried /enterprise/audit-logs (found {len(logs_data['audit_logs'])} records)")
    print("✅ [ENTERPRISE ROUTE TEST 2 PASSED]\n")


if __name__ == "__main__":
    print("\n" + "=" * 76)
    print("   VERITAS ENTERPRISE API ROUTER VALIDATION SUITE")
    print("=" * 76 + "\n")
    test_enterprise_auth_enforcement()
    test_enterprise_admin_endpoints()
    print("=" * 76)
    print("🎉 ALL ENTERPRISE API ROUTER TESTS PASSED!")
    print("=" * 76 + "\n")
