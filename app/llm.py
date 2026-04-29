from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncGenerator

from llama_cpp import Llama


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LLM_PATH = ROOT_DIR / "Qwen3-8B-Q4_K_M.gguf"


class Generator:
	def __init__(self, model_path: str | Path | None = None) -> None:
		self.model_path = Path(model_path) if model_path is not None else DEFAULT_LLM_PATH
		if not self.model_path.exists():
			raise FileNotFoundError(f"LLM not found at {self.model_path}")

		self.llm = Llama(
			model_path=str(self.model_path),
			n_gpu_layers=-1,
			n_ctx=4096,
			verbose=False,
		)

	async def stream_response(
		self,
		query: str,
		retrieved_context: list[dict[str, Any]],
		history: list[dict[str, Any]],
	) -> AsyncGenerator[str, None]:
		system_prompt = (
			"You are a expert medical text interpreter, not a medical expert. Answer only from the provided context. Be direct, concise, and clinically useful. Do not add filler, hedging, or meta commentary. If the answer is not in the context, simply state so. In your response, never mention pages, chunk numbers, filenames, scores, retrieval metadata, or that images or attachments were provided. Give the answer itself, not instructions about the source. Be concise, direct, and clinically useful. Do not make up any language not in the source text. It is ok to repeat the source verbatim if it answers the user's query."
		)

		context_parts: list[str] = []
		for index, chunk in enumerate(retrieved_context, start=1):
			heading = chunk.get("heading_context") or ""
			text = chunk.get("text_content") or ""
			context_parts.append(
				f"--- Chunk {index} ---\n"
				f"Heading: {heading}\n"
				f"Text: {text}"
			)

		context_text = "\n\n".join(context_parts) if context_parts else "No retrieved context available."
		user_prompt = f"Context:\n{context_text}\n\nQuestion:{query}\n\n/think"

		messages = [
			{"role": "system", "content": system_prompt},
			*[
				{"role": message.get("role", "user"), "content": message.get("content", "")}
				for message in history
				if message.get("content")
			],
			{"role": "user", "content": user_prompt},
		]

		stream = self.llm.create_chat_completion(
			messages=messages,
			stream=True,
			temperature=0.6,
			top_p=0.95,
			presence_penalty=1.5,
		)

		for chunk in stream:
			delta = chunk.get("choices", [{}])[0].get("delta", {})
			text = delta.get("content")
			if text:
				yield text
