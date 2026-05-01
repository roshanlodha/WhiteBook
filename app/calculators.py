"""Deterministic arithmetic helper used by the LLM tool.

`eval()` is intentionally avoided. We compile the expression to a constant
arithmetic AST and walk it; anything outside `+ - * / // % **` and numeric
literals is rejected. This keeps the tool safe even if the model is induced to
emit hostile expressions.
"""

from __future__ import annotations

import ast
import math
import operator

_BIN_OPS: dict[type[ast.operator], object] = {
	ast.Add: operator.add,
	ast.Sub: operator.sub,
	ast.Mult: operator.mul,
	ast.Div: operator.truediv,
	ast.FloorDiv: operator.floordiv,
	ast.Mod: operator.mod,
	ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], object] = {
	ast.UAdd: operator.pos,
	ast.USub: operator.neg,
}

_ALLOWED_NAMES: dict[str, float] = {"pi": math.pi, "e": math.e}


def _evaluate(node: ast.AST) -> float:
	if isinstance(node, ast.Expression):
		return _evaluate(node.body)
	if isinstance(node, ast.Constant):
		if isinstance(node.value, (int, float)):
			return float(node.value)
		raise ValueError(f"Unsupported literal: {node.value!r}")
	if isinstance(node, ast.Name):
		if node.id in _ALLOWED_NAMES:
			return float(_ALLOWED_NAMES[node.id])
		raise ValueError(f"Unsupported name: {node.id}")
	if isinstance(node, ast.BinOp):
		op_type = type(node.op)
		if op_type not in _BIN_OPS:
			raise ValueError(f"Unsupported operator: {op_type.__name__}")
		left = _evaluate(node.left)
		right = _evaluate(node.right)
		return float(_BIN_OPS[op_type](left, right))  # type: ignore[arg-type]
	if isinstance(node, ast.UnaryOp):
		op_type = type(node.op)
		if op_type not in _UNARY_OPS:
			raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
		operand = _evaluate(node.operand)
		return float(_UNARY_OPS[op_type](operand))  # type: ignore[operator]
	raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def calculate_math(expression: str) -> dict:
	"""Evaluate `expression` (basic arithmetic) and return a structured result."""
	expression = (expression or "").strip()
	if not expression:
		return {"error": "Empty expression."}
	try:
		tree = ast.parse(expression, mode="eval")
		result = _evaluate(tree)
	except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
		return {"error": f"{type(exc).__name__}: {exc}", "expression": expression}

	if math.isnan(result) or math.isinf(result):
		return {"error": "Result is not a finite number.", "expression": expression}

	rounded = round(result, 4)
	return {"expression": expression, "result": rounded}
