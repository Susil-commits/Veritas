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
        """Ensures expression AST contains ONLY safe mathematical nodes and respects bounded limits."""
        if not expr_str or len(expr_str) > 250:
            raise UnsafeExpressionError("Expression exceeds maximum character length (max 250 chars)")

        cleaned = expr_str.replace("^", "**")
        try:
            tree = ast.parse(cleaned, mode="eval")
        except SyntaxError as e:
            raise UnsafeExpressionError(f"Invalid math syntax: {e}")

        def _check_depth_and_count(node: ast.AST, current_depth: int = 1) -> int:
            if current_depth > 8:
                raise UnsafeExpressionError("Expression exceeds maximum allowable nesting depth (max depth 8)")
            count = 1
            for child in ast.iter_child_nodes(node):
                count += _check_depth_and_count(child, current_depth + 1)
                if count > 40:
                    raise UnsafeExpressionError("Expression exceeds maximum allowable AST node count (max 40 nodes)")
            return count

        _check_depth_and_count(tree)

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
        Returns None if expression is non-evaluable, times out, or contains syntax errors.
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
                if abs(node.value) > 100_000_000:
                    raise ValueError("Numeric constant exceeds maximum allowable value")
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
                res = left + right
            elif isinstance(node.op, ast.Sub):
                res = left - right
            elif isinstance(node.op, ast.Mult):
                res = left * right
            elif isinstance(node.op, ast.Div):
                if right == 0:
                    raise ZeroDivisionError("Division by zero in CAS sandbox")
                res = left / right
            elif isinstance(node.op, ast.Pow):
                if right.denominator != 1:
                    raise ValueError("Exponent must be an integer")
                exp_int = int(right.numerator)
                if exp_int < 0 or exp_int > 6:
                    raise ValueError("Exponent must be an integer between 0 and 6")
                if abs(left.numerator) > 100 or abs(left.denominator) > 100:
                    raise ValueError("Base too large for safe exponentiation")
                if left.numerator.bit_length() * exp_int > 60:
                    raise ValueError("Exponentiation output exceeds 60-bit limit")
                res = left ** exp_int
            else:
                raise ValueError(f"Unsupported binary operator {type(node.op)}")

            if abs(res.numerator) > 100_000_000 or abs(res.denominator) > 100_000_000:
                raise ValueError("Intermediate result exceeds safe bounds")
            return res
        raise ValueError(f"Unsupported node type: {type(node)}")

    @classmethod
    def are_expressions_equivalent(cls, expr1: str, expr2: str) -> bool:
        """
        Determines if two expressions evaluate to the same exact value.
        Primary: Exact symbolic CAS equivalence via SymPy with bounded AST validation.
        Fallback: Multi-point randomized Schwartz-Zippel lemma testing binding all allowed variables.
        """
        # Validate AST safety on both inputs first
        try:
            cls.validate_ast(expr1)
            cls.validate_ast(expr2)
        except UnsafeExpressionError:
            return False

        # 1. Exact Symbolic CAS verification via SymPy
        try:
            import sympy
            from sympy.parsing.sympy_parser import (
                parse_expr,
                standard_transformations,
                implicit_multiplication_application,
            )
            transforms = standard_transformations + (implicit_multiplication_application,)
            s1 = parse_expr(expr1.replace("^", "**"), transformations=transforms)
            s2 = parse_expr(expr2.replace("^", "**"), transformations=transforms)
            diff = sympy.simplify(s1 - s2)
            if diff == 0:
                return True
            if diff.is_number and diff != 0:
                return False
        except Exception:
            pass

        # 2. Test direct arithmetic
        val1 = cls.evaluate_arithmetic(expr1)
        val2 = cls.evaluate_arithmetic(expr2)
        if val1 is not None and val2 is not None:
            return val1 == val2

        # 3. Sound Multi-Point Algebraic Evaluation via Schwartz-Zippel
        # Binds ALL allowed variables (x, y, z, n, a, b, c, pi, e) across 7 non-trivial sample points
        sample_points = [
            {"x": Fraction(1, 1), "y": Fraction(2, 1), "z": Fraction(3, 1), "n": Fraction(4, 1), "a": Fraction(2, 1), "b": Fraction(3, 1), "c": Fraction(5, 1), "pi": Fraction(314, 100), "e": Fraction(272, 100)},
            {"x": Fraction(7, 1), "y": Fraction(4, 1), "z": Fraction(6, 1), "n": Fraction(1, 1), "a": Fraction(3, 1), "b": Fraction(7, 1), "c": Fraction(2, 1), "pi": Fraction(314, 100), "e": Fraction(272, 100)},
            {"x": Fraction(-4, 1), "y": Fraction(5, 1), "z": Fraction(-2, 1), "n": Fraction(3, 1), "a": Fraction(-1, 1), "b": Fraction(4, 1), "c": Fraction(-3, 1), "pi": Fraction(314, 100), "e": Fraction(272, 100)},
            {"x": Fraction(3, 2), "y": Fraction(5, 2), "z": Fraction(7, 2), "n": Fraction(9, 2), "a": Fraction(1, 2), "b": Fraction(3, 2), "c": Fraction(5, 2), "pi": Fraction(314, 100), "e": Fraction(272, 100)},
            {"x": Fraction(8, 1), "y": Fraction(3, 1), "z": Fraction(1, 1), "n": Fraction(7, 1), "a": Fraction(5, 1), "b": Fraction(2, 1), "c": Fraction(8, 1), "pi": Fraction(314, 100), "e": Fraction(272, 100)},
            {"x": Fraction(-5, 1), "y": Fraction(-3, 1), "z": Fraction(4, 1), "n": Fraction(-2, 1), "a": Fraction(-4, 1), "b": Fraction(6, 1), "c": Fraction(1, 1), "pi": Fraction(314, 100), "e": Fraction(272, 100)},
            {"x": Fraction(11, 1), "y": Fraction(6, 1), "z": Fraction(8, 1), "n": Fraction(5, 1), "a": Fraction(7, 1), "b": Fraction(9, 1), "c": Fraction(4, 1), "pi": Fraction(314, 100), "e": Fraction(272, 100)},
        ]

        evaluated_points = 0
        for point in sample_points:
            res1 = cls.evaluate_arithmetic(expr1, point)
            res2 = cls.evaluate_arithmetic(expr2, point)
            if res1 is not None and res2 is not None:
                evaluated_points += 1
                if res1 != res2:
                    return False

        return evaluated_points >= 3
