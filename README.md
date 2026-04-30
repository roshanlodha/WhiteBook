# WhiteBookLM

WhiteBookLM is retrieval-augmented generation (RAG) model built on knowledge from the MGH WhiteBook bundled with some useful clinical calculators. The app supports local (or server-side) GGUF inference, and a lightweight web interface.

## Live deployment

- Web app (phone-friendly): [https://roshanlodha--whitebook-fastapi-app.modal.run](https://roshanlodha--whitebook-fastapi-app.modal.run)
- Modal deployment dashboard: [https://modal.com/apps/roshanlodha/main/deployed/whitebook](https://modal.com/apps/roshanlodha/main/deployed/whitebook)

## Quick Start (60 seconds)

### Use the live app from phone

1. Open [https://roshanlodha--whitebook-fastapi-app.modal.run](https://roshanlodha--whitebook-fastapi-app.modal.run).
2. Start a new chat and ask a query.
3. If responses look delayed after a cold start, wait for model warmup and retry.

### Run locally fast

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Deploy latest code fast

```bash
.venv/bin/python -m modal deploy -m app.main::app_modal
```

## What this project does

WhiteBook combines:

- A curated clinical knowledge base stored in SQLite (`staffbook_kb.sqlite`).
- Dense embeddings for retrieval against medical reference content.
- A local Qwen3 GGUF model for answer generation and token streaming.
- Tool-capable chat flow (math tool + optional MCP medcalc integration).
- A minimal web client backed by FastAPI + SSE (`/api/chat`).

The goal is high-signal, context-grounded responses for emergency workflows.

## Current architecture

### Backend (`app/`)

- `app/main.py`
  - FastAPI app and API routes.
  - Modal app definition (`app_modal`) and GPU function (`fastapi_app`).
  - Non-blocking startup warmup for model/vector initialization.
  - Health diagnostics (`/health`) with startup status.
- `app/database.py`
  - `VectorStore` loads chunk embeddings from SQLite and performs cosine similarity search.
- `app/llm.py`
  - `Generator` loads llama.cpp model and streams completion tokens.
  - Optional MCP tool bootstrap for medical calculators.
- `app/calculators.py`
  - Deterministic internal math helper for tool calls.

### Frontend (`static/`)

- `index.html`, `app.js`, `style.css`, `mobile.css`
- Chat UI, source previews, and streaming token display.

### Data / assets

- `staffbook_kb.sqlite` (knowledge base with embedded chunks)
- `images/` (page assets used by retrieval context/source viewing)
- `Qwen3-8B-Q4_K_M.gguf` (local model file, large)

## Runtime behavior (important)

Recent deployment updates changed startup to improve reliability:

- Heavy initialization (vector store, GGUF model, MCP setup) no longer blocks ASGI lifespan startup.
- Warmup now starts in background and routes wait on-demand if needed.
- This avoids Modal startup timeout failures for large models.
- `/health` now reports:
  - `startup_state`: `initializing`, `ready`, or `failed`
  - `startup_error`: error message when initialization fails
  - `vector_store_loaded`, `chunk_count`, `mcp_initialized`

## API surface

- `GET /`
  - Serves the web app.
- `GET /health`
  - Runtime health and startup diagnostics.
- `POST /api/retrieve`
  - Request body:
    - `query` (string, required)
    - `top_k` (int, default `5`)
    - `cutoff` (float, default `0.6`)
  - Returns ranked relevant chunks.
- `POST /api/chat`
  - SSE endpoint for streamed answer generation.
  - Request body includes `query`, optional `history`, and tool/thinking mode toggles.

## Local development

### Prerequisites

- Python 3.12 recommended
- Virtual environment at `.venv/`
- SQLite KB file present
- GGUF model file present

### Install dependencies

```bash
.venv/bin/python -m pip install -r requirements.txt
```

### Run locally

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open [http://localhost:8000](http://localhost:8000).

## Modal deployment

### Deploy command

Use module mode with the Modal app object:

```bash
.venv/bin/python -m modal deploy -m app.main::app_modal
```

### Why this form matters

- `app/main.py` uses package-relative imports (for example `from .database import ...`), so file-script deploy mode can fail.
- `-m app.main::app_modal` ensures Modal resolves the correct app object.

### Modal runtime notes

- GPU: `T4`
- Persistent volume: `whitebook-data` mounted at `/data`
- `startup_timeout`: increased to handle large model initialization
- Static and image directories are mounted into the deployment

## Data and model paths in deployment

In Modal:

- Model path: `/data/Qwen3-8B-Q4_K_M.gguf`
- KB path: `/data/staffbook_kb.sqlite`

If either file is missing from the volume, startup will fail and `/health` will show the reason.

## Troubleshooting

### `Runner has been initializing for too long`

Cause:
- Blocking heavy startup (often model load) during ASGI lifespan.

Fix:
- Keep startup non-blocking and ensure warmup happens in background/on-demand.
- Increase `startup_timeout` for large model cold starts.

### `ASGI lifespan startup failed`

Cause:
- Initialization exception thrown during startup.

Fix:
- Check `/health` for `startup_error`.
- Check Modal app logs:

```bash
.venv/bin/python -m modal app logs whitebook --tail 300 --timestamps
```

### HF Hub warning about unauthenticated requests

You may see:

`Warning: You are sending unauthenticated requests to the HF Hub...`

This is non-fatal. Add an `HF_TOKEN` secret in Modal if you want:

- Better Hugging Face rate limits
- Faster model/embedding asset downloads during builds

## Ingestion pipeline (high level)

`ingest.py` is used to build/refresh the retrieval DB:

- Converts PDF pages to images
- Extracts dense clinical chunks via multimodal calls
- Embeds chunks and stores them in SQLite (`chunks` table)

This is typically run separately from deployment, then copied into the runtime volume.

## Updating WhiteBookLM

This section is the operational runbook for updating model/runtime assets and pushing changes live.

### Update the model

Use this when you switch GGUF variants, quantization, or context-window profile.

1. Place the new model file in your runtime data location (Modal volume path is `/data` at runtime).
2. Update the default model path/name in `app/llm.py` if the filename changes:
   - `DEFAULT_LLM_PATH = "/data/<your-model>.gguf"`
3. If needed, adjust llama.cpp runtime params in `Generator` (for example `n_ctx`, `n_gpu_layers`).
4. Re-run a local smoke check:

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
curl -sS http://localhost:8000/health
```

### Update the vector store

Use this when source documents/chunks/embeddings change.

1. Rebuild the KB with `ingest.py` (or your updated ingestion flow).
2. Confirm the generated SQLite DB is valid and contains rows in `chunks`.
3. Replace the runtime DB file used by the app (`/data/staffbook_kb.sqlite` in Modal).
4. Verify retrieval quality locally before deploy:

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
curl -sS -X POST "http://localhost:8000/api/retrieve" \
  -H "Content-Type: application/json" \
  -d '{"query":"ventricular tachycardia treatment","top_k":3,"cutoff":0.2}'
```

### Redeploy after any update

Redeploy whenever code, model path, DB, or static UI assets are changed.

```bash
.venv/bin/python -m modal deploy -m app.main::app_modal
```

Post-deploy checks:

```bash
curl -sS https://roshanlodha--whitebook-fastapi-app.modal.run/health
curl -sS https://roshanlodha--whitebook-fastapi-app.modal.run/
```

Optional logs check if anything looks off:

```bash
.venv/bin/python -m modal app logs whitebook --tail 300 --timestamps
```

## Project layout

```text
WhiteBook/
├── app/
│   ├── main.py
│   ├── llm.py
│   ├── database.py
│   └── calculators.py
├── static/
├── images/
├── ingest.py
├── requirements.txt
├── staffbook_kb.sqlite
└── Qwen3-8B-Q4_K_M.gguf
```
