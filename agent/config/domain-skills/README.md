# Domain Skills (Sprint 07.04, #1033)

Plain-markdown skill files persisted by
`SkillEvolutionEngine.persist_skill_to_markdown`.

## Layout

```
agent/config/domain-skills/
  <domain>/
    <sanitized-skill-name>.md
```

## Discovery

`SkillEvolutionEngine.discover_markdown_skills(base_dir)` walks the
tree and returns `MarkdownSkill` records for every file that passes
`validate_skill`. Sprint 07.05 will wire `tool_shed` to consume the
discovered files.

## Feature flag

Default OFF. Operator flips
`[skill_evolution] markdown_skills_enabled = true` in
`config/bridge.toml` after A/B validation.

## Conventions

- Files are written atomically via `<file>.tmp` rename.
- Skill names are lowercased; whitespace + slashes collapse to `-`;
  non-alphanumeric (other than `-`/`_`) is stripped.
- Optional YAML frontmatter at the top of each file is parsed when
  the `yaml` library is importable.
- Concept-only port of browser-harness's git-friendly skill directory
  (MIT, paraphrased — no source code copied verbatim).
