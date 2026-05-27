# Outreach Message Rules — Full Reference

---

## Message Formats and Limits

| Format | Limit |
|--------|-------|
| `linkedin_invite` | 290–300 characters |
| `linkedin_dm` | under 150 words |
| `long_reference` | under 170 words |

---

## Core Structure (MANDATORY)

Every message follows this three-part structure:

1. **Opening** — describe a real situation, problem, or behavior specific to the company
2. **Credibility** — one first-person signal that shows you've thought about this
3. **Soft Ask** — a simple question that invites a response

---

## Opening Rule

The opening must:
- be specific to the company
- describe a real situation or behavior
- be easy to understand in one read
- let tension emerge naturally — do NOT force a reframe or "not X, but Y" structure

### For `linkedin_invite` (CRITICAL)

Must use a soft entry before the observation:
- "had a quick thought while looking into…"
- "was looking into X and noticed…"
- "one thing I was thinking about…"

Then describe the situation.

Do NOT start directly with "feels like" or jump straight into diagnosis — invite messages should feel like entering a conversation, not analyzing from the outside.

### For `linkedin_dm` and `long_reference`

Can open directly with the situation:
- "feels like…"
- "when X happens, Y tends to show up…"
- "as X scales, Y becomes harder to manage…"

### Strong openings (DM / Long Reference)
- "When someone searches across multiple connected tools, keeping results accurate while showing only what they should see can get tricky"
- "When a decision comes from a model, explaining it later in a real situation can be harder than getting the answer"
- "As workflows become more automated, people still tend to question certain steps before fully trusting them"

### Weak openings (reject these)
- "interesting problem"
- "curious how you think about this"
- "this seems challenging"

---

## Credibility Line

Must include ONE real signal from first-person experience:
- something you observed
- a pattern you've seen
- something from your own workflow

Keep it simple and exploratory — NOT a credential drop.

| Good | Bad |
|------|-----|
| "I've seen this become a bottleneck in similar systems" | "I've worked on similar systems" (too vague) |
| "in my workflow, I ran into something similar" | "I've built X that solved this" (credential-dropping) |
| "I've seen systems where outputs worked well, but this still became tricky" | "my background in Y is relevant here" |

---

## Soft Ask

Must invite a response. Keep it simple and direct.

Prefer:
- "does this show up in practice?"
- "is this something you see?"
- "how does this usually play out?"
- "curious how this shows up in your flow?"
- "does this show up more on X, or somewhere else?"

Avoid:
- long or complex questions
- meeting requests ("would love a 15-min chat")
- binary questions that are hard to answer
- sounding like you're testing a framework

---

## Tone Rules

### Humility Rule
Always sound like you're exploring, not diagnosing.

Use: "feels like", "seems", "I've seen", "tends to", "can get tricky"
Avoid: "this is the problem", "this will break", "you need to"

### Plain Language Rule
Always prefer simple language.

| Instead of | Use |
|------------|-----|
| permission enforcement | keeping results limited to what someone should see |
| access control layer | the part that decides what to show |
| retrieval quality | finding the right answers |
| indexing vs retrieval | where to filter — when you store it or when you show it |
| permission propagation | making sure limits follow the data |
| hallucinated outputs | wrong or made-up answers |
| orchestration complexity | keeping all the steps in sync |
| latency tradeoff | things slowing down |
| defensibility | being able to explain the decision later |
| auditability | a clear trail of how an answer was reached |
| adoption friction | whether people actually use it |
| decision reliability | whether people trust and act on the output |
| multi-connector systems | as you connect more tools |
| context window | how much the model can work with at once |
| evaluation pipeline | how you test whether it's working |
| per-document access | what each person is allowed to see |
| trust gap | the gap between what the system says and what users believe |
| workflow integration | fitting into how people already work |
| enforcement layer | the system that decides who sees what |
| grounding | making sure answers come from real data |
| semantic search | finding things by meaning, not exact words |
| embedding space | how the model represents meaning |
| inference-time | when the model is actually generating |
| token limits | how long the response can be |

**Rule**: If a term appears in this table, it must be replaced before the message is saved.
**Rule**: If a term is NOT in this table but still sounds like a technical paper → rewrite it anyway.

If it sounds like a technical blog, rewrite it.

### Formatting Rule
Never use em dashes (—). Use commas, full stops, or simple sentence breaks.
Em dashes make the message feel stylized or AI-written.

### Concrete Tension Rule
Every message must include a contrast or tension — but let it emerge from the situation.

Good:
- "when X happens, Y tends to become tricky"
- "in situations like X, Y starts to show up"

Bad:
- "not X, but Y" (forced reframe)
- "the real problem isn't X, it's Y" (sounds like you're correcting them)

### Situation-First Rule
Always describe a real moment, workflow, or behavior first.
The founder should feel: "this actually happens" — not "this person is reframing my problem."

---

## Sentence-Level Readability Checks

Run these on every sentence before saving:

**Test 1 — The Out-Loud Test**
Read the sentence out loud. If you'd never say it in a real conversation, rewrite it.
Bad: "The enforcement layer introduces non-trivial complexity around permission propagation."
Good: "As you connect more tools, keeping the right data in front of the right person gets harder."

**Test 2 — The Founder Test**
Would a busy founder understand this in 3 seconds? If they'd need to re-read it → rewrite it.

**Test 3 — The Blog Test**
Does this sentence sound like it came from a technical blog post? If yes → rewrite it in a more direct, conversational style.

---

## Tension Quality Reference

A valid tension creates a fork — the founder can answer one side or the other. That's what makes it easy to reply to.

Valid tensions:
- "accurate vs whether someone will trust it" ✓
- "fast vs explainable" ✓
- "automates the work vs fits how people already work" ✓
- "scales well vs stays consistent" ✓

Invalid tensions:
- "trust is hard" ✗ (observation, not tension)
- "there are tradeoffs" ✗ (too abstract)
- "AI is complex" ✗ (meaningless)

---

## Role-Based Framing

| Role | Focus |
|------|-------|
| CEO / Founder | business impact, user behavior, trust and adoption |
| CTO / Technical Co-founder | system behavior, scaling challenges, tradeoffs (explained simply) |
| CPO / Head of Product | user experience, friction, workflow problems |
| Head of AI / AI Lead | real-world use of AI, reliability in practice |
| Co-founder (unknown) | company-building tensions, early decisions, product-market tradeoffs |

Default → CEO framing

### Role-Aware Language Level

The same idea expressed at different levels:

| Idea | CEO framing | CTO framing |
|---|---|---|
| Trust in AI output | "whether people trust it enough to act on it" | "whether the output is grounded enough for someone to rely on" |
| Access control | "showing people only what they should see" | "enforcing limits at indexing or at retrieval" |
| Scale problems | "as you add more data or tools, things break" | "as connectors scale, edge cases multiply" |
| AI reliability | "whether users can count on the answer" | "how often the system produces consistent results" |

CEO → simplest phrasing. CTO → one technical term is OK if it's the precise one.

---

## Validation Checklist

| Check | Pass condition |
|-------|----------------|
| Format limits | Within character/word limit for the format |
| Soft entry (invite only) | linkedin_invite uses entry phrase before observation |
| Opening | Describes a real, specific situation — not generic |
| Credibility | Has one first-person "I've seen…" or "in my workflow…" signal |
| Soft Ask | Ends with a simple question, not a meeting request |
| Humility tone | Uses exploratory language, not diagnostic claims |
| Specificity | References this company specifically — passes anti-generic check |
| No em dashes | Zero em dashes in the message |For your reference this is an em dash "—"
| Banned phrases | Zero: "looking for a job", "seeking", "would love to connect", "I came across" |
| No job framing | Zero mentions of job, role, opportunity, salary, referral |
| No links | No LinkedIn URL, no resume, no portfolio link |
| Sign-off | Just "[YOUR_FIRST_NAME]" — no title, no links |

---

## Anti-Generic Check

Reject if:
- message could be sent to any company
- no real situation described
- sounds like networking instead of thinking

---

## Hard Constraints (never violate)

Never mention:
- job, role, opportunity, referral
- salary, compensation, equity

Never say:
- "I came across your company"
- "impressed by"
- "would love to connect"
- "looking for a job" / "seeking"

Never use em dashes (—).

---

## Low Confidence Handling

If research data is sparse or confidence in the observation is low:
- keep it exploratory
- avoid strong claims
- stay general but still meaningful
- do not fabricate specifics
