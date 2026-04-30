from __future__ import annotations

import asyncio
import modal

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from .database import VectorStore
from .llm import Generator

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
		"uv",
	)
	.pip_install(
		"llama-cpp-python",
		extra_index_url="https://abetlen.github.io/llama-cpp-python/whl/cu121",
	)
	.pip_install("mcp")
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
	tools_mode: bool = False
	thinking_mode: bool = True


async def _initialize_runtime(app: FastAPI) -> None:
	"""Initialize heavy runtime components in a worker thread."""
	try:
		vector_store = await asyncio.to_thread(VectorStore)
		generator = await asyncio.to_thread(Generator)
		mcp_initialized = False
		try:
			await generator.setup_mcp()
			mcp_initialized = True
		except Exception:  # pragma: no cover - MCP is optional at runtime
			mcp_initialized = False

		app.state.vector_store = vector_store
		app.state.generator = generator
		app.state.mcp_initialized = mcp_initialized
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
	app.state.generator = None
	app.state.mcp_initialized = False
	app.state.initialized = False
	app.state.initialization_error = None
	app.state.init_lock = asyncio.Lock()
	# Start warmup asynchronously so ASGI startup never blocks and times out.
	app.state.initialization_task = asyncio.create_task(_initialize_runtime(app))
	app.state.initialization_task.add_done_callback(lambda t: _capture_init_task_result(t, app))

	yield

	task: asyncio.Task[None] | None = getattr(app.state, "initialization_task", None)
	if task and not task.done():
		task.cancel()
	app.state.vector_store = None
	generator: Generator | None = getattr(app.state, "generator", None)
	if generator is not None:
		await generator.close()
	app.state.generator = None


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

	return RetrieveResponse(results=[ChunkResponse(**result) for result in results])


@app.post("/api/chat")
async def chat(request: ChatRequest) -> EventSourceResponse:
	try:
		await ensure_runtime_ready(app)
	except Exception as exc:
		raise HTTPException(status_code=503, detail=f"Runtime initialization failed: {exc}") from exc

	vector_store: VectorStore | None = getattr(app.state, "vector_store", None)
	generator: Generator | None = getattr(app.state, "generator", None)
	if vector_store is None or generator is None:
		raise HTTPException(status_code=503, detail="Application components are not initialized")

	try:
		retrieved_context = vector_store.search(request.query)
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}") from exc

	async def event_stream():
		yield {"event": "start", "data": json.dumps({"query": request.query, "results": len(retrieved_context)})}
		try:
			async for token in generator.stream_response(
				query=request.query,
				retrieved_context=retrieved_context,
				history=[
					message.model_dump() if hasattr(message, "model_dump") else message.dict()
					for message in request.history
				],
				tools_mode=request.tools_mode,
				thinking_mode=request.thinking_mode

			):
				yield {"event": "token", "data": token}
			yield {"event": "done", "data": "[DONE]"}
		except Exception as exc:
			yield {"event": "error", "data": json.dumps({"detail": str(exc)})}

	return EventSourceResponse(event_stream())


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
		"mcp_initialized": bool(getattr(app.state, "mcp_initialized", False)),
		"startup_error": getattr(app.state, "initialization_error", None),
	}


@app_modal.function(
	gpu="T4",
	volumes={"/data": volume},
	min_containers=1,  # Keeps 1 container warm for instant ED use
	startup_timeout=900,
	timeout=300,
)
@modal.concurrent(max_inputs=10)
@modal.asgi_app()
def fastapi_app():
	return app
