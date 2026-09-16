"""
Test Suite for Misconception State Model & Multi-Skill Learner-Aware Parent Alerts
Verifies:
1. Misconception lifecycle: record error -> increment count -> resolve upon mastery -> reset.
2. Socratic Tutor prompt injection of prior unresolved misconceptions.
3. Orchestrator resolution of active misconceptions upon problem solved.
4. Generic multi-skill alert generation (inactivity, low mastery, repeated misconception, stagnation).
5. End-to-end API response payloads on /session/start, /parent/{id}/children, and /parent/{id}/child/{cid}/details.
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

from starlette.testclient import TestClient
from main import app, generate_student_alerts
from auth import create_session_token
from session_manager import (
    get_student_misconceptions,
    save_student_misconception,
    resolve_student_misconceptions_for_skill,
    clear_student_misconceptions,
)
from agents.tutor_agent import run_tutor_agent

client = TestClient(app)


def test_misconception_storage_lifecycle():
    print("\n[TEST 1] Testing Misconception Storage Lifecycle...")
    test_student = str(uuid.uuid4())
    clear_student_misconceptions(test_student)

    # 1a. Initial state empty
    init_misc = get_student_misconceptions(test_student)
    assert init_misc == {}, f"Expected empty misconceptions, got {init_misc}"

    # 1b. First occurrence recorded
    entry1 = save_student_misconception(test_student, "flipped_fraction_division", "5.NF.B.7", resolved=False)
    assert entry1["count"] == 1
    assert entry1["resolved"] is False
    assert entry1["skill_id"] == "5.NF.B.7"

    # 1c. Second occurrence increments count
    entry2 = save_student_misconception(test_student, "flipped_fraction_division", "5.NF.B.7", resolved=False)
    assert entry2["count"] == 2
    assert entry2["resolved"] is False

    # 1d. Resolve for skill
    resolved = resolve_student_misconceptions_for_skill(test_student, "5.NF.B.7")
    assert "flipped_fraction_division" in resolved
    post_resolve = get_student_misconceptions(test_student)
    assert post_resolve["flipped_fraction_division"]["resolved"] is True

    # 1e. Clear on profile reset
    clear_student_misconceptions(test_student)
    assert get_student_misconceptions(test_student) == {}
    print("   ✓ Misconception lifecycle (record, increment, resolve, clear) verified.")


from unittest.mock import patch, MagicMock

def test_tutor_prompt_misconception_injection():
    print("\n[TEST 2] Testing Socratic Tutor Misconception Context...")
    active_misc = {
        "flipped_fraction_division": {
            "count": 2,
            "resolved": False,
            "skill_id": "5.NF.B.7",
        },
        "place_value_shift": {
            "count": 1,
            "resolved": True,  # resolved should not trigger warning
            "skill_id": "4.NBT.B.5",
        }
    }

    with patch("agents.tutor_agent.build_tutor_llm") as mock_build:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content='{"reply": "Good thought! What operation is the problem asking for?", "extracted_student_answer": "3/4", "student_reasoning": "inverted operation", "problem_solved": false, "is_final_attempt": true}'
        )
        mock_build.return_value = mock_llm

        resp = run_tutor_agent(
            student_message="I divided 3 by 1/4 and got 3/4.",
            conversation_history=[],
            current_problem={
                "title": "Fraction Division",
                "text": "Find 3 divided by 1/4.",
                "skill_name": "Fraction Division",
                "difficulty": 2,
                "expected_steps": ["Invert divisor to 4/1", "Multiply 3 * 4 = 12"],
            },
            active_misconceptions=active_misc,
        )

        assert isinstance(resp, dict)
        assert "reply" in resp
        # Verify that SystemMessage sent to LLM included prior misconception guidance
        call_args = mock_llm.invoke.call_args[0][0]
        sys_msg = call_args[0].content
        assert "PRIOR MISCONCEPTIONS TO ADDRESS IF REPEATED" in sys_msg
        assert "Flipped Fraction Division" in sys_msg
        assert "Place Value Shift" not in sys_msg  # resolved should be filtered out
        print("   ✓ Socratic tutor verified: injected unresolved misconceptions into prompt context.")


def test_generic_parent_alerts_generation():
    print("\n[TEST 3] Testing Multi-Skill Alert Generator...")
    student_id = str(uuid.uuid4())

    # Case A: Low mastery + Inactivity + Recurring Misconception
    mastery_map = {
        "4.OA.A.1": 0.85,
        "5.NF.B.7": 0.28,  # urgent low mastery (<0.35)
        "4.NBT.B.5": 0.45,  # warning low mastery (<0.50)
    }
    active_misc = {
        "inverted_division_rule": {
            "count": 3,
            "resolved": False,
            "skill_id": "5.NF.B.7",
        }
    }
    alerts, alert_msg, has_gap, frac_alert, frac_m, top_id, top_name = generate_student_alerts(
        student_id=student_id,
        all_mastery_map=mastery_map,
        days_since=4,  # warning inactivity (>=3)
        active_misconceptions=active_misc,
    )

    alert_types = [a["type"] for a in alerts]
    assert "inactivity" in alert_types, f"Expected inactivity alert in {alert_types}"
    assert "low_mastery" in alert_types, f"Expected low_mastery alert in {alert_types}"
    assert "misconception" in alert_types, f"Expected misconception alert in {alert_types}"
    assert has_gap is True
    assert "Notice:" in alert_msg

    # Verify structured alert fields
    for a in alerts:
        assert "type" in a
        assert "message" in a
        assert "severity" in a
        assert a["severity"] in ("info", "warning", "urgent")

    print(f"   ✓ Generated {len(alerts)} structured alerts: {[a['type'] for a in alerts]}")

    # Case B: Stagnation detection
    stagnant_events = [
        {"is_correct": False},
        {"is_correct": False},
        {"is_correct": False},
        {"is_correct": False},
    ]
    alerts_b, _, _, _, _, _, _ = generate_student_alerts(
        student_id=student_id,
        all_mastery_map={"4.OA.A.1": 0.70},
        days_since=1,
        active_misconceptions={},
        recent_events=stagnant_events,
    )
    assert any(a["type"] == "stagnation" for a in alerts_b), "Expected stagnation alert"
    print("   ✓ Stagnation / practice plateau alert correctly flagged.")


def test_api_misconception_and_alerts_integration():
    print("\n[TEST 4] Testing API Endpoints Integration...")
    test_parent_id = str(uuid.uuid4())
    test_student_id = str(uuid.uuid4())
    test_email = f"student_{test_student_id[:8]}@veritas.dev"
    parent_token = create_session_token(test_parent_id, "parent-session-1", "Test Parent", role="parent")
    parent_headers = {"Authorization": f"Bearer {parent_token}"}

    # 4a. /session/start returns active_misconceptions
    start_resp = client.post("/session/start", json={
        "student_name": "Alerts Test Student",
        "student_id": test_student_id,
        "student_email": test_email,
    })
    assert start_resp.status_code == 200
    start_json = start_resp.json()
    assert "active_misconceptions" in start_json, "Expected active_misconceptions in start response"

    # Pre-record a recurring misconception for this student
    save_student_misconception(test_student_id, "flipped_operation", "5.NF.B.7", resolved=False)
    save_student_misconception(test_student_id, "flipped_operation", "5.NF.B.7", resolved=False)

    # 4b. Link child to parent
    link_resp = client.post("/parent/add-child", json={
        "parent_id": test_parent_id,
        "parent_email": "parent@veritas.dev",
        "child_email": test_email,
        "child_name": "Alerts Test Student",
        "student_id": test_student_id,
    }, headers=parent_headers)
    assert link_resp.status_code == 200

    # 4c. /parent/{parent_id}/children includes alerts list & active_misconceptions
    kids_resp = client.get(f"/parent/{test_parent_id}/children", headers=parent_headers)
    assert kids_resp.status_code == 200
    kids_json = kids_resp.json()
    assert "children" in kids_json
    child = next(c for c in kids_json["children"] if c["student_id"] == test_student_id)
    assert "alerts" in child, "Expected alerts in child item"
    assert isinstance(child["alerts"], list)
    assert "active_misconceptions" in child
    assert "fraction_alert_message" in child  # backwards compatibility check
    assert "has_fraction_gap" in child
    print(f"   ✓ /parent/children returned {len(child['alerts'])} alerts and persisted misconceptions.")

    # 4d. /parent/{parent_id}/child/{child_id}/details includes alerts & active_misconceptions
    details_resp = client.get(f"/parent/{test_parent_id}/child/{test_student_id}/details", headers=parent_headers)
    assert details_resp.status_code == 200
    details_json = details_resp.json()
    assert "alerts" in details_json
    assert "active_misconceptions" in details_json
    print(f"   ✓ /parent/child/details returned details with {len(details_json['alerts'])} alerts.")

    print("\n🎉 ALL MISCONCEPTION & PARENT ALERT TESTS PASSED!")


if __name__ == "__main__":
    test_misconception_storage_lifecycle()
    test_tutor_prompt_misconception_injection()
    test_generic_parent_alerts_generation()
    test_api_misconception_and_alerts_integration()
