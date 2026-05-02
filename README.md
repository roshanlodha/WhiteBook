# WhiteBookLM

WhiteBookLM is a Groq-first retrieval-augmented clinical assistant built on MGH WhiteBook content, with optional clinical calculator tools and a lightweight web UI.

## Quick start

```bash
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000`.

## First-run checklist

- Copy env template: `cp .env.example .env`
- Add your Groq key in `.env` (`GROQ_API_KEY`)
- Confirm `staffbook_kb.sqlite` exists in project root (or set `DB_PATH`)
- Optional: pre-download embedding model to warm cache
- Start server: `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- Verify health: `curl -sS http://localhost:8000/health`

## Environment

Required:

- `GROQ_API_KEY`

Optional:

- `GROQ_MODEL` (defaults to `qwen/qwen3-32b`)
- `DB_PATH` (overrides database discovery)

Database path resolution order:

1. `DB_PATH` env var
2. `/data/staffbook_kb.sqlite` (runtime mount path)
3. `./staffbook_kb.sqlite`

## Local downloads (models/data)

This Groq-only pipeline does **not** require downloading a local chat model (no GGUF / `llama.cpp` path).

You still need local retrieval assets:

- `staffbook_kb.sqlite` (required for `POST /api/retrieve` and normal RAG chat)
- `images/` (optional, only for source image previews in the UI)

Embedding model behavior:

- `app/database.py` uses `Alibaba-NLP/gte-modernbert-base` via `sentence-transformers`.
- It is auto-downloaded on first run if not already cached.
- You can pre-download it to avoid first-request latency:

```bash
.venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('Alibaba-NLP/gte-modernbert-base', trust_remote_code=True)"
```

If the machine is fully offline, pre-populate the Hugging Face cache before starting the app.

## Architecture

- `app/main.py`: FastAPI routes, retrieval orchestration, Groq streaming chat integration.
- `app/providers/groq_provider.py`: Groq payload/build/stream logic, tool loop, error mapping.
- `app/database.py`: `VectorStore` embedding search against SQLite chunks.
- `app/tooling.py`: Tool registry (math + medcalc dispatcher).
- `app/prompts.py`: Prompt construction for RAG and calculator modes.
- `static/`: Web UI and streaming parser.

## API

- `GET /` - Web app.
- `GET /health` - Startup/runtime diagnostics.
- `POST /api/retrieve` - Retrieve relevant chunks.
- `POST /api/chat` - SSE streaming chat endpoint.

## iOS app (native SwiftUI)

The repository now includes an iOS SwiftUI app at `WhiteBook/` that keeps retrieval local and only calls Groq for final generation.

### What runs where

- **Local on device**: SQLite lookup from bundled `staffbook_kb.sqlite` plus source-image resolution from bundled `images/`.
- **Remote**: Groq `chat/completions` API call.

### Setup (Xcode)

1. Open `WhiteBook/WhiteBook.xcodeproj`.
2. In target **WhiteBook** -> **Build Settings**, set:
   - `GROQ_API_KEY` = your Groq API key
   - optional `GROQ_MODEL` (defaults to `qwen/qwen3-32b`)
3. Add local retrieval assets into `WhiteBook/WhiteBook/`:
   - `staffbook_kb.sqlite`
   - `images/` folder (all referenced source images)
4. In Xcode navigator, drag both into the **WhiteBook** target folder and check:
   - **Copy items if needed**
   - **Add to targets: WhiteBook**
5. Build for any iOS simulator/device.

The app expects the following bundled paths:

- `staffbook_kb.sqlite` at bundle root
- images inside bundle subfolder `images/` (loaded by filename from `chunks.image_filename`)

## Tests

```bash
.venv/bin/python -m pytest
```

## Notes

- Retrieval source images are only returned when files exist under `images/`.
- This repository no longer includes Modal or local `llama.cpp` generation paths.
- Groq free-tier TPM limits can be too small for tool-calling mode on some models. If you see tool-call limit errors, disable Calculate mode or use a higher-limit model/tier.

## License

MIT.

The tool is intended for informational use only and is not a substitute for professional medical advice, diagnosis, or treatment. Clinical calculators are based on MDCalc formulas and used with permission where applicable.
