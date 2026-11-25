"""
Tests for Veritas Phase-2 Upgrades:
1. Unified native `google.genai` adapter (GeminiChatWrapper & GeminiEmbeddingWrapper)
2. Server-authoritative Math Arcade rounds (/games/round/start, grading, replay rejection, BKT fluency boost)
3. Student activity streak telemetry (_compute_streak_metrics & GET /student/{student_id}/activity)
"""
import datetime as dt
import hashlib
import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from main import app
from routes.student import _compute_streak_metrics
from services.arcade_rounds import issue_arcade_round
from services.gemini_client import GeminiChatWrapper, GeminiEmbeddingWrapper, _convert_messages

client = TestClient(app)


def test_gemini_client_wrappers():
    sys_inst, contents = _convert_messages([
        SystemMessage(content="You are Socratic."),
        HumanMessage(content="What is 2+2?"),
        AIMessage(content="What happens when you combine 2 and 2?"),
        HumanMessage(content=[
            {"type": "text", "text": "Here is my work:"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        ]),
    ])
    assert sys_inst == "You are Socratic."
    assert len(contents) == 3
    assert contents[0].role == "user"
    assert contents[1].role == "model"
    assert len(contents[2].parts) == 2

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(text="Let's break it down together!")
    mock_client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3])]
    )

    with patch("services.gemini_client._get_genai_client", return_value=mock_client):
        chat = GeminiChatWrapper(model="gemini-3.5-flash-lite", google_api_key="test-key", timeout=5)
        reply = chat.invoke([SystemMessage(content="Socratic"), HumanMessage(content="Help")])
        assert isinstance(reply, AIMessage)
        assert reply.content == "Let's break it down together!"

        emb = GeminiEmbeddingWrapper(model="models/gemini-embedding-001", google_api_key="test-key")
        vec = emb.embed_query("fractions")
        assert vec == [0.1, 0.2, 0.3]
    print("   [OK] Unified google.genai chat & embedding wrappers verified.")


def test_arcade_server_authoritative_rounds_and_bkt():
    student_id = str(uuid.uuid4())
    sess = client.post("/session/start", json={
        "student_name": "ArcadeTester",
        "student_id": student_id,
        "student_email": f"arcade_{student_id[:8]}@example.com",
    }).json()
    token = sess["session_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Start a server-issued round
    round_resp = client.post(
        "/games/round/start",
        json={"student_id": student_id, "game_id": "multiplier_matrix", "mode": "blitz"},
        headers=headers,
    )
    assert round_resp.status_code == 200, round_resp.text
    round_data = round_resp.json()
    round_id = round_data["round_id"]
    questions = round_data["questions"]
    assert len(questions) >= 25
    # Canonical answer must never be exposed in plaintext
    assert "answer" not in questions[0]
    assert "answer_digest" in questions[0]

    # Match each question's matching option via digest (mirrors Web Crypto client verification)
    submissions = []
    for q in questions[:6]:
        matched_opt = None
        for opt in q["options"]:
            digest = hashlib.sha256(f"{round_id}:{q['qid']}:{opt}".encode("utf-8")).hexdigest()
            if digest == q["answer_digest"]:
                matched_opt = opt
                break
        assert matched_opt is not None, "One option must match answer_digest"
        submissions.append({"qid": q["qid"], "selected": matched_opt})

    # 2. Submit deliberately inflated client score; server must ignore it and compute 700
    score_resp = client.post(
        "/games/score",
        json={
            "student_id": student_id,
            "game_id": "multiplier_matrix",
            "score": 99999,
            "stars": 3,
            "streak_max": 99,
            "mode": "blitz",
            "round_id": round_id,
            "submissions": submissions,
        },
        headers=headers,
    )
    assert score_resp.status_code == 200, score_resp.text
    score_data = score_resp.json()
    assert score_data["round_verified"] is True
    # 6 correct in a row: 100+100+100 (streak 0..2 => x1) + 200+200+200 (streak 3..5 => x2) = 900
    assert score_data["verified_score"] == 900
    assert score_data["verified_streak_max"] == 6
    assert score_data["verified_stars"] == 3
    assert score_data["mastery_delta"] > 0

    # 3. Replay attempt with same round_id must be rejected with 400
    replay_resp = client.post(
        "/games/score",
        json={
            "student_id": student_id,
            "game_id": "multiplier_matrix",
            "round_id": round_id,
            "submissions": submissions,
        },
        headers=headers,
    )
    assert replay_resp.status_code == 400

    # 4. Cross-student round submission must be rejected with 403
    other_round = issue_arcade_round(str(uuid.uuid4()), "multiplier_matrix", count=5)
    idor_resp = client.post(
        "/games/score",
        json={
            "student_id": student_id,
            "game_id": "multiplier_matrix",
            "round_id": other_round["round_id"],
            "submissions": [],
        },
        headers=headers,
    )
    assert idor_resp.status_code == 403
    print("   [OK] Server-authoritative arcade rounds, replay block, and BKT sync verified.")


def test_student_streak_calculation_and_endpoint():
    today = dt.date(2026, 11, 25)
    dates = {
        today,
        today - dt.timedelta(days=1),
        today - dt.timedelta(days=2),
        today - dt.timedelta(days=5),
        today - dt.timedelta(days=6),
    }
    stats = _compute_streak_metrics(dates, today=today)
    assert stats["current_streak_days"] == 3
    assert stats["longest_streak_days"] == 3
    assert stats["active_days_last_7"] == 5

    empty_stats = _compute_streak_metrics(set(), today=today)
    assert empty_stats == {"current_streak_days": 0, "longest_streak_days": 0, "active_days_last_7": 0}

    student_id = str(uuid.uuid4())
    unauth = client.get(f"/student/{student_id}/activity")
    assert unauth.status_code == 401

    sess = client.post("/session/start", json={
        "student_name": "StreakStudent",
        "student_id": student_id,
        "student_email": f"streak_{student_id[:8]}@example.com",
    }).json()
    resp = client.get(
        f"/student/{student_id}/activity",
        headers={"Authorization": f"Bearer {sess['session_token']}"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["student_id"] == student_id
    assert "current_streak_days" in payload
    assert "longest_streak_days" in payload
    assert "active_days_last_7" in payload
    print("   [OK] Student streak calculation & /activity endpoint verified.")


if __name__ == "__main__":
    os.environ.setdefault("VERITAS_TEST_MODE", "true")
    os.environ.setdefault("VERITAS_MOCK_LLM", "true")
    test_gemini_client_wrappers()
    test_arcade_server_authoritative_rounds_and_bkt()
    test_student_streak_calculation_and_endpoint()
    print("\n=== ALL PHASE-2 UPGRADE TESTS PASSED! ===")
