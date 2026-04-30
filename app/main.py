from __future__ import annotations

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

image = (
	modal.Image.debian_slim(python_version="3.12")
	.pip_install(
		"fastapi",
		"uvicorn",
		"sse-starlette",
		"sentence-transformers",
		"numpy",
	)
	.pip_install(
		"llama-cpp-python",
		extra_index_url="https://abetlen.github.io/llama-cpp-python/whl/cu121",
	)
	.pip_install("mcp")
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



@asynccontextmanager
async def lifespan(app: FastAPI):
	try:
		app.state.vector_store = VectorStore()
		app.state.generator = Generator()
		await app.state.generator.setup_mcp()
	except Exception as exc:  # pragma: no cover - startup failure is surfaced to the server log
		app.state.vector_store = None
		app.state.generator = None
		raise RuntimeError(f"Failed to initialize vector store: {exc}") from exc

	yield

	app.state.vector_store = None
	app.state.generator = None


app = FastAPI(title="WhiteBook Retrieval API", lifespan=lifespan)
ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
IMAGES_DIR = ROOT_DIR / "images"

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
	return {
		"status": "ok",
		"vector_store_loaded": vector_store is not None,
		"chunk_count": vector_store.size if vector_store is not None else 0,
	}


@app_modal.function(
	gpu="T4",
	volumes={"/data": volume},
	min_containers=1,  # Keeps 1 container warm for instant ED use
	timeout=300,
)
@modal.concurrent(max_inputs=10)
@modal.asgi_app()
def fastapi_app():
	return app
