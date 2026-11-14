# jaguarserve-agent

Minimal, production-shaped chatbot agent: a self-hosted LLM with tool calling, retrieval over a product catalog, prices and stock by user role, appointment booking with explicit confirmation, and allow-listed web search. Every factual claim is cited. The target domain is medical-equipment product information (equipment only, no clinical advice).

Status: baseline code for plan phases 1–6 plus the local compose file. The plan and cost notes are local only (see below).

This repository is public. It contains no real company data: the demo catalog in `data/demo_catalog/` is fictional (brands, models, prices, stock).

## How it works

```
browser ── POST /v1/chat (SSE) ──► agent-api (FastAPI, CPU)
                                     ├─ scope pre-filter (no clinical questions)
                                     ├─ tool loop ──► vLLM (GPU) : OpenAI chat completions + tools
                                     │     tools: search_catalog, list_products, get_product, check_availability,
                                     │            get_price (role), list_slots, book_appointment (confirm first),
                                     │            web_search / fetch_page (allow-list)
                                     ├─ guardrails: citation ids, prices grounded in tool results, no internal prices
                                     └─ Postgres + pgvector (or in-memory): products, chunks, appointments
```

SSE events: `session`, `status` (`warming_up` while a scaled-to-zero GPU starts), `tool`, `slots`, `confirm`, `booking`, `token`, `citation`, `error`, `done`.

## Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker for the Postgres variant, and a GPU for the model: local or a cloud VM (an L4 24 GB runs model A or B). The API only needs the model's URL in `LLM_BASE_URL`.

1. Start the model on the GPU machine in its own terminal (long-running), or point `LLM_BASE_URL` at a remote vLLM:

   ```bash
   serve/serve_llm.sh            # model A: Qwen3-14B AWQ on :8002
   ```

   Machine-specific variables (CUDA library paths and so on) go in `serve/local.env` (gitignored).

2. Run the API without a database (catalog loaded in memory at startup):

   ```bash
   uv sync
   uv run uvicorn api.app:app --port 8080     # then open http://localhost:8080
   ```

3. Or run with Postgres + pgvector and the multilingual CPU embedding model:

   ```bash
   cp .env.example .env                        # set POSTGRES_PASSWORD
   docker compose up -d --build
   docker compose --profile tools run --rm ingest
   ```

   Optional profiles: `gpu` (vLLM in a container instead of step 1), `search` (SearXNG), `obs` (Prometheus).

Internal role: set `INTERNAL_TOKENS` and paste a token in the page header. Internal users see internal-only products and prices.

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest                       # offline: fake LLM, in-memory store, fake search
TEST_DATABASE_URL=postgresql://... uv run pytest -m pg     # Postgres suite (disposable database)
uv run python -m eval.probe_tools   # tool-calling probe against the running vLLM (20 prompts)
uv run python -m eval.run_redteam   # 40 red-team prompts against the running API
```

## Layout

| Path | What |
|---|---|
| `agent/` | loop, tools, LLM client, guardrails, sessions, catalog stores, mock calendar, web search |
| `api/` | FastAPI app, rate limits |
| `ingest/` | catalog ingestion CLI (`python -m ingest <dir>`) |
| `web/index.html` | chat page (served at `/`) |
| `serve/` | vLLM launch script and model profiles A and B |
| `eval/` | tool-calling probe, red-team set and runner |
| `db/schema.sql` | Postgres schema (applied at startup) |
| `data/demo_catalog/` | fictional catalog; regenerate with `scripts/make_demo_catalog.py` |

Every setting is an environment variable listed in `.env.example` (defaults in `agent/config.py`).

## Internal documents (local only, gitignored)

`internal/` and `plans/` are gitignored. Agents and contributors working locally: read these first if they exist on your machine. Never copy their contents into tracked files.

- `plans/plan_minimal_agent.md` — implementation plan (phases, checklist, decisions)
- `plans/economics.md` — cost, cold start and GPU count per scenario
- `plans/checks.md` — pre-implementation checks
- `internal/internal_agents.md` — rules and setup for agents
- `internal/project_context.md` — project background
- `internal/questions.md` — open decisions

## Licence

Apache-2.0.
