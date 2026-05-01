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

## Groq Migration

This runbook migrates WhiteBook from Modal-hosted generation to Groq-hosted generation, with local FastAPI + frontend during development and a cloud web deployment later.

It is intentionally written for two audiences at once:

1. A human operator doing account/UI setup.
2. A coding agent (including small models) implementing code changes safely, phase-by-phase.

### Important facts from Groq docs (read first)

- Rate limits are org-level, not per-user; you can hit RPM, RPD, TPM, or TPD first.
- `qwen/qwen3-32b` is currently listed at `RPM 60`, `RPD 1K`, `TPM 6K`, `TPD 500K` in the public table; always verify your exact limits in your Groq limits page because plan and org overrides can differ.
- On limit exceed, API returns `429` and `retry-after`; other rate headers are always present.
- Prompt caching is automatic, no extra fee, and cached tokens do not count toward rate limits.
- Prompt caching currently supports only `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, and `openai/gpt-oss-safeguard-20b`.
- Because your chosen model is `qwen/qwen3-32b`, prompt caching may not be active yet for your production path. Build the code to be cache-ready anyway, and optionally add a switchable caching-capable model profile later.

### Migration strategy

Use strict phase gates. Do not proceed to the next phase until the tests for the current phase pass.

- Phase 0: Groq console and local environment setup.
- Phase 1: Backend provider abstraction + Groq streaming integration.
- Phase 2: Rate-limit handling, retries, and observability.
- Phase 3: Prompt-structure hardening for cacheability (and optional cache-capable model profile).
- Phase 4: Frontend validation for unchanged SSE contract.
- Phase 5: Local production-like hardening.
- Phase 6: Cloud publish of FastAPI + static frontend.

### Phase 0 - Account, project, and environment (human steps)

Goal: Confirm account-level prerequisites and lock environment values before code changes.

1. Open [Groq Console](https://console.groq.com).
2. Confirm API key exists; rotate and replace if the key was ever pasted in logs/screenshots.
3. Open limits page in Groq settings and record the actual values for your org.
4. Confirm `.env` contains:

```env
GROQ_API_KEY="gsk_..."
GROQ_MODEL="qwen/qwen3-32b"
```

5. Keep `.env` out of git; verify `.gitignore` includes it.
6. If old Modal secrets/URLs exist, keep them temporarily for rollback only; do not remove yet.

Phase 0 tests:

- `python -c "import os; from dotenv import load_dotenv; load_dotenv(); assert os.getenv('GROQ_API_KEY'); assert os.getenv('GROQ_MODEL')"`
- `curl -sS https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY" | jq '.data[].id' | rg "qwen/qwen3-32b"`

Pass criteria:

- API key authenticates.
- Target model is visible.
- `.env` is loaded locally.

### Phase 1 - Backend Groq integration (coding agent implementation)

Goal: Replace generation calls with Groq while preserving retrieval and SSE behavior.

Required code outcomes:

- Create a provider module (for example `app/providers/groq_provider.py`) that owns all Groq API calls.
- Keep retrieval logic in existing backend modules; only the generation provider changes.
- Preserve SSE output contract used by `static/app.js` so frontend behavior does not regress.
- Centralize prompt assembly so message order is deterministic and testable.
- Put static system instructions first and user/session content last.

Copy/paste prompt for coding agent:

```text
Act as a senior Python/FastAPI migration engineer. Update this project to use Groq as the primary generation backend without changing retrieval behavior.

Constraints:
- Keep API route paths stable unless already versioned.
- Keep SSE response framing stable so current frontend stream parser still works.
- Read GROQ_API_KEY and GROQ_MODEL from environment.
- Add/update dependencies required by Groq client usage.
- Keep code modular: provider file for Groq calls, no monolithic edits.

Implementation tasks:
1) Create a Groq provider module with:
   - a function to build chat completion request payloads
   - a streaming function that yields SSE-compatible chunks
   - explicit timeout and error mapping for upstream failures
2) Wire FastAPI chat endpoint to call the Groq provider.
3) Ensure retrieval chunks are still injected into the prompt.
4) Ensure system message remains stable across turns.
5) Add minimal unit tests for:
   - payload construction order
   - error mapping behavior
   - stream chunk formatting
6) Do not add Modal fallback logic in this migration.

Deliverable:
- Production-ready code edits + tests.
- A short test command list to verify locally.
```

Phase 1 tests:

- Run backend tests.
- Start app locally and run one chat request end-to-end.
- Confirm streamed tokens render continuously in UI (not batch at end).

Pass criteria:

- Chat endpoint returns valid SSE stream from Groq.
- Retrieval augmentation still appears in answers.
- No Modal dependency remains on main generation path.

### Phase 2 - Rate-limit resilience and telemetry (coding + human verification)

Goal: Make the app robust against `429` and transient failures.

Required code outcomes:

- Retry policy for transient failures with capped exponential backoff and jitter.
- Special-case `429` using `retry-after` when available.
- Log and surface rate-limit headers:
  - `x-ratelimit-limit-requests`
  - `x-ratelimit-remaining-requests`
  - `x-ratelimit-limit-tokens`
  - `x-ratelimit-remaining-tokens`
  - `x-ratelimit-reset-requests`
  - `x-ratelimit-reset-tokens`
- Return user-friendly error text when retries exhausted.
- Never leak API keys in logs/errors.

Copy/paste prompt for coding agent:

```text
Harden Groq API handling for production.

Implement:
1) Retry wrapper for transient failures and rate limiting.
2) On HTTP 429, parse retry-after and sleep that duration before retrying.
3) Attach selected x-ratelimit-* header values to structured logs.
4) Add a small helper that converts provider exceptions into user-safe FastAPI errors.
5) Add tests that mock:
   - success
   - repeated 429 then success
   - repeated 429 then final failure
   - timeout/network error

Do not change endpoint contracts.
Do not expose secrets in logs.
```

Phase 2 tests:

- Synthetic test with mocked `429` verifies backoff behavior.
- Confirm logs include rate-limit metadata keys.
- Confirm client receives stable error shape when retries fail.

Pass criteria:

- No crash loops on throttling.
- Actionable observability exists for debugging quota pressure.

### Phase 3 - Prompt caching readiness and model policy (coding + product decision)

Goal: Structure prompts for maximum cacheability and explicitly handle your chosen model policy.

Decision gate:

- If you must stay on `qwen/qwen3-32b`, keep cache-ready prompt design and track `cached_tokens` for future support rollout.
- If you want prompt-caching benefit now, add optional model switch to a supported model (`openai/gpt-oss-20b` or `openai/gpt-oss-120b`) for selected routes or environments.

Required code outcomes:

- Stable static prefix:
  - system instructions
  - tool definitions (if used)
  - fixed schemas/examples
- Dynamic suffix:
  - user query
  - per-request metadata
  - volatile timestamps/IDs
- Capture and log `usage.prompt_tokens_details.cached_tokens` when present.
- Add a feature flag/env for optional alternate model profile.

Copy/paste prompt for coding agent:

```text
Optimize prompt assembly for Groq prompt-caching compatibility and add instrumentation.

Tasks:
1) Refactor prompt builder so static sections always come first and remain byte-stable between requests.
2) Ensure dynamic session/user data is appended after static sections.
3) Parse usage payload and log prompt_tokens plus cached_tokens if available.
4) Add env-based optional model override for cache-capable models, while preserving GROQ_MODEL default.
5) Add tests that verify exact-prefix stability across turns.

Important:
- Keep behavior unchanged for qwen/qwen3-32b default.
- Do not introduce schema-breaking API changes.
```

Phase 3 tests:

- Multi-turn local test using same system prompt and different user turns.
- Validate usage logging path handles missing `cached_tokens` gracefully.
- If using a supported model in staging, verify cache hit rate rises on repeated prefix calls.

Pass criteria:

- Prompt order is deterministic.
- Cache telemetry exists.
- Model policy is explicit and configurable.

### Phase 4 - Frontend compatibility check (coding agent + manual QA)

Goal: Confirm no UI regression from backend migration.

Required outcomes:

- Existing `/api/chat` request and SSE parsing still work.
- Error states render clearly when provider throttles/fails.
- Optional small UI hint showing current provider/model (from health/config endpoint).

Copy/paste prompt for coding agent:

```text
Validate and patch frontend compatibility after backend Groq migration.

Tasks:
1) Confirm stream parser handles tokenized SSE chunks exactly as emitted by backend.
2) Improve client-side error display for provider timeouts/429 exhaustion.
3) Add lightweight model/provider indicator in UI if a config endpoint exists.
4) Do not redesign styling or alter chat UX flow.
```

Phase 4 tests:

- Manual browser test: first token appears quickly and continues streaming.
- Manual error injection test: verify user sees readable fallback message.
- No console errors in browser devtools during normal chat.

Pass criteria:

- Chat UX remains smooth.
- Error handling is understandable to end users.

### Phase 5 - Local release candidate checklist

Goal: Freeze a reliable local build before cloud deployment.

Checklist:

1. Run full test suite.
2. Run lints/format checks.
3. Verify `/health` includes provider/model status without secrets.
4. Run 20 sequential chat smoke requests and confirm no memory blow-up.
5. Run small burst concurrency test and inspect throttling behavior.
6. Confirm README and `.env.example` (if present) reflect Groq-first setup.

Suggested smoke commands:

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
curl -sS http://localhost:8000/health | jq
curl -N -X POST "http://localhost:8000/api/chat" -H "Content-Type: application/json" -d '{"query":"What is SVT?","history":[]}'
```

Pass criteria:

- Stable local behavior for single and burst traffic.
- Clear operational signals for rate limiting and provider failures.

### Phase 6 - Publish to website (human + coding agent)

Goal: Deploy FastAPI + static frontend publicly with secure secret handling.

Platform options:

- Render, Railway, Fly.io, or any container host supporting environment secrets and HTTPS.

Deployment steps:

1. Push migration code to Git provider.
2. Create web service and set build/start commands.
3. Add secrets in host dashboard:
   - `GROQ_API_KEY`
   - `GROQ_MODEL`
4. Set production-safe worker/timeouts for streaming endpoints.
5. Deploy and test `/health` + one full chat stream.
6. Enable log retention/alerts for repeated `429` and upstream failures.

Production tests:

- Real browser session on public URL.
- Verify SSE streaming survives reverse proxy.
- Verify throttling path returns user-safe errors.
- Verify no secret appears in logs.

Pass criteria:

- Public HTTPS app functions end-to-end.
- Rate-limit events are observable and recover gracefully.

### MCP and Groq tooling notes

- You do not need an MCP server to call Groq chat completions; direct API integration is simplest and lowest risk.
- Groq supports tool-use patterns; keep your existing server-side tools callable through normal chat completion/tool schema flows.
- If you add MCP later, treat it as a separate project after Groq migration is stable.

### Rollback plan

If any phase fails and cannot be fixed quickly:

1. Revert to last known good commit.
2. Restore previous provider wiring.
3. Keep Groq code on feature branch for iterative repair.
4. Re-run Phase 1 through Phase 3 tests before reattempting release.