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

## Tests

```bash
.venv/bin/python -m pytest
```

## Notes

- Retrieval source images are only returned when files exist under `images/`.
- This repository no longer includes Modal or local `llama.cpp` generation paths.

## License

MIT.

The tool is intended for informational use only and is not a substitute for professional medical advice, diagnosis, or treatment. Clinical calculators are based on MDCalc formulas and used with permission where applicable.
