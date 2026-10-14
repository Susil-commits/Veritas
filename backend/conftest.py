"""
Hermetic Pytest Configuration and Fixtures — Veritas.
Ensures routing and unit test suites execute completely offline
with zero network dependencies and no required environment secrets.
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock
import pytest

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run real DB integration tests that connect to external services.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring external network/database services (skipped by default)",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(
            reason="Integration test skipped by default. Pass --run-integration to execute against real DB."
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


# Canonical mock candidate problems for adaptive curriculum progression
MOCK_CANDIDATE_PROBLEMS: List[Dict[str, Any]] = [
    {
        "id": "mock_cand_4nf3_01",
        "title": "Adding Fractions with Common Denominators",
        "text": "Calculate 1/5 + 2/5.",
        "skill_id": "4.NF.B.3",
        "difficulty": 2,
        "answer": "3/5",
        "expected_steps": [
            "Keep the common denominator 5",
            "Add the numerators: 1 + 2 = 3",
            "Final result: 3/5",
        ],
    },
    {
        "id": "mock_cand_4nfa_01",
        "title": "Generating Equivalent Fractions",
        "text": "Find an equivalent fraction for 3/4 with denominator 12.",
        "skill_id": "4.NF.A.1",
        "difficulty": 2,
        "answer": "9/12",
        "expected_steps": [
            "Find multiplier: 12 / 4 = 3",
            "Multiply numerator: 3 * 3 = 9",
            "Result: 9/12",
        ],
    },
    {
        "id": "mock_cand_6ee_01",
        "title": "Balancing Single-Variable Linear Equations",
        "text": "Solve x + 5 = 12.",
        "skill_id": "6.EE.B.7",
        "difficulty": 2,
        "answer": "7",
        "expected_steps": [
            "Subtract 5 from both sides: x = 12 - 5",
            "Result: x = 7",
        ],
    },
    {
        "id": "mock_cand_7ee_01",
        "title": "Distributive Property with Negative Numbers",
        "text": "Solve -2(x - 3) = 8.",
        "skill_id": "7.EE.B.4",
        "difficulty": 3,
        "answer": "-1",
        "expected_steps": [
            "Distribute -2: -2x + 6 = 8",
            "Subtract 6: -2x = 2",
            "Divide by -2: x = -1",
        ],
    },
]


def _mock_get_candidate_problems(
    skill_id: str | None = None,
    mastery_prob: float = 0.5,
    student_id: str = "default",
    exclude_problem_ids: list[str] | None = None,
    misconception_text: str | None = None,
    top_k: int = 5,
    unrestricted: bool = False,
    keywords: list[str] | None = None,
    mode: str = "auto",
) -> list[dict]:
    """Hermetic replacement for content_agent.get_candidate_problems without network/Supabase."""
    exclude = set(exclude_problem_ids or [])
    candidates = [p for p in MOCK_CANDIDATE_PROBLEMS if p["id"] not in exclude]
    if skill_id and not unrestricted:
        matching = [p for p in candidates if p.get("skill_id") == skill_id]
        if matching:
            return matching[:top_k]
    return candidates[:top_k] if candidates else MOCK_CANDIDATE_PROBLEMS[:top_k]


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch, request):
    """
    Automatically isolates all tests from live Supabase network calls
    unless explicitly marked with @pytest.mark.integration.
    """
    if "integration" in request.keywords:
        return

    # Ensure test flags are set
    monkeypatch.setenv("VERITAS_TEST_MODE", "true")
    monkeypatch.setenv("VERITAS_MOCK_LLM", "true")

    # 1. Monkeypatch content_agent.get_candidate_problems
    try:
        import agents.content_agent as content_agent
        monkeypatch.setattr(content_agent, "get_candidate_problems", _mock_get_candidate_problems)
    except Exception:
        pass

    # 2. Monkeypatch db.supabase_client.get_supabase to prevent credential crashes
    try:
        import db.supabase_client as supabase_client
        mock_client = MagicMock()
        # Mock table chain: .table().select().eq().execute() etc.
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.neq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.order.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])
        monkeypatch.setattr(supabase_client, "get_supabase", lambda: mock_client)
    except Exception:
        pass
