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

### (Re)Deploy latest code fast

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

## (Re)Deployment

### Deploy command

```bash
.venv/bin/python -m modal deploy -m app.main::app_modal
```

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

This section is the operational runbook for updating model/runtime assets and then (re)deploying.

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

### (Re)Deploy after any update

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

## License

Licensed under MIT license.

The tool is intended for use as a research and informational tool only and is not a substitute for professional medical advice, diagnosis, or treatment. The Service is provided "as is" without any warranties of any kind, express or implied, including but not limited to the accuracy, completeness, or reliability of the calculations or results.

Choice of calculation tasks chosen from "most popular" calculators list from website of MDCalc Ltd (New York, NY). Used with permission. Inclusion of these calculators does not constitute endorsement by MDCalc.

## TODO

## WhiteBook Groq Migration & Deployment Plan
**Stack:** FastAPI (Router & Vector Store), Vanilla JS/HTML/CSS (Frontend), Groq (Primary Inference), Modal (Backup Inference).

This document outlines the phased migration to a dual-backend generation strategy and the final deployment steps to publish WhiteBook for public use. It contains manual instructions for the developer and strict, copy-paste prompts for AI coding agents.

### Phase 0: Preparation & Accounts (Manual Steps)

Before writing code, establish your cloud API credentials.

**1. Groq Setup (Primary)**
* Go to the [Groq Console](https://console.groq.com).
* Create an API key named `whitebook-router`.
* Identify your target model (recommended: `llama-3.1-8b-instant` or `llama3-70b-8192`).

**2. Modal Setup (Backup)**
* Ensure you have a Modal account ([modal.com](https://modal.com)).
* Install the CLI locally: `pip install modal`
* Authenticate: `modal setup`

**3. Local Environment Variables**
Create or update your `.env` file in the root of your repository:
` ` `env
GROQ_API_KEY="gsk_your_key_here"
GROQ_MODEL="llama-3.1-8b-instant"
MODAL_INFERENCE_URL="We will paste this here after Phase 3"
` ` `

---

### Phase 1: The FastAPI Router (Agent Prompt)

*Copy and paste this exact prompt into your AI coding assistant (e.g., Gemini Flash, GPT-4o).*

> **System Context:** Act as a Lead Backend Python Engineer. We are migrating our FastAPI medical RAG application. The FastAPI server holds a 15MB SQLite database in memory as a NumPy matrix for zero-latency vector search. We need to implement a dual-backend generation routing system.
>
> **Task:** Update `main.py` and create an LLM routing module.
> 
> **1. Groq Client Integration:**
> * Use the official `groq` async Python SDK. 
> * Implement an `@retry` decorator using `tenacity` (catch `RateLimitError` and `APIConnectionError`, use exponential backoff with jitter, max 5 attempts).
> * Write an async generator `stream_groq(messages: list)`. Yield SSE data strings: `yield f"data: {text}\n\n"`.
> * **Crucial Prompt Injection:** Because Groq runs LLaMA models, inject this directive into the System message to maintain UI compatibility with our Qwen3 setup: `"You must write your internal clinical reasoning inside <think>...</think> tags before providing your final answer."`
>
> **2. Modal Fallback Integration:**
> * Write an async generator `stream_modal(messages: list)`.
> * Use `httpx.AsyncClient` to send a POST request to `os.getenv("MODAL_INFERENCE_URL")` with `stream=True`.
> * Yield the streaming SSE chunks as they arrive from Modal.
>
> **3. The `/chat` Endpoint:**
> * Update the POST `/chat` endpoint to accept a JSON body containing `query`, `history`, and a string parameter `backend` (either `"groq"` or `"modal"`).
> * Perform the in-memory vector search against the user's query.
> * Build the final message array (System Prompt + Retrieved Chunks + History + Latest Query).
> * **Strict Routing:** If `backend == "groq"`, return a `StreamingResponse` using `stream_groq`. If `backend == "modal"`, return a `StreamingResponse` using `stream_modal`. Do NOT automatically failover.
> 
> Provide the complete, production-ready Python code with robust error handling.

---

### Phase 2: Frontend Toggle UI (Agent Prompt)

*Copy and paste this exact prompt into your AI coding assistant.*

> **System Context:** Act as a Frontend Engineer. We are updating the Vanilla HTML/JS/CSS frontend for our medical RAG app. The UI is strictly "minimalist maximalism" (pure black background, white text, SF Pro fonts, pastel orange `#FFB347` accents).
> 
> **Task:** Update `index.html`, `style.css`, and `app.js`.
>
> **1. Backend Toggle Switch:**
> * Add a sleek, minimalist toggle switch or dropdown near the chat input labeled "Inference Engine".
> * Options must be: "Groq (Ultra-Fast)" and "Modal Qwen3 (Backup)".
> * Ensure the selected state is visually clear (use pastel orange for the active state).
>
> **2. API Request Update:**
> * Modify the `fetch` call in `app.js` that hits `/chat`. 
> * Extract the value of the toggle switch and include it in the JSON payload as `"backend": "groq"` or `"backend": "modal"`.
>
> **3. Streaming Token Parser Validation:**
> * Ensure the `ReadableStream` parser (`body.getReader()`) correctly splits SSE `data: ` chunks.
> * Ensure the state machine correctly identifies `<think>` and `</think>` tags, wrapping the text between them in `<span class="reasoning">` (styled as italicized pastel orange).
> 
> Provide the complete HTML, CSS, and JS code. Ensure it handles network errors gracefully by displaying a red error message in the chat feed if the selected backend fails.

---

### Phase 3: Modal Backup Deployment (Agent Prompt)

*Copy and paste this exact prompt into your AI coding assistant.*

> **System Context:** Act as a DevOps Engineer. We need to deploy our backup inference engine to Modal. This app does NOT handle the database or UI; it acts solely as a stateless, GPU-accelerated LLM API.
> 
> **Task:** Write the `modal_app.py` deployment script.
> 
> **1. Container Image:**
> * Define a `modal.Image` that installs `llama-cpp-python` with `cuBLAS` enabled for Nvidia GPU acceleration.
> * Download the `Qwen3-4B-Instruct-Q4_K_M.gguf` weights into the container during the build step.
>
> **2. Modal App Definition:**
> * Define a Modal App named `whitebook-inference-backup`.
> * Create a class `QwenInference` decorated with `@app.cls(gpu="T4", keep_warm=0)`. We want `keep_warm=0` to save money since this is strictly a backup.
> * In the `@modal.enter()` method, initialize the `Llama` instance with `n_gpu_layers=-1` and `n_ctx=4096`.
>
> **3. Web Endpoint:**
> * Define a method decorated with `@modal.web_endpoint(method="POST")`.
> * It must accept a JSON payload of `messages`.
> * It must format the messages using the Qwen ChatML template.
> * It must return a FastAPI `StreamingResponse` that yields Server-Sent Events (SSE) from the `llama.cpp` generator.
>
> Provide the complete `modal_app.py` script. Include the terminal command required to deploy this app.

*Manual Step after Agent Completion:*
Run the deployment command (`modal deploy modal_app.py`). Modal will output a live web URL (e.g., `https://yourname--whitebook-inference-backup-web.modal.run`). Copy this URL and paste it into your `.env` file as `MODAL_INFERENCE_URL`.

---

### Phase 4: Public Deployment (Manual Steps)

To share WhiteBook with other clinicians, you must deploy the main FastAPI Router. Since the heavy AI generation is offloaded to Groq and Modal, your router only needs ~1GB of RAM to hold the 15MB SQLite database and handle web traffic.

**1. Prepare the Repository:**
* Ensure your `staffbook_kb.sqlite`, `ios_images` folder, `main.py`, `requirements.txt`, and `static` folder are committed to a GitHub repository.
* Ensure `.env` is listed in your `.gitignore` file. Never commit API keys.

**2. Choose a Hosting Platform (Render or Railway):**
* Create an account on [Render.com](https://render.com) (easiest for FastAPI) or [Railway.app](https://railway.app).
* Create a new "Web Service" and connect it to your GitHub repository.

**3. Configure the Deployment:**
* **Build Command:** `pip install -r requirements.txt`
* **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
* **Environment Variables:** Add `GROQ_API_KEY` and `MODAL_INFERENCE_URL` in the hosting dashboard's secrets manager. 

**4. Go Live:**
* Deploy the service.
* Render/Railway will automatically provision an SSL certificate and provide a public HTTPS URL (e.g., `https://whitebook-router.onrender.com`).
* You can now access WhiteBook from any iPhone or hospital computer instantly. If Groq rate limits are hit during heavy usage, instruct users to tap the "Modal Qwen3" toggle to switch to the dedicated GPU backup.