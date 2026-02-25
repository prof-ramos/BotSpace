# CLAUDE.md — BotSpace

AI assistant guide for the BotSpace codebase. Read this before making changes.

---

## Project Overview

BotSpace is a **RAG (Retrieval-Augmented Generation) Discord bot** for Portuguese legal document search. Users ask questions in Discord and the bot retrieves relevant chunks from a FAISS vector index built from PDF/DOCX legal documents, then calls a Hugging Face LLM to generate an answer in Portuguese.

The application runs as a single Python process that simultaneously hosts:
1. A **FastAPI HTTP server** (port 7860) — health check, log viewer, reindex trigger
2. A **Discord bot** — answers questions via `!rag`, handles `@mentions`, admin `!reindex`
3. An optional **scheduler thread** — auto-reindexes on a timer

Deployed on **Hugging Face Spaces** (Docker runtime) with persistent `/data` storage.

---

## Repository Structure

```
BotSpace/
├── main.py                  # Entry point: starts API + scheduler + Discord bot
├── bot_app.py               # Discord bot commands and event handlers
├── ingest_job.py            # Document ingestion pipeline (run as a subprocess or standalone)
├── index_local_runtime.py   # FAISS index loader with hot-reload and thread-safe search
├── hf_client.py             # Hugging Face Inference API HTTP client
├── prompts.py               # System prompt and user prompt builder (Portuguese)
├── sanitize_docs.py         # CLI utility: .doc→.docx conversion + cleanup
├── requirements.txt         # Python dependencies (14 packages)
├── Dockerfile               # HF Spaces Docker image (python:3.12-slim + LibreOffice)
├── README.md                # User-facing documentation
├── plan.md                  # Operational architecture notes (HF ecosystem)
└── docs_rag/                # Local document corpus (legal PDFs/DOCXs, NOT committed via LFS)
    ├── legislacao_grifada_e_anotada_atualiz_em_01_01_2026/
    └── sumulas_tse_stj_stf_e_tnu_atualiz_01_01_2026_2/
```

---

## Architecture & Data Flow

```
Discord User
  │
  ├─ !rag <question>  ──→  bot_app.py:rag_cmd()
  ├─ @bot <question>  ──→  bot_app.py:on_message()
  └─ !reindex (admin) ──→  bot_app.py:reindex_cmd()
                                │ HTTP POST /reindex
                                ▼
                          main.py:run_ingest()
                                │ subprocess
                                ▼
                          ingest_job.py:main()
                           1. Download docs from HF Hub dataset (DOCS_REPO_ID)
                           2. sanitize_docs.py  (.doc→.docx, remove non-PDF/DOCX)
                           3. parse_pdf / parse_docx  → extract text
                           4. chunk_chars()  → 1200-char chunks, 200 overlap
                           5. SentenceTransformer.encode()  → 384-dim vectors
                           6. faiss.IndexFlatIP  → inner-product similarity
                           7. Publish artifacts to HF Hub dataset (INDEX_REPO_ID)

index_local_runtime.py:LocalIndexRuntime
  - Loads faiss.index + meta.json from /data/work/out/artifacts/
  - Polls mtime every RELOAD_POLL_SECONDS for hot-reload
  - Thread-safe via RLock

hf_client.py:call_hf()
  - Formats messages → [SYSTEM]/[USER]/[ASSISTANT] prompt
  - POST to HF Inference API
  - Returns generated text (max_new_tokens=500, temperature=0.2)
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Discord | discord.py 2.4.0 |
| Web API | FastAPI 0.115.6 + uvicorn 0.30.6 |
| Vector DB | FAISS (IndexFlatIP, faiss-cpu) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2, 384-dim) |
| LLM | Hugging Face Inference API (default: microsoft/Phi-3.5-mini-instruct) |
| Document parsing | pypdf (PDF), python-docx (DOCX) |
| Doc conversion | LibreOffice headless via `soffice` subprocess |
| Artifact storage | Hugging Face Hub (datasets) |
| Deployment | Docker on HF Spaces |

---

## Environment Variables

All configuration is via environment variables read at module import time.

### Required

| Variable | Used In | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | bot_app.py | Discord bot authentication token |
| `HF_TOKEN` | hf_client.py | Hugging Face API token for inference |
| `REINDEX_API_TOKEN` | main.py, bot_app.py | Bearer token for `/reindex` endpoint |
| `DOCS_REPO_ID` | ingest_job.py | HF Hub dataset repo with source documents |
| `INDEX_REPO_ID` | ingest_job.py | HF Hub dataset repo for publishing index artifacts |

### Optional (with defaults)

| Variable | Default | Purpose |
|---|---|---|
| `BOT_PREFIX` | `!` | Discord command prefix |
| `HF_TEXT_MODEL` | `microsoft/Phi-3.5-mini-instruct` | HF model ID for text generation |
| `HF_INFERENCE_URL` | auto from `HF_TEXT_MODEL` | Override inference endpoint URL |
| `EMBED_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model for chunking and queries |
| `CHUNK_CHARS` | `1200` | Characters per text chunk |
| `CHUNK_OVERLAP` | `200` | Overlap between consecutive chunks |
| `WORK_DIR` | `/data/work` (runtime) / `/tmp/rag_job` (ingest) | Working directory for artifacts |
| `ARTIFACTS_PREFIX` | `artifacts` | Subdirectory prefix in HF Hub dataset |
| `RELOAD_POLL_SECONDS` | `30` | How often to check for updated index |
| `REINDEX_EVERY_SECONDS` | `0` (disabled) | Auto-reindex interval; 0 disables scheduler |
| `DOCS_SUBDIR` | `docs_rag` | Subdirectory within DOCS_REPO_ID containing documents |

---

## Key Files In Depth

### `main.py` — Entry Point
- Starts three threads: FastAPI (uvicorn on 0.0.0.0:7860), scheduler loop, Discord bot
- `run_ingest()` acquires a file-based lock (`reindex.lock`) to prevent concurrent runs; lock expires after 2 hours
- Logs last 200KB of ingest output to `reindex.log`
- API endpoints: `GET /health`, `GET /logs`, `POST /reindex` (Bearer auth required)

### `bot_app.py` — Discord Bot
- Commands: `!rag <question>` (public), `!reindex` (admin only)
- Mention handler: strips `<@bot_id>` from message content, then calls `_build_answer()`
- All Discord replies are truncated to 1900 chars (Discord limit is 2000)
- Uses `asyncio.to_thread()` for CPU-bound embedding + HTTP calls to avoid blocking the event loop
- Index is loaded eagerly on `on_ready` if it exists

### `ingest_job.py` — Pipeline
- Run via `python ingest_job.py` or as subprocess from `main.py`
- Requires `DOCS_REPO_ID` and `INDEX_REPO_ID` to be set
- Pipeline stages: download → sanitize → parse → chunk → embed → FAISS index → publish
- Publishes 5 artifacts: `faiss.index`, `meta.json`, `failures.json`, `conversion_report.json`, `manifest.json`
- Manifest includes SHA256 checksums of all artifacts and embedding configuration

### `index_local_runtime.py` — Index Runtime
- `LocalIndexRuntime` is a singleton-style class instantiated once at bot startup
- `maybe_reload()` is called before every search; polls mtime, reloads if changed
- `search(query, k=4)` encodes the query and returns top-k chunks with cosine similarity scores
- Thread-safe: all index operations use `threading.RLock`

### `hf_client.py` — LLM Client
- Converts `[{"role": "system/user", "content": "..."}]` messages to a `[ROLE]\ncontent` prompt string
- POSTs to HF Inference API; handles both list and dict response formats
- Default: `max_new_tokens=500`, `temperature=0.2`

### `prompts.py` — Prompts
- `SYSTEM_PROMPT`: Portuguese-language instruction to use context and admit when information is missing
- `build_user_prompt(question, context)`: formats retrieved chunks with source + score info

### `sanitize_docs.py` — Document Utility
- CLI: `python sanitize_docs.py --root <path> --report <path> [--delete-original-doc]`
- Stage 1: Convert `.doc` → `.docx` via `soffice --headless --convert-to docx`
- Stage 2: Delete all files not in `{.pdf, .docx}`
- Stage 3: Remove empty directories
- Called by `ingest_job.py` as a subprocess

---

## Artifact Layout (at runtime)

```
/data/work/
├── reindex.lock               # Ingest lock file (deleted on completion)
├── reindex.log                # Last 200KB of ingest stdout+stderr
├── docs/                      # Downloaded documents (temporary)
└── out/
    └── artifacts/
        ├── faiss.index        # FAISS IndexFlatIP binary
        ├── meta.json          # [{text, source, chunk_id}, ...]
        ├── manifest.json      # Index metadata + checksums + revision
        ├── failures.json      # [{path, error}, ...]
        └── conversion_report.json  # DOC→DOCX conversion results
```

---

## Code Conventions

### Python Style
- **Python 3.12+** features used: `str | None` union types, `tuple[Path, Path]` generics
- **Type hints** on all functions; use modern syntax (not `Optional`, `Union`)
- **Imports** ordered: stdlib → third-party → local
- **Constants**: `UPPER_SNAKE_CASE` at module level via `os.getenv()`
- **Private methods**: leading underscore (`_paths()`, `_build_answer()`, `_messages_to_prompt()`)
- **Error handling**: catch `Exception as exc` with `# noqa: BLE001` lint suppressor; never swallow errors silently in user-facing code
- **Logging**: print with `[MODULE]` prefix tags — `[BOT]`, `[JOB]`, `[INDEX]`, `[SCHEDULER]`

### Language
- **Code**: English variable/function names, English error messages for internal/automation use
- **User-facing messages**: Portuguese (Discord replies, prompts, bot error messages)
- **Comments**: mix of Portuguese and English is acceptable; prefer self-documenting code over comments

### Commit Convention
Follows semantic commit prefixes:
- `feat:` — new feature
- `fix:` — bug fix
- `chore:` — non-functional changes (deps, config, docs)
- `refactor:` — code restructuring without behavior change

---

## Running Locally

### Prerequisites
- Python 3.12+
- LibreOffice (`soffice` must be on PATH) — only needed for `.doc` conversion
- All required environment variables set

### Install dependencies
```bash
pip install -r requirements.txt
# or with uv:
uv pip install -r requirements.txt
```

### Start the application
```bash
python main.py
```
This starts FastAPI on port 7860, the scheduler (if `REINDEX_EVERY_SECONDS > 0`), and the Discord bot.

### Run ingest job standalone
```bash
export DOCS_REPO_ID=your-hf-username/your-docs-dataset
export INDEX_REPO_ID=your-hf-username/your-index-dataset
python ingest_job.py
```

### Sanitize a local docs folder
```bash
python sanitize_docs.py \
  --root ./docs_rag \
  --report ./conversion_report.json \
  --delete-original-doc
```

### Docker build and run
```bash
docker build -t botspace .
docker run -p 7860:7860 \
  -e DISCORD_TOKEN=... \
  -e HF_TOKEN=... \
  -e REINDEX_API_TOKEN=... \
  -e DOCS_REPO_ID=... \
  -e INDEX_REPO_ID=... \
  -v /local/data:/data \
  botspace
```

---

## API Reference

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | None | Returns `"ok"` — liveness probe |
| `/logs` | GET | None | Returns last 200KB of `reindex.log` |
| `/reindex` | POST | `Bearer <REINDEX_API_TOKEN>` | Triggers ingest pipeline synchronously (up to 3600s timeout) |

---

## Discord Commands

| Command | Permissions | Description |
|---|---|---|
| `!rag <question>` | Everyone | RAG query; returns answer based on top-4 index chunks |
| `!reindex` | Administrator | Triggers reindex via `/reindex` API; reloads index on success |
| `@bot <question>` | Everyone | Same as `!rag` but triggered by mention |

---

## No Tests / No CI

There is currently **no test suite** and **no CI/CD pipeline**. When adding tests:
- Use `pytest` (not yet in requirements.txt — add it)
- Test files should follow `test_<module>.py` naming
- Place tests in a `tests/` directory at the project root

---

## Important Constraints

1. **Never hardcode tokens or secrets.** All credentials are injected via environment variables.
2. **FAISS index must exist before the bot can answer queries.** Run `!reindex` after first deploy.
3. **Only PDF and DOCX files are indexed.** `.doc` files are auto-converted; all other formats are discarded.
4. **Ingest is serialized by a file lock.** Only one ingest run at a time; lock auto-expires after 2 hours.
5. **Discord replies are capped at 1900 chars.** Truncate all bot responses with `[:1900]`.
6. **The bot runs with uid 1000** on HF Spaces. Do not assume root access.
7. **`DOCS_REPO_ID` and `INDEX_REPO_ID` are only required by `ingest_job.py`**, not by the bot at query time. The bot only reads from the local FAISS index.
