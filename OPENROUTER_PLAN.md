# Plan: Route All LLM Calls Through OpenRouter

## How it works (zero code changes)

The Anthropic Python SDK reads two environment variables at startup:

| Env var | Default | What to override |
|---|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key | your OpenRouter key |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | `https://openrouter.ai/api/v1` |

Every `anthropic.Anthropic()` call in the codebase picks these up automatically — no imports, no constructor args, nothing to touch. Setting both vars in `.env` redirects every node to OpenRouter.

---

## Step 1 — Add to `.env`

Replace your current `ANTHROPIC_API_KEY` line and add the base URL override:

```env
# ── AI / LLM ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-or-v1-...your-openrouter-key...
ANTHROPIC_BASE_URL=https://openrouter.ai/api
```

Get your key at: openrouter.ai → Keys

---

## Step 2 — Update model names in `config.yaml`

`config.yaml` has a `models:` block. The three values there drive the filter, research, and drafting nodes. Change them to OpenRouter model IDs:

```yaml
models:
  filter: "deepseek/deepseek-chat"           # replaces claude-haiku — cheap, fast entity extraction
  research: "deepseek/deepseek-r1"           # replaces claude-opus — strong reasoning for research
  drafting: "anthropic/claude-sonnet-4-6"    # keep Sonnet via OpenRouter, or swap below
```

### Recommended alternatives

| Job | Suggested model | Why |
|---|---|---|
| `filter` (entity extraction, cheap) | `deepseek/deepseek-chat` | ~1/20th the cost of Haiku, same quality for JSON extraction |
| `filter` (fallback) | `google/gemini-flash-1.5` | Fast, very cheap, good at structured output |
| `research` (heavy reasoning) | `deepseek/deepseek-r1` | Best open-weight reasoning model, cheap vs Opus |
| `research` (fallback) | `anthropic/claude-opus-4-6` | Anthropic Opus via OpenRouter — same model, routed cost |
| `drafting` | `anthropic/claude-sonnet-4-6` | Keep Sonnet, just routed through OpenRouter |
| `drafting` (cheaper) | `openai/gpt-4o-mini` | Good at following tone/format rules |

---

## Step 3 — One hardcoded model to be aware of

`pipeline_v2/nodes/supervisor.py` line 27 has a hardcoded constant that is **not** read from `config.yaml`:

```python
_OPUS_MODEL = "claude-opus-4-6"
```

This controls the supervisor's quality-gate decisions (promotes/skips companies, writes end-of-run summary). It **will** still route through OpenRouter once `ANTHROPIC_BASE_URL` is set — but the model name stays `claude-opus-4-6`. OpenRouter knows this model ID so it works as-is.

If you want to swap the supervisor to a different model (e.g. DeepSeek R1), that is a **one-line change** in supervisor.py. Not urgent — the env vars alone are enough to get everything routed.

---

## What does NOT need to change

- No Python file edits (except the optional one-liner in supervisor.py above)
- `wrap_anthropic()` from LangSmith wraps the same client — it follows `ANTHROPIC_BASE_URL` automatically
- All 6 nodes + `linkdapi_v2.py` use bare `anthropic.Anthropic()` with no hardcoded base URL or key
- `tools/config_loader.py`, `tools/db_conn.py`, Firecrawl, LinkdAPI — unaffected

---

## Verification (after making the changes)

Run a smoke test — it caps at 2 companies and uses the cheapest paths:

```bash
python scheduler.py --smoke-test
```

Watch the logs for lines like:
```
model=deepseek/deepseek-chat  # confirms the new model IDs are being sent
```

If you see a `401` or `model not found` error, the most likely cause is either the wrong key format in `.env` or a model ID typo in `config.yaml`. OpenRouter model IDs are always `provider/model-name` — check openrouter.ai/models for the exact string.

---

## Summary of files to touch

| File | Change |
|---|---|
| `.env` | Replace `ANTHROPIC_API_KEY` value + add `ANTHROPIC_BASE_URL` |
| `config.yaml` | Update 3 model names under `models:` |
| `pipeline_v2/nodes/supervisor.py` line 27 | Optional: change `_OPUS_MODEL` string if you want supervisor on a different model |
