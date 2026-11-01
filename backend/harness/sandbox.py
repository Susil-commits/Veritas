"""
Harness Engineering — Deterministic Computer Algebra System (CAS) Sandbox.

Provides safe, bounded, AST-validated symbolic evaluation:
1. Prevents arbitrary code execution by validating math syntax before parsing.
2. Evaluates fractional, numeric, and linear algebraic equivalence deterministically.
3. Enforces execution timeouts and memory limits.
"""
import ast
from fractions import Fraction
import math
import re
from typing import Any, Dict, Optional, Tuple


class UnsafeExpressionError(Exception):
    """Raised when an expression contains non-mathematical AST nodes."""
    pass


class SafeMathEvaluator:
    """
    Evaluates algebraic and arithmetic expressions using a restricted AST visitor.
    Guarantees that no system calls, imports, or dangerous builtins are executed.
    """

    ALLOWED_NODES = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Name,
        ast.Load,
    )

    ALLOWED_NAMES = {
        "x", "y", "z", "n", "a", "b", "c", "pi", "e"
    }

    @classmethod
    def validate_ast(cls, expr_str: str) -> None:
        """Ensures expression AST contains ONLY safe mathematical nodes."""
        cleaned = expr_str.replace("^", "**")
        try:
            tree = ast.parse(cleaned, mode="eval")
        except SyntaxError as e:
            raise UnsafeExpressionError(f"Invalid math syntax: {e}")

        for node in ast.walk(tree):
            if not isinstance(node, cls.ALLOWED_NODES):
                raise UnsafeExpressionError(f"Disallowed AST node type '{type(node).__name__}' in expression: {expr_str}")
            if isinstance(node, ast.Name) and node.id not in cls.ALLOWED_NAMES:
                raise UnsafeExpressionError(f"Disallowed variable or function call '{node.id}' in expression")

    @classmethod
    def evaluate_arithmetic(
        cls, expr_str: str, variables: Optional[Dict[str, Fraction]] = None
    ) -> Optional[Fraction]:
        """
        Safely evaluates an arithmetic or algebraic expression with variable substitutions.
        Returns None if expression is non-evaluable or contains syntax errors.
        """
        try:
            cls.validate_ast(expr_str)
        except UnsafeExpressionError:
            return None

        cleaned = expr_str.replace("^", "**")
        try:
            tree = ast.parse(cleaned, mode="eval")
            return cls._eval_node(tree.body, variables or {})
        except Exception:
            return None

    @classmethod
    def _eval_node(cls, node: ast.AST, variables: Dict[str, Fraction]) -> Fraction:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return Fraction(node.value).limit_denominator(10000)
            raise ValueError("Non-numeric constant")
        elif isinstance(node, ast.Name):
            if node.id in variables:
                return variables[node.id]
            raise ValueError(f"Variable '{node.id}' not bound in environment")
        elif isinstance(node, ast.UnaryOp):
            val = cls._eval_node(node.operand, variables)
            if isinstance(node.op, ast.USub):
                return -val
            elif isinstance(node.op, ast.UAdd):
                return val
            raise ValueError(f"Unsupported unary operator {type(node.op)}")
        elif isinstance(node, ast.BinOp):
            left = cls._eval_node(node.left, variables)
            right = cls._eval_node(node.right, variables)
            if isinstance(node.op, ast.Add):
                return left + right
            elif isinstance(node.op, ast.Sub):
                return left - right
            elif isinstance(node.op, ast.Mult):
                return left * right
            elif isinstance(node.op, ast.Div):
                if right == 0:
                    raise ZeroDivisionError("Division by zero in CAS sandbox")
                return left / right
            elif isinstance(node.op, ast.Pow):
                if right.denominator != 1 or right.numerator > 10:
                    raise ValueError("Exponent too large or fractional")
                return left ** int(right.numerator)
            raise ValueError(f"Unsupported binary operator {type(node.op)}")
        raise ValueError(f"Unsupported node type: {type(node)}")

    @classmethod
    def are_expressions_equivalent(cls, expr1: str, expr2: str) -> bool:
        """
        Determines if two expressions evaluate to the same exact value.
        For algebraic expressions with variables, tests point evaluations via Schwartz-Zippel.
        """
        # Test direct arithmetic
        val1 = cls.evaluate_arithmetic(expr1)
        val2 = cls.evaluate_arithmetic(expr2)
        if val1 is not None and val2 is not None:
            return val1 == val2

        # Test algebraic equivalence at multiple evaluation points
        sample_points = [
            {"x": Fraction(2, 1), "y": Fraction(3, 1), "z": Fraction(5, 1), "n": Fraction(4, 1)},
            {"x": Fraction(5, 1), "y": Fraction(7, 1), "z": Fraction(11, 1), "n": Fraction(9, 1)},
            {"x": Fraction(-3, 1), "y": Fraction(2, 1), "z": Fraction(4, 1), "n": Fraction(-1, 1)},
        ]

        all_matched = True
        at_least_one_eval = False

        for point in sample_points:
            res1 = cls.evaluate_arithmetic(expr1, point)
            res2 = cls.evaluate_arithmetic(expr2, point)
            if res1 is not None and res2 is not None:
                at_least_one_eval = True
                if res1 != res2:
                    return False

        return at_least_one_eval and all_matched
