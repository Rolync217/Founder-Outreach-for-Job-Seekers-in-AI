# `/post` Build-in-Public Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a global `/post` skill that reads git context, generates LinkedIn + Twitter posts in Abhinav's writing style, and validates character counts with a deterministic Python script.

**Architecture:** Two files at `~/.claude/skills/post/` — `validate_post.py` handles exact character counting and limit enforcement (exit 0/1), `SKILL.md` holds the full writing style guide and instructs Claude to run the validator before printing posts. The skill has no runtime dependencies beyond standard Python 3.

**Tech Stack:** Python 3 stdlib only (re, sys, unicodedata), SKILL.md YAML frontmatter format matching other skills in `~/.claude/skills/`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `~/.claude/skills/post/validate_post.py` | Exact char counting, limit enforcement, exit codes |
| Create | `~/.claude/skills/post/tests/test_validate_post.py` | Unit tests for all counting rules |
| Create | `~/.claude/skills/post/SKILL.md` | Skill frontmatter + workflow + style guide |

---

## Task 1: Write failing tests for validate_post.py

**Files:**
- Create: `~/.claude/skills/post/tests/test_validate_post.py`

- [ ] **Step 1: Create test file**

```bash
mkdir -p ~/.claude/skills/post/tests
touch ~/.claude/skills/post/tests/__init__.py
```

- [ ] **Step 2: Write tests**

Write `~/.claude/skills/post/tests/test_validate_post.py`:

```python
import subprocess
import sys
import os
import tempfile

SCRIPT = os.path.expanduser("~/.claude/skills/post/validate_post.py")


def run(li_text, tw_text):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lf:
        lf.write(li_text)
        li_path = lf.name
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write(tw_text)
        tw_path = tf.name
    result = subprocess.run(
        [sys.executable, SCRIPT, li_path, tw_path],
        capture_output=True, text=True
    )
    os.unlink(li_path)
    os.unlink(tw_path)
    return result.returncode, result.stdout


def test_both_pass():
    code, out = run("hello", "hi")
    assert code == 0
    assert "✓" in out


def test_linkedin_exact_count():
    text = "a" * 100
    code, out = run(text, "hi")
    assert code == 0
    assert "100 / 3,000" in out


def test_linkedin_over_limit():
    text = "a" * 3001
    code, out = run(text, "hi")
    assert code == 1
    assert "3,001 / 3,000" in out
    assert "✗" in out
    assert "1 chars over" in out


def test_twitter_plain_text():
    text = "a" * 280
    code, out = run("hello", text)
    assert code == 0
    assert "280 / 280" in out


def test_twitter_over_limit():
    text = "a" * 281
    code, out = run("hello", text)
    assert code == 1
    assert "281 / 280" in out
    assert "✗" in out
    assert "1 chars over" in out


def test_twitter_url_counts_as_23():
    # 23 chars for the URL + 10 plain chars = 33 total
    text = "hello hey! https://example.com/this-is-a-long-url-that-doesnt-matter"
    code, out = run("hello", text)
    assert code == 0
    # "hello hey! " = 11 chars + URL = 23 → total 34
    assert "34 / 280" in out


def test_twitter_emoji_counts_as_2():
    # "hi " = 3 chars + 1 emoji = 2 chars → total 5
    text = "hi 🚀"
    code, out = run("hello", text)
    assert code == 0
    assert "5 / 280" in out


def test_twitter_multiple_urls():
    # two URLs = 46 chars, plus "x " = 2 → total 48
    text = "x https://a.com https://b.com"
    code, out = run("hello", text)
    assert code == 0
    assert "48 / 280" in out


def test_newlines_count_as_one_char():
    text = "line1\nline2"  # 11 chars including \n
    code, out = run(text, "hi")
    assert "11 / 3,000" in out
```

- [ ] **Step 3: Run tests — confirm they all fail**

```bash
cd ~/.claude/skills/post && python3 -m pytest tests/test_validate_post.py -v 2>&1 | head -30
```

Expected: errors like `FileNotFoundError` or `ModuleNotFoundError` because `validate_post.py` doesn't exist yet.

---

## Task 2: Implement validate_post.py

**Files:**
- Create: `~/.claude/skills/post/validate_post.py`

- [ ] **Step 1: Write the implementation**

Write `~/.claude/skills/post/validate_post.py`:

```python
#!/usr/bin/env python3
"""
Validates LinkedIn and Twitter post character counts.
Usage: validate_post.py <linkedin_file> <twitter_file>
Exit 0: both posts within limits.
Exit 1: one or more posts exceed limits.
"""

import re
import sys

LINKEDIN_LIMIT = 3000
TWITTER_LIMIT = 280
TWITTER_URL_LENGTH = 23

URL_RE = re.compile(r'https?://\S+')

# Emoji ranges (covers the main Unicode emoji blocks)
EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)


def count_twitter_chars(text: str) -> int:
    working = text
    count = 0

    # Replace each URL with a fixed-length placeholder
    for match in URL_RE.finditer(working):
        count += TWITTER_URL_LENGTH
    working = URL_RE.sub("", working)

    # Each emoji counts as 2
    for match in EMOJI_RE.finditer(working):
        count += 2 * len(match.group())
    working = EMOJI_RE.sub("", working)

    # Everything else is 1 char each
    count += len(working)
    return count


def count_linkedin_chars(text: str) -> int:
    return len(text)


def fmt(count: int, limit: int) -> str:
    status = "✓" if count <= limit else "✗"
    over = f"  ({count - limit} chars over)" if count > limit else ""
    return f"{count:,} / {limit:,} {status}{over}"


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: validate_post.py <linkedin_file> <twitter_file>", file=sys.stderr)
        return 2

    li_path, tw_path = sys.argv[1], sys.argv[2]

    with open(li_path, encoding="utf-8") as f:
        li_text = f.read()
    with open(tw_path, encoding="utf-8") as f:
        tw_text = f.read()

    li_count = count_linkedin_chars(li_text)
    tw_count = count_twitter_chars(tw_text)

    print(f"LinkedIn: {fmt(li_count, LINKEDIN_LIMIT)}")
    print(f"Twitter:  {fmt(tw_count, TWITTER_LIMIT)}")

    failed = li_count > LINKEDIN_LIMIT or tw_count > TWITTER_LIMIT
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/.claude/skills/post/validate_post.py
```

- [ ] **Step 3: Run tests — all should pass**

```bash
cd ~/.claude/skills/post && python3 -m pytest tests/test_validate_post.py -v
```

Expected output:
```
test_both_pass PASSED
test_linkedin_exact_count PASSED
test_linkedin_over_limit PASSED
test_twitter_plain_text PASSED
test_twitter_over_limit PASSED
test_twitter_url_counts_as_23 PASSED
test_twitter_emoji_counts_as_2 PASSED
test_twitter_multiple_urls PASSED
test_newlines_count_as_one_char PASSED
9 passed
```

- [ ] **Step 4: Quick smoke test**

```bash
echo "Hello world" > /tmp/li.txt
echo "Hello 🚀 https://github.com/abhinav-anand217/outreach-pipeline" > /tmp/tw.txt
python3 ~/.claude/skills/post/validate_post.py /tmp/li.txt /tmp/tw.txt
```

Expected:
```
LinkedIn: 11 / 3,000 ✓
Twitter:  32 / 280 ✓
```
(Breakdown: "Hello  " after stripping URL+emoji = 7 chars, emoji 🚀 = 2 chars, URL = 23 chars → 7 + 2 + 23 = 32)

- [ ] **Step 5: Commit**

```bash
git -C ~/.claude/skills/post init 2>/dev/null || true
cd ~/.claude/skills/post && git add validate_post.py tests/ && git commit -m "feat: add validate_post.py with tests" 2>/dev/null || echo "No git in skills dir — skipping commit"
```

Note: `~/.claude/skills/` may not be a git repo. If `git commit` fails, that's fine — move on.

---

## Task 3: Create SKILL.md

**Files:**
- Create: `~/.claude/skills/post/SKILL.md`

- [ ] **Step 1: Write the skill file**

Write `~/.claude/skills/post/SKILL.md`:

````markdown
---
name: post
version: 1.0.0
description: |
  Generate LinkedIn + Twitter build-in-public posts from git context.
  Use when asked to "/post", "write a post", "tweet this", "announce this",
  "write a LinkedIn post", "build in public post", or after shipping/fixing something.
  Reads git context automatically. Optional notes can be added after /post.
allowed-tools:
  - Bash
  - Read
triggers:
  - write a post
  - tweet this
  - announce this
  - build in public
  - post this
---

# Skill: Build-in-Public Post Generator

Generate one LinkedIn post and one Twitter post from recent git activity.
Both posts are written in Abhinav's voice (style guide below).
Character limits are enforced by a validator script before output.

---

## Workflow

Run these steps in order every time this skill is triggered.

### Step 1 — Read git context

```bash
git log --oneline -10
git diff HEAD~1 --stat
git diff HEAD~1
```

If `HEAD~1` fails (only one commit), use `git diff HEAD --stat && git diff HEAD`.

### Step 2 — Merge with user notes

If the user typed anything after `/post`, treat it as additional framing:
- Topic focus ("focus on the Docker fix")
- Post type override ("this is a bug post")
- Extra context not visible in git ("also mention the hosted version is coming")

### Step 3 — Infer post type

Pick one based on the git diff and any user notes:
- **ship** — new feature landed, something users can now do
- **bug** — something broke, was found, was fixed
- **update** — in-progress work, progress report, what's next

### Step 4 — Generate LinkedIn post

Follow the style guide below exactly.
Target: **1,200–1,800 characters**. Hard max: **3,000 characters**.

### Step 5 — Generate Twitter post

A distilled version of the LinkedIn post.
Hard max: **280 characters**.
URL counting rule: every URL = 23 chars toward the limit.
Emoji counting rule: every emoji = 2 chars toward the limit.

### Step 6 — Validate character counts

Write both posts to temp files and run the validator:

```bash
cat > /tmp/li_post.txt << 'LIEOF'
[LINKEDIN POST TEXT HERE]
LIEOF

cat > /tmp/tw_post.txt << 'TWEOF'
[TWITTER POST TEXT HERE]
TWEOF

python3 ~/.claude/skills/post/validate_post.py /tmp/li_post.txt /tmp/tw_post.txt
```

If exit code is 1, revise the over-limit post inline and re-run. Do not ask the user — just fix and re-validate.

### Step 7 — Print final output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LINKEDIN  [N / 3,000 chars]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[post text]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TWITTER   [N / 280 chars]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[post text]
```

---

## Writing Style Guide

This is Abhinav's voice extracted from 100 LinkedIn posts. Follow these rules exactly — do not improvise tone or structure.

### Opening hook (first line)
- Single sentence. Fact or tension. No preamble.
- Never start with: "I'm excited to share", "Today I want to talk about", "Big news", or any filler.
- Good examples:
  - "Two things broke. Both are fixed now."
  - "I was spending a full day trying to apply to 5 AI startups."
  - "As promised."
  - "Spent an hour on a call today helping a user set up the pipeline."

### Paragraph structure
- 1–2 sentences per paragraph max
- Heavy whitespace between paragraphs (blank line between each)
- No walls of text

### Technical lists (for ship/bug posts)
- Numbered, with Unicode 𝗯𝗼𝗹𝗱 header on each item
- Example:
  ```
  1. 𝗦𝘂𝗽𝗮𝗯𝗮𝘀𝗲 𝗰𝗼𝗻𝗻𝗲𝗰𝘁𝗶𝗼𝗻 𝘀𝘁𝗿𝗶𝗻𝗴
  
  If you paste the "Direct connection" URL it fails silently — it's IPv6 only.
  Use the Session pooler instead. Dashboard → Connect → Session pooler.
  ```
- Use ➡️ for context/explanation bullets
- Use ✅ for wins or features

### CTA (call to action — always last before hashtags)
- Always include one. Pick the format that fits:
  - Comment-to-DM: `Comment "𝗿𝗲𝗽𝗼" and I'll DM you the link.`
  - Invitation: `Setting it up? Let me know if you hit a wall.`
  - Question: `Curious if this is a problem others are running into or just me.`
- Never end without a CTA.

### Hashtags
- 3–6 hashtags only
- Mix: 1–2 niche (e.g. `#LangGraph`, `#buildingInPublic`, `#openSource`) + 1–2 broad (e.g. `#AI`, `#startup`, `#developer`)
- No hashtag spam

### Tone rules
- First-person throughout ("I built", "I fixed", "I shipped")
- Name what actually broke and what the actual fix was — never say "various improvements"
- Honest about failures and dead-ends, not just wins
- Free/open-source framing when relevant ("Free. Open source code.")
- No corporate language, no passive voice, no buzzwords

### Post type patterns

**Ship post:**
```
[Hook: what just shipped in one sentence]

[What it does for users — 1-2 sentences]

[How it works or what's inside — numbered list if multiple things]

[Free/open-source callout if applicable]

[CTA]

[Hashtags]
```

**Bug post:**
```
[Hook: what broke — name it specifically]

[Numbered list: each bug with bold header + 1-2 sentence explanation + fix]

[Reassurance: it's resolved, here's what changed]

[CTA]

[Hashtags]
```

**Update post:**
```
[Hook: where things stand right now]

[What was built or decided — 1-2 bullets with ➡️]

[What's coming next]

[CTA or open question to the audience]

[Hashtags]
```

### Twitter adaptation rules
- Take the LinkedIn opening hook — that's your first line
- Add one punchy follow-up (the "so what" — what this means or why it matters)
- End with repo link or "more in the thread" CTA
- Drop most hashtags; keep one niche tag only if chars allow
- No filler — every word must earn its place at 280 chars
````

- [ ] **Step 2: Verify the file was written correctly**

```bash
head -10 ~/.claude/skills/post/SKILL.md
```

Expected: YAML frontmatter starting with `---` and `name: post`.

- [ ] **Step 3: Verify skill is discoverable**

Restart Claude Code (or open a new session). Type `/post` — the skill should appear in autocomplete.

---

## Task 4: End-to-end smoke test

- [ ] **Step 1: Run a test invocation from the outreach-pipeline repo**

In a Claude Code session inside `/Users/abhinavanand/outreach-pipeline`, type:

```
/post
```

Claude should:
1. Run `git log --oneline -10` and `git diff HEAD~1`
2. Generate a LinkedIn post and a Twitter post
3. Run the validator
4. Print both posts with character counts

- [ ] **Step 2: Test with optional notes**

```
/post focus on the bug fix for Supabase connection string
```

Claude should weight the Supabase fix prominently in both posts.

- [ ] **Step 3: Verify Twitter is under 280 chars**

Check the printed Twitter count is ≤ 280.

- [ ] **Step 4: Verify LinkedIn is in the 1,200–1,800 range**

Check the printed LinkedIn count is in range (or at minimum under 3,000).
