from __future__ import annotations

import asyncio
import modal

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .database import VectorStore
from .prompts import (
	SYSTEM_PROMPT,
	build_calculator_messages,
	build_chat_messages,
	build_retrieval_query,
)
from .providers.groq_provider import stream_chat as stream_groq_chat
from .tooling import build_calculator_tools, build_rag_tools

load_dotenv()

# Modal provides the driver / libcuda, but not libcudart. llama-cpp-python's cu121
# wheel links against libcudart.so.12 — use NVIDIA's CUDA 12 runtime image (see Modal CUDA guide).
_CUDA_TAG = "12.4.0-runtime-ubuntu22.04"

image = (
	modal.Image.from_registry(f"nvidia/cuda:{_CUDA_TAG}", add_python="3.12")
	.entrypoint([])
	.pip_install(
		"fastapi",
		"uvicorn",
		"sse-starlette",
		"sentence-transformers",
		"numpy",
		"httpx",
		"groq",
		"tenacity",
		"uv",
	)
	.pip_install(
		"llama-cpp-python",
		extra_index_url="https://abetlen.github.io/llama-cpp-python/whl/cu121",
	)
	.pip_install("mcp", "medcalc")
	.run_commands(
		"python -c \"from sentence_transformers import SentenceTransformer; SentenceTransformer('Alibaba-NLP/gte-modernbert-base', trust_remote_code=True)\""
	)
	.add_local_dir("static", "/app/static")
	.add_local_dir("images", "/app/images")
)

app_modal = modal.App("whitebook", image=image)
volume = modal.Volume.from_name("whitebook-data")


class RetrieveRequest(BaseModel):
	query: str = Field(..., min_length=1, description="Clinical query to retrieve context for")
	top_k: int = Field(default=5, ge=1, le=20, description="Maximum number of chunks to return")
	cutoff: float = Field(default=0.6, ge=0.0, le=1.0, description="Minimum cosine similarity score")


class ChunkResponse(BaseModel):
	id: str
	heading_context: str | None = None
	text_content: str
	page_start: int | None = None
	page_end: int | None = None
	image_filename: str | None = None
	score: float


class RetrieveResponse(BaseModel):
	results: list[ChunkResponse]


class ChatMessage(BaseModel):
	role: Literal["user", "assistant"]
	content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
	query: str = Field(..., min_length=1, description="Clinical query to answer")
	history: list[ChatMessage] = Field(default_factory=list, description="Prior conversation turns")
	backend: Literal["groq"] = Field(
		default="groq",
		description='Generation backend. This migration supports only "groq".',
	)
	tools_mode: bool = Field(
		default=False,
		description=(
			"If true, route the query through the clinical calculator path "
			"(MedCalc tools only, no WhiteBook retrieval). If false, "
			"route through the strict RAG path (no tools attached, much smaller "
			"per-request payload)."
		),
	)
	thinking_mode: bool = Field(default=False, description="If true, request Qwen thinking mode (/think).")


def _normalize_image_filename(raw_filename: str | None) -> str | None:
	if not raw_filename:
		return None

	safe_name = Path(raw_filename).name
	candidates = [safe_name]
	stem = Path(safe_name).stem
	for ext in (".png", ".jpg", ".jpeg", ".webp"):
		candidate = f"{stem}{ext}"
		if candidate not in candidates:
			candidates.append(candidate)

	for candidate in candidates:
		if (IMAGES_DIR / candidate).exists():
			return candidate
	return None


def _with_resolved_images(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
	resolved: list[dict[str, Any]] = []
	for chunk in chunks:
		normalized = dict(chunk)
		normalized["image_filename"] = _normalize_image_filename(chunk.get("image_filename"))
		resolved.append(normalized)
	return resolved


async def _initialize_runtime(app: FastAPI) -> None:
	"""Initialize heavy runtime components in a worker thread."""
	try:
		vector_store = await asyncio.to_thread(VectorStore)

		app.state.vector_store = vector_store
		app.state.initialized = True
		app.state.initialization_error = None
	except Exception as exc:
		app.state.initialized = False
		app.state.initialization_error = str(exc)
		raise


def _capture_init_task_result(task: asyncio.Task[None], app: FastAPI) -> None:
	"""Avoid unobserved task-exception warnings for warmup task."""
	try:
		task.exception()
	except asyncio.CancelledError:
		app.state.initialization_error = "Initialization task cancelled"
	finally:
		if getattr(app.state, "initialization_task", None) is task:
			app.state.initialization_task = None


async def ensure_runtime_ready(app: FastAPI) -> None:
	"""Ensure initialization finishes before handling model-backed routes."""
	if getattr(app.state, "initialized", False):
		return

	lock: asyncio.Lock = app.state.init_lock
	async with lock:
		if getattr(app.state, "initialized", False):
			return
		if getattr(app.state, "initialization_task", None):
			task: asyncio.Task[None] = app.state.initialization_task
			await task
			return
		task = asyncio.create_task(_initialize_runtime(app))
		app.state.initialization_task = task
		task.add_done_callback(lambda t: _capture_init_task_result(t, app))
		await task



@asynccontextmanager
async def lifespan(app: FastAPI):
	app.state.vector_store = None
	app.state.initialized = False
	app.state.initialization_error = None
	app.state.init_lock = asyncio.Lock()
	app.state.initialization_task = asyncio.create_task(_initialize_runtime(app))
	app.state.initialization_task.add_done_callback(lambda t: _capture_init_task_result(t, app))

	yield

	task: asyncio.Task[None] | None = getattr(app.state, "initialization_task", None)
	if task and not task.done():
		task.cancel()
	app.state.vector_store = None


app = FastAPI(title="WhiteBook Retrieval API", lifespan=lifespan)
ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
IMAGES_DIR = ROOT_DIR / "images"
if not STATIC_DIR.exists():
	STATIC_DIR = Path("/app/static")
if not IMAGES_DIR.exists():
	IMAGES_DIR = Path("/app/images")

IMAGES_DIR.mkdir(parents=True, exist_ok=True)

if STATIC_DIR.exists():
	app.mount("/static/images", StaticFiles(directory=IMAGES_DIR), name="static-images")
	app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
	index_file = STATIC_DIR / "index.html"
	if not index_file.exists():
		raise HTTPException(status_code=404, detail="Frontend not found")
	return FileResponse(index_file)


@app.post("/api/retrieve", response_model=RetrieveResponse)
async def retrieve(request: RetrieveRequest) -> RetrieveResponse:
	try:
		await ensure_runtime_ready(app)
	except Exception as exc:
		raise HTTPException(status_code=503, detail=f"Runtime initialization failed: {exc}") from exc

	vector_store: VectorStore | None = getattr(app.state, "vector_store", None)
	if vector_store is None:
		raise HTTPException(status_code=503, detail="Vector store is not initialized")

	try:
		results = vector_store.search(request.query, top_k=request.top_k, cutoff=request.cutoff)
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}") from exc

	return RetrieveResponse(results=[ChunkResponse(**result) for result in _with_resolved_images(results)])


@app.post("/api/chat")
@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
	try:
		await ensure_runtime_ready(app)
	except Exception as exc:
		raise HTTPException(status_code=503, detail=f"Runtime initialization failed: {exc}") from exc

	vector_store: VectorStore | None = getattr(app.state, "vector_store", None)
	if vector_store is None:
		raise HTTPException(status_code=503, detail="Vector store is not initialized")

	history_dicts = [{"role": message.role, "content": message.content} for message in request.history]

	if request.tools_mode:
		# Calculator path: no retrieval, calculator-tooling attached, calculator
		# system prompt. Bypassing retrieval keeps the per-request payload small
		# (1.4k tokens of tools instead of 1.4k tools + 5k retrieval) and avoids
		# the model getting nudged into "answer from the WhiteBook" mode when
		# the user explicitly asked for a calculation.
		tools, handlers = build_calculator_tools()
		messages = build_calculator_messages(
			query=request.query,
			history=history_dicts,
			thinking_mode=request.thinking_mode,
		)
	else:
		# RAG path: WhiteBook retrieval is the source of truth, with no calculator
		# tools attached.
		try:
			retrieval_query = build_retrieval_query(request.query, history_dicts)
			retrieved_context = _with_resolved_images(vector_store.search(retrieval_query))
		except Exception as exc:
			raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}") from exc
		tools, handlers = build_rag_tools()
		messages = build_chat_messages(
			query=request.query,
			history=history_dicts,
			retrieved_context=retrieved_context,
			thinking_mode=request.thinking_mode,
		)

	async def _execute_tool(name: str, arguments: dict[str, Any]) -> Any:
		handler = handlers.get(name)
		if handler is None:
			return {"error": f"Unknown tool: {name}"}
		try:
			return handler(arguments)
		except Exception as exc:
			return {"error": str(exc)}

	streamer = stream_groq_chat(
		messages,
		tools=tools,
		tool_executor=_execute_tool,
	)

	return StreamingResponse(
		streamer,
		media_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
			"X-Accel-Buffering": "no",
		},
	)


@app.get("/health")
async def health() -> dict[str, Any]:
	vector_store: VectorStore | None = getattr(app.state, "vector_store", None)
	task: asyncio.Task[None] | None = getattr(app.state, "initialization_task", None)
	startup_state = "ready" if getattr(app.state, "initialized", False) else "initializing"
	if task and task.done() and task.cancelled():
		startup_state = "failed"
	if getattr(app.state, "initialization_error", None):
		startup_state = "failed"
	return {
		"status": "ok",
		"startup_state": startup_state,
		"vector_store_loaded": vector_store is not None,
		"chunk_count": vector_store.size if vector_store is not None else 0,
		"startup_error": getattr(app.state, "initialization_error", None),
	}


@app_modal.function(
	gpu="T4",
	volumes={"/data": volume},
	min_containers=1,
	startup_timeout=900,
	timeout=300,
)
@modal.concurrent(max_inputs=10)
@modal.asgi_app()
def fastapi_app():
	return app


# Re-export for backward compatibility / tests.
CHAT_SYSTEM_PROMPT = SYSTEM_PROMPT
