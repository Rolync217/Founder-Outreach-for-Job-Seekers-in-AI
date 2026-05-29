# Rename Model Variables to Role-Based Names

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename all `_HAIKU_MODEL`, `_SONNET_MODEL`, `_OPUS_MODEL` variables in pipeline nodes to role-based names so the code is model-agnostic (works with DeepSeek, GPT-4o, Kimi, or any other provider).

**Architecture:** Pure rename — no logic changes. Each variable gets a new name that matches its `config.yaml` key. Use `replace_all=True` on each rename to catch every occurrence in the file in one edit.

**Tech Stack:** Python (no dependencies change)

---

## Rename mapping

| File | Old name | New name | Occurrences |
|------|----------|----------|-------------|
| `sourcing.py` | `_HAIKU_MODEL` | `_FILTER_MODEL` | lines 39, 532, 540, 821 |
| `sourcing.py` | `_SONNET_MODEL` | `_SOURCING_MODEL` | lines 40, 330, 661, 668, 729 |
| `research.py` | `_SONNET_MODEL` | `_RESEARCH_MODEL` | lines 44, 338, 482, 743, 748, 767, 893, 898, 945 |
| `research.py` | `_OPUS_MODEL` | `_SYNTHESIS_MODEL` | lines 45, 633, 991, 996, 1024, 1054 |
| `scoring.py` | `_SONNET_MODEL` | `_SCORING_MODEL` | lines 25, 93, 170, 175, 211 |
| `leverage.py` | `_OPUS_MODEL` | `_LEVERAGE_MODEL` | lines 19, 111, 168, 218, 223, 237, 245, 250, 284 |
| `drafting.py` | `_SONNET_MODEL` | `_DRAFTING_MODEL` | lines 20, 237, 243, 272, 278, 322, 338, 377 |
| `supervisor.py` | `_OPUS_MODEL` | `_SUPERVISOR_MODEL` | lines 28, 140, 148, 197, 203, 347 |

**No other files need changing.** `config_loader.py`, `config.yaml`, `config.example.yaml` are untouched.

---

## Task 1: sourcing.py — rename _HAIKU_MODEL → _FILTER_MODEL

**Files:**
- Modify: `pipeline_v2/nodes/sourcing.py`

- [ ] Read the file first.
- [ ] Replace all occurrences of `_HAIKU_MODEL` with `_FILTER_MODEL` using replace_all=True.
- [ ] Verify with:
  ```bash
  grep -n "_HAIKU_MODEL" pipeline_v2/nodes/sourcing.py
  ```
  Expected: no output (zero occurrences remaining).
- [ ] Verify new name exists:
  ```bash
  grep -n "_FILTER_MODEL" pipeline_v2/nodes/sourcing.py
  ```
  Expected: lines 39, 532, 540, 821.

---

## Task 2: sourcing.py — rename _SONNET_MODEL → _SOURCING_MODEL

**Files:**
- Modify: `pipeline_v2/nodes/sourcing.py`

- [ ] Replace all occurrences of `_SONNET_MODEL` with `_SOURCING_MODEL` using replace_all=True.
- [ ] Verify with:
  ```bash
  grep -n "_SONNET_MODEL" pipeline_v2/nodes/sourcing.py
  ```
  Expected: no output.
- [ ] Verify new name exists:
  ```bash
  grep -n "_SOURCING_MODEL" pipeline_v2/nodes/sourcing.py
  ```
  Expected: lines 40, 330, 661, 668, 729.

---

## Task 3: research.py — rename _SONNET_MODEL → _RESEARCH_MODEL

**Files:**
- Modify: `pipeline_v2/nodes/research.py`

- [ ] Read the file first.
- [ ] Replace all occurrences of `_SONNET_MODEL` with `_RESEARCH_MODEL` using replace_all=True.
- [ ] Verify with:
  ```bash
  grep -n "_SONNET_MODEL" pipeline_v2/nodes/research.py
  ```
  Expected: no output.
- [ ] Verify new name exists:
  ```bash
  grep -n "_RESEARCH_MODEL" pipeline_v2/nodes/research.py
  ```
  Expected: lines 44, 338, 482, 743, 748, 767, 893, 898, 945.

---

## Task 4: research.py — rename _OPUS_MODEL → _SYNTHESIS_MODEL

**Files:**
- Modify: `pipeline_v2/nodes/research.py`

- [ ] Replace all occurrences of `_OPUS_MODEL` with `_SYNTHESIS_MODEL` using replace_all=True.
- [ ] Verify with:
  ```bash
  grep -n "_OPUS_MODEL" pipeline_v2/nodes/research.py
  ```
  Expected: no output.
- [ ] Verify new name exists:
  ```bash
  grep -n "_SYNTHESIS_MODEL" pipeline_v2/nodes/research.py
  ```
  Expected: lines 45, 633, 991, 996, 1024, 1054.

---

## Task 5: scoring.py — rename _SONNET_MODEL → _SCORING_MODEL

**Files:**
- Modify: `pipeline_v2/nodes/scoring.py`

- [ ] Read the file first.
- [ ] Replace all occurrences of `_SONNET_MODEL` with `_SCORING_MODEL` using replace_all=True.
- [ ] Verify with:
  ```bash
  grep -n "_SONNET_MODEL" pipeline_v2/nodes/scoring.py
  ```
  Expected: no output.
- [ ] Verify new name exists:
  ```bash
  grep -n "_SCORING_MODEL" pipeline_v2/nodes/scoring.py
  ```
  Expected: lines 25, 93, 170, 175, 211.

---

## Task 6: leverage.py — rename _OPUS_MODEL → _LEVERAGE_MODEL

**Files:**
- Modify: `pipeline_v2/nodes/leverage.py`

- [ ] Read the file first.
- [ ] Replace all occurrences of `_OPUS_MODEL` with `_LEVERAGE_MODEL` using replace_all=True.
- [ ] Verify with:
  ```bash
  grep -n "_OPUS_MODEL" pipeline_v2/nodes/leverage.py
  ```
  Expected: no output.
- [ ] Verify new name exists:
  ```bash
  grep -n "_LEVERAGE_MODEL" pipeline_v2/nodes/leverage.py
  ```
  Expected: lines 19, 111, 168, 218, 223, 237, 245, 250, 284.

---

## Task 7: drafting.py — rename _SONNET_MODEL → _DRAFTING_MODEL

**Files:**
- Modify: `pipeline_v2/nodes/drafting.py`

- [ ] Read the file first.
- [ ] Replace all occurrences of `_SONNET_MODEL` with `_DRAFTING_MODEL` using replace_all=True.
- [ ] Verify with:
  ```bash
  grep -n "_SONNET_MODEL" pipeline_v2/nodes/drafting.py
  ```
  Expected: no output.
- [ ] Verify new name exists:
  ```bash
  grep -n "_DRAFTING_MODEL" pipeline_v2/nodes/drafting.py
  ```
  Expected: lines 20, 237, 243, 272, 278, 322, 338, 377.

---

## Task 8: supervisor.py — rename _OPUS_MODEL → _SUPERVISOR_MODEL

**Files:**
- Modify: `pipeline_v2/nodes/supervisor.py`

- [ ] Read the file first.
- [ ] Replace all occurrences of `_OPUS_MODEL` with `_SUPERVISOR_MODEL` using replace_all=True.
- [ ] Verify with:
  ```bash
  grep -n "_OPUS_MODEL" pipeline_v2/nodes/supervisor.py
  ```
  Expected: no output.
- [ ] Verify new name exists:
  ```bash
  grep -n "_SUPERVISOR_MODEL" pipeline_v2/nodes/supervisor.py
  ```
  Expected: lines 28, 140, 148, 197, 203, 347.

---

## Task 9: Final verification + commit

- [ ] Confirm zero old names remain anywhere in the nodes directory:
  ```bash
  grep -rn "_HAIKU_MODEL\|_SONNET_MODEL\|_OPUS_MODEL" pipeline_v2/nodes/
  ```
  Expected: no output.

- [ ] Confirm all new names are present:
  ```bash
  grep -rn "_FILTER_MODEL\|_SOURCING_MODEL\|_RESEARCH_MODEL\|_SYNTHESIS_MODEL\|_SCORING_MODEL\|_LEVERAGE_MODEL\|_DRAFTING_MODEL\|_SUPERVISOR_MODEL" pipeline_v2/nodes/
  ```
  Expected: 8 distinct names, each appearing in exactly one file.

- [ ] Run import smoke test:
  ```bash
  python -c "
  from pipeline_v2.nodes import sourcing, research, scoring, leverage, drafting, supervisor
  print('filter   :', sourcing._FILTER_MODEL)
  print('sourcing :', sourcing._SOURCING_MODEL)
  print('research :', research._RESEARCH_MODEL)
  print('synthesis:', research._SYNTHESIS_MODEL)
  print('scoring  :', scoring._SCORING_MODEL)
  print('leverage :', leverage._LEVERAGE_MODEL)
  print('drafting :', drafting._DRAFTING_MODEL)
  print('supervisor:', supervisor._SUPERVISOR_MODEL)
  "
  ```
  Expected: 8 lines each printing the model string from config.yaml — no errors.

- [ ] Commit:
  ```bash
  git add pipeline_v2/nodes/sourcing.py pipeline_v2/nodes/research.py \
    pipeline_v2/nodes/scoring.py pipeline_v2/nodes/leverage.py \
    pipeline_v2/nodes/drafting.py pipeline_v2/nodes/supervisor.py \
    docs/superpowers/plans/2026-05-29-rename-model-variables.md
  git commit -m "Rename model variables to role-based names (provider-agnostic)"
  ```
