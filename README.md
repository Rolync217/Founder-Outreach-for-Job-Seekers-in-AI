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
| [Anthropic](https://console.anthropic.com) | all LLM calls | yes |
| [Firecrawl](https://firecrawl.dev) | web scraping and search | yes |
| [LinkdAPI](https://linkdapi.com) | LinkedIn hiring signals | yes |
| PostgreSQL | data storage | yes |
| [LangSmith](https://smith.langchain.com) | pipeline tracing | optional |

---

## Quickest start

**One prerequisite:** you need a running Postgres database. The pipeline stores everything there and the agent cannot provision one for you. Any of these work:
- Local: `brew install postgresql && brew services start postgresql`
- Hosted (free tier): [Supabase](https://supabase.com), [Neon](https://neon.tech), [Railway](https://railway.app)

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

## Viewing your data

**Export to Excel:**
```bash
python tools/export.py
# writes reports/outreach_export_<timestamp>.xlsx
# Sheets: Companies · Scores · Outreach Drafts · Research
```

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

Restart Claude Desktop. The pipeline's 17 tools (search, scrape, LinkedIn, YC sourcing) will be available as MCP tools you can call directly in conversation.

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
