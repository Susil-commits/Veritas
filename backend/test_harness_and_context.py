"""
Unit & Integration Test Suite for:
1. Context Engineering (CognitiveContextManager, Epistemic Injection, Compaction)
2. Harness Engineering (Invariants, CAS Sandbox, ExecutionHarness)
3. Inferencing Systems (Tiered InferenceRouter, Streaming Invariant Buffer)
4. Model Context Protocol (VeritasMCPServer JSON-RPC 2.0)
"""
import pytest
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.context.cognitive_context import (
    CognitiveContextManager,
    EpistemicStudentState,
    STATIC_SOCRATIC_PREFIX,
)
from backend.harness.invariants import PedagogicalInvariantChecker
from backend.harness.sandbox import SafeMathEvaluator, UnsafeExpressionError
from backend.harness.engine import VeritasExecutionHarness
from backend.services.inference_router import (
    InferenceRouter,
    InferenceTier,
    StreamingInvariantBuffer,
)
from backend.mcp.server import VeritasMCPServer


# ==============================================================================
# 1. CONTEXT ENGINEERING TESTS
# ==============================================================================

def test_context_prefix_caching_and_hash():
    cm = CognitiveContextManager(keep_recent_turns=2)
    prefix = cm.get_static_prefix()
    assert len(prefix) > 500
    assert "ZERO ANSWER LEAKAGE AXIOM" in prefix
    assert cm.prefix_hash is not None
    assert len(cm.prefix_hash) == 64  # SHA-256


def test_epistemic_state_injection_and_scaffolding():
    cm = CognitiveContextManager(keep_recent_turns=2)
    state = EpistemicStudentState(
        student_id="student_123",
        active_skill_id="CCSS.MATH.6.EE.A.2",
        mastery_prob=0.42,
        diagnosed_misconceptions=["MISCONCEPTION_FLIPPED_FRACTION"],
        consecutive_errors=3
    )
    block = cm.build_epistemic_block(state)
    assert "CCSS.MATH.6.EE.A.2" in block
    assert "0.42" in block
    assert "MISCONCEPTION_FLIPPED_FRACTION" in block
    assert "Level 3" in block  # High scaffolding due to consecutive errors


def test_dialogue_turn_compaction():
    cm = CognitiveContextManager(keep_recent_turns=2)
    raw_history = [
        {"role": "user", "content": "How do I solve 2x + 4 = 10?"},
        {"role": "assistant", "content": "What happens if we isolate the variable term first?"},
        {"role": "user", "content": "Should I subtract 4 from both sides?"},
        {"role": "assistant", "content": "Spot on! What does 10 minus 4 give us?"},
        {"role": "user", "content": "It gives 6, so 2x = 6."},
        {"role": "assistant", "content": "Exactly right. How do we find x from 2x = 6?"},
    ]

    recent_msgs, summary = cm.compact_history(raw_history)
    # 2 turns = 4 messages kept
    assert len(recent_msgs) == 4
    assert summary is not None
    assert "Earlier turns:" in summary
    assert "Student attempted:" in summary


# ==============================================================================
# 2. HARNESS ENGINEERING TESTS
# ==============================================================================

def test_zero_leakage_detection():
    # Test leak: explicit phrase
    ok, err = PedagogicalInvariantChecker.check_zero_answer_leakage("So the answer is 7.", "7")
    assert not ok
    assert "Direct answer leak" in err

    # Test leak: equation assignment
    ok, err = PedagogicalInvariantChecker.check_zero_answer_leakage("Notice that x = 7.", "7")
    assert not ok

    # Test safe Socratic response
    ok, err = PedagogicalInvariantChecker.check_zero_answer_leakage(
        "What happens when you divide both sides by 2?", "7"
    )
    assert ok
    assert err is None


def test_socratic_inquiry_invariant():
    # Fails when tutor just makes a statement with no question
    ok, err = PedagogicalInvariantChecker.check_socratic_inquiry("You need to simplify the fraction.")
    assert not ok

    # Passes when a question is posed
    ok, err = PedagogicalInvariantChecker.check_socratic_inquiry("What is the greatest common factor of 4 and 8?")
    assert ok


def test_cas_sandbox_equivalence():
    assert SafeMathEvaluator.are_expressions_equivalent("2 * (3 + 4)", "14")
    assert SafeMathEvaluator.are_expressions_equivalent("3/4 + 1/4", "1")
    assert not SafeMathEvaluator.are_expressions_equivalent("2 + 2", "5")


def test_cas_sandbox_ast_containment():
    with pytest.raises(UnsafeExpressionError):
        SafeMathEvaluator.validate_ast("__import__('os').system('dir')")


def test_execution_harness_safe_fallback():
    harness = VeritasExecutionHarness(record_traces=True)
    
    # Simulate a rogue LLM trying to leak the answer "12"
    def rogue_llm():
        return "The answer is 12."

    result = harness.execute_turn(
        tutor_callable=rogue_llm,
        target_solution="12",
        student_input="Can you just tell me the answer?"
    )

    assert result["used_fallback"] is True
    assert "12" not in result["verified_reply"]
    assert "?" in result["verified_reply"]
    assert len(harness.session_traces) == 1


# ==============================================================================
# 3. INFERENCING SYSTEMS TESTS
# ==============================================================================

def test_inference_router_triage():
    # Fast greeting triage
    tier, canned = InferenceRouter.classify_request("hello!")
    assert tier == InferenceTier.TIER_1_FAST_TRIAGE
    assert canned is not None

    # Fast acknowledgment triage
    tier, canned = InferenceRouter.classify_request("ok, got it")
    assert tier == InferenceTier.TIER_1_FAST_TRIAGE

    # Socratic tier for math input
    tier, canned = InferenceRouter.classify_request("I subtracted 3 from both sides and got 2x = 8")
    assert tier == InferenceTier.TIER_2_SOCRATIC_REASONING
    assert canned is None

    # Vision tier for image
    tier, _ = InferenceRouter.classify_request("Here is my paper", has_image=True)
    assert tier == InferenceTier.TIER_3_MULTIMODAL_VISION


def test_streaming_invariant_buffer():
    buf = StreamingInvariantBuffer(target_solution="42")
    tokens = ["Let's ", "look ", "at ", "the ", "answer ", "is ", "42", " now."]
    
    streamed = []
    for tok in tokens:
        res = buf.process_chunk(tok)
        if res:
            streamed.append(res)

    joined = "".join(streamed)
    assert "42" not in joined
    assert buf.leak_detected is True


# ==============================================================================
# 4. MODEL CONTEXT PROTOCOL (MCP) TESTS
# ==============================================================================

def test_mcp_server_initialize():
    server = VeritasMCPServer()
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = server.handle_request(req)
    assert resp["result"]["serverInfo"]["name"] == "veritas-socratic-math-mcp"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_server_tools_list_and_call():
    server = VeritasMCPServer()
    
    # 1. List tools
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    list_resp = server.handle_request(list_req)
    tool_names = [t["name"] for t in list_resp["result"]["tools"]]
    assert "veritas_verify_math_step" in tool_names
    assert "veritas_check_answer_leakage" in tool_names
    assert "veritas_update_bkt" in tool_names

    # 2. Call veritas_verify_math_step
    call_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "veritas_verify_math_step",
            "arguments": {
                "previous_expr": "2 * (x + 3)",
                "student_step_expr": "2 * x + 6"
            }
        }
    }
    call_resp = server.handle_request(call_req)
    content = json.loads(call_resp["result"]["content"][0]["text"])
    assert content["equivalent"] is True


def test_mcp_server_bkt_tool_call():
    server = VeritasMCPServer()
    call_req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "veritas_update_bkt",
            "arguments": {
                "student_id": "test_student",
                "skill_id": "CCSS.MATH.6.RP.A.1",
                "is_correct": True,
                "current_mastery": 0.50
            }
        }
    }
    call_resp = server.handle_request(call_req)
    content = json.loads(call_resp["result"]["content"][0]["text"])
    assert content["updated_mastery"] > 0.50
    assert content["student_id"] == "test_student"


def test_mcp_server_resources_read():
    server = VeritasMCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "resources/read",
        "params": {"uri": "veritas://curriculum/standards"}
    }
    resp = server.handle_request(req)
    contents = json.loads(resp["result"]["contents"][0]["text"])
    assert len(contents) >= 5
    assert contents[0]["id"].startswith("CCSS.MATH")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))

