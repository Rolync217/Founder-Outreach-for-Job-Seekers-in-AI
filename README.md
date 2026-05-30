# Outreach Pipeline

A research and drafting pipeline for founder outreach. It finds early-stage AI companies, reads their product and hiring signals, scores your fit, and writes a personalized message — then runs on a schedule or responds interactively through Claude Code or Claude Desktop. You review and send.

## What it does

1. **Sourcing** — finds AI startups via YC Algolia, LinkedIn posts, and funding news
2. **Research** — scrapes each company's website, jobs page, and LinkedIn using Firecrawl
3. **Scoring** — rates fit across six dimensions: hiring intent, founder background, product, traction, recency, alignment
4. **Leverage** — matches your background to what the company is actually building
5. **Drafting** — writes a LinkedIn invite, DM, or longer reference message

Drafted messages are stored in Postgres. Sending is not yet implemented — `dry_run: true` is the default and there is no send layer. This is a research and drafting pipeline.

## You'll need API keys for

| Service | Used for | Required |
|---------|----------|----------|
| LLM provider (your choice) | all LLM calls — OpenRouter (recommended), Anthropic, Moonshot, or OpenAI | yes — one key for your chosen provider |
| [Firecrawl](https://firecrawl.dev) | web scraping and search | yes |
| [LinkdAPI](https://linkdapi.com) | LinkedIn hiring signals | yes |
| PostgreSQL | data storage | yes |
| [LangSmith](https://smith.langchain.com) | pipeline tracing | optional |

**LLM provider options** (one key required):
- **[OpenRouter](https://openrouter.ai/keys)** — recommended. One key covers 200+ models from Anthropic, DeepSeek, OpenAI, and others. Model strings use prefix `openrouter/` — e.g. `openrouter/anthropic/claude-sonnet-4-6`
- **[Anthropic direct](https://console.anthropic.com)** — if you have a direct Anthropic API key. Prefix: `anthropic/` — e.g. `anthropic/claude-sonnet-4-6`
- **[Moonshot / Kimi](https://platform.moonshot.cn)** — Prefix: `moonshot/` — e.g. `moonshot/moonshot-v1-8k`
- **[OpenAI](https://platform.openai.com)** — Prefix: `openai/` — e.g. `openai/gpt-4o`

---

## Quickest start

**One prerequisite:** you need a running Postgres database. The pipeline stores everything there and the agent cannot provision one for you. Any of these work:
- Local: `brew install postgresql && brew services start postgresql`
- Hosted (free tier): [Supabase](https://supabase.com), [Neon](https://neon.tech), [Railway](https://railway.app)

> **Supabase users:** use the **Session mode** connection string, not the Direct connection. The direct connection is IPv6-only and will fail on most networks. In your Supabase dashboard click **Connect → Session pooler** and copy that URL.

Once you have a connection string (`postgresql://user:pass@host:5432/dbname`), open the repo in **Claude Code** or **Codex** and paste this:

```
I just cloned this outreach-pipeline repo. Read CLAUDE.md and set up the entire project for me.
Ask me for my personal details and API keys as you go.
Install all dependencies, run the database migration, and leave the project ready to run.
```

The agent will ask for your information, fill in all config files, install dependencies, and run the migration. You don't need to do anything else.

---

## Manual setup (if you prefer)

```bash
cp config.example.yaml config.yaml   # fill in user_profile section
cp .env.example .env                 # fill in API keys
# fill in skills/candidate-leverage/SKILL.md with your background
pip install -r requirements.txt
playwright install chromium
python tools/migrate.py
```

---

## Upgrading from an older version

### Upgrading from the OpenRouter SDK-hack setup (pre-LiteLLM, before June 2026)

If your `.env` has `ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1`, you're on the old setup. The pipeline now uses LiteLLM, so model strings and the env var have changed.

**1. Update `.env`:** Replace `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` with `OPENROUTER_API_KEY`:
```bash
# Remove these two lines:
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1

# Add this instead:
OPENROUTER_API_KEY=sk-or-v1-...
```

**2. Update model strings in `config.yaml`:** All model strings now require a provider prefix. Add `openrouter/` in front of every model entry:
```yaml
# Before:
filter: "deepseek/deepseek-chat"
sourcing: "anthropic/claude-sonnet-4-6"

# After:
filter: "openrouter/deepseek/deepseek-chat"
sourcing: "openrouter/anthropic/claude-sonnet-4-6"
```
Apply this to all 8 keys. Or just re-copy the example: `cp config.example.yaml config.yaml` then re-fill your `user_profile` block.

**3. Install LiteLLM:**
```bash
pip install -r requirements.txt
```

### Upgrading from before May 2026 (missing model keys)

If you already have a `config.yaml` from before May 2026, the `models:` block needs to be updated — 5 new model-role keys were added. You have two options:

**Option A (recommended):** Re-copy the example and re-fill your profile:
```bash
cp config.example.yaml config.yaml
# Then re-enter your user_profile details (name, background, target_role, etc.)
```

**Option B:** Open your existing `config.yaml` and add the 5 missing keys under `models:` (using your chosen provider prefix):
```yaml
models:
  # ... your existing keys ...
  sourcing: "openrouter/anthropic/claude-sonnet-4-6"
  research_synthesis: "openrouter/anthropic/claude-opus-4-6"
  scoring: "openrouter/anthropic/claude-sonnet-4-6"
  leverage: "openrouter/anthropic/claude-opus-4-6"
  supervisor: "openrouter/anthropic/claude-opus-4-6"
```

---

## Model configuration

All model names live in `config.yaml` under the `models:` block. Change any entry to swap the model for that role — no Python edits needed. Model strings use LiteLLM's `provider/model` prefix format:

| Prefix | Provider | Required env var |
|--------|----------|-----------------|
| `openrouter/` | OpenRouter (default) | `OPENROUTER_API_KEY` |
| `anthropic/` | Anthropic direct | `ANTHROPIC_API_KEY` |
| `moonshot/` | Moonshot / Kimi | `MOONSHOT_API_KEY` |
| `openai/` | OpenAI | `OPENAI_API_KEY` |

Example: `openrouter/anthropic/claude-sonnet-4-6` routes via OpenRouter; change the prefix to `anthropic/claude-sonnet-4-6` to call Anthropic directly.

| Key | Node | Role | Default |
|-----|------|------|---------|
| `filter` | sourcing | Entity extraction from raw search results — cheap, high-volume | `openrouter/deepseek/deepseek-chat` |
| `sourcing` | sourcing | Company planning and search query generation | `openrouter/anthropic/claude-sonnet-4-6` |
| `research` | research | Per-iteration source selection and knowledge evaluation | `openrouter/deepseek/deepseek-r1` |
| `research_synthesis` | research | Advisor checkpoints — synthesizes or redirects the agent when stuck | `openrouter/anthropic/claude-opus-4-6` |
| `scoring` | scoring | Assigns qualitative fit labels across 6 dimensions | `openrouter/anthropic/claude-sonnet-4-6` |
| `leverage` | leverage | Matches your background to what the company is actually building | `openrouter/anthropic/claude-opus-4-6` |
| `drafting` | drafting | Writes the outreach message | `openrouter/anthropic/claude-sonnet-4-6` |
| `supervisor` | supervisor | Quality gate decisions and end-of-run summary | `openrouter/anthropic/claude-opus-4-6` |

> **Cost accuracy note:** When using OpenRouter, per-token pricing may differ slightly from the provider list prices used internally for tracking. The pipeline's daily cost cap (`cost_cap_daily_usd` in `config.yaml`) is an estimate — actual charges on your provider invoice may be a little higher or lower. To stay safely within your real budget, set `cost_cap_daily_usd` a few dollars below your actual daily limit.

**Provider prefixes:** Model strings follow LiteLLM's `provider/model` format. Change the prefix to switch providers without touching any Python code:
- `openrouter/anthropic/claude-sonnet-4-6` — via OpenRouter (default)
- `anthropic/claude-sonnet-4-6` — Anthropic direct
- `moonshot/moonshot-v1-8k` — Moonshot / Kimi direct
- `openai/gpt-4o` — OpenAI direct

Set the matching API key in `.env` — only the one for your chosen provider is needed.

---

## Viewing your data

**Export to Excel:**

The pipeline automatically writes `reports/outreach_export_<timestamp>.xlsx` at the end of every run. Open it directly — no extra command needed.

To export manually at any time:
```bash
python tools/export.py
```

Sheets: Companies · Scores · Outreach Drafts · Research

**Connect directly with a Postgres client:**

Point any client (TablePlus, DBeaver, psql) at your `DATABASE_URL`. Key tables:

| Table | Contents |
|---|---|
| `companies_v2` | every sourced company |
| `scoring_v2` | fit scores across 6 dimensions |
| `outreach_v2` | drafted messages |
| `research_v2` | product, hiring signals, founder info |

---

## Running

**Autonomous (scheduled):**

```bash
python scheduler.py
```

Set `pipeline_enabled: true` in `config.yaml` first. Or with Docker:

```bash
# 1. Copy and fill .env (including POSTGRES_PASSWORD) and config.yaml
cp .env.example .env && cp config.example.yaml config.yaml
# edit both files, then:

# 2. Build the image and start Postgres + the scheduler
docker compose up --build -d

# 3. Run migrations (safe to re-run)
docker compose run --rm scheduler python tools/migrate.py
```

> **Note:** `config.yaml` is gitignored. It must exist on the host before running `docker compose up` — the scheduler mounts it at startup and crashes without it.

**Interactive via Claude Desktop (MCP):**

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "outreach-pipeline": {
      "command": "python",
      "args": ["-m", "pipeline_v2.mcp_server.server"],
      "cwd": "/absolute/path/to/outreach-pipeline"
    }
  }
}
```

Restart Claude Desktop. The pipeline's 17 tools (search, scrape, LinkedIn, YC sourcing, and Excel export) will be available as MCP tools you can call directly in conversation.

**Important:** In MCP mode, Claude Desktop has access to the data-gathering tools only — the LangGraph pipeline workflow is not exposed. Claude Desktop is itself the reasoning layer. You ask it to research a company, check hiring signals, or draft a message, and it calls the tools directly based on your conversation. There is no graph execution, no supervisor node, and no scoring loop running in the background.

---

## Project structure

```
pipeline_v2/           main pipeline (LangGraph, 6 nodes)
  nodes/               sourcing, research, scoring, leverage, drafting, supervisor
  lib/                 cost tracking, DB persistence, scoring math, config loaders
  mcp_server/          FastMCP server + tool implementations (17 tools)
skills/                YAML/Markdown config loaded at runtime by the nodes
  search_scope.yaml    scoring weights, cost caps, dimension priorities
  sources.yaml         15 source definitions with trust and cost metadata
  candidate-leverage/  your background profile — fill this in before running
  outreach-rules/      message format rules, tone templates, examples
tools/                 shared utilities: config loader, DB connection, migrations
migrations/            SQL schema — run once via python tools/migrate.py
scheduler.py           APScheduler entry point (runs pipeline_v2)
config.example.yaml    template — copy to config.yaml and fill in
.env.example           template — copy to .env and fill in
```
