# /project/new — Create a New Zone 3 Project

Create a new project with full SDD pipeline integration.

## Usage

```
/project/new <name> [--stack <stack>] [--template <template>]
```

## What This Does

1. **Create ProjectRegistry entry** — YAML file in `data/projects/<name>.yaml` with:
   - `status: active`
   - `sdd_stage: specify`
   - Stack from `--stack` flag or prompted
   - Description prompted from user

2. **Bootstrap SDD structure** — Run `specify init <name> --ai claude --here` to create:
   - `.specify/` directory with constitution and 9 speckit commands
   - Project-local `speckit.*` commands under `.claude/commands/`

3. **Optional template scaffolding** — If `--template` provided:
   - `node` → scaffold from `config/templates/node/`
   - `python` → scaffold from `config/templates/python/`
   - `design-bridge` → scaffold from `config/templates/design-bridge-server/`

4. **Switch to new project** — Activate the project via track switching.

## Example

```
/project/new auth-service --stack "FastAPI + PostgreSQL" --template python
```

## Implementation Steps

1. Prompt for project name if not provided
2. Prompt for description
3. Create YAML entry via ProjectRegistry.create_new()
4. Run `specify init` if the specify CLI is available
5. Apply template if requested
6. Switch to the new project

## Notes

- Replaces the separate `/project/register` + `/speckit-init` flow
- The `sdd_stage` field starts at `specify` — the first pipeline stage
- Templates are optional
