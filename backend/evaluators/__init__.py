"""
Evaluators package — Deterministic objective verification and benchmark evaluation.
"""
from .math_evaluator import evaluate_student_solution, verify_math_equivalence

__all__ = ["evaluate_student_solution", "verify_math_equivalence"]
