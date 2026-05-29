# Model Config From YAML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all hardcoded model name strings in pipeline nodes with lookups from `config.yaml`, so users change one file to swap any model.

**Architecture:** `config_loader.py` wraps the raw YAML dict in a `_Config` subclass that exposes a `.models` attribute returning a `_Models` helper with attribute-style access (`cfg.models.filter`, etc.). Each node replaces its hardcoded constant definition with a single line reading from `cfg.models.<key>`. The `models:` block in `config.example.yaml` is expanded from 3 keys to 8 — one per distinct model role across all nodes.

**Tech Stack:** Python, PyYAML, existing `tools/config_loader.py` pattern

---

## File Map

| File | Change |
|------|--------|
| `tools/config_loader.py` | Add `_Models` + `_Config` classes; replace `cfg = load_config()` with `cfg = _load_config()` |
| `config.example.yaml` | Expand `models:` from 3 keys to 8 keys |
| `config.yaml` (gitignored, on disk) | Same expansion — must be updated manually since gitignored |
| `pipeline_v2/nodes/sourcing.py` | Line 39-40: replace hardcoded strings with `cfg.models.filter` / `cfg.models.sourcing` |
| `pipeline_v2/nodes/research.py` | Line 44-45: replace with `cfg.models.research` / `cfg.models.research_synthesis` |
| `pipeline_v2/nodes/scoring.py` | Line 21: add `cfg` import; line 24: replace with `cfg.models.scoring` |
| `pipeline_v2/nodes/leverage.py` | Line 15: add `cfg` import; line 18: replace with `cfg.models.leverage` |
| `pipeline_v2/nodes/drafting.py` | Line 20: replace with `cfg.models.drafting` (import already present) |
| `pipeline_v2/nodes/supervisor.py` | Line 24: add `cfg` import; line 27: replace with `cfg.models.supervisor` |

---

## Task 1: Update tools/config_loader.py

**Files:**
- Modify: `tools/config_loader.py`

The final file must be exactly:

```python
"""
tools/config_loader.py
Loads config.yaml and .env. All agents import this.
"""
import yaml
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")


class _Models:
    """Attribute-style access to the models block in config.yaml."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getattr__(self, name: str) -> str:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(
                f"Model key '{name}' not found in config.yaml models block. "
                f"Available keys: {list(self._data.keys())}"
            )


class _Config(dict):
    """dict subclass that also exposes cfg.models for attribute-style access."""

    @property
    def models(self) -> _Models:
        return _Models(self.get("models") or {})


def _load_config() -> _Config:
    with open(ROOT / "config.yaml") as f:
        return _Config(yaml.safe_load(f))


cfg = _load_config()
```

- [ ] Verify `tools/config_loader.py` matches the above exactly. If not, rewrite it.
- [ ] Run: `cd /Users/abhinavanand/outreach-pipeline/.worktrees/feature-model-config && python -c "from tools.config_loader import cfg; print(cfg.models.filter)"`
  Expected output: the model string set under `filter:` in config.yaml (e.g. `deepseek/deepseek-chat`)

---

## Task 2: Expand models block in config.example.yaml

**Files:**
- Modify: `config.example.yaml` (lines 51-54)

The `models:` block must be replaced with exactly:

```yaml
models:
  filter: "claude-haiku-4-5-20251001"          # sourcing node — entity extraction (cheap/fast)
  sourcing: "claude-sonnet-4-6"                # sourcing node — company planning
  research: "claude-sonnet-4-6"                # research node — deep research iterations
  research_synthesis: "claude-opus-4-6"        # research node — final synthesis checkpoints
  scoring: "claude-sonnet-4-6"                 # scoring node
  leverage: "claude-opus-4-6"                  # leverage node
  drafting: "claude-sonnet-4-6"                # drafting node
  supervisor: "claude-opus-4-6"                # supervisor node — quality gate + summary
```

Note: `config.example.yaml` uses original Anthropic model IDs (no `provider/` prefix) as the default template for new users who may not use OpenRouter. Users who set `ANTHROPIC_BASE_URL` and want OpenRouter-specific models update their own `config.yaml`.

- [ ] Verify `config.example.yaml` `models:` block has exactly 8 keys with the values above.

---

## Task 3: Update local config.yaml (gitignored)

**Files:**
- Modify: `config.yaml` (gitignored — exists on disk, not tracked by git)

The `models:` block in the local `config.yaml` must be expanded to 8 keys. Use the OpenRouter model IDs since this is the user's active config routing through OpenRouter:

```yaml
models:
  filter: "deepseek/deepseek-chat"                # sourcing node — entity extraction
  sourcing: "anthropic/claude-sonnet-4-6"         # sourcing node — company planning
  research: "deepseek/deepseek-r1"                # research node — deep research
  research_synthesis: "anthropic/claude-opus-4-6" # research node — final synthesis
  scoring: "anthropic/claude-sonnet-4-6"          # scoring node
  leverage: "anthropic/claude-opus-4-6"           # leverage node
  drafting: "anthropic/claude-sonnet-4-6"         # drafting node
  supervisor: "anthropic/claude-opus-4-6"         # supervisor node
```

- [ ] Read `config.yaml`, find the `models:` block, replace it with the 8 keys above.
- [ ] Verify with: `python -c "from tools.config_loader import cfg; print(list(cfg['models'].keys()))"`
  Expected: `['filter', 'sourcing', 'research', 'research_synthesis', 'scoring', 'leverage', 'drafting', 'supervisor']`

---

## Task 4: Wire sourcing.py

**Files:**
- Modify: `pipeline_v2/nodes/sourcing.py` lines 39-40

`cfg` import already exists at line 32. The constant block must be:

```python
_HAIKU_MODEL = cfg.models.filter
_SONNET_MODEL = cfg.models.sourcing
```

- [ ] Verify lines 39-40 of `sourcing.py` match the above.

---

## Task 5: Wire research.py

**Files:**
- Modify: `pipeline_v2/nodes/research.py` lines 44-45

`cfg` import already exists at line 36. The constant block must be:

```python
_SONNET_MODEL = cfg.models.research
_OPUS_MODEL = cfg.models.research_synthesis
```

- [ ] Verify lines 44-45 of `research.py` match the above.

---

## Task 6: Wire scoring.py

**Files:**
- Modify: `pipeline_v2/nodes/scoring.py`

`cfg` import must be added (not present in original). Final state of imports + constant (around line 20-25):

```python
from tools.config_loader import cfg

logger = logging.getLogger(__name__)

_SONNET_MODEL = cfg.models.scoring
```

- [ ] Verify `scoring.py` has `from tools.config_loader import cfg` and `_SONNET_MODEL = cfg.models.scoring`.

---

## Task 7: Wire leverage.py

**Files:**
- Modify: `pipeline_v2/nodes/leverage.py`

`cfg` import must be added. Final state:

```python
from tools.config_loader import cfg

logger = logging.getLogger(__name__)

_OPUS_MODEL = cfg.models.leverage
```

- [ ] Verify `leverage.py` has `from tools.config_loader import cfg` and `_OPUS_MODEL = cfg.models.leverage`.

---

## Task 8: Wire drafting.py

**Files:**
- Modify: `pipeline_v2/nodes/drafting.py` line 20

`cfg` import already exists at line 16. The constant must be:

```python
_SONNET_MODEL = cfg.models.drafting
```

- [ ] Verify line 20 of `drafting.py` is `_SONNET_MODEL = cfg.models.drafting`.

---

## Task 9: Wire supervisor.py

**Files:**
- Modify: `pipeline_v2/nodes/supervisor.py`

`cfg` import must be added. Final state:

```python
from tools.config_loader import cfg

logger = logging.getLogger(__name__)

_OPUS_MODEL = cfg.models.supervisor
```

- [ ] Verify `supervisor.py` has `from tools.config_loader import cfg` and `_OPUS_MODEL = cfg.models.supervisor`.

---

## Task 10: Final import smoke test + commit

- [ ] Run from the worktree root:
  ```bash
  cd /Users/abhinavanand/outreach-pipeline/.worktrees/feature-model-config
  python -c "
  from tools.config_loader import cfg
  from pipeline_v2.nodes import sourcing, research, scoring, leverage, drafting, supervisor
  print('filter   :', sourcing._HAIKU_MODEL)
  print('sourcing :', sourcing._SONNET_MODEL)
  print('research :', research._SONNET_MODEL)
  print('synthesis:', research._OPUS_MODEL)
  print('scoring  :', scoring._SONNET_MODEL)
  print('leverage :', leverage._OPUS_MODEL)
  print('drafting :', drafting._SONNET_MODEL)
  print('supervisor:', supervisor._OPUS_MODEL)
  "
  ```
  Expected: 8 lines each printing the model string from config.yaml — no AttributeError, no ImportError.

- [ ] Stage and commit all tracked file changes (NOT config.yaml — it is gitignored):
  ```bash
  git add tools/config_loader.py config.example.yaml \
    pipeline_v2/nodes/sourcing.py pipeline_v2/nodes/research.py \
    pipeline_v2/nodes/scoring.py pipeline_v2/nodes/leverage.py \
    pipeline_v2/nodes/drafting.py pipeline_v2/nodes/supervisor.py \
    docs/superpowers/plans/2026-05-29-model-config-from-yaml.md
  git commit -m "Wire config.yaml models block to all pipeline nodes"
  ```
  If a commit already exists from a previous run, amend it: `git commit --amend --no-edit`
