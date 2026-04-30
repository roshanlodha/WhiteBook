import json
import time
import re
from pathlib import Path
from typing import Any, AsyncGenerator

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from llama_cpp import Llama
from app.calculators import calculate_math

DEFAULT_LLM_PATH = "/data/Qwen3-8B-Q4_K_M.gguf"

MATH_TOOL_SCHEMA = [
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

        self.llm = Llama(
            model_path=str(self.model_path),
            n_gpu_layers=-1,
            n_ctx=16384,
            verbose=False,
        )

    async def setup_mcp(self):
        server_params = StdioServerParameters(
            command="uvx",
            args=["medcalc@latest"]
        )
        self.stdio_transport = stdio_client(server_params)
        self.read, self.write = await self.stdio_transport.__aenter__()
        self.session = ClientSession(self.read, self.write)
        await self.session.__aenter__()
        await self.session.initialize()
        
        # Fetch and format tools into OpenAI schema
        mcp_tools = await self.session.list_tools()
        self.cached_mcp_schemas = []
        for tool in mcp_tools.tools:
            self.cached_mcp_schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            })
        print(f"Loaded {len(self.cached_mcp_schemas)} MCP tools.")

    async def stream_response(
        self,
        query: str,
        retrieved_context: list[dict[str, Any]],
        history: list[dict[str, Any]],
        tools_mode: bool,
        thinking_mode: bool = True,

    ) -> AsyncGenerator[str, None]:
        
        if not tools_mode:
            # Pure RAG Mode
            active_tools = MATH_TOOL_SCHEMA
            system_prompt = "You are a expert medical text interpreter, not a medical expert. Answer only from the provided context. Be direct, concise, and clinically useful. Do not add filler, hedging, or meta commentary. If the answer is not in the context, simply state so. In your response, never mention pages, chunk numbers, filenames, scores, retrieval metadata, or that images or attachments were provided. Give the answer itself, not instructions about the source. Be concise, direct, and clinically useful. Do not make up any language not in the source text. It is ok to repeat the source verbatim if it answers the user's query. Tool use is mandatory where it is necessary: DO NOT perform mental math, you must use tool calls for all deterministic things and anywhere they can be used. When choosing a tool, choose one that will accomplish a task in the fewest tool calls (e.g. dont call the math twice when a single tool will provide the appropriate calculation). As always, plan which tools you will call in order. Be direct and clinically useful."

            # Construct context_string from retrieved_context here
            context_parts: list[str] = []
            for index, chunk in enumerate(retrieved_context, start=1):
                heading = chunk.get("heading_context") or ""
                text = chunk.get("text_content") or ""
                context_parts.append(f"--- Chunk {index} ---\nHeading: {heading}\nText: {text}")
            context_string = "\n\n".join(context_parts) if context_parts else "No retrieved context available."
        else:
            # Pure Calculator Mode
            active_tools = MATH_TOOL_SCHEMA + self.cached_mcp_schemas
            system_prompt = "You are a expert medical calculator, not a medical expert. Based on the requested calculation, choose a tool from your available tools to answer the query. Be direct, concise, and clinically useful. Do not add filler, hedging, or meta commentary. If you are unable to answer due to a lack of tools or a lack of information in the context, simply state so. In your response, never mention pages, chunk numbers, filenames, scores, retrieval metadata, or that images or attachments were provided. Give the answer itself, not instructions about the source. Do not make up any information not in provided input and tool. Tool use is mandatory where it is necessary: DO NOT perform mental math, you must use tool calls for all deterministic things and anywhere they can be used. When choosing a tool, choose one that will accomplish a task in the fewest tool calls (e.g. dont call the math twice when a single tool will provide the appropriate calculation). As always, plan which tools you will call in order. Be direct and clinically useful."
            context_string = "" # Bypass RAG completely

        user_prompt = f"Context:\n{context_string}\n\nQuestion:{query}" if context_string else query
        if thinking_mode:
            user_prompt += "\n\n/think"
        else:
            user_prompt += "\n\n/no_think"

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
                tools=active_tools,
                tool_choice="auto",
                stream=True,
                temperature=0.1,
            )

            full_content = ""
            tool_calls_collected = []
            raw_text_buffer = ""

            for chunk in stream:
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                
                if "tool_calls" in delta:
                    for tc_chunk in delta["tool_calls"]:
                        index = tc_chunk.get("index", 0)
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

                if "content" in delta and delta["content"]:
                    content = delta["content"]
                    full_content += content
                    raw_text_buffer += content
                    if "<tool_call>" not in raw_text_buffer:
                        yield content

            if not tool_calls_collected and ("<tool_call>" in raw_text_buffer or "{" in raw_text_buffer):
                qwen_matches = list(re.finditer(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', raw_text_buffer, re.DOTALL))
                if not qwen_matches:
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
                            full_content = full_content.replace(match.group(0), "").strip()
                    except json.JSONDecodeError:
                        continue

            if not tool_calls_collected:
                break

            messages.append({
                "role": "assistant",
                "content": full_content if full_content else None,
                "tool_calls": tool_calls_collected
            })

            for tool_call in tool_calls_collected:
                name = tool_call["function"]["name"]
                args_raw = tool_call["function"]["arguments"]
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                result = None
                
                try:
                    if name == "calculate_math":
                        result = calculate_math(**args)
                    else:
                        # Execute via MCP
                        try:
                            mcp_response = await self.session.call_tool(name, arguments=args)
                            # MCP responses return a list of content blocks; extract the text
                            result = mcp_response.content[0].text if mcp_response.content else str(mcp_response)
                        except Exception as e:
                            result = {"error": f"MCP execution failed: {str(e)}"}
                except Exception as e:
                    result = {"error": str(e)}

                # Format result for readability
                display_result = result
                if isinstance(result, dict):
                    if "error" in result:
                        display_result = f"Error: {result['error']}"
                    elif "result" in result:
                        display_result = str(result["result"])
                    elif "loading_dose_mg" in result:
                        display_result = f"Loading Dose: {result['loading_dose_mg']} mg (Max: {result['max_dose_mg']} mg)"
                    elif "mean_arterial_pressure" in result:
                        display_result = f"MAP: {result['mean_arterial_pressure']} mmHg"
                    elif "maintenance_rate_ml_hr" in result:
                        display_result = f"Maintenance Rate: {result['maintenance_rate_ml_hr']} mL/hr"
                    elif "wells_score" in result:
                        display_result = f"Wells Score: {result['wells_score']} ({result['probability']} probability)"
                    else:
                        display_result = ", ".join(f"{k}: {v}" for k, v in result.items())

                yield f"<tool_result>{display_result}</tool_result>"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": name,
                    "content": json.dumps(result),
                })