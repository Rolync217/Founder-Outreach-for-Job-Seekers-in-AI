# Design: `/post` Build-in-Public Skill

**Date:** 2026-05-28
**Status:** Approved

---

## Problem

After every ship, bug fix, or update to the outreach pipeline, Abhinav needs to post on LinkedIn and Twitter/X in his voice. Writing both from scratch takes time and risks drifting from the tone that works. He wants to type `/post` (with optional notes), have Claude read git context automatically, and get back two ready-to-send posts — one per platform — with exact character counts enforced.

---

## Solution Overview

Two files installed globally at `~/.claude/skills/post/`:

| File | Role |
|------|------|
| `SKILL.md` | Skill instructions + Abhinav's writing style guide baked in |
| `validate_post.py` | Deterministic character counter and limit enforcer |

The skill is triggered by `/post` anywhere in Claude Code. It reads git context automatically, accepts optional freetext notes, generates both posts in Abhinav's style, validates character counts via the Python script, and prints the final posts with counts.

---

## Workflow (what happens on every `/post` invocation)

1. **Read git context** — run `git log --oneline -10` and `git diff HEAD~1` to understand what changed
2. **Merge with user notes** — if the user typed anything after `/post`, treat it as additional context or framing hints (e.g. "focus on the Docker fix" or "this is a bug post")
3. **Infer post type** — from context determine: `ship` (new feature/release), `bug` (broke + fixed), or `update` (in-progress progress report). User can override by stating it in notes.
4. **Generate LinkedIn post** — target 1,200–1,800 chars, hard max 3,000
5. **Generate Twitter post** — hard max 280 chars (URLs = 23 chars toward limit, emojis = 2 chars)
6. **Run validator** — write each post to a temp file, then run `python3 ~/.claude/skills/post/validate_post.py /tmp/li_post.txt /tmp/tw_post.txt`
7. **Auto-revise if over limit** — if either post fails, Claude trims/rewrites inline without asking
8. **Print final output** — both posts clearly labelled with exact character counts

---

## Character Limits

| Platform | Hard Max | Target / Sweet Spot |
|----------|----------|---------------------|
| LinkedIn | 3,000 chars | 1,200–1,800 chars |
| Twitter/X (free) | 280 chars | ≤270 (leave buffer for manual edits) |

Twitter counting rules:
- Every URL (any length) = 23 chars
- Every emoji = 2 chars
- All other characters = 1 char each

---

## Writing Style Guide (baked into SKILL.md)

Extracted from 100 LinkedIn posts. These rules are permanent — Claude must follow them exactly.

### Structure
- **Opening hook**: single sentence, fact or tension, no preamble. Never start with "I'm excited to share" or any filler.
- **Paragraphs**: 1–2 sentences max, heavy whitespace between each
- **Technical lists**: numbered with Unicode 𝗯𝗼𝗹𝗱 headers (e.g. `𝗦𝘂𝗽𝗮𝗯𝗮𝘀𝗲 𝗰𝗼𝗻𝗻𝗲𝗰𝘁𝗶𝗼𝗻 𝘀𝘁𝗿𝗶𝗻𝗴`)
- **Bullets**: ➡️ for context/explanation, ✅ for wins/features added
- **CTA**: always ends with one — "Comment X and I'll DM you the link" style or "Let me know if you hit a wall"
- **Hashtags**: 3–6, mix of niche (e.g. `#buildingInPublic`, `#LangGraph`) and broad (e.g. `#AI`, `#opensource`)

### Tone
- First-person, builder's voice throughout
- Honest about what broke ("Two things broke. Both are fixed.")
- No corporate language, no passive voice, no hype
- Names the actual problem and the actual fix — no vague "improvements"
- Free/open-source framing when relevant

### Post type variations
- **Ship**: what shipped, what it does for users, CTA to try it
- **Bug**: what broke (named specifically), what the fix was, reassurance it's resolved
- **Update**: where things stand, what's next, invitation to follow along

### Twitter adaptation
- Distilled hook from the LinkedIn post
- One punchy follow-up line (the "so what")
- Repo/link CTA or "thread below" if more context needed
- No hashtags if they'd push over 280; one niche tag maximum

---

## `validate_post.py` Spec

**Inputs:** two file paths as positional arguments — `validate_post.py <linkedin_file> <twitter_file>`. The skill writes each post to a temp file before calling the script. This avoids shell quoting issues with multiline text.

**Logic:**
- Count LinkedIn chars: `len(linkedin_text)` (raw file contents)
- Count Twitter chars: replace each URL (matched via regex) with a 23-char placeholder, count emojis (matched via `\U0001F...` ranges) as 2 chars each, count everything else as 1
- Report both counts
- Exit code 0 if both pass; exit code 1 if either is over limit, with clear message showing overage

**Output format (stdout):**
```
LinkedIn: 1,342 / 3,000 ✓
Twitter:  267 / 280 ✓
```
Or on failure:
```
LinkedIn: 3,124 / 3,000 ✗  (124 chars over)
Twitter:  267 / 280 ✓
```

---

## File Locations

```
~/.claude/skills/post/
├── SKILL.md          ← global skill, available in all projects
└── validate_post.py  ← helper script called by the skill
```

No project-level files. No `.env` dependency. The style guide is static text in the skill file.

---

## Out of Scope

- Automatically posting to LinkedIn or Twitter (user reviews and sends manually)
- Fetching fresh LinkedIn posts at runtime (style is baked in from the one-time extraction)
- Scheduling posts
- Image/media generation
