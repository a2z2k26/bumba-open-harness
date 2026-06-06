---
name: idea
description: Capture an idea to the Obsidian second brain. Quick-capture for creative brainstorming, thought clouds, and pre-formal concepts. Use when the operator wants to record an idea, insight, or connection without formalizing it into Notion.
allowed-tools: Bash, Read
---

# /idea — Capture to Obsidian Second Brain

Capture a thought, idea, or creative insight into the operator's Obsidian vault via the Obsidian CLI. This is the dream-state, pre-formal layer — raw ideas that aren't ready for Notion yet.

## Instructions

### Step 1: Understand the Idea

Read the user's input. It may be a sentence fragment, a multi-paragraph concept, a connection between ideas, a question, or a creative direction. Don't over-formalize — capture the spirit as the operator expressed it.

### Step 2: Create the Note

Use the Obsidian CLI to create a new note:

```bash
obsidian create name="<Idea Title>" content="---\ncreated: $(date '+%Y-%m-%d %H:%M')\ntags:\n  - idea\n  - <topic-tag>\n---\n\n<The idea content here>\n\n## Connections\n\n- [[related concept if obvious]]\n\n## Questions\n\n- <open questions if any>"
```

**Title**: Short, evocative, searchable. Capture the essence in 3-6 words.

**Content**: Write in the operator's voice. Preserve the raw energy. Don't sanitize or over-structure.

**Tags**: Always include `idea`. Add relevant topic tags from: `bumba`, `business`, `design`, `engineering`, `strategy`, `product`, `motion`, `ui`, `ux`, `voice`, `agent`, `infrastructure`, `business`. Create new tags freely.

**Connections**: Use `[[wiki-link]]` syntax for Obsidian internal links to related concepts. Only if obvious — don't force connections.

### Step 3: Confirm

Tell the operator the title and a one-line summary. Keep it brief.

## Quick Capture Examples

**Input**: "What if the design bridge could work bidirectionally with Paper.design?"
```bash
obsidian create name="Bidirectional Paper.design Bridge" content="---\ncreated: 2026-03-16 14:30\ntags:\n  - idea\n  - bumba\n  - design\n  - infrastructure\n---\n\nWhat if the design bridge could work bidirectionally with Paper.design, not just Figma? Paper has a real-time canvas API now. Could extend the transform pipeline to push/pull from both design tools simultaneously.\n\n## Connections\n\n- [[Bumba Design Bridge]]\n- [[Paper MCP]]\n\n## Questions\n\n- Does Paper's API expose the same primitives as Figma's?"
```

**Input**: "reggae-inspired loading animations"
```bash
obsidian create name="Reggae Loading Animations" content="---\ncreated: 2026-03-16 14:35\ntags:\n  - idea\n  - design\n  - motion\n  - bumba\n---\n\nReggae-inspired loading animations. Offbeat rhythmic pulses instead of standard spinners. Skanking dots. Bass-drop progress bars. The motion language should feel like a riddim — steady, confident, with unexpected accents.\n\n## Questions\n\n- What CSS easing curves feel most like a reggae groove?"
```

## Useful Follow-up Commands

After capturing, the operator can explore the vault:
- `obsidian search query="<keyword>"` — find related ideas
- `obsidian tags counts sort=count` — see what themes are emerging
- `obsidian backlinks file="<note>"` — find what connects to an idea
- `obsidian orphans` — find isolated ideas that need connections
