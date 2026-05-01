"""Groq streaming chat provider with tool-calling, token budget, and 413 guard.

This module owns every Groq API call. It implements:

- A static-prefix-first message order so prompt caching can engage when we
  switch to a cache-eligible model.
- A token-budget guard: large `qwen/qwen3-32b` payloads have triggered
  HTTP 413 in production, surfacing as a useless 502 in the UI. We estimate
  payload size up-front and trim the oldest non-system messages until we are
  within `MAX_PROMPT_TOKENS`.
- A tool-call loop that runs the non-streaming completion only as long as the
  model emits tool calls. Once the model is ready to answer, we switch to a
  streaming completion so the user sees the answer token-by-token.
- Error mapping so the frontend can render actionable, user-safe messages
  instead of "Groq streaming failed".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from collections.abc import AsyncGenerator
from typing import Any, Awaitable, Callable

from groq import APIConnectionError, APIError, APIStatusError, AsyncGroq, RateLimitError

logger = logging.getLogger("whitebook.groq")

DEFAULT_GROQ_MODEL = "qwen/qwen3-32b"
DEFAULT_GROQ_TIMEOUT_SECONDS = 60.0
MAX_TOOL_ROUNDS = 4
MAX_PROMPT_TOKENS = 24_000
MAX_TOOL_RESULT_CHARS = 1_800
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_OUTPUT_TOKENS = 1_400

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]


class GroqProviderError(Exception):
	status_code = 502
	error_type = "upstream_error"

	def __init__(self, detail: str, *, status_code: int | None = None, error_type: str | None = None) -> None:
		super().__init__(detail)
		if status_code is not None:
			self.status_code = status_code
		if error_type is not None:
			self.error_type = error_type


class GroqConfigError(GroqProviderError):
	status_code = 500
	error_type = "configuration_error"


class GroqUpstreamTimeoutError(GroqProviderError):
	status_code = 504
	error_type = "timeout"


class GroqPayloadTooLargeError(GroqProviderError):
	status_code = 413
	error_type = "payload_too_large"


def build_chat_payload(*, model: str, messages: list[dict[str, str]], temperature: float = DEFAULT_TEMPERATURE) -> dict[str, Any]:
	return {
		"model": model,
		"messages": messages,
		"stream": True,
		"temperature": temperature,
	}


def format_sse_data(payload: str) -> str:
	lines = payload.splitlines() or [""]
	return "".join(f"data: {line}\n" for line in lines) + "\n"


def _approx_message_tokens(message: dict[str, Any]) -> int:
	content = message.get("content")
	tool_calls = message.get("tool_calls")
	cost = 0
	if isinstance(content, str):
		cost += max(1, len(content) // 4)
	if isinstance(tool_calls, list):
		cost += max(1, len(json.dumps(tool_calls)) // 4)
	return cost + 6  # role overhead


def _approx_conversation_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> int:
	total = sum(_approx_message_tokens(m) for m in messages)
	if tools:
		total += max(1, len(json.dumps(tools)) // 4)
	return total


def _trim_to_budget(
	messages: list[dict[str, Any]],
	tools: list[dict[str, Any]] | None,
	budget: int,
) -> list[dict[str, Any]]:
	"""Drop the oldest non-system messages until we fit within `budget`.

	System messages and the most recent user turn are always preserved so the
	model never loses its role and never loses the question we are answering.
	"""
	if _approx_conversation_tokens(messages, tools) <= budget:
		return messages

	system_msgs = [m for m in messages if m.get("role") == "system"]
	conversation = [m for m in messages if m.get("role") != "system"]
	if not conversation:
		return messages

	last_user_index: int | None = None
	for index in range(len(conversation) - 1, -1, -1):
		if conversation[index].get("role") == "user":
			last_user_index = index
			break

	keep_tail_from = last_user_index if last_user_index is not None else max(0, len(conversation) - 1)
	preserved_tail = conversation[keep_tail_from:]
	candidates = conversation[:keep_tail_from]

	while candidates and _approx_conversation_tokens(system_msgs + candidates + preserved_tail, tools) > budget:
		candidates.pop(0)

	if _approx_conversation_tokens(system_msgs + candidates + preserved_tail, tools) > budget:
		# Last resort: shrink the largest message body.
		all_remaining = system_msgs + candidates + preserved_tail
		largest_index = max(range(len(all_remaining)), key=lambda i: _approx_message_tokens(all_remaining[i]))
		message = dict(all_remaining[largest_index])
		content = message.get("content") or ""
		if isinstance(content, str) and len(content) > 800:
			message["content"] = content[:800].rstrip() + "\n\n[content trimmed by token budget guard]"
			all_remaining[largest_index] = message
		return all_remaining

	return system_msgs + candidates + preserved_tail


def map_groq_error(exc: Exception) -> dict[str, Any]:
	is_provider_timeout = exc.__class__.__name__ == "APITimeoutError"
	if isinstance(exc, GroqProviderError):
		return {
			"error": str(exc),
			"type": exc.error_type,
			"status_code": exc.status_code,
		}
	if is_provider_timeout or isinstance(exc, asyncio.TimeoutError):
		mapped: GroqProviderError = GroqUpstreamTimeoutError("Groq request timed out. Please retry.")
	elif isinstance(exc, RateLimitError):
		retry_after_seconds = _extract_retry_after_seconds(exc)
		retry_hint = (
			f" Please retry in about {retry_after_seconds} seconds." if retry_after_seconds is not None else " Please retry in a moment."
		)
		mapped = GroqProviderError(
			f"WhiteBook is rate-limited by Groq.{retry_hint}",
			status_code=429,
			error_type="rate_limit",
		)
	elif isinstance(exc, APIConnectionError):
		mapped = GroqProviderError(
			"Could not reach Groq. Check connectivity and try again.",
			status_code=502,
			error_type="connection_error",
		)
	elif isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 413:
		mapped = GroqPayloadTooLargeError(
			"This conversation is too long for the model. Start a new chat to reset context."
		)
	elif isinstance(exc, APIError):
		mapped = GroqProviderError(
			f"Groq returned an error: {getattr(exc, 'message', str(exc))}",
			status_code=getattr(exc, "status_code", 502) or 502,
			error_type="upstream_error",
		)
	else:
		mapped = GroqProviderError("Groq streaming failed", status_code=502, error_type="upstream_error")
	payload = {
		"error": str(mapped),
		"type": mapped.error_type,
		"status_code": mapped.status_code,
	}
	if isinstance(exc, RateLimitError):
		retry_after_seconds = _extract_retry_after_seconds(exc)
		if retry_after_seconds is not None:
			payload["retry_after_seconds"] = retry_after_seconds
	return payload


def _extract_retry_after_seconds(exc: RateLimitError) -> int | None:
	"""Best-effort parse of retry-after from headers/body text."""
	response = getattr(exc, "response", None)
	headers = getattr(response, "headers", None) if response is not None else None
	if headers:
		raw_retry_after = headers.get("retry-after") or headers.get("Retry-After")
		if raw_retry_after:
			parsed = _parse_retry_after_value(raw_retry_after)
			if parsed is not None:
				return parsed
	error_text = str(getattr(exc, "message", "") or str(exc))
	return _parse_retry_after_from_text(error_text)


def _parse_retry_after_value(raw_retry_after: str) -> int | None:
	try:
		return max(1, int(float(raw_retry_after.strip())))
	except ValueError:
		pass
	try:
		retry_at = datetime.fromisoformat(raw_retry_after.strip())
		now = datetime.now(tz=retry_at.tzinfo or timezone.utc)
		seconds = int((retry_at - now).total_seconds())
		return max(1, seconds)
	except ValueError:
		try:
			retry_at = parsedate_to_datetime(raw_retry_after.strip())
			now = datetime.now(tz=retry_at.tzinfo or timezone.utc)
			seconds = int((retry_at - now).total_seconds())
			return max(1, seconds)
		except (TypeError, ValueError):
			pass
	return None


def _parse_retry_after_from_text(error_text: str) -> int | None:
	if not error_text:
		return None
	patterns = [
		r"retry (?:again )?in\s+(\d+)\s*(?:seconds|second|secs|sec|s)\b",
		r"try again in\s+(\d+)\s*(?:seconds|second|secs|sec|s)\b",
	]
	for pattern in patterns:
		match = re.search(pattern, error_text, flags=re.IGNORECASE)
		if match:
			return max(1, int(match.group(1)))
	return None


def _trim_tool_result_for_followup(result: Any) -> Any:
	"""Tool results echoed back to the model are capped to keep follow-up payload small."""
	rendered = json.dumps(result) if not isinstance(result, str) else result
	if len(rendered) <= MAX_TOOL_RESULT_CHARS:
		return result
	if isinstance(result, dict):
		trimmed = dict(result)
		for key, value in trimmed.items():
			as_text = str(value)
			if len(as_text) > 600:
				trimmed[key] = as_text[:600] + "…"
		return trimmed
	return rendered[:MAX_TOOL_RESULT_CHARS] + "…"


def _chunk_for_streaming(text: str, chunk_size: int = 18) -> list[str]:
	"""Split a non-streamed answer into small SSE-friendly chunks.

	Used when the tool-loop returns a final answer in a single non-streaming
	completion: we want the UI to still see incremental tokens (smooth typing)
	but we MUST NOT re-call the model to stream the same content (that path
	caused the answer to be emitted twice).
	"""
	if not text:
		return []
	chunks: list[str] = []
	for start in range(0, len(text), chunk_size):
		chunks.append(text[start : start + chunk_size])
	return chunks


def _tool_result_preview(result: Any) -> str:
	if isinstance(result, dict):
		if "error" in result:
			calculator = result.get("calculator")
			prefix = f"{calculator}: " if calculator else ""
			return f"{prefix}Error — {result['error']}"
		if "result" in result:
			calculator = result.get("calculator")
			prefix = f"{calculator}: " if calculator else ""
			risk_band = result.get("risk_class") or result.get("interpretation")
			if risk_band:
				return f"{prefix}{result['result']} — {risk_band}"
			return f"{prefix}{result['result']}"
		return ", ".join(f"{key}: {value}" for key, value in result.items())
	return str(result)


async def _stream_final_answer(
	client: AsyncGroq,
	*,
	model: str,
	messages: list[dict[str, Any]],
	temperature: float = DEFAULT_TEMPERATURE,
) -> AsyncGenerator[str, None]:
	stream = await client.chat.completions.create(
		model=model,
		messages=messages,
		stream=True,
		temperature=temperature,
		max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
	)
	async with asyncio.timeout(DEFAULT_GROQ_TIMEOUT_SECONDS):
		async for chunk in stream:
			choices: list[Any] = chunk.choices or []
			if not choices:
				continue
			token = choices[0].delta.content or ""
			if token:
				yield format_sse_data(token)


async def stream_chat(
	messages: list[dict[str, str]],
	*,
	tools: list[dict[str, Any]] | None = None,
	tool_executor: ToolExecutor | None = None,
) -> AsyncGenerator[str, None]:
	api_key = os.getenv("GROQ_API_KEY")
	if not api_key:
		yield format_sse_data(json.dumps(map_groq_error(GroqConfigError("GROQ_API_KEY is not configured"))))
		return

	model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
	# Disable SDK-level automatic retries so 429s surface immediately and the
	# frontend can offer explicit user-controlled retry.
	client = AsyncGroq(api_key=api_key, timeout=DEFAULT_GROQ_TIMEOUT_SECONDS, max_retries=0)
	conversation: list[dict[str, Any]] = _trim_to_budget(
		[dict(message) for message in messages],
		tools,
		MAX_PROMPT_TOKENS,
	)

	final_answer_emitted = False
	try:
		if tools and tool_executor:
			for _tool_round in range(MAX_TOOL_ROUNDS):
				conversation = _trim_to_budget(conversation, tools, MAX_PROMPT_TOKENS)
				completion = await client.chat.completions.create(
					model=model,
					messages=conversation,
					tools=tools,
					tool_choice="auto",
					stream=False,
					temperature=DEFAULT_TEMPERATURE,
					max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
				)
				assistant_message = completion.choices[0].message
				tool_calls = assistant_message.tool_calls or []

				if not tool_calls:
					if assistant_message.content:
						# Stream the already-produced answer character-by-character
						# so the UI sees a smooth typing effect AND we never re-call
						# the model (which would duplicate the answer).
						for token in _chunk_for_streaming(assistant_message.content):
							yield format_sse_data(token)
						final_answer_emitted = True
					break

				conversation.append(
					{
						"role": "assistant",
						"content": assistant_message.content or "",
						"tool_calls": [
							{
								"id": tool_call.id,
								"type": "function",
								"function": {
									"name": tool_call.function.name,
									"arguments": tool_call.function.arguments,
								},
							}
							for tool_call in tool_calls
						],
					}
				)

				for tool_call in tool_calls:
					try:
						raw_args = tool_call.function.arguments or "{}"
						parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
					except Exception:
						parsed_args = {}

					result = await tool_executor(tool_call.function.name, parsed_args)
					yield format_sse_data(f"<tool_result>{_tool_result_preview(result)}</tool_result>")

					trimmed_result = _trim_tool_result_for_followup(result)
					conversation.append(
						{
							"role": "tool",
							"tool_call_id": tool_call.id,
							"name": tool_call.function.name,
							"content": json.dumps(trimmed_result),
						}
					)
			else:
				# Reached MAX_TOOL_ROUNDS without an answer — push the model to finalize.
				conversation.append(
					{
						"role": "system",
						"content": (
							"You have used the maximum number of tool calls. Produce the final "
							"answer now using the prior tool results and retrieved context, with "
							"no further tool calls."
						),
					}
				)

		if not final_answer_emitted:
			final_messages = _trim_to_budget(conversation, None, MAX_PROMPT_TOKENS)
			async for frame in _stream_final_answer(client, model=model, messages=final_messages):
				yield frame
		yield format_sse_data("[DONE]")
	except Exception as exc:
		logger.exception("Groq stream failed")
		yield format_sse_data(json.dumps(map_groq_error(exc)))
	finally:
		await client.close()
