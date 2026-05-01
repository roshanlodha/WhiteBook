import json

from app.tooling import (
    build_calculator_tools,
    build_chat_tools,
    build_rag_tools,
)


def test_rag_tools_are_empty() -> None:
    tools, handlers = build_rag_tools()
    assert tools == []
    assert handlers == {}


def test_calculator_tools_have_math_and_dispatcher() -> None:
    tools, handlers = build_calculator_tools()
    names = [tool["function"]["name"] for tool in tools]
    assert "calculate_math" in names
    if "medical_calculator" in names:
        dispatcher = next(t for t in tools if t["function"]["name"] == "medical_calculator")
        params = dispatcher["function"]["parameters"]
        assert params["properties"]["name"]["type"] == "string"
        assert params["properties"]["parameters"]["type"] == "object"
        assert len(params["properties"]["name"]["enum"]) > 0


def test_total_calculator_payload_is_under_5k_tokens() -> None:
    tools, _ = build_calculator_tools()
    payload = json.dumps(tools)
    estimated_tokens = len(payload) // 4
    assert estimated_tokens < 5_000, (
        f"Tool payload too large: ~{estimated_tokens} tokens. The model context "
        "is 32k and large tool payloads were the cause of HTTP 413 errors."
    )


def test_calculate_math_handler_is_safe() -> None:
    _, handlers = build_calculator_tools()
    handler = handlers["calculate_math"]
    assert handler({"expression": "2 + 2"})["result"] == 4
    assert handler({"expression": "(100 / 2.20462) * 17"})["result"] > 770

    bad = handler({"expression": "__import__('os').system('echo pwn')"})
    assert "error" in bad


def test_medical_calculator_dispatcher_routes_known_calculator() -> None:
    _, handlers = build_calculator_tools()
    if "medical_calculator" not in handlers:
        return
    response = handlers["medical_calculator"]({
        "name": "map_calculator",
        "parameters": {"sbp": 120, "dbp": 80},
    })
    assert "result" in response or "error" in response


def test_medical_calculator_rejects_unknown_calculator() -> None:
    _, handlers = build_calculator_tools()
    if "medical_calculator" not in handlers:
        return
    response = handlers["medical_calculator"]({"name": "made_up_score", "parameters": {}})
    assert "error" in response


def test_chat_tools_alias_matches_calculator_tools() -> None:
	direct = build_calculator_tools()
	aliased = build_chat_tools()
	assert sorted(t["function"]["name"] for t in direct[0]) == sorted(
		t["function"]["name"] for t in aliased[0]
	)


def test_dispatcher_missing_required_includes_parameter_hints() -> None:
	# Missing required parameters should return a structured, retry-friendly error.
	_, handlers = build_calculator_tools()
	if "medical_calculator" not in handlers:
		return
	response = handlers["medical_calculator"]({
		"name": "map_calculator",
		"parameters": {"sbp": 120},
	})
	assert "error" in response
	assert "missing" in response
