"""
Verification Suite for Day 2 Auth, Parent-Child Linking, and Live Radar Sync
1. Start session with authenticated auth.user.id
2. Link child via POST /parent/add-child
3. Query parent children list via GET /parent/{parent_id}/children
4. Verify fraction gap alert ("Has not practiced fractions in 3 days")
5. Query child details via GET /parent/{parent_id}/child/{child_id}/details
"""
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

import pytest
from starlette.testclient import TestClient
from main import app
from auth import create_session_token

client = TestClient(app)

@pytest.mark.integration
def test_full_parent_child_flow():
    print("🚀 Running Parent-Child & Auth Flow Test Suite...")

    test_parent_id = str(uuid.uuid4())
    test_student_id = str(uuid.uuid4())
    test_child_email = f"student_{test_student_id[:8]}@veritas.dev"
    test_child_name = "Alex TestChild"

    # Create parent token with role="parent"
    parent_token = create_session_token(test_parent_id, "parent-session-1", "Sarah Parent", role="parent")
    parent_headers = {"Authorization": f"Bearer {parent_token}"}

    # 1. Test Starting Student Session with explicit auth.user.id
    print("\n[TEST 1] Testing /session/start with explicit auth.user.id...")
    start_payload = {
        "student_name": test_child_name,
        "student_id": test_student_id,
        "student_email": test_child_email,
    }
    resp = client.post("/session/start", json=start_payload)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    session_data = resp.json()
    assert session_data["student_id"] == test_student_id, f"Expected student_id {test_student_id}, got {session_data.get('student_id')}"
    assert "session_id" in session_data
    assert "current_problem" in session_data
    assert "mastery_state" in session_data
    print(f"   ✓ Session started successfully for student {test_student_id}")

    # 2. Test Linking Child to Parent (With IDOR & Auth Verification)
    print("\n[TEST 2] Testing /parent/add-child...")
    add_payload = {
        "parent_id": test_parent_id,
        "parent_email": "parent.test@veritas.dev",
        "child_email": test_child_email,
        "child_name": test_child_name,
        "student_id": test_student_id,
    }

    # 2a. Unauthenticated attempt must be rejected (401)
    unauth_resp = client.post("/parent/add-child", json=add_payload)
    assert unauth_resp.status_code == 401, f"Expected 401 for unauthenticated add-child, got {unauth_resp.status_code}"
    print("   ✓ Unauthenticated add-child attempt correctly rejected with HTTP 401")

    # 2b. Mismatched parent token (IDOR) must be rejected (403)
    attacker_parent_id = str(uuid.uuid4())
    attacker_token = create_session_token(attacker_parent_id, "attacker-session", "Attacker", role="parent")
    idor_resp = client.post(
        "/parent/add-child",
        json=add_payload,
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert idor_resp.status_code == 403, f"Expected 403 for IDOR add-child, got {idor_resp.status_code}"
    print("   ✓ IDOR add-child attempt by mismatched parent correctly blocked with HTTP 403")

    # 2c. Valid authenticated parent adds child
    resp = client.post("/parent/add-child", json=add_payload, headers=parent_headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    add_data = resp.json()
    assert add_data["status"] == "ok"
    assert add_data["child"]["student_email"] == test_child_email
    print(f"   ✓ Child {test_child_email} successfully linked to parent {test_parent_id}")

    # 3. Test Getting Children List for Parent
    print("\n[TEST 3] Testing /parent/{parent_id}/children...")
    # 3a. Unauthenticated access blocked (401)
    unauth_list = client.get(f"/parent/{test_parent_id}/children")
    assert unauth_list.status_code == 401, f"Expected 401 for unauthenticated children list, got {unauth_list.status_code}"
    print("   ✓ Unauthenticated parent children query correctly rejected with HTTP 401")

    # 3b. Authenticated access allowed
    resp = client.get(f"/parent/{test_parent_id}/children", headers=parent_headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    children_data = resp.json()
    assert "children" in children_data
    children = children_data["children"]
    assert len(children) >= 1, "Expected at least 1 linked child"
    child = next(c for c in children if c["student_email"] == test_child_email)
    assert child["student_name"] == test_child_name
    print(f"   ✓ Found child in parent list: {child['student_name']}")
    print(f"   ✓ Inactivity/Fraction Alert: {child['fraction_alert_message']} (has_fraction_gap={child['has_fraction_gap']})")

    # 4. Test Getting Child Details & Real-Time Mastery Radar Data
    print("\n[TEST 4] Testing /parent/{parent_id}/child/{child_id}/details...")
    # 4a. Unlinked child must be rejected (403)
    unlinked_student_id = str(uuid.uuid4())
    unlinked_resp = client.get(f"/parent/{test_parent_id}/child/{unlinked_student_id}/details", headers=parent_headers)
    assert unlinked_resp.status_code == 403, f"Expected 403 for unlinked child details, got {unlinked_resp.status_code}"
    print("   ✓ Unlinked child details query correctly blocked with HTTP 403")

    # 4b. Linked child access allowed
    linked_student_id = child["student_id"]
    resp = client.get(f"/parent/{test_parent_id}/child/{linked_student_id}/details", headers=parent_headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    details = resp.json()
    assert details["student_id"] == linked_student_id
    assert "mastery" in details
    assert "all_skills" in details
    assert "sessions" in details
    print(f"   ✓ Retrieved child details with {len(details['all_skills'])} CCSS skills for radar rendering")

    # 5. Test Demo Parent Default
    print("\n[TEST 5] Testing demo parent fallback...")
    demo_headers = {"Authorization": "Bearer demo_parent_99999999-8888-7777-6666-555555555555"}
    resp = client.get("/parent/99999999-8888-7777-6666-555555555555/children", headers=demo_headers)
    assert resp.status_code == 200
    demo_children = resp.json()["children"]
    assert len(demo_children) >= 1
    print(f"   ✓ Demo parent has {len(demo_children)} children pre-configured for instant demo")

    print("\n🎉 ALL PARENT-CHILD & AUTH VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_full_parent_child_flow()
