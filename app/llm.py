import json
import time
import re
from pathlib import Path
from typing import Any, AsyncGenerator

from llama_cpp import Llama
from app.calculators import calculate_math

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LLM_PATH = ROOT_DIR / "Qwen3-8B-Q4_K_M.gguf"

AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculate_math",
            "description": "Performs basic math (multiplication, division, addition, subtraction). Use this for ALL calculations to ensure accuracy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression to evaluate (e.g., '17 * 45.36').",
                    }
                },
                "required": ["expression"],
            },
        },
    }
]

class Generator:
    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(model_path) if model_path is not None else DEFAULT_LLM_PATH
        if not self.model_path.exists():
            raise FileNotFoundError(f"LLM not found at {self.model_path}")

        # CRITICAL FIX: Removed chat_format="chatml". 
        # llama-cpp-python will now use the embedded Jinja template in the GGUF
        # which contains Qwen3's specific system prompt logic for tool calling.
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
        
        # We no longer tell it HOW to format JSON. The embedded Jinja template handles that.
        # We only dictate clinical behavior and tool triggering rules.
        system_prompt = (
			"You are a expert medical text interpreter, not a medical expert. Answer only from the provided context. Be direct, concise, and clinically useful. Do not add filler, hedging, or meta commentary. If the answer is not in the context, simply state so. In your response, never mention pages, chunk numbers, filenames, scores, retrieval metadata, or that images or attachments were provided. Give the answer itself, not instructions about the source. Be concise, direct, and clinically useful. Do not make up any language not in the source text. It is ok to repeat the source verbatim if it answers the user's query. Tool use is mandatory where it is necessary: DO NOT perform mental math, you must use tool calls for all deterministic things and anywhere they can be used. When choosing a tool, choose one that will accomplish a task in the fewest tool calls (e.g. dont call the math twice when a single tool will provide the appropriate calculation). As always, plan which tools you will call in order. Be direct and clinically useful."
        )

        context_parts: list[str] = []
        for index, chunk in enumerate(retrieved_context, start=1):
            heading = chunk.get("heading_context") or ""
            text = chunk.get("text_content") or ""
            context_parts.append(f"--- Chunk {index} ---\nHeading: {heading}\nText: {text}")

        context_text = "\n\n".join(context_parts) if context_parts else "No retrieved context available."
        user_prompt = f"Context:\n{context_text}\n\nQuestion:{query}"

        messages = [
            {"role": "system", "content": system_prompt},
            *[
                {"role": message.get("role", "user"), "content": message.get("content", "")}
                for message in history
                if message.get("content")
            ],
            {"role": "user", "content": user_prompt},
        ]

        # The Interception Loop
        while True:
            stream = self.llm.create_chat_completion(
                messages=messages,
                tools=AVAILABLE_TOOLS,
                tool_choice="auto",
                stream=True,
                temperature=0.1,
            )

            full_content = ""
            tool_calls_collected = []
            
            # Buffer for capturing raw unparsed tool calls (fallback mechanism)
            raw_text_buffer = ""

            for chunk in stream:
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                
                # 1. Native Llama-CPP Tool Call Parsing (Ideal Scenario)
                if "tool_calls" in delta:
                    for tc_chunk in delta["tool_calls"]:
                        index = tc_chunk.get("index", 0)
                        
                        # Ensure our list is long enough to hold this index
                        while len(tool_calls_collected) <= index:
                            tool_calls_collected.append({
                                "id": f"call_{int(time.time())}_{index}",
                                "type": "function",
                                "function": {"name": "", "arguments": ""}
                            })
                        
                        target = tool_calls_collected[index]
                        
                        if tc_chunk.get("id"):
                            target["id"] = tc_chunk["id"]
                        if tc_chunk.get("function"):
                            if tc_chunk["function"].get("name"):
                                target["function"]["name"] += tc_chunk["function"]["name"]
                            if tc_chunk["function"].get("arguments"):
                                target["function"]["arguments"] += tc_chunk["function"]["arguments"]
                    continue

                # 2. Standard Content Streaming (Thinking & Answers)
                if "content" in delta and delta["content"]:
                    content = delta["content"]
                    full_content += content
                    raw_text_buffer += content
                    
                    # We yield content immediately to the frontend UNLESS we suspect it's about to hallucinate a raw tool block
                    if "<tool_call>" not in raw_text_buffer and "✿RESULT✿" not in raw_text_buffer:
                        yield content

            # 3. Fallback Parser for Qwen's specific raw formats
            # If llama.cpp failed to parse the tool calls into the delta stream, Qwen might have outputted raw JSON
            if not tool_calls_collected and ("<tool_call>" in raw_text_buffer or "{" in raw_text_buffer):
                # Look for Qwen's specific <tool_call> tags
                qwen_matches = list(re.finditer(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', raw_text_buffer, re.DOTALL))
                if not qwen_matches:
                    # Generic JSON block fallback
                    qwen_matches = list(re.finditer(r'(\{[\s\n]*"name"[\s\n]*:[\s\n]*"[^"]+"[\s\n]*,[\s\n]*"arguments"[\s\n]*:[\s\n]*\{.*\}[\s\n]*\})', raw_text_buffer, re.DOTALL))
                
                for match in qwen_matches:
                    try:
                        tc_data = json.loads(match.group(1))
                        if "name" in tc_data and "arguments" in tc_data:
                            tool_calls_collected.append({
                                "id": f"call_{int(time.time())}_{len(tool_calls_collected)}",
                                "type": "function",
                                "function": tc_data
                            })
                            # Strip the raw JSON from the assistant's content so it doesn't show in the UI
                            full_content = full_content.replace(match.group(0), "").strip()
                    except json.JSONDecodeError:
                        continue

            # If no tools were called either natively or via fallback, the LLM is done thinking/answering
            if not tool_calls_collected:
                break

            # --- Execute Intercepted Tool Calls ---
            
            # Record the assistant's request to use a tool in the history
            messages.append({
                "role": "assistant",
                "content": full_content if full_content else None,
                "tool_calls": tool_calls_collected
            })

            for tool_call in tool_calls_collected:
                name = tool_call["function"]["name"]
                args_raw = tool_call["function"]["arguments"]
                
                # Parse arguments if they are a string (OpenAI standard)
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw

                result = None
                
                # Route to the deterministic Python functions
                try:
                    if name == "calculate_procainamide_dose":
                        result = calculate_procainamide_dose(**args)
                        yield f"\n> **🧮 Calculator Output:** Evaluated Procainamide Dose for {args.get('weight_kg')} kg.\n\n"
                    
                    elif name == "convert_lbs_to_kg":
                        result = convert_lbs_to_kg(**args)
                        yield f"\n> **🧮 Calculator Output:** {args.get('weight_lbs')} lbs = {result} kg.\n\n"
                    
                    elif name == "calculate_math":
                        result = calculate_math(**args)
                        expr = args.get('expression')
                        res_val = result.get('result') if isinstance(result, dict) else result
                        yield f"\n> **🧮 Calculator Output:** `{expr} = {res_val}`\n\n"
                    else:
                        result = {"error": f"Tool '{name}' not found."}
                except Exception as e:
                    result = {"error": str(e)}

                # Inject the mathematical result back into the LLM's context
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": name,
                    "content": json.dumps(result),
                })
            
            # The loop continues: The LLM processes the tool result and generates the final synthesis text