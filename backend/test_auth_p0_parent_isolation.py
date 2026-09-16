"""
Regression and Isolation Tests for P0 Parent Authorization Boundaries:
1. /games/score rejects parent token with HTTP 403 ("Student authentication required")
2. /games/reset rejects parent token with HTTP 403 ("Student authentication required")
3. /games/score rejects cross-student mutation with HTTP 403 ("Cannot modify another student's game state")
4. /games/reset rejects cross-student reset with HTTP 403 ("Cannot modify another student's game state")
5. /session/start rejects parent token with HTTP 403 ("Student account required for tutoring sessions")
6. /games/score allows valid student with own token
"""
import uuid
from starlette.testclient import TestClient
from main import app
from auth import create_session_token

client = TestClient(app)


def test_parent_cannot_mutate_game_score():
    student_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())

    parent_token = create_session_token(parent_id, "p-sess-1", "Parent One", role="parent")
    parent_headers = {"Authorization": f"Bearer {parent_token}"}

    resp = client.post(
        "/games/score",
        json={
            "student_id": student_id,
            "game_id": "multiplier_matrix",
            "score": 100,
            "stars": 2,
        },
        headers=parent_headers,
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "Student authentication required" in resp.json()["detail"]


def test_parent_cannot_reset_game_score():
    student_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())

    parent_token = create_session_token(parent_id, "p-sess-1", "Parent One", role="parent")
    parent_headers = {"Authorization": f"Bearer {parent_token}"}

    resp = client.post(
        "/games/reset",
        json={
            "student_id": student_id,
            "game_id": "multiplier_matrix",
        },
        headers=parent_headers,
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "Student authentication required" in resp.json()["detail"]


def test_student_cannot_mutate_other_student_game_score():
    student_a = str(uuid.uuid4())
    student_b = str(uuid.uuid4())

    student_a_token = create_session_token(student_a, "s-sess-a", "Student A", role="student")
    student_a_headers = {"Authorization": f"Bearer {student_a_token}"}

    resp = client.post(
        "/games/score",
        json={
            "student_id": student_b,
            "game_id": "multiplier_matrix",
            "score": 100,
            "stars": 2,
        },
        headers=student_a_headers,
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "Cannot modify another student's game state" in resp.json()["detail"]


def test_student_cannot_reset_other_student_game_score():
    student_a = str(uuid.uuid4())
    student_b = str(uuid.uuid4())

    student_a_token = create_session_token(student_a, "s-sess-a", "Student A", role="student")
    student_a_headers = {"Authorization": f"Bearer {student_a_token}"}

    resp = client.post(
        "/games/reset",
        json={
            "student_id": student_b,
            "game_id": "multiplier_matrix",
        },
        headers=student_a_headers,
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "Cannot modify another student's game state" in resp.json()["detail"]


def test_parent_cannot_create_tutoring_session():
    parent_id = str(uuid.uuid4())
    parent_token = create_session_token(parent_id, "p-sess-1", "Parent One", role="parent")
    parent_headers = {"Authorization": f"Bearer {parent_token}"}

    resp = client.post(
        "/session/start",
        json={
            "student_name": "Should Fail",
            "student_id": parent_id,
        },
        headers=parent_headers,
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "Student account required for tutoring sessions" in resp.json()["detail"]


def test_student_can_record_own_game_score():
    student_id = str(uuid.uuid4())
    student_token = create_session_token(student_id, "s-sess-own", "Student Own", role="student")
    student_headers = {"Authorization": f"Bearer {student_token}"}

    resp = client.post(
        "/games/score",
        json={
            "student_id": student_id,
            "game_id": "multiplier_matrix",
            "score": 250,
            "stars": 3,
        },
        headers=student_headers,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["student_id"] == student_id


import sys
if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

if __name__ == "__main__":
    test_parent_cannot_mutate_game_score()
    print("[OK] test_parent_cannot_mutate_game_score passed")
    test_parent_cannot_reset_game_score()
    print("[OK] test_parent_cannot_reset_game_score passed")
    test_student_cannot_mutate_other_student_game_score()
    print("[OK] test_student_cannot_mutate_other_student_game_score passed")
    test_student_cannot_reset_other_student_game_score()
    print("[OK] test_student_cannot_reset_other_student_game_score passed")
    test_parent_cannot_create_tutoring_session()
    print("[OK] test_parent_cannot_create_tutoring_session passed")
    test_student_can_record_own_game_score()
    print("[OK] test_student_can_record_own_game_score passed")
    print("\nAll P0 authorization boundary tests passed successfully!")
