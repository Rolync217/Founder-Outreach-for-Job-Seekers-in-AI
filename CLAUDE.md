# Outreach Pipeline — Claude Code Instructions

This is a research and drafting pipeline for founder outreach. It finds early-stage AI companies, reads their product and hiring signals, scores fit across six dimensions, and drafts personalized outreach messages. The user reviews and sends — there is no automated send layer. Runs on a schedule (`scheduler.py`) or as an MCP server for interactive use with Claude Desktop.

---

## First-time setup

When the user says anything like "set me up", "get me started", or "I just cloned this", follow these steps in order. Don't ask for everything upfront — gather information as each step needs it.

### Step 1 — User profile

Ask the user for:
- Full name
- One-sentence background (what they build, their expertise)
- Target role (e.g. "Founding Engineer", "AI Engineer")
- Target cities (e.g. SF, NYC, Remote-US)

### Step 2 — config.yaml

```bash
cp config.example.yaml config.yaml
```

Fill in the `user_profile` block with the user's answers from Step 1. Leave `pipeline_enabled: false` and `dry_run: true` — safe defaults until they're ready to run.

### Step 3 — API keys and .env

Before asking for `DATABASE_URL`: confirm the user already has a running Postgres instance. If they don't, suggest one of these (all have free tiers): Supabase (supabase.com), Neon (neon.tech), or Railway (railway.app). A local install also works: `brew install postgresql && brew services start postgresql`. Do not proceed past this step until they have a connection string.

Tell the user you need four keys. Ask for them one at a time and tell them where to get each:

- `ANTHROPIC_API_KEY` — console.anthropic.com
- `FIRECRAWL_API_KEY` — firecrawl.dev
- `LINKDAPI_KEY` — linkdapi.com
- `DATABASE_URL` — a Postgres connection string: `postgresql://user:pass@host:5432/dbname`
- `LANGSMITH_API_KEY` — optional, smith.langchain.com (for pipeline tracing)

```bash
cp .env.example .env
```

Write the collected keys into `.env`.

### Step 4 — Candidate leverage profile

Edit `skills/candidate-leverage/SKILL.md`. Ask the user for:
- Current or most recent title
- 3–5 specific things they've shipped, with outcomes (e.g. "built a production RAG pipeline serving 20k users")
- In their own words: why early-stage AI companies specifically
- Their 3 strongest signals for a founder hiring a first engineer

Replace all `[placeholder]` lines with their actual answers.

### Step 5 — Personalise the skills files

Four lines across three files contain `[YOUR_FIRST_NAME]` placeholders. Replace each with the user's first name:

- `skills/outreach-rules/SKILL.md` line 3: `"for [YOUR_FIRST_NAME]"` → `"for [FirstName]"`
- `skills/outreach-rules/SKILL.md` line 57: `just "[YOUR_FIRST_NAME]"` → `just "[FirstName]"`
- `skills/outreach-rules/references/rules.md` line 239: `Just "[YOUR_FIRST_NAME]"` → `Just "[FirstName]"`
- `skills/search_scope.yaml` line 76: `the candidate's stack` → `[FirstName]'s stack`

### Step 6 — Choose a runtime: Docker or Python

Ask the user: **"Do you want to run this with Docker or directly with Python?"**

**If Python (local)** — continue to Step 6a.

**If Docker** — skip to Step 6b.

---

### Step 6a — Python: install dependencies and run migration

```bash
pip install -r requirements.txt
playwright install chromium
python tools/migrate.py
```

`DATABASE_URL` must be in `.env`. The migration is idempotent — safe to re-run.

Skip to Step 7 (Done).

---

### Step 6b — Docker: build image and start services

Confirm the user has Docker Desktop installed. If not, tell them to install it from docker.com first.

Make sure `config.yaml` exists on the host (created in Step 2) — it gets mounted into the container and the scheduler crashes without it.

```bash
# Build and start Postgres + the scheduler
docker compose up --build -d

# Run the DB migration inside the container (idempotent — safe to re-run)
docker compose run --rm scheduler python tools/migrate.py
```

> `docker compose up --build` builds the image automatically. No separate `docker build` step needed.

Skip to Step 7 (Done).

---

### Step 7 — Done

Tell the user:
- Everything is set up
- `dry_run: true` is on — no messages will actually send until they change it in `config.yaml`
- To run automatically: set `pipeline_enabled: true` in `config.yaml`, then:
  - Python: `python scheduler.py`
  - Docker: `docker compose up -d` (the scheduler restarts automatically)
- To run interactively: add the MCP server to Claude Desktop (see README.md)

---

## How the pipeline works

**Graph topology (LangGraph):**
```
supervisor → sourcing → supervisor → research → scoring → supervisor → leverage → supervisor → drafting → supervisor → END
```

**Key files:**

| File | Purpose |
|------|---------|
| `pipeline_v2/graph.py` | LangGraph graph definition |
| `pipeline_v2/run.py` | entrypoint — `run_pipeline()` |
| `pipeline_v2/nodes/` | the 6 node implementations |
| `pipeline_v2/lib/tool_router.py` | single import point for all tools (nodes use this, not the MCP server directly) |
| `pipeline_v2/mcp_server/server.py` | FastMCP server — same tools exposed over stdio |
| `pipeline_v2/state.py` | `AgentState` TypedDict — the full state object passed between nodes |
| `skills/search_scope.yaml` | scoring weights, cost caps, iteration limits, dimension priorities |
| `skills/sources.yaml` | 15 source definitions with trust/cost metadata |
| `tools/config_loader.py` | loads `config.yaml` + `.env` at **import time** — `config.yaml` must exist before any node runs |

**Models used:**
- `claude-haiku-4-5-20251001` — entity extraction in the sourcing node (cheap, fast)
- `claude-sonnet-4-6` — main decision-making in research, scoring, leverage, drafting
- Opus — quality eval checkpoints in supervisor and end-of-run summary

**Two runtime modes:**
- **Autonomous** — `scheduler.py` runs the full LangGraph graph on a cron schedule via APScheduler
- **MCP** — `python -m pipeline_v2.mcp_server.server` exposes 17 tools over stdio for Claude Desktop or Claude Code

**MCP mode does NOT expose the pipeline workflow.** Claude Desktop only gets the data-gathering tools (search, scrape, LinkedIn, YC sourcing, Excel export). There is no LangGraph graph, no supervisor, no scoring loop. Claude Desktop is the reasoning layer — it calls tools directly based on the conversation. If you ask it to research a company, it calls the scraping and LinkedIn tools itself.

**Cost controls:**
- Daily cap: `pipeline.cost_cap_daily_usd` in `config.yaml`
- Per-stage cost is logged to the `cost_logs_v2` Postgres table
- `is_over_limit()` is checked before each expensive node

---

## Important

- Never commit `.env` or `config.yaml` — both are gitignored
- `config.yaml` is read at **import time** — if it doesn't exist the process crashes on startup
- `dry_run: true` means no messages send — always verify this before enabling the scheduler
- The sourcing node reads `skills/candidate-leverage/SKILL.md` to understand who to find companies for — if this is empty the outreach will be generic
