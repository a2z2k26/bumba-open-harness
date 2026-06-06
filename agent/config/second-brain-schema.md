# Second Brain — Schema Conventions

**Status:** Adopted 2026-05-01 (per ADR `agent/docs/architecture/second-brain.md`).
**Audience:** The `bridge.second_brain` subsystem (NOT every Claude session). Loaded only by 05.06 ingest, 05.08 query, 05.09 lint.
**Schema version:** 1

## Vault layout

The operator's Obsidian vault is the wiki (ADR Decision 1). Subtrees:

- `<vault>/` — operator-owned canonical content. Bumba reads, never writes.
- `<vault>/bumba-contributions/staging/` — `daily_log` + `reflection` outputs auto-drop here. Subject to lint. Operator promotes to canonical via `/promote` (Sprint 05.10) or rejects via `/reject_wiki`.
- `<vault>/bumba-contributions/curated/` — consolidation pipeline outputs (already curated). Subject to lint but lower noise threshold. Same promote/reject UX.
- `<vault>/index.md` — operator-maintained primary index (per Decision 4). Bumba READS only; never writes (except the auto-maintained `Bumba contributions` section, see below).
- `<vault>/log.md` — append-only narrative log of significant changes. Bumba reads + appends one line per write session (audit trail).

The hybrid quarantine (`bumba-contributions/staging/` + `bumba-contributions/curated/`) is reversible — deleting the directory removes every Bumba-authored file at once without touching operator-owned content (ADR Decision 3).

## File frontmatter (YAML)

Every Bumba-authored `.md` file in `bumba-contributions/` MUST carry YAML frontmatter:

```yaml
---
source: <ingest|reflection|consolidation|daily_log>
session_id: <session-uuid>
authored_at: <ISO8601>
provenance: <one-line summary of why Bumba wrote this>
schema_version: 1
---
```

Field rules:
- `source` — one of the four enum values above. Identifies which subsystem produced the note.
- `session_id` — bridge session UUID at write time. Lets the operator trace any note back to its originating conversation.
- `authored_at` — ISO 8601 timestamp at write time (e.g. `2026-05-01T14:32:00Z`).
- `provenance` — single-line human-readable reason for the write. Free-form prose, ≤200 chars.
- `schema_version` — integer matching the current schema version (currently `1`).

When the operator edits a Bumba-authored file, they SHOULD drop the `source` field. Lint detects this transition and re-classifies the file as canonical (operator-owned), exempting it from further `bumba-contributions/` rules.

## Index.md format

`index.md` is operator-owned. Bumba READS to build retrieval candidate lists (consumed by Sprint 05.08 query). Format:

```markdown
# Vault Index

## Active threads
- [[thread-name]] — one-line description

## Reference docs
- [[doc-name]] — one-line description

## Bumba contributions (staged for review)
- [[bumba-contributions/staging/note-name]] — operator review pending
```

The `Active threads` and `Reference docs` sections are operator-owned. The third section (`Bumba contributions (staged for review)`) is auto-maintained by Bumba — populated by walking `bumba-contributions/staging/` and emitting one bullet per file pending operator review. Bumba MUST NOT write to the first two sections.

If `index.md` is missing, Sprint 05.08 query falls back to a directory walk; lint emits a warning but does not block. Operator owns whether to seed `index.md` initially.

## Log.md format

Append-only. One entry per Bumba write session (a write session = one ingest pass, one consolidation run, or one operator-triggered promote/reject batch):

```markdown
## 2026-05-01 14:32 — session abc-123
- Added 3 daily_log notes to staging/
- Promoted [[note-x]] from staging to canonical (operator action 14:35)
- 0 lint warnings
```

Header line: `## <YYYY-MM-DD HH:MM> — session <session-id>`.

Body bullets: one per significant action, written in past tense. Promotion/rejection events recorded by the operator command handler (not the ingest path) include the operator action timestamp inline.

Bumba MUST NOT rewrite or delete prior `log.md` entries. Append-only is enforced by lint (Sprint 05.09).

## Lint rules (consumed by Sprint 05.09)

Each file under `bumba-contributions/` is checked for:

1. **Frontmatter present + valid** — YAML parses, all five required fields present, values match the enums/types above.
2. **No broken `[[wikilinks]]`** — every wikilink target resolves to an existing file in the vault (operator-owned or `bumba-contributions/`).
3. **No duplicate filenames** — within the entire `bumba-contributions/` subtree, no two files share a basename.
4. **Schema version matches current** — `schema_version: 1` (or whatever is current). Mismatched versions trigger a migration pointer, not a hard fail.
5. **Not orphaned** — file is referenced by `index.md` OR by another note in the vault. Pure orphans are flagged for operator review (likely promote-or-delete candidates).

Files grandfathered by the Sprint 05.0a baseline-ingest pass are exempt from rules 1, 4, and 5 (operator's own content predates the schema and is not retroactively conformed).

Lint is non-blocking by default — warnings surface to the operator via `/wiki_lint` (Sprint 05.09) but do not halt ingest. The operator decides which warnings warrant action.

## Contradiction detection (consumed by Sprint 05.08 query, Sprint 05.09 lint)

When a note's content contradicts an entry in `temporal_knowledge.py` (the audit log per ADR Decision 5), surface it as a lint warning. The wiki wins for source-of-truth; `temporal_knowledge` is the delta log of detected changes, not an authority.

Detection mechanism is owned by Sprint 05.08 (query-time) and 05.09 (batch lint); this doc only fixes the contract: contradictions are warnings, never silent rewrites of either side.

## Schema versioning

`schema_version` is a single integer, monotonically increasing. Bumps require:

1. An ADR addendum to `agent/docs/architecture/second-brain.md` documenting the change.
2. A migration script in `agent/bridge/second_brain/migrations/` that walks `bumba-contributions/` and rewrites frontmatter from version N to N+1.
3. An operator-signed approval before the migration runs.

Version 1 is the initial release (this sprint). Version bumps are expected to be rare — frontmatter additions can usually be retro-applied without a version bump if they default safely.

---
*Cite by anchor (e.g. `second-brain-schema.md#frontmatter`). Downstream sprints 05.03 (wiki_repo), 05.04 (contributor protocol), 05.06 (ingest), 05.08 (query), 05.09 (lint) reference this contract.*
