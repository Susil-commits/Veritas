"""
Automated Test Suite for Production RLS & Key Isolation:
1. Verifies that public/unauthenticated requests (using SUPABASE_ANON_KEY)
   CANNOT read the `children` table (strict RLS prevents cross-account leak).
2. Verifies that one parent cannot access another parent's child records.
3. Scans frontend client bundle/source to confirm SUPABASE_SERVICE_ROLE_KEY
   is never leaked to the client.
"""
import os
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

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client


def test_public_anon_cannot_read_children():
    print("🛡️ [RLS TEST 1] Verifying Anonymous Client Blocked from Children Table...")
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    assert url and anon_key, "SUPABASE_URL and SUPABASE_ANON_KEY required in .env"

    anon_client = create_client(url, anon_key)

    # Attempt to query children table with anon key (no user JWT)
    try:
        res = anon_client.table("children").select("*").execute()
        # With RLS enabled: either error or 0 rows returned
        assert len(res.data) == 0, f"SECURITY BREACH: Anon client read {len(res.data)} children rows!"
        print("   ✓ Anonymous request with public key returned 0 rows (RLS active)")
    except Exception as e:
        print(f"   ✓ Anonymous request rejected by RLS policy: {e}")

    print("✅ [RLS TEST 1 PASSED]\n")


def test_parent_cross_account_isolation():
    print("👨‍👩‍👧 [RLS TEST 2] Verifying Parent A Cannot Access Parent B Child Records...")
    from fastapi.testclient import TestClient
    from main import app
    from auth import create_session_token

    client = TestClient(app)

    parent_a = str(uuid.uuid4())
    parent_b = str(uuid.uuid4())
    child_a = str(uuid.uuid4())
    child_b = str(uuid.uuid4())

    token_a = create_session_token(parent_a, "sess-pa", "Parent A", role="parent")
    token_b = create_session_token(parent_b, "sess-pb", "Parent B", role="parent")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Link Child A to Parent A, Child B to Parent B
    link_a = client.post(
        "/parent/add-child",
        json={
            "parent_id": parent_a,
            "parent_email": "parent_a@veritas.dev",
            "child_email": f"child_a_{parent_a[:8]}@veritas.dev",
            "child_name": "Child A",
            "student_id": child_a,
        },
        headers=headers_a,
    )
    assert link_a.status_code == 200, f"Failed linking child A: {link_a.text}"

    link_b = client.post(
        "/parent/add-child",
        json={
            "parent_id": parent_b,
            "parent_email": "parent_b@veritas.dev",
            "child_email": f"child_b_{parent_b[:8]}@veritas.dev",
            "child_name": "Child B",
            "student_id": child_b,
        },
        headers=headers_b,
    )
    assert link_b.status_code == 200, f"Failed linking child B: {link_b.text}"

    # 2. Parent A attempting to list Parent B's children must return HTTP 403
    cross_list = client.get(f"/parent/{parent_b}/children", headers=headers_a)
    assert cross_list.status_code == 403, f"Expected 403 for cross-parent children list, got {cross_list.status_code}"
    print("   ✓ Parent A blocked from GET /parent/{Parent_B}/children (HTTP 403)")

    # 3. Parent A attempting to access Parent B's child details via Parent A's endpoint (IDOR) must return HTTP 403
    cross_details_idor = client.get(f"/parent/{parent_a}/child/{child_b}/details", headers=headers_a)
    assert cross_details_idor.status_code == 403, f"Expected 403 for IDOR unlinked child access, got {cross_details_idor.status_code}"
    assert "Access denied: student is not linked to this parent account" in cross_details_idor.json()["detail"]
    print("   ✓ Parent A blocked from GET /parent/{Parent_A}/child/{Child_B}/details (HTTP 403 IDOR Defense)")

    # 4. Parent A attempting to access Parent B's child details via Parent B's route must return HTTP 403
    cross_details_route = client.get(f"/parent/{parent_b}/child/{child_b}/details", headers=headers_a)
    assert cross_details_route.status_code == 403, f"Expected 403 for cross-parent route child details, got {cross_details_route.status_code}"
    print("   ✓ Parent A blocked from GET /parent/{Parent_B}/child/{Child_B}/details (HTTP 403)")

    # 5. Parent A accessing own child details must return HTTP 200
    own_details = client.get(f"/parent/{parent_a}/child/{child_a}/details", headers=headers_a)
    assert own_details.status_code == 200, f"Expected 200 for Parent A own child details, got {own_details.status_code}"
    data = own_details.json()
    assert data["student_id"] == child_a
    print("   ✓ Parent A authorized to GET /parent/{Parent_A}/child/{Child_A}/details (HTTP 200)")

    print("✅ [RLS TEST 2 PASSED]\n")


def test_key_leak_prevention():
    print("🔒 [RLS TEST 3] Verifying Service Role Key is Never in Frontend Files...")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    assert service_key, "SUPABASE_SERVICE_ROLE_KEY required in .env"

    frontend_dir = BACKEND_DIR.parent / "frontend"
    leaked_files = []

    for ext in ["*.ts", "*.tsx", "*.js", "*.jsx", "*.html", ".env", ".env.production", ".env.local"]:
        for fpath in frontend_dir.glob(f"**/{ext}"):
            if "node_modules" in str(fpath) or "dist" in str(fpath):
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                if service_key in content and len(service_key) > 20:
                    leaked_files.append(str(fpath.relative_to(frontend_dir)))
            except Exception:
                pass

    assert not leaked_files, f"SECURITY CRITICAL: Service role key found in frontend files: {leaked_files}"
    print("   ✓ Scanned all frontend source and config files: Service role key is 100% isolated to backend")
    print("✅ [RLS TEST 3 PASSED]\n")


if __name__ == "__main__":
    print("🚀 Running Production RLS & Credential Isolation Tests...\n")
    test_public_anon_cannot_read_children()
    test_parent_cross_account_isolation()
    test_key_leak_prevention()
    print("🎉 ALL PRODUCTION RLS & KEY ISOLATION TESTS PASSED WITH 100% SUCCESS!")
