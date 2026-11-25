"""
Tests for Veritas Phase-2 & Phase-3 Upgrades:
1. Unified native `google.genai` adapter (invoke + live generate_content_stream)
2. Socratic streaming JSON partial reply extractor & live event generator
3. Server-authoritative Math Arcade rounds (/games/round/start, strict round_id requirement, replay block, BKT boost)
4. Student activity streak telemetry (_compute_streak_metrics & GET /student/{student_id}/activity)
5. Ephemeral VERITAS_DATA_DIR isolation for test suites
"""
import datetime as dt
import hashlib
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import session_manager
from agents.tutor_agent import extract_partial_reply_from_stream, stream_tutor_agent_events
from main import app
from routes.student import _compute_streak_metrics
from services.arcade_rounds import issue_arcade_round
from services.gemini_client import GeminiChatWrapper, GeminiEmbeddingWrapper, _convert_messages

client = TestClient(app)


def test_gemini_client_wrappers_and_streaming():
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
    mock_client.models.generate_content_stream.return_value = iter([
        SimpleNamespace(text='{"reply": "Great '),
        SimpleNamespace(text='first step!'),
        SimpleNamespace(text='", "problem_solved": false}'),
    ])
    mock_client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3])]
    )

    with patch("services.gemini_client._get_genai_client", return_value=mock_client):
        chat = GeminiChatWrapper(model="gemini-3.5-flash-lite", google_api_key="test-key", timeout=5)
        reply = chat.invoke([SystemMessage(content="Socratic"), HumanMessage(content="Help")])
        assert isinstance(reply, AIMessage)
        assert reply.content == "Let's break it down together!"

        deltas = list(chat.stream([SystemMessage(content="Socratic"), HumanMessage(content="Help")]))
        assert "".join(deltas) == '{"reply": "Great first step!", "problem_solved": false}'

        emb = GeminiEmbeddingWrapper(model="models/gemini-embedding-001", google_api_key="test-key")
        vec = emb.embed_query("fractions")
        assert vec == [0.1, 0.2, 0.3]

    # Verify incremental JSON reply unescaping during partial streaming
    assert extract_partial_reply_from_stream('{"reply": "Line 1\\nLine') == "Line 1\nLine"
    assert extract_partial_reply_from_stream('Plain prose reply') == "Plain prose reply"

    # Verify live event generator yields ('delta', ...) chunks followed by ('done', dict)
    fake_llm = MagicMock()
    fake_llm.stream.return_value = iter([
        '{"reply": "Try ',
        'checking the denominator!", ',
        '"problem_solved": false}',
    ])
    with patch("agents.tutor_agent.build_tutor_llm", return_value=fake_llm):
        events = list(stream_tutor_agent_events(
            student_message="How do I start this fraction?",
            conversation_history=[],
            current_problem={"id": "p1", "title": "Fractions", "text": "1/2 + 1/3", "answer": "5/6"},
        ))
    delta_text = "".join(val for kind, val in events if kind == "delta")
    done_payloads = [val for kind, val in events if kind == "done"]
    assert delta_text == "Try checking the denominator!"
    assert len(done_payloads) == 1
    assert done_payloads[0]["reply"] == "Try checking the denominator!"
    print("   [OK] Unified google.genai invoke + live token streaming verified.")


def test_arcade_server_authoritative_rounds_and_bkt():
    student_id = str(uuid.uuid4())
    sess = client.post("/session/start", json={
        "student_name": "ArcadeTester",
        "student_id": student_id,
        "student_email": f"arcade_{student_id[:8]}@example.com",
    }).json()
    token = sess["session_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 0. Strict enforcement: /games/score without round_id must be rejected with 400
    missing_round = client.post(
        "/games/score",
        json={"student_id": student_id, "game_id": "multiplier_matrix", "score": 999, "stars": 3},
        headers=headers,
    )
    assert missing_round.status_code == 400

    # 1. Start a server-issued round (zen fetches 80, blitz fetches 40)
    round_resp = client.post(
        "/games/round/start",
        json={"student_id": student_id, "game_id": "multiplier_matrix", "mode": "blitz"},
        headers=headers,
    )
    assert round_resp.status_code == 200, round_resp.text
    round_data = round_resp.json()
    round_id = round_data["round_id"]
    questions = round_data["questions"]
    assert len(questions) == 40
    assert "answer" not in questions[0]
    assert "answer_digest" in questions[0]

    submissions = []
    for q in questions[:6]:
        matched_opt = next(
            opt for opt in q["options"]
            if hashlib.sha256(f"{round_id}:{q['qid']}:{opt}".encode()).hexdigest() == q["answer_digest"]
        )
        submissions.append({"qid": q["qid"], "selected": matched_opt})

    # 2. Server ignores inflated client score (99999) and computes 900 + BKT boost
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
    assert score_data["verified_score"] == 900
    assert score_data["verified_streak_max"] == 6
    assert score_data["verified_stars"] == 3
    assert score_data["mastery_delta"] > 0

    # 3. Replay attempt with same round_id must return 400
    replay_resp = client.post(
        "/games/score",
        json={"student_id": student_id, "game_id": "multiplier_matrix", "round_id": round_id, "submissions": submissions},
        headers=headers,
    )
    assert replay_resp.status_code == 400

    # 4. Cross-student round submission must return 403
    other_round = issue_arcade_round(str(uuid.uuid4()), "multiplier_matrix", count=5)
    idor_resp = client.post(
        "/games/score",
        json={"student_id": student_id, "game_id": "multiplier_matrix", "round_id": other_round["round_id"], "submissions": []},
        headers=headers,
    )
    assert idor_resp.status_code == 403
    print("   [OK] Server-authoritative arcade rounds, strict round_id gate, replay block, and BKT sync verified.")


def test_student_streak_and_ephemeral_data_dir():
    env_dir = os.environ.get("VERITAS_DATA_DIR")
    if env_dir:
        assert session_manager.DATA_DIR == Path(env_dir)

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

    student_id = str(uuid.uuid4())
    assert client.get(f"/student/{student_id}/activity").status_code == 401

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
    print("   [OK] Student streak telemetry & ephemeral VERITAS_DATA_DIR isolation verified.")


if __name__ == "__main__":
    os.environ.setdefault("VERITAS_TEST_MODE", "true")
    os.environ.setdefault("VERITAS_MOCK_LLM", "true")
    test_gemini_client_wrappers_and_streaming()
    test_arcade_server_authoritative_rounds_and_bkt()
    test_student_streak_and_ephemeral_data_dir()
    print("\n=== ALL PHASE-2 & PHASE-3 UPGRADE TESTS PASSED! ===")
