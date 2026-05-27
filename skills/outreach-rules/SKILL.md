---
name: outreach-rules
description: "Load the outreach message rules when drafting or validating a cold outreach message for the candidate. Trigger when writing a new outreach draft, reviewing a draft for quality, fixing a message that failed validation, or when asked about 'message rules', 'outreach format', 'how to write the message', or 'what makes a good message'. Contains the hard constraints, format-specific templates, and pass/fail examples."
---

# Skill: Outreach Message Rules

Load this whenever drafting or validating a cold message. These rules define what a good message looks like and what fails.

## Target Audience

Only founders / co-founders:
- CEO / Founder
- CTO / Technical Co-founder
- CPO / Head of Product
- Head of AI / AI Lead
- Co-founder (unknown function)

Do not draft for any other seniority level or function.

## Workflow

### When Drafting
1. Identify the message format: `linkedin_invite`, `linkedin_dm`, or `long_reference`
2. Load `references/rules.md` — structure, tone rules, hard constraints, and role-based framing
3. Load `references/tone-templates.md` — format-specific and role-specific templates
4. Use research data to build the opening in this priority order:
   - `outreach_angle` > `product_gaps` > `solution_insight` > `problem`
5. Follow the three-part structure: **Opening → Credibility → Soft Ask**
6. Apply the opening rule for the format:
   - `linkedin_invite`: soft entry before the observation ("had a quick thought while looking into…")
   - `linkedin_dm` / `long_reference`: can open directly with the situation
7. Check character/word limits before finalizing
8. Run the validation checklist in `references/rules.md`

### When Validating
1. Load `references/rules.md` — run the checklist
2. Load `references/examples.md` — compare against known failure patterns (bad examples section)
3. If fixable (word count, weak CTA, missing soft entry): rewrite and mark `validation_status = fixed`
4. If unfixable (no real personalization, banned phrase, job-search framing): mark `validation_status = failed`

## Hard Rules (enforced every time)
- Structure: Opening → Credibility → Soft Ask
- `linkedin_invite`: 285–300 characters — validate with `tools/count_chars.py`
- `linkedin_dm`: under 150 words
- `long_reference`: under 170 words
- Opening must describe a real situation — let the tension emerge naturally, never force a reframe
- `linkedin_invite` opening MUST use a soft entry — do NOT jump straight into analysis
- Credibility: one first-person signal using "I've seen…" or "in my workflow…" — NOT credential-dropping ("I've built X")
- Soft Ask: a simple question that invites response — NOT a meeting request
- Tone: always exploring, not diagnosing — use "feels like", "seems", "I've seen"
- Never use em dashes (—) — use commas or full stops instead
- Never start with "I came across your company", "I noticed you", "I saw that you"
- Never mention job, role, opportunity, referral, salary, compensation, equity
- Never say "looking for a job", "seeking", "would love to connect", "impressed by"
- No links, no resume, no LinkedIn URL in the message body
- Sign off with just "[YOUR_FIRST_NAME]" — no title, no links, nothing else

## Multi-Format Behavior

Messages across formats must DIFFER — not just compress.

| Mode | One idea | Explanation | Thinking shown | Length |
|---|---|---|---|---|
| `linkedin_invite` | Yes — one only | None | None | 290–300 chars |
| `linkedin_dm` | Yes — one only | Short | Briefly | under 150 words |
| `long_reference` | Yes — one only | Yes | Step by step | under 170 words |

- `linkedin_invite`: compress the core observation + ask. Cut everything else. No line breaks.
- `linkedin_dm`: introduce the situation, add one sentence of thinking, ask. Max 3 short paragraphs.
- `long_reference`: set up the situation, show the thinking in 2–3 sentences, ask. Each paragraph does one thing.

All three ask the SAME question, framed for the same audience — but at different depths.

## Role-Based Framing

### CEO / Founder
- Language: simplest of all formats
- Frame around: what users do, whether people trust the output, whether it works in real workflows
- Avoid: technical terms, system internals

### CTO / Technical Co-founder
- Language: slightly more technical, but still conversational
- Frame around: how the system behaves, what breaks at scale, tradeoffs in how it's built
- Avoid: wall-of-text system design language

### CPO / Head of Product
- Language: user and workflow language
- Frame around: friction, what users do vs what the product expects, prioritization choices

### Head of AI / AI Lead
- Language: applied, grounded
- Frame around: how AI behaves in real use, what breaks in practice, reliability vs capability

### Co-founder (unknown function)
- Language: simple, broad
- Frame around: company-building tensions — early decisions, product-market tradeoffs, team constraints

**Unknown role → CEO framing**

## Anti-Generic Test

Reject and rewrite if ANY of these are true:
- Opening could apply to 3+ startups without changing a word
- Opening is purely conceptual — no real situation described
- No concrete tension in the message
- Credibility line is vague ("I've worked on similar systems")
- Question is broad enough to ask anyone in the space
- Message sounds like networking or a pitch

## Low-Confidence Handling

If leverage match is low or research data is sparse:
- Do NOT fabricate experience
- Shift to adjacent pattern recognition
- Keep language exploratory, not assertive
- Narrow the observation to the smallest honest claim
- Still draft all three modes, but soften the credibility line
