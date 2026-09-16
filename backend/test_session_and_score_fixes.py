"""
Unit & Integration tests for:
1. Score protection on next-problem (score does NOT jump when mark_previous_correct=False).
2. Title sanitization (no 'GSM8K:' prefix returned in current_problem).
3. Session resumption for authenticated students on /session/start.
4. /session/reset resetting mastery back to 0.30 and starting problem 1 fresh.
5. Parent linking accepting student UUID code as well as email.
"""
import uuid
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_score_inflation_prevention_and_title_clean():
    print("\n[TEST 1] Testing Next-Problem Score Inflation Prevention...")
    test_student_id = str(uuid.uuid4())
    start_resp = client.post("/session/start", json={
        "student_name": "TestStudent",
        "student_id": test_student_id,
        "student_email": f"test_{test_student_id[:8]}@example.com",
    })
    assert start_resp.status_code == 200, f"Failed to start session: {start_resp.text}"
    session_data = start_resp.json()
    session_id = session_data["session_id"]
    initial_mastery = dict(session_data["mastery_state"])
    current_problem = session_data["current_problem"]

    # Verify title is cleaned of GSM8K:
    assert not current_problem.get("title", "").startswith("GSM8K:"), f"Title still contains GSM8K: prefix: {current_problem.get('title')}"
    print("   [OK] Title cleaned:", current_problem.get("title"))

    # Advance to next problem WITHOUT solving (mark_previous_correct=False, the default)
    next_resp = client.post("/session/next-problem", json={
        "session_id": session_id,
        "mark_previous_correct": False,
    })
    assert next_resp.status_code == 200, f"Next problem failed: {next_resp.text}"
    next_data = next_resp.json()
    new_mastery = next_data["mastery_state"]

    # Check that mastery did NOT inflate!
    for skill, prob in initial_mastery.items():
        assert new_mastery[skill] == prob, f"Mastery inflated unearned! Skill {skill} changed from {prob} to {new_mastery[skill]}"
    print("   [OK] Score did not jump: mastery stayed at baseline (30%) on next problem without answer.")

    # Now verify advancing WITH solved problem credits mastery
    next_solved_resp = client.post("/session/next-problem", json={
        "session_id": session_id,
        "mark_previous_correct": True,
    })
    assert next_solved_resp.status_code == 200
    solved_mastery = next_solved_resp.json()["mastery_state"]
    # At least one skill increased
    increased = any(solved_mastery[s] > initial_mastery[s] for s in initial_mastery)
    assert increased, "Solved problem should have increased mastery for the credited skill"
    print("   [OK] Solved problem correctly credited mastery.")


def test_session_resumption_and_reset():
    print("\n[TEST 2] Testing Session Resumption and Reset...")
    test_student_id = str(uuid.uuid4())
    # Start first session
    s1 = client.post("/session/start", json={
        "student_name": "ResumingStudent",
        "student_id": test_student_id,
        "student_email": f"resume_{test_student_id[:8]}@example.com",
    }).json()
    s1_id = s1["session_id"]
    s1_problem_id = s1["current_problem"]["id"]

    # Start again with same student_id — should resume s1!
    s2 = client.post("/session/start", json={
        "student_name": "ResumingStudent",
        "student_id": test_student_id,
        "student_email": f"resume_{test_student_id[:8]}@example.com",
    }).json()
    assert s2["session_id"] == s1_id, "Session was not resumed!"
    assert s2["current_problem"]["id"] == s1_problem_id, "Current problem did not match resumed session!"
    assert s2.get("resumed") is True, "Resumed flag was not True"
    print("   [OK] Session resumption succeeded (retained session ID & problem).")

    # Now call /session/reset
    reset_resp = client.post("/session/reset", json={
        "student_id": test_student_id,
        "session_id": s1_id,
    })
    assert reset_resp.status_code == 200, f"Reset failed: {reset_resp.text}"
    reset_data = reset_resp.json()
    assert reset_data["session_id"] != s1_id, "Reset should yield a new session ID"
    assert reset_data.get("resumed") is False
    # Mastery should be reset back to baseline priors across all skills
    from bkt.tracker import initialize_mastery
    expected_priors = initialize_mastery()
    assert reset_data["mastery_state"] == expected_priors, f"Mastery not reset to priors: {reset_data['mastery_state']}"
    print("   [OK] Session reset succeeded (cleared state & reset mastery to baseline priors).")


def test_parent_linking_with_student_code():
    print("\n[TEST 3] Testing Parent Linking via Student Code (UUID)...")
    test_student_id = str(uuid.uuid4())
    test_parent_id = "99999999-8888-7777-6666-555555555555"

    # Create student via session start
    client.post("/session/start", json={
        "student_name": "LinkedAlex",
        "student_id": test_student_id,
        "student_email": f"alex_{test_student_id[:8]}@example.com",
    })

    # Link child using child's student UUID code instead of email
    link_resp = client.post(
        "/parent/add-child",
        json={
            "parent_id": test_parent_id,
            "child_email": test_student_id,  # Passing UUID into the input field!
            "child_name": "LinkedAlex",
        },
        headers={
            "Authorization": "Bearer demo_parent_99999999-8888-7777-6666-555555555555",
            "X-Parent-Id": test_parent_id,
        }
    )
    assert link_resp.status_code == 200, f"Failed to link child via UUID: {link_resp.text}"
    link_data = link_resp.json()
    assert link_data["child"]["student_id"] == test_student_id, "Linked student ID does not match!"
    print("   [OK] Parent linking by Student Code (UUID) succeeded.")


if __name__ == "__main__":
    test_score_inflation_prevention_and_title_clean()
    test_session_resumption_and_reset()
    test_parent_linking_with_student_code()
    print("\n=== ALL NEW TESTS PASSED! ===")
