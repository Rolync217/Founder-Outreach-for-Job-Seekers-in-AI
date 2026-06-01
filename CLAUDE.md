# Outreach Pipeline — Claude Code Instructions

This is a research and drafting pipeline for founder outreach. It finds early-stage AI companies, reads their product and hiring signals, scores fit across six dimensions, and drafts personalized outreach messages. The user reviews and sends — there is no automated send layer. Runs on a schedule (`scheduler.py`) or as an MCP server for interactive use with Claude Desktop.

---

## Upgrading an existing installation

### Upgrading from the OpenRouter SDK-hack setup (pre-LiteLLM, before June 2026)

If the user's `.env` has `ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1`, they're on the old setup. The pipeline now uses LiteLLM — model strings and the env var have changed.

Tell the user to:

1. **Update `.env`:** Remove `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL`. Add `OPENROUTER_API_KEY=sk-or-v1-...` instead. Their existing OpenRouter key will work — it's the same key they were using before, just under the correct env var name.

2. **Update `config.yaml` model strings:** All model strings now need a provider prefix. Add `openrouter/` in front of every model entry:
   - `deepseek/deepseek-chat` → `openrouter/deepseek/deepseek-chat`
   - `anthropic/claude-sonnet-4-6` → `openrouter/anthropic/claude-sonnet-4-6`
   - Apply to all 8 keys. Or re-copy: `cp config.example.yaml config.yaml` then re-fill `user_profile`.

3. **Install LiteLLM:** `pip install -r requirements.txt` (or rebuild Docker image).

### Upgrading from before May 2026 (missing model keys)

If the user already has a `config.yaml`, check their `models:` block. The latest version requires 8 keys (see `config.example.yaml`). Missing keys crash the pipeline at startup with an `AttributeError` that tells you which key is absent. Either re-copy `config.example.yaml` (then re-fill `user_profile`) or add the missing keys manually using the `openrouter/` prefix format.

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

Fill in the `user_profile` block with the user's answers from Step 1. Leave `pipeline_enabled: false` — safe default until they're ready to run.

### Step 3 — API keys and .env

Before asking for `DATABASE_URL`: confirm the user already has a running Postgres instance. If they don't, suggest one of these (all have free tiers): Supabase (supabase.com), Neon (neon.tech), or Railway (railway.app). A local install also works: `brew install postgresql && brew services start postgresql`. Do not proceed past this step until they have a connection string.

First ask: **"Which LLM provider do you want to use?"**

Options:
- **OpenRouter** (recommended — one key, 200+ models, easiest setup): ask for `OPENROUTER_API_KEY` from openrouter.ai/keys. The default model strings in `config.yaml` already use `openrouter/` prefix — no changes needed.
- **Anthropic direct**: ask for `ANTHROPIC_API_KEY` from console.anthropic.com. Update all 8 model strings in `config.yaml` to remove the `openrouter/` prefix (e.g. `openrouter/anthropic/claude-sonnet-4-6` → `anthropic/claude-sonnet-4-6`).
- **Moonshot / Kimi direct**: ask for `MOONSHOT_API_KEY` from platform.moonshot.cn. Update model strings in `config.yaml` to `moonshot/moonshot-v1-8k` (or whichever Moonshot model they want).
- **OpenAI direct**: ask for `OPENAI_API_KEY` from platform.openai.com. Update model strings in `config.yaml` to `openai/gpt-4o` or similar.

Then ask for these keys one at a time:

- The provider API key they chose above
- `FIRECRAWL_API_KEY` — firecrawl.dev
- `LINKDAPI_KEY` — linkdapi.com
- `DATABASE_URL` — a Postgres connection string: `postgresql://user:pass@host:5432/dbname`

  **If using Supabase:** do NOT use the "Direct connection" string — it is IPv6 only and will fail on most networks. Use the **Session mode** string instead. In your Supabase dashboard click **Connect → Session pooler** and copy that URL. It looks like: `postgresql://postgres.PROJECTREF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres`
- `LANGSMITH_API_KEY` — optional, smith.langchain.com (for pipeline tracing)

```bash
cp .env.example .env
```

Write the collected keys into `.env`.

### Step 3b — Voice calibration (optional)

```bash
python tools/calibrate_voice.py
```

Fetches your recent LinkedIn posts via LinkdAPI and generates a personal voice profile
for the drafting node. Requires LINKDAPI_KEY to be set. Skippable — the pipeline works
without it, drafts will just follow the base tone rules.

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

**Models:** configured in `config.yaml` under `models:` — 8 keys, one per node role. Change any entry to swap the model; no Python edits needed. See README for the full key reference.

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
- The sourcing node reads `skills/candidate-leverage/SKILL.md` to understand who to find companies for — if this is empty the outreach will be generic
