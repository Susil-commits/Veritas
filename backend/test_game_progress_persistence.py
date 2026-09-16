"""
Tests for Veritas Math Arcade:
1. /games/progress returns 5-level hierarchy with requirements and lock/unlock states.
2. Multiplication mastery/completion unlocks Level 1 (Multiplier Matrix).
3. POST /games/score saves high score, stars, and times played.
4. Relogin / fresh request with the same student_id returns 100% persisted unlocks, scores, and stars without reset.
"""
import uuid
from fastapi.testclient import TestClient
from main import app, DEMO_STUDENT_ID

client = TestClient(app)


def test_game_hierarchy_structure():
    print("\n[TEST 1] Testing Game Hierarchy Structure...")
    resp = client.get(f"/games/progress?student_id={DEMO_STUDENT_ID}")
    assert resp.status_code == 200, f"Failed: {resp.text}"
    data = resp.json()

    assert "levels" in data, "levels key missing"
    assert len(data["levels"]) == 5, f"Expected 5 levels, got {len(data['levels'])}"
    assert data["levels"][0]["id"] == "multiplier_matrix"
    assert data["levels"][0]["level"] == 1
    assert data["levels"][0]["is_unlocked"] is True, "Demo student should have Level 1 unlocked"
    assert data["levels"][0]["skill_required"] == "3.OA.A.1"

    # Level 2 should have locked state if requirements not met
    assert data["levels"][1]["id"] == "division_dungeons"
    assert data["levels"][1]["level"] == 2
    assert "Complete Division part" in data["levels"][1]["unlock_requirement"]
    print("   [OK] 5-level hierarchy roadmap validated with proper skill requirements.")


def test_game_score_and_relogin_persistence():
    print("\n[TEST 2] Testing Game Score & Relogin Persistence...")
    test_student_id = str(uuid.uuid4())

    # Initial state for brand new student
    p1 = client.get(f"/games/progress?student_id={test_student_id}").json()
    assert p1["total_stars"] == 0
    assert p1["total_score"] == 0

    # Play Level 1 and record score: 850 points, 3 stars
    score_resp = client.post("/games/score", json={
        "student_id": test_student_id,
        "game_id": "multiplier_matrix",
        "score": 850,
        "stars": 3,
    })
    assert score_resp.status_code == 200
    p2 = score_resp.json()
    assert p2["total_score"] == 850
    assert p2["total_stars"] == 3

    lvl1 = next(l for l in p2["levels"] if l["id"] == "multiplier_matrix")
    assert lvl1["high_score"] == 850
    assert lvl1["stars"] == 3
    assert lvl1["times_played"] == 1

    # SIMULATE RELOGIN: Simulate opening a brand new browser tab / session and requesting progress again
    relogin_resp = client.get(f"/games/progress?student_id={test_student_id}")
    assert relogin_resp.status_code == 200
    p_relogin = relogin_resp.json()

    # Verify everything persisted without refresh
    assert p_relogin["total_score"] == 850, "Total score reset on relogin!"
    assert p_relogin["total_stars"] == 3, "Total stars reset on relogin!"
    lvl1_relogin = next(l for l in p_relogin["levels"] if l["id"] == "multiplier_matrix")
    assert lvl1_relogin["high_score"] == 850, "High score reset on relogin!"
    assert lvl1_relogin["stars"] == 3, "Stars reset on relogin!"
    assert lvl1_relogin["times_played"] == 1, "Times played reset on relogin!"
    print("   [OK] Relogin persistence verified: scores, stars, and history 100% retained across logins!")


def test_unlock_progression_on_problem_solve():
    print("\n[TEST 3] Testing Game Level Unlock on Curriculum Completion...")
    test_student_id = str(uuid.uuid4())

    # Start a session
    sess = client.post("/session/start", json={
        "student_name": "MultiplicationMaster",
        "student_id": test_student_id,
        "student_email": f"arcade_{test_student_id[:8]}@example.com",
    }).json()
    session_id = sess["session_id"]

    # Solve multiplication problem
    next_res = client.post("/session/next-problem", json={
        "session_id": session_id,
        "mark_previous_correct": True,
    })
    assert next_res.status_code == 200

    # Fetch game progress: Level 1 should be unlocked!
    p = client.get(f"/games/progress?student_id={test_student_id}").json()
    lvl1 = next(l for l in p["levels"] if l["id"] == "multiplier_matrix")
    assert lvl1["is_unlocked"] is True, "Level 1 (Multiplier Matrix) was not unlocked after solving multiplication!"
    assert lvl1["progress_percent"] == 100
    print("   [OK] Curriculum completion properly unlocked Level 1 Multiplier Matrix!")


if __name__ == "__main__":
    test_game_hierarchy_structure()
    test_game_score_and_relogin_persistence()
    test_unlock_progression_on_problem_solve()
    print("\n=== ALL GAME PROGRESSION & PERSISTENCE TESTS PASSED! ===")
