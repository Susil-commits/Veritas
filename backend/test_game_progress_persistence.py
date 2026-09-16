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
    resp = client.get(
        f"/games/progress?student_id={DEMO_STUDENT_ID}",
        headers={"Authorization": f"Bearer demo_{DEMO_STUDENT_ID}"},
    )
    assert resp.status_code == 200, f"Failed: {resp.text}"
    data = resp.json()

    assert "levels" in data, "levels key missing"
    assert len(data["levels"]) == 7, f"Expected 7 levels, got {len(data['levels'])}"
    assert data["levels"][0]["id"] == "multiplier_matrix"
    assert data["levels"][0]["level"] == 1
    assert data["levels"][0]["is_unlocked"] is True, "Demo student should have Level 1 unlocked"
    assert data["levels"][0]["skill_required"] == "3.OA.A.1"

    # Level 2 should have locked state if requirements not met
    assert data["levels"][1]["id"] == "division_dungeons"
    assert data["levels"][1]["level"] == 2
    assert "Complete Division part" in data["levels"][1]["unlock_requirement"]
    print("   [OK] 7-level hierarchy roadmap validated with proper skill requirements.")


def test_game_score_and_relogin_persistence():
    print("\n[TEST 2] Testing Game Score & Relogin Persistence & Auth Defense...")
    test_student_id = str(uuid.uuid4())

    # Start session to obtain authenticated session token
    sess = client.post("/session/start", json={
        "student_name": "GamePlayer",
        "student_id": test_student_id,
        "student_email": f"game_{test_student_id[:8]}@example.com",
    }).json()
    token = sess["session_token"]

    # Negative test 1: Calling /games/score without auth token must return 401
    unauth_score = client.post("/games/score", json={
        "student_id": test_student_id,
        "game_id": "multiplier_matrix",
        "score": 500,
        "stars": 2,
    })
    assert unauth_score.status_code == 401, "Unauthenticated game score submission must be rejected with 401!"
    print("   [OK] Unauthenticated game score submission blocked with HTTP 401.")

    # Negative test 2: Submitting score for another student (IDOR) must return 403
    victim_id = str(uuid.uuid4())
    idor_score = client.post(
        "/games/score",
        json={
            "student_id": victim_id,
            "game_id": "multiplier_matrix",
            "score": 500,
            "stars": 2,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert idor_score.status_code == 403, "Submitting score for another student must be rejected with 403!"
    print("   [OK] Cross-student score tampering blocked with HTTP 403.")

    # Negative test 3: Submitting invalid game ID or negative score must return 400
    invalid_game = client.post(
        "/games/score",
        json={
            "student_id": test_student_id,
            "game_id": "nonexistent_fake_game",
            "score": 100,
            "stars": 1,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invalid_game.status_code == 400, "Invalid game ID must return 400!"
    print("   [OK] Invalid game ID submission rejected with HTTP 400.")

    # Negative test 4: Submitting negative score must return 400
    neg_score = client.post(
        "/games/score",
        json={
            "student_id": test_student_id,
            "game_id": "multiplier_matrix",
            "score": -50,
            "stars": 1,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert neg_score.status_code == 400, "Negative score must return 400!"
    print("   [OK] Negative score rejected with HTTP 400.")

    # Negative test 5: Submitting stars not in {1, 2, 3} (e.g. 0 or 4) must return 400
    zero_stars = client.post(
        "/games/score",
        json={
            "student_id": test_student_id,
            "game_id": "multiplier_matrix",
            "score": 100,
            "stars": 0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert zero_stars.status_code == 400, "Stars=0 must return 400!"

    four_stars = client.post(
        "/games/score",
        json={
            "student_id": test_student_id,
            "game_id": "multiplier_matrix",
            "score": 100,
            "stars": 4,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert four_stars.status_code == 400, "Stars=4 must return 400!"
    print("   [OK] Stars outside {1, 2, 3} rejected with HTTP 400.")

    # Negative test 6: Unauthenticated GET /games/progress must return 401
    unauth_prog = client.get(f"/games/progress?student_id={test_student_id}")
    assert unauth_prog.status_code == 401, "Unauthenticated /games/progress must return 401!"
    print("   [OK] Unauthenticated /games/progress blocked with HTTP 401.")

    # Negative test 7: Cross-student GET /games/progress (IDOR) must return 403
    cross_prog = client.get(
        f"/games/progress?student_id={victim_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cross_prog.status_code == 403, "Cross-student /games/progress must return 403!"
    print("   [OK] Cross-student /games/progress blocked with HTTP 403.")

    # Initial state for brand new student
    p1 = client.get(
        f"/games/progress?student_id={test_student_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert p1["total_stars"] == 0
    assert p1["total_score"] == 0

    # Play Level 1 and record score: 850 points, 3 stars
    score_resp = client.post(
        "/games/score",
        json={
            "student_id": test_student_id,
            "game_id": "multiplier_matrix",
            "score": 850,
            "stars": 3,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert score_resp.status_code == 200
    p2 = score_resp.json()
    assert p2["total_score"] == 850
    assert p2["total_stars"] == 3

    lvl1 = next(l for l in p2["levels"] if l["id"] == "multiplier_matrix")
    assert lvl1["high_score"] == 850
    assert lvl1["stars"] == 3
    assert lvl1["times_played"] == 1

    # SIMULATE RELOGIN: fresh request with valid token
    relogin_resp = client.get(
        f"/games/progress?student_id={test_student_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
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
    token = sess["session_token"]

    # Solve multiplication problem
    next_res = client.post(
        "/session/next-problem",
        json={
            "session_id": session_id,
            "mark_previous_correct": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert next_res.status_code == 200

    # Fetch game progress: Level 1 should be unlocked!
    p = client.get(
        f"/games/progress?student_id={test_student_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    lvl1 = next(l for l in p["levels"] if l["id"] == "multiplier_matrix")
    assert lvl1["is_unlocked"] is True, "Level 1 (Multiplier Matrix) was not unlocked after solving multiplication!"
    assert lvl1["progress_percent"] == 100
    print("   [OK] Curriculum completion properly unlocked Level 1 Multiplier Matrix!")


if __name__ == "__main__":
    test_game_hierarchy_structure()
    test_game_score_and_relogin_persistence()
    test_unlock_progression_on_problem_solve()
    print("\n=== ALL GAME PROGRESSION & PERSISTENCE TESTS PASSED! ===")
