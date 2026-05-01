"""Compact tool surface for the chat model.

Why a dispatcher?
-----------------
The MedCalc package ships ~70 calculators, each with a 500–1000 char docstring.
Sending all of them as separate Groq function-tool definitions costs ~27,000
tokens. Combined with `qwen/qwen3-32b`'s 32k context, that triggers
`HTTP/1.1 413 Payload Too Large` and surfaces as a 502 in the UI.

Instead we expose ONE wrapper tool, `medical_calculator`, whose description
contains a compact catalog (calculator name → one-line summary). The model picks
a calculator name and passes a parameters dict; the dispatcher performs argument
binding against the actual MedCalc Python signature. This collapses the tooling
payload to ~2.5k tokens while preserving access to every calculator.

`calculate_math` remains as a separate, deterministic arithmetic helper.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .calculators import calculate_math

ToolHandler = Callable[[dict[str, Any]], Any]

EXCLUDED_MEDCALC_NAMES = {"main", "shutdown_server", "mean", "calc_mu", "get_cvd_risk_category", "get_trimester"}


def _safe_preview(value: Any, *, limit: int = 600) -> str:
	rendered = str(value)
	return rendered if len(rendered) <= limit else f"{rendered[:limit]}..."


def _extract_param_hints(fn: Callable[..., Any]) -> dict[str, str]:
	"""Pull per-parameter blurbs from a NumPy-style ``Parameters`` docstring section.

	Most MedCalc calculators (and our local ones) document parameters as::

	    Parameters
	    ----------
	    foo : int
	        Description with allowed values (0: ..., 1: ..., 2: ...).

	When the dispatcher reports a missing-required or runtime error, embedding
	these blurbs in the response gives the chat model (and therefore the user)
	the exact vocabulary needed to retry — instead of a bare 'Missing parameters'
	or a TypeError leaking through.
	"""
	doc = inspect.getdoc(fn) or ""
	if not doc:
		return {}
	lines = doc.splitlines()
	param_block_start: int | None = None
	for index, line in enumerate(lines):
		if line.strip().lower() in {"parameters", "parameters:"}:
			param_block_start = index + 1
			# Skip a NumPy-style underline like '----------' if present.
			if (
				param_block_start < len(lines)
				and lines[param_block_start].strip()
				and set(lines[param_block_start].strip()) <= {"-"}
			):
				param_block_start += 1
			break
	if param_block_start is None:
		return {}

	hints: dict[str, str] = {}
	current_name: str | None = None
	current_lines: list[str] = []
	for line in lines[param_block_start:]:
		stripped = line.strip()
		# End of the parameter block (next NumPy section).
		if stripped.lower() in {"returns", "returns:"} or (stripped and set(stripped) <= {"-"} and not current_lines):
			break
		# Header line: 'name : type' at no indent.
		if stripped and not line.startswith((" ", "\t")) and " : " in stripped:
			if current_name and current_lines:
				hints[current_name] = " ".join(current_lines).strip()
			current_name = stripped.split(" : ", 1)[0].strip()
			current_lines = []
		elif stripped:
			current_lines.append(stripped)
	if current_name and current_lines:
		hints[current_name] = " ".join(current_lines).strip()
	return hints


def _format_parameter_hint_line(hints: dict[str, str], names: list[str]) -> str:
	"""Render a compact single-line hint summary for a subset of parameter names."""
	pieces = [f"`{name}` — {hints[name]}" for name in names if name in hints]
	return "; ".join(pieces)


def _import_medcalc_calculator() -> Any | None:
	try:
		from medcalc import calculator
	except Exception:
		return None
	return calculator


def _build_calculator_registry() -> dict[str, Callable[..., Any]]:
	registry: dict[str, Callable[..., Any]] = {}
	calculator_module = _import_medcalc_calculator()
	if calculator_module is None:
		return registry

	for name, fn in inspect.getmembers(calculator_module, inspect.isfunction):
		if fn.__module__ != calculator_module.__name__:
			continue
		if name in EXCLUDED_MEDCALC_NAMES or name.startswith("_"):
			continue
		registry.setdefault(name, fn)
	return registry


def _short_doc(fn: Callable[..., Any]) -> str:
	doc = (fn.__doc__ or fn.__name__).strip()
	first_line = doc.splitlines()[0].strip().rstrip(".")
	return first_line[:90]


def _calculator_catalog(registry: dict[str, Callable[..., Any]]) -> str:
	"""Compact one-line-per-calculator catalog for the tool description."""
	if not registry:
		return ""
	lines: list[str] = []
	for name in sorted(registry):
		fn = registry[name]
		params = ", ".join(inspect.signature(fn).parameters.keys())
		lines.append(f"- {name}({params}) — {_short_doc(fn)}")
	return "\n".join(lines)


def _bind_and_call(fn: Callable[..., Any], params: dict[str, Any]) -> Any:
	signature = inspect.signature(fn)
	accepted = {k: v for k, v in params.items() if k in signature.parameters}
	missing_required = [
		name
		for name, parameter in signature.parameters.items()
		if parameter.default is inspect._empty and name not in accepted
	]
	if missing_required:
		hints = _extract_param_hints(fn)
		hint_line = _format_parameter_hint_line(hints, missing_required)
		message = (
			f"Missing required parameters for {fn.__name__}: "
			f"{', '.join(missing_required)}. Please provide and retry."
		)
		if hint_line:
			message = f"{message} Allowed values — {hint_line}"
		return {
			"error": message,
			"missing": missing_required,
			"parameter_hints": {name: hints[name] for name in missing_required if name in hints},
			"calculator": fn.__name__,
		}
	try:
		bound = signature.bind_partial(**accepted)
		raw_result = fn(*bound.args, **bound.kwargs)
	except Exception as exc:
		hints = _extract_param_hints(fn)
		message = _safe_preview(exc)
		hint_line = _format_parameter_hint_line(hints, list(signature.parameters))
		if hint_line:
			message = f"{message}. Calculator parameter reference — {hint_line}"
		return {
			"calculator": fn.__name__,
			"error": message,
			"parameter_hints": hints,
		}

	# If the calculator already returned a structured dict (with `result`,
	# `risk_class`, etc.), surface those keys at the top level so the chat
	# model and the SSE preview can read them without nested unwrapping.
	if isinstance(raw_result, dict):
		merged = {"calculator": fn.__name__, **raw_result}
		return merged
	return {"calculator": fn.__name__, "result": raw_result}


def _build_medical_calculator_tool(
	registry: dict[str, Callable[..., Any]],
) -> tuple[dict[str, Any], ToolHandler]:
	catalog = _calculator_catalog(registry)
	available_names = sorted(registry.keys())
	description = (
		"Run a named clinical calculator/score. Use this for HEART, Wells, "
		"CHA2DS2-VASc, MAP, BMI, BSA, MELD, NIHSS, GCS, CURB-65, SOFA, PSI/PORT, "
		"PESI, etc. Pick `name` from the catalog below and pass numeric/boolean "
		"inputs in `parameters` matching the calculator's argument names exactly. "
		"For Pneumonia Severity Index use `psi_port_score`. For Pulmonary "
		"Embolism severity use `pesi_score` (or `simplified_pesi_score`).\n\n"
		f"Catalog:\n{catalog}"
	)
	tool_definition = {
		"type": "function",
		"function": {
			"name": "medical_calculator",
			"description": description[:3500],
			"parameters": {
				"type": "object",
				"properties": {
					"name": {
						"type": "string",
						"description": "Calculator name from the catalog.",
						"enum": available_names,
					},
					"parameters": {
						"type": "object",
						"description": "Keyword arguments for the calculator.",
						"additionalProperties": True,
					},
				},
				"required": ["name", "parameters"],
			},
		},
	}

	def _handler(args: dict[str, Any]) -> Any:
		name = str(args.get("name", "")).strip()
		params = args.get("parameters") or {}
		if not isinstance(params, dict):
			return {
				"error": "`parameters` must be an object of keyword arguments.",
				"calculator": name,
			}
		fn = registry.get(name)
		if fn is None:
			return {
				"error": (
					f"Calculator '{name}' is not available. Pick one from the catalog "
					f"in the tool description."
				),
				"calculator": name,
			}
		return _bind_and_call(fn, params)

	return tool_definition, _handler


def _build_math_tool() -> tuple[dict[str, Any], ToolHandler]:
	tool_definition = {
		"type": "function",
		"function": {
			"name": "calculate_math",
			"description": (
				"Evaluate a deterministic arithmetic expression. Use this for any "
				"plain numeric work that is NOT a named clinical score (weight "
				"conversions, unit math, totals, ratios)."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"expression": {
						"type": "string",
						"description": "Math expression, e.g. '(100 / 2.20462) * 17'.",
					}
				},
				"required": ["expression"],
			},
		},
	}
	handler: ToolHandler = lambda args: calculate_math(expression=str(args.get("expression", "")))
	return tool_definition, handler


def build_calculator_tools() -> tuple[list[dict[str, Any]], dict[str, ToolHandler]]:
	"""Calculator-mode tool surface: math + medical_calculator dispatcher.

	Used when the user explicitly toggles Calculate. Carries the full clinical
	calculator catalog (~1.4k tokens) but no retrieval payload.
	"""
	math_tool, math_handler = _build_math_tool()
	tools: list[dict[str, Any]] = [math_tool]
	handlers: dict[str, ToolHandler] = {"calculate_math": math_handler}

	registry = _build_calculator_registry()
	if registry:
		dispatcher_tool, dispatcher_handler = _build_medical_calculator_tool(registry)
		tools.append(dispatcher_tool)
		handlers["medical_calculator"] = dispatcher_handler

	return tools, handlers


def build_rag_tools() -> tuple[list[dict[str, Any]], dict[str, ToolHandler]]:
	"""RAG-mode tool surface: NO calculator tools."""
	return [], {}


# Backwards-compatible names used by older callers/tests.
def build_always_available_tools() -> tuple[list[dict[str, Any]], dict[str, ToolHandler]]:
	return build_calculator_tools()


def build_chat_tools() -> tuple[list[dict[str, Any]], dict[str, ToolHandler]]:
	return build_calculator_tools()


def build_medcalc_tools() -> tuple[list[dict[str, Any]], dict[str, ToolHandler]]:
	registry = _build_calculator_registry()
	if not registry:
		return [], {}
	tool, handler = _build_medical_calculator_tool(registry)
	return [tool], {"medical_calculator": handler}
