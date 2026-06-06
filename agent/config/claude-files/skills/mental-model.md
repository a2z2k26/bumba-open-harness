# Mental Model Skill

You maintain a persistent expertise file that grows with every session. This file is your memory across sessions — without it, you restart from zero every time.

## When to Read Your Expertise File

Read your expertise file at the start of every session before taking any action. It contains:
- Domain patterns you have observed
- Risks you have encountered
- Decisions you have made and why
- Notes for other agents or the chief

## When to Update Your Expertise File

Update after every session where you learned something meaningful:
- A new pattern that changes how you approach problems in your domain
- A risk you encountered that others should know about
- A decision with non-obvious rationale
- Information that would have helped you if you had known it at the start

Do NOT update for routine work that produced no new insight.

## What to Track

**Domain Patterns** — recurring structures, anti-patterns, and heuristics. Write these as actionable observations, not descriptions. Example: "Greenhouse ATS form submission fails silently if the resume field is missing — always verify the field exists before submit."

**Known Risks** — specific risks in your domain with context on when they apply. Include the trigger and the consequence. Keep this list short; remove risks that are no longer relevant.

**Decision Log** — key decisions made during sessions, with date and rationale. Format: `YYYY-MM-DD: <decision> — <why>`. Only log decisions that a future session would benefit from knowing.

**Cross-Agent Notes** — information for other agents or the chief. Surface blockers, handoff context, and anything that crosses domain boundaries.

## Growth Management

Your expertise file has a line limit (default 500). To stay within it:
- Merge related patterns into single, more general observations
- Remove decisions older than 90 days unless they remain relevant
- Summarize verbose decision entries

When you are near the limit, consolidate before adding new entries.

## Format

Write in concise, direct bullet points. Avoid prose paragraphs. Each entry should be independently understandable — do not rely on context from adjacent bullets.

## Read-Only Files

Some expertise files are marked `type: read-only` (e.g., billing-rules, deployment-procedures, security-requirements). You may read and apply these but must not write to them. They are maintained by the system.
