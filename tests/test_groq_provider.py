import asyncio
import json

import pytest

from app.providers.groq_provider import (
    GroqConfigError,
    GroqPayloadTooLargeError,
    MAX_PROMPT_TOKENS,
    _trim_to_budget,
    build_chat_payload,
    format_sse_data,
    map_groq_error,
)


def test_payload_construction_preserves_message_order() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ]

    payload = build_chat_payload(model="test-model", messages=messages)

    assert payload["model"] == "test-model"
    assert payload["stream"] is True
    assert [m["role"] for m in payload["messages"]] == ["system", "user", "assistant", "user"]


def test_error_mapping_for_timeout() -> None:
    mapped = map_groq_error(asyncio.TimeoutError())

    assert mapped["type"] == "timeout"
    assert mapped["status_code"] == 504


def test_error_mapping_for_config_error() -> None:
    mapped = map_groq_error(GroqConfigError("GROQ_API_KEY is not configured"))

    assert mapped["type"] == "configuration_error"
    assert mapped["status_code"] == 500
    assert mapped["error"] == "GROQ_API_KEY is not configured"


def test_error_mapping_for_payload_too_large() -> None:
    mapped = map_groq_error(GroqPayloadTooLargeError("payload too large"))

    assert mapped["type"] == "payload_too_large"
    assert mapped["status_code"] == 413


def test_stream_chunk_formatting() -> None:
    assert format_sse_data("hello") == "data: hello\n\n"
    assert format_sse_data("line one\nline two") == "data: line one\ndata: line two\n\n"


def test_trim_to_budget_preserves_system_and_last_user() -> None:
    big = "x" * 60_000
    messages = [
        {"role": "system", "content": "you are an assistant"},
        {"role": "user", "content": big},
        {"role": "assistant", "content": big},
        {"role": "user", "content": "what now?"},
    ]

    trimmed = _trim_to_budget(messages, tools=None, budget=4_000)

    roles = [m["role"] for m in trimmed]
    assert roles[0] == "system"
    assert trimmed[-1]["role"] == "user"
    assert trimmed[-1]["content"] == "what now?"


def test_trim_to_budget_noop_when_under_budget() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    assert _trim_to_budget(messages, tools=None, budget=MAX_PROMPT_TOKENS) == messages
