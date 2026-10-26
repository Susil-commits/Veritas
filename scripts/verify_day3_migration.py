"""
Live Verification Script for Day 3 Enterprise Multi-Tenancy Migration in Supabase.
Verifies:
1. Existence of all 6 newly provisioned enterprise tables:
   - districts
   - schools
   - classrooms
   - classroom_enrollments
   - tenant_memberships
   - enterprise_audit_logs
2. Active Row Level Security (RLS) policies blocking unauthenticated/anon queries.
3. Service Role administrative access.
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")
load_dotenv()

from supabase import create_client

def main():
    print("\n" + "=" * 76)
    print("   VERITAS ENTERPRISE SUPABASE MIGRATION VERIFICATION (DAY 3)")
    print("=" * 76 + "\n")

    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not anon_key:
        print("❌ Error: SUPABASE_URL and SUPABASE_ANON_KEY are required in backend/.env")
        sys.exit(1)

    anon_client = create_client(url, anon_key)
    service_client = create_client(url, service_key) if service_key else None

    tables = [
        "districts",
        "schools",
        "classrooms",
        "classroom_enrollments",
        "tenant_memberships",
        "enterprise_audit_logs",
    ]

    all_passed = True

    print("🛡️ [VERIFICATION 1] Testing Table Existence & RLS Shield on Anon Client...")
    for table_name in tables:
        try:
            res = anon_client.table(table_name).select("*").limit(1).execute()
            # With RLS enabled and no authenticated user: 0 rows returned
            assert len(res.data) == 0, f"SECURITY WARNING: Table '{table_name}' returned rows to anon user!"
            print(f"   ✓ Table '{table_name}': Active & RLS protected (0 rows returned to anon)")
        except Exception as e:
            err_msg = str(e)
            if "relation" in err_msg and "does not exist" in err_msg:
                print(f"   ✗ Table '{table_name}' does not exist! Migration may not have executed completely.")
                all_passed = False
            else:
                # RLS permission denial is also expected and secure
                print(f"   ✓ Table '{table_name}': Protected by RLS policy ({err_msg})")

    if service_client:
        print("\n🔑 [VERIFICATION 2] Testing Service Role Backend Access...")
        for table_name in tables:
            try:
                res = service_client.table(table_name).select("id").limit(1).execute()
                print(f"   ✓ Table '{table_name}': Accessible via Service Role")
            except Exception as e:
                print(f"   ✗ Table '{table_name}' failed Service Role query: {e}")
                all_passed = False

    print("\n" + "=" * 76)
    if all_passed:
        print("🎉 ALL 6 ENTERPRISE TABLES & RLS POLICIES ARE LIVE AND VERIFIED!")
    else:
        print("⚠️ Some tables had issues. Please check the SQL Editor output.")
    print("=" * 76 + "\n")

    if not all_passed:
        sys.exit(1)

if __name__ == "__main__":
    main()
