from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from groq import APIConnectionError, AsyncGroq, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

GROQ_SYSTEM_INJECTION = (
    "You must write your internal clinical reasoning inside <think>...</think> "
    "tags before providing your final answer."
)
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"


def _append_system_injection(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if not messages:
        return [{"role": "system", "content": GROQ_SYSTEM_INJECTION}]

    merged = [dict(message) for message in messages]
    first = merged[0]
    if first.get("role") == "system":
        content = (first.get("content") or "").strip()
        first["content"] = (
            f"{content}\n\n{GROQ_SYSTEM_INJECTION}" if content else GROQ_SYSTEM_INJECTION
        )
        return merged

    return [{"role": "system", "content": GROQ_SYSTEM_INJECTION}, *merged]


@retry(
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
    wait=wait_exponential_jitter(initial=1, max=16),
    stop=stop_after_attempt(5),
    reraise=True,
)
async def _start_groq_stream(
    client: AsyncGroq,
    model: str,
    messages: list[dict[str, str]],
):
    return await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        temperature=0.1,
    )


async def stream_groq(messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        payload = {"error": "GROQ_API_KEY is not configured"}
        yield f"data: {json.dumps(payload)}\n\n"
        return

    model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    patched_messages = _append_system_injection(messages)
    client = AsyncGroq(api_key=api_key)

    try:
        stream = await _start_groq_stream(client=client, model=model, messages=patched_messages)
        async for chunk in stream:
            choices: list[Any] = chunk.choices or []
            if not choices:
                continue
            text = choices[0].delta.content or ""
            if text:
                yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"
    except (RateLimitError, APIConnectionError) as exc:
        payload = {"error": f"Transient Groq error after retries: {str(exc)}"}
        yield f"data: {json.dumps(payload)}\n\n"
    except Exception as exc:  # pragma: no cover - external provider behavior
        payload = {"error": f"Groq streaming failed: {str(exc)}"}
        yield f"data: {json.dumps(payload)}\n\n"
    finally:
        await client.close()


async def stream_modal(messages: list[dict[str, str]]) -> AsyncGenerator[str, None]:
    modal_url = os.getenv("MODAL_INFERENCE_URL")
    if not modal_url:
        payload = {"error": "MODAL_INFERENCE_URL is not configured"}
        yield f"data: {json.dumps(payload)}\n\n"
        return

    timeout = httpx.Timeout(connect=20.0, read=None, write=20.0, pool=20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                modal_url,
                json={"messages": messages},
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_text():
                    if chunk:
                        yield chunk
    except httpx.HTTPStatusError as exc:
        payload = {
            "error": "Modal request failed",
            "status_code": exc.response.status_code,
            "detail": exc.response.text,
        }
        yield f"data: {json.dumps(payload)}\n\n"
    except httpx.HTTPError as exc:
        payload = {"error": f"Modal connection error: {str(exc)}"}
        yield f"data: {json.dumps(payload)}\n\n"
    except Exception as exc:  # pragma: no cover - external provider behavior
        payload = {"error": f"Modal streaming failed: {str(exc)}"}
        yield f"data: {json.dumps(payload)}\n\n"
