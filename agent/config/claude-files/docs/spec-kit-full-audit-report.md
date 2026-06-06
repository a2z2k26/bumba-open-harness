# Spec Kit — Complete Audit & Agent Instruction Layer

> **Purpose**: Implementation-grade reference for the bumba-agent to adopt and operate GitHub Spec Kit.
> **Repository**: https://github.com/github/spec-kit
> **Website**: https://github.github.com/spec-kit/
> **Version**: 0.1.13 | **License**: MIT | **Python**: >=3.11 | **Build**: hatchling
> **Single Code Owner**: `@mnriem`
> **Audited**: 2026-03-04 — every file in the repository examined at function/method level

---

## Table of Contents

1. [What Spec Kit Is](#1-what-spec-kit-is)
2. [SDD Methodology & Philosophy](#2-sdd-methodology--philosophy)
3. [The Nine Constitutional Articles](#3-the-nine-constitutional-articles)
4. [Core Workflow — The 9 Slash Commands](#4-core-workflow--the-9-slash-commands)
5. [CLI Architecture — `specify` Command](#5-cli-architecture--specify-command)
6. [AGENT_CONFIG — 22 Supported Agents](#6-agent_config--22-supported-agents)
7. [Extension System Architecture](#7-extension-system-architecture)
8. [Template System — Structure Templates](#8-template-system--structure-templates)
9. [Slash Command Definitions — Full Behavioral Specs](#9-slash-command-definitions--full-behavioral-specs)
10. [Script System — Bash & PowerShell Parity](#10-script-system--bash--powershell-parity)
11. [CI/CD & Release Pipeline](#11-cicd--release-pipeline)
12. [Project File Structure](#12-project-file-structure)
13. [Test Coverage Map](#13-test-coverage-map)
14. [Data Flows Between Commands](#14-data-flows-between-commands)
15. [Adoption Checklist for bumba-agent](#15-adoption-checklist-for-bumba-agent)

---

## 1. What Spec Kit Is

Spec Kit is GitHub's open-source toolkit for **Specification-Driven Development (SDD)** — a methodology where specifications are executable artifacts that generate implementation, rather than documents that merely guide it. The tagline: *"Build high-quality software faster."*

**Installation**:
```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
# Or one-time use:
uvx --from git+https://github.com/github/spec-kit.git specify init my-project --ai claude
```

**Entry point**: `specify` (maps to `specify_cli:main`)

**Runtime dependencies** (8 packages): typer, click>=8.1, rich, httpx[socks], platformdirs, readchar, truststore>=0.10.4, pyyaml>=6.0, packaging>=23.0

**Prerequisites**: Linux/macOS/Windows, Python 3.11+, uv, Git, a supported AI coding agent.

---

## 2. SDD Methodology & Philosophy

Source: `spec-driven.md` (413 lines)

### The Power Inversion
Specifications don't serve code — **code serves specifications**. The specification is the primary artifact. Code is its expression in a particular language/framework. Maintaining software means evolving specifications. This is **intent-driven development**: the lingua franca moves to natural language.

### SDD Workflow
1. **Idea** → iterative AI dialogue → comprehensive PRD
2. **Research agents** gather context (library compatibility, performance, security, org constraints)
3. **PRD** → AI generates implementation plans (every tech choice traced to requirements)
4. **Consistency validation** runs continuously (not one-time gate)
5. **Code generation** begins when specs are stable enough (not necessarily "complete")
6. **Feedback loop**: production metrics/incidents update specifications for next regeneration

### Why SDD Matters Now
1. AI capabilities have reached the threshold for reliable code generation from natural language
2. Software complexity grows exponentially (dozens of services, frameworks, dependencies)
3. Pace of change accelerates — pivots are expected, not exceptional

### Core Principles
- **Executable Specifications**: Precise enough to generate working systems
- **Continuous Refinement**: Ongoing AI analysis for ambiguity, contradictions, gaps
- **Research-Driven Context**: Agents investigate technical options and organizational constraints
- **Bidirectional Feedback**: Production reality informs specification evolution
- **Branching for Exploration**: Multiple implementation approaches from same specification

### Template-Driven Quality (7 Constraints on LLMs)
1. **Prevent Premature Implementation**: Focus on WHAT/WHY, not HOW
2. **Force Explicit Uncertainty**: `[NEEDS CLARIFICATION]` markers (max 3 per spec)
3. **Structured Checklists**: "Unit tests for English" — validate requirement quality
4. **Constitutional Gates**: Phase -1 gates enforce architectural principles
5. **Hierarchical Detail**: Main doc navigable, complexity extracted to separate files
6. **Test-First Thinking**: Contracts → integration tests → e2e → unit → then source files
7. **Prevent Speculation**: Every feature traces to concrete user story with acceptance criteria

---

## 3. The Nine Constitutional Articles

Source: `spec-driven.md` lines 278-406, `templates/constitution-template.md`

The constitution (`memory/constitution.md`) is the architectural DNA of every SDD project. Principles are **immutable** — implementation details evolve, core principles remain constant.

| Article | Name | Core Rule |
|---------|------|-----------|
| I | Library-First | Every feature MUST begin as a standalone library. No feature implemented directly in application code without library abstraction. |
| II | CLI Interface Mandate | All libraries MUST expose functionality via CLI. Accept text input (stdin/args/files), produce text output (stdout), support JSON. |
| III | Test-First Imperative | **NON-NEGOTIABLE** TDD. No implementation before: 1) unit tests written, 2) tests validated by user, 3) tests confirmed to FAIL (Red phase). |
| IV | Integration Testing | Contract tests for new library contracts, contract changes, inter-service communication, shared schemas. |
| V | Observability | Text I/O ensures debuggability. Structured logging required. |
| VI | Versioning & Breaking Changes | MAJOR.MINOR.BUILD format. Breaking changes documented. |
| VII | Simplicity | Maximum 3 projects for initial implementation. Additional requires documented justification. YAGNI. |
| VIII | Anti-Abstraction | Use framework features directly. Single model representation. No wrapping. |
| IX | Integration-First Testing | Prefer real databases over mocks. Actual service instances over stubs. Contract tests mandatory before implementation. |

**Constitutional Enforcement**: The plan template operationalizes articles through Phase -1 gates:
- **Simplicity Gate (Article VII)**: Using ≤3 projects? No future-proofing?
- **Anti-Abstraction Gate (Article VIII)**: Using framework directly? Single model representation?
- **Integration-First Gate (Article IX)**: Contracts defined? Contract tests written?

**Constitutional Evolution**: Amendments require explicit rationale, maintainer approval, backwards compatibility assessment. Version bumped semantically (MAJOR/MINOR/PATCH).

---

## 4. Core Workflow — The 9 Slash Commands

### Primary Pipeline (5 commands, sequential)

```
/speckit.constitution → /speckit.specify → /speckit.plan → /speckit.tasks → /speckit.implement
```

### Enhancement Commands (3 optional)

```
/speckit.clarify  (before /speckit.plan — resolve ambiguities)
/speckit.analyze  (after /speckit.tasks — cross-artifact consistency)
/speckit.checklist (after /speckit.plan — quality validation)
```

### Utility Command (1)

```
/speckit.taskstoissues (after /speckit.tasks — convert to GitHub Issues via MCP)
```

### Command Summary

| Command | Purpose | Input Script | Output Artifacts | Handoffs |
|---------|---------|-------------|-----------------|----------|
| `/speckit.constitution` | Create/update project governing principles | None | `.specify/memory/constitution.md` | → specify |
| `/speckit.specify` | Create feature specification from description | `create-new-feature.sh` | `specs/NNN-name/spec.md`, `checklists/requirements.md` | → plan, → clarify |
| `/speckit.plan` | Generate implementation plan from spec | `setup-plan.sh` + `update-agent-context.sh` | `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`, agent context file | → tasks, → checklist |
| `/speckit.tasks` | Break plan into ordered task list | `check-prerequisites.sh` | `tasks.md` | → analyze, → implement |
| `/speckit.implement` | Execute all tasks from tasks.md | `check-prerequisites.sh --require-tasks` | Source code, tests, ignore files | — |
| `/speckit.clarify` | Structured Q&A for ambiguous specs | `check-prerequisites.sh --paths-only` | Updated `spec.md` with Clarifications section | → plan |
| `/speckit.analyze` | Cross-artifact consistency analysis | `check-prerequisites.sh --require-tasks` | Analysis report (stdout, no file writes) | — |
| `/speckit.checklist` | Generate quality checklists | `check-prerequisites.sh` | `checklists/{domain}.md` | — |
| `/speckit.taskstoissues` | Convert tasks to GitHub Issues | `check-prerequisites.sh --require-tasks` | GitHub Issues via MCP | — |

---

## 5. CLI Architecture — `specify` Command

Source: `src/specify_cli/__init__.py` (2390 lines)

### Commands

| CLI Command | Function | Lines |
|-------------|----------|-------|
| `specify init` | Initialize new Spec Kit project | 1247-1625 |
| `specify check` | Check installed tools availability | 1627-1669 |
| `specify version` | Display version and system info | 1671-1748 |
| `specify extension list` | List installed extensions | 1782-1823 |
| `specify extension add` | Install extension (catalog/URL/local) | 1825-1943 |
| `specify extension remove` | Uninstall extension (with backup) | 1946-2006 |
| `specify extension search` | Search extension catalog | 2009-2077 |
| `specify extension info` | Show extension details | 2080-2185 |
| `specify extension update` | Check/apply updates (TODO: auto-update) | 2188-2292 |
| `specify extension enable` | Re-enable disabled extension | 2295-2336 |
| `specify extension disable` | Disable without removing | 2339-2383 |

### `specify init` — 17 Options

```
specify init <project-name>
  --ai <agent>              # AI assistant (22 choices + generic)
  --ai-commands-dir <path>  # Required with --ai generic
  --script <sh|ps>          # Script type
  --ignore-agent-tools      # Skip CLI tool checks
  --no-git                  # Skip git init
  --here                    # Init in current directory
  --force                   # Skip confirmation for --here
  --skip-tls                # Skip SSL verification
  --debug                   # Verbose diagnostics
  --github-token <token>    # GitHub API token (or GH_TOKEN/GITHUB_TOKEN env)
  --ai-skills               # Install skills (agentskills.io spec)
```

### Init Execution Flow
1. Show banner
2. Validate parameters (detect misinterpreted flags, resolve aliases like `kiro` → `kiro-cli`)
3. Handle `project_name == "."` as `--here`
4. Validate mutual exclusivity (`--here` + project_name = error)
5. Check `--ai-skills` requires `--ai`
6. Interactive AI selection if `--ai` not provided (arrow key selection, default: copilot)
7. Validate generic agent requires `--ai-commands-dir`
8. Check CLI tool availability (special handling: Claude local path, Kiro dual executable)
9. Interactive script type selection (default: `ps` on Windows, `sh` otherwise)
10. Download template from GitHub API (`github/spec-kit` releases)
11. Extract ZIP (flatten nested dirs, merge with existing for `--here`, deep-merge `.vscode/settings.json`)
12. Rename generic placeholder dir to `--ai-commands-dir` path
13. `ensure_executable_scripts()` — set POSIX chmod on `.sh` files with shebangs
14. `ensure_constitution_from_template()` — copy constitution template preserving existing
15. If `--ai-skills`: `install_ai_skills()` — create SKILL.md files per agentskills.io spec, then remove command files for new projects
16. Git init (if not `--no-git`, not existing repo, git available)
17. Display security notice, next steps panel, enhancement commands panel

### Key Helper Functions

| Function | Lines | Purpose |
|----------|-------|---------|
| `_github_token()` | 60-62 | CLI arg → `GH_TOKEN` → `GITHUB_TOKEN` → None |
| `_github_auth_headers()` | 64-67 | Bearer token header if token exists |
| `_parse_rate_limit_headers()` | 69-95 | Extract X-RateLimit-* headers |
| `_format_rate_limit_error()` | 97-124 | User-friendly rate limit message (60/hr unauth, 5000/hr auth) |
| `StepTracker` | 305-388 | Hierarchical progress with Rich Tree (statuses: pending/running/done/error/skipped) |
| `get_key()` | 390-408 | Cross-platform keypress (readchar): up/down/enter/escape/ctrl-c |
| `select_with_arrows()` | 410-483 | Interactive selection with Rich Live display |
| `check_tool()` | 544-578 | Tool detection with special handling for Claude (local path) and Kiro (dual executable) |
| `init_git_repo()` | 600-633 | Git init + add + commit "Initial commit from Specify template" |
| `handle_vscode_settings()` | 635-700 | Deep-merge `.vscode/settings.json` files |
| `merge_json_files()` | 659-700 | Recursive dict merge (new keys added, nested dicts merged, lists replaced) |
| `download_template_from_github()` | 702-814 | GitHub API release fetch, streaming download with progress |
| `download_and_extract_template()` | 816-963 | Download, extract ZIP, flatten, merge for --here mode |
| `ensure_executable_scripts()` | 966-1012 | POSIX chmod with shebang detection (no-op on Windows) |
| `ensure_constitution_from_template()` | 1014-1047 | Copy template to `.specify/memory/constitution.md`, preserve existing |
| `_get_skills_dir()` | 1072-1087 | Override → AGENT_CONFIG → `.agents/skills` default |
| `install_ai_skills()` | 1090-1244 | Parse YAML frontmatter, generate SKILL.md per agentskills.io, additive/idempotent |

### AI Skills Installation (agentskills.io)
- Skills installed to `<agent_folder>/skills/speckit-<command>/SKILL.md`
- Override: `AGENT_SKILLS_DIR_OVERRIDES = {"codex": ".agents/skills"}`
- Default: `.agents/skills`
- Frontmatter includes: name, description (enhanced from `SKILL_DESCRIPTIONS`), compatibility, metadata
- Installation is additive — existing SKILL.md files never overwritten
- For new projects with `--ai-skills`, command files are removed after skills install (skills replace commands)

---

## 6. AGENT_CONFIG — 22 Supported Agents

Source: `__init__.py` lines 127-261

| Key | Name | Folder | Commands Subdir | Install URL | Requires CLI |
|-----|------|--------|----------------|-------------|-------------|
| `copilot` | GitHub Copilot | `.github/` | `agents` | None (IDE) | No |
| `claude` | Claude Code | `.claude/` | `commands` | anthropic docs | Yes |
| `gemini` | Gemini CLI | `.gemini/` | `commands` | github.com/google-gemini | Yes |
| `cursor-agent` | Cursor | `.cursor/` | `commands` | None (IDE) | No |
| `qwen` | Qwen Code | `.qwen/` | `commands` | github.com/QwenLM | Yes |
| `opencode` | opencode | `.opencode/` | `command` (singular) | opencode.ai | Yes |
| `codex` | Codex CLI | `.codex/` | `prompts` | github.com/openai/codex | Yes |
| `windsurf` | Windsurf | `.windsurf/` | `workflows` | None (IDE) | No |
| `kilocode` | Kilo Code | `.kilocode/` | `workflows` | None (IDE) | No |
| `auggie` | Auggie CLI | `.augment/` | `commands` | docs.augmentcode.com | Yes |
| `codebuddy` | CodeBuddy | `.codebuddy/` | `commands` | codebuddy.ai | Yes |
| `qodercli` | Qoder CLI | `.qoder/` | `commands` | qoder.com | Yes |
| `roo` | Roo Code | `.roo/` | `commands` | None (IDE) | No |
| `kiro-cli` | Kiro CLI | `.kiro/` | `prompts` | kiro.dev | Yes |
| `amp` | Amp | `.agents/` | `commands` | ampcode.com | Yes |
| `shai` | SHAI | `.shai/` | `commands` | github.com/ovh/shai | Yes |
| `agy` | Antigravity | `.agent/` | `workflows` | None (IDE) | No |
| `bob` | IBM Bob | `.bob/` | `commands` | None (IDE) | No |
| `generic` | Generic (BYO) | None (dynamic) | `commands` | None | No |

**Aliases**: `AI_ASSISTANT_ALIASES = {"kiro": "kiro-cli"}`

**Command subdirectory variations**: `commands` (default), `agents` (Copilot), `command` (opencode, singular), `prompts` (Codex, Kiro), `workflows` (Windsurf, Kilocode, Agy)

**Critical design rule** (from AGENTS.md): Dictionary keys MUST match the actual CLI executable name to avoid special-case mappings.

---

## 7. Extension System Architecture

Source: `src/specify_cli/extensions.py` (1815 lines)

### Class Hierarchy

```
ExtensionError (base)
├── ValidationError
└── CompatibilityError

ExtensionManifest          — Schema v1.0 validation, YAML loading
ExtensionRegistry          — JSON persistence at .specify/extensions/.registry
ExtensionManager           — Lifecycle: install, remove, list, get
CommandRegistrar           — Per-agent format conversion (16 agents)
ExtensionCatalog           — Dual catalogs with 1-hour caching
ConfigManager              — 4-layer precedence configuration
HookExecutor               — Event-based hooks with conditions
```

### ExtensionManifest (lines 39-161)
- **Schema version**: 1.0
- **Required fields**: `schema_version`, `extension`, `requires`, `provides`
- **Extension ID pattern**: `^[a-z0-9-]+$`
- **Command name pattern**: `^speckit\.[a-z0-9-]+\.[a-z0-9-]+$`
- **Version**: PEP 440 semantic versioning
- **Validation**: Extension must provide at least one command with `name` and `file`
- **Hash**: SHA256 of manifest file

### ExtensionRegistry (lines 164-255)
- **Storage**: `.specify/extensions/.registry` (JSON)
- **Schema version**: 1.0
- **Operations**: add (with timestamp), remove, get, list, is_installed

### ExtensionManager (lines 258-564)
- **`install_from_directory()`**: Validate manifest → check compatibility → copy to `.specify/extensions/<id>/` → register commands for all detected agents → register hooks → update registry
- **`install_from_zip()`**: Extract to temp dir with **Zip Slip prevention** (validate all paths before extraction via `is_relative_to`) → find manifest in subdirectory if nested → delegate to `install_from_directory()`
- **`remove()`**: Unregister commands from all agents → remove Copilot companion `.prompt.md` files → backup config files to `.specify/extensions/.backup/<id>/` → unregister hooks → update registry
- **`list_installed()`**: Returns id, name, version, description, enabled status, command_count, hook_count
- **`get_extension()`**: Returns ExtensionManifest or None

### CommandRegistrar (lines 585-966)
**AGENT_CONFIGS** — 16 agents with format details:

| Agent | Dir | Format | Args Placeholder | File Extension |
|-------|-----|--------|-----------------|---------------|
| claude | `.claude/commands` | markdown | `$ARGUMENTS` | `.md` |
| gemini | `.gemini/commands` | toml | `{{args}}` | `.toml` |
| copilot | `.github/agents` | markdown | `$ARGUMENTS` | `.agent.md` |
| cursor | `.cursor/commands` | markdown | `$ARGUMENTS` | `.md` |
| qwen | `.qwen/commands` | toml | `{{args}}` | `.toml` |
| opencode | `.opencode/command` | markdown | `$ARGUMENTS` | `.md` |
| windsurf | `.windsurf/workflows` | markdown | `$ARGUMENTS` | `.md` |
| kilocode | `.kilocode/rules` | markdown | `$ARGUMENTS` | `.md` |
| auggie | `.augment/rules` | markdown | `$ARGUMENTS` | `.md` |
| roo | `.roo/rules` | markdown | `$ARGUMENTS` | `.md` |
| codebuddy | `.codebuddy/commands` | markdown | `$ARGUMENTS` | `.md` |
| qodercli | `.qoder/commands` | markdown | `$ARGUMENTS` | `.md` |
| kiro-cli | `.kiro/prompts` | markdown | `$ARGUMENTS` | `.md` |
| amp | `.agents/commands` | markdown | `$ARGUMENTS` | `.md` |
| shai | `.shai/commands` | markdown | `$ARGUMENTS` | `.md` |
| bob | `.bob/commands` | markdown | `$ARGUMENTS` | `.md` |

**Key methods**:
- `parse_frontmatter()` / `render_frontmatter()` — YAML frontmatter handling
- `_adjust_script_paths()` — Convert `../../scripts/` to `.specify/scripts/`
- `_render_markdown_command()` — Add extension context comments
- `_render_toml_command()` — Convert to TOML for Gemini/Qwen
- `_convert_argument_placeholder()` — `$ARGUMENTS` ↔ `{{args}}`
- `register_commands_for_agent()` — Read source, parse frontmatter, adjust paths, convert placeholders, render in agent format, write to agent dir, handle aliases
- `_write_copilot_prompt()` — Generate companion `.prompt.md` with `agent:` frontmatter for `.github/prompts/`
- `register_commands_for_all_agents()` — Detect agents by directory existence, register for all found
- `register_commands_for_claude()` — Convenience shortcut

### ExtensionCatalog (lines 969-1237)
- **Default URL**: `https://raw.githubusercontent.com/github/spec-kit/main/extensions/catalog.json`
- **Cache**: 1 hour, stored in `.specify/extensions/.cache/`
- **Custom catalog**: `SPECKIT_CATALOG_URL` env var (HTTPS enforced, localhost exception)
- **`search()`**: Filter by query (name/description/tags), tag, author, verified_only
- **`download_extension()`**: Download ZIP with HTTPS enforcement, save to cache/downloads
- **Community catalog**: `extensions/catalog.community.json` has 5 extensions (cleanup, retrospective, sync, v-model, verify)

### ConfigManager (lines 1240-1436)
**4-layer precedence** (lowest → highest):
1. **Defaults**: `extension.yml` → `config.defaults`
2. **Project config**: `.specify/extensions/{id}/{id}-config.yml`
3. **Local config**: `.specify/extensions/{id}/local-config.yml` (gitignored)
4. **Environment**: `SPECKIT_{EXT_ID}_{SECTION}_{KEY}` (e.g., `SPECKIT_JIRA_CONNECTION_URL`)

**Methods**: `get_config()` (merged), `get_value(key_path)` (dot-notation), `has_value(key_path)`

### HookExecutor (lines 1439-1815)
- **Storage**: `.specify/extensions.yml`
- **Default settings**: `auto_execute_hooks: True`
- **Hook registration**: From manifest hooks → project config, idempotent (update if exists)
- **Hook unregistration**: Remove by extension_id from all events
- **Condition evaluation** patterns:
  - `config.key.path is set` — checks if config value exists
  - `config.key.path == 'value'` — equality check (boolean normalization)
  - `config.key.path != 'value'` — inequality check
  - `env.VAR_NAME is set` — environment variable exists
  - `env.VAR_NAME == 'value'` / `!= 'value'` — env var comparison
- **Hook execution**: Returns info for AI agent to execute (command, extension, optional flag, description, prompt)
- **Event format**: `format_hook_message()` produces markdown with Optional/Automatic hook sections

---

## 8. Template System — Structure Templates

Source: `templates/` directory

### spec-template.md (116 lines)
The feature specification template. Key structure:
- **Header**: Feature Branch, Created, Status, Input
- **User Scenarios & Testing** (mandatory): Prioritized user stories (P1/P2/P3), each independently testable with Given/When/Then acceptance scenarios
- **Edge Cases**: Boundary conditions, error scenarios
- **Requirements** (mandatory): Functional Requirements (FR-001 format), `[NEEDS CLARIFICATION]` markers for ambiguities
- **Key Entities**: Data entities with attributes and relationships (if data involved)
- **Success Criteria** (mandatory): Measurable Outcomes (SC-001 format), technology-agnostic, verifiable

### plan-template.md (105 lines)
The implementation plan template. Key structure:
- **Header**: Branch, Date, Spec link, Input
- **Summary**: Primary requirement + technical approach
- **Technical Context**: Language/Version, Dependencies, Storage, Testing, Platform, ProjectType, Performance Goals, Constraints, Scale/Scope — all with `NEEDS CLARIFICATION` if unknown
- **Constitution Check**: GATE — must pass before Phase 0 research, re-check after Phase 1
- **Project Structure**: Documentation tree (`specs/[###-feature]/`) + Source Code (3 options: Single project, Web app, Mobile+API)
- **Complexity Tracking**: Only filled if Constitution Check has violations (table: Violation | Why Needed | Simpler Alternative Rejected Because)

### tasks-template.md (252 lines)
The task breakdown template. Key structure:
- **Format**: `[ID] [P?] [Story] Description` — checkbox, task ID (T001), parallel marker, user story label (US1/US2/US3)
- **Phase 1**: Setup (project init)
- **Phase 2**: Foundational (blocking prerequisites — MUST complete before any user story)
- **Phase 3+**: One phase per user story in priority order, each with optional tests + implementation tasks
- **Phase N**: Polish & Cross-Cutting Concerns
- **Dependencies**: Phase dependencies, user story dependencies, within-story ordering
- **Strategies**: MVP First (complete US1, stop, validate), Incremental Delivery, Parallel Team

### checklist-template.md (41 lines)
Quality checklist template. Key structure:
- **Header**: Type, Purpose, Created, Feature link
- **Categories**: CHK-numbered items grouped by category
- **Notes**: Usage instructions

### agent-file-template.md (29 lines)
Auto-generated agent context file. Key structure:
- Active Technologies, Project Structure, Commands, Code Style, Recent Changes
- `<!-- MANUAL ADDITIONS START -->` / `<!-- MANUAL ADDITIONS END -->` markers

### constitution-template.md (51 lines)
Project constitution template with placeholders:
- `[PROJECT_NAME]`, `[PRINCIPLE_1_NAME]`, `[PRINCIPLE_1_DESCRIPTION]`, etc.
- Core Principles (flexible number)
- Governance section
- Version metadata: `[CONSTITUTION_VERSION]` | `[RATIFICATION_DATE]` | `[LAST_AMENDED_DATE]`

---

## 9. Slash Command Definitions — Full Behavioral Specs

Source: `templates/commands/*.md`

### `/speckit.specify` — Feature Specification

**Frontmatter**:
```yaml
description: Create or update the feature specification from a natural language feature description.
handoffs: [{label: Build Technical Plan, agent: speckit.plan}, {label: Clarify Spec Requirements, agent: speckit.clarify}]
scripts:
  sh: scripts/bash/create-new-feature.sh --json "{ARGS}"
  ps: scripts/powershell/create-new-feature.ps1 -Json "{ARGS}"
```

**Execution Flow**:
1. Generate concise branch short name (2-4 words, action-noun format)
2. Check existing branches across remote, local, and specs/ directories to find highest feature number
3. Run `create-new-feature.sh` with `--number N+1 --short-name "name"` and feature description
4. Load `templates/spec-template.md`
5. Parse user description → extract actors, actions, data, constraints
6. For unclear aspects: make informed guesses, limit to max 3 `[NEEDS CLARIFICATION]` markers, prioritize by: scope > security/privacy > UX > technical
7. Fill User Scenarios, Functional Requirements (each testable), Success Criteria (measurable, tech-agnostic)
8. Write to SPEC_FILE
9. **Quality Validation**: Generate `checklists/requirements.md`, validate against quality criteria (Content Quality, Requirement Completeness, Feature Readiness), self-correct up to 3 iterations
10. Handle `[NEEDS CLARIFICATION]`: present max 3 questions with option tables (A/B/C/Custom), wait for user response, update spec

**Key Rules**: Focus on WHAT/WHY not HOW. No tech stack. Written for business stakeholders. Reasonable defaults for: data retention, performance, error handling, auth, integration patterns.

### `/speckit.plan` — Implementation Planning

**Frontmatter**:
```yaml
description: Execute the implementation planning workflow using the plan template.
handoffs: [{label: Create Tasks, agent: speckit.tasks}, {label: Create Checklist, agent: speckit.checklist}]
scripts: {sh: setup-plan.sh --json, ps: setup-plan.ps1 -Json}
agent_scripts: {sh: update-agent-context.sh __AGENT__, ps: update-agent-context.ps1 -AgentType __AGENT__}
```

**Execution Flow**:
1. Run `setup-plan.sh` → get FEATURE_SPEC, IMPL_PLAN, SPECS_DIR, BRANCH
2. Load spec + constitution
3. Fill Technical Context, Constitution Check
4. **Phase 0: Research** — Generate research agents for unknowns, consolidate into `research.md` (Decision/Rationale/Alternatives)
5. **Phase 1: Design** — Extract entities → `data-model.md`, define interface contracts → `contracts/`, run agent context update script
6. Re-evaluate Constitution Check post-design
7. Stop and report (does NOT create tasks — that's `/speckit.tasks`)

### `/speckit.tasks` — Task Generation

**Frontmatter**:
```yaml
description: Generate actionable, dependency-ordered tasks.md.
handoffs: [{label: Analyze, agent: speckit.analyze}, {label: Implement, agent: speckit.implement}]
scripts: {sh: check-prerequisites.sh --json, ps: check-prerequisites.ps1 -Json}
```

**Execution Flow**:
1. Run `check-prerequisites.sh` → get FEATURE_DIR, AVAILABLE_DOCS
2. Load plan.md (required) + spec.md (required for user stories) + optional: data-model.md, contracts/, research.md, quickstart.md
3. Extract tech stack, user stories with priorities, entities, contracts, decisions
4. Generate tasks organized by user story using strict format: `- [ ] T001 [P] [US1] Description with file path`
5. Phase structure: Setup → Foundational (blocking) → User Stories (P1→P2→P3) → Polish
6. Each user story independently testable
7. Report: total tasks, per-story counts, parallel opportunities, MVP scope suggestion

**Task Generation Rules**:
- Tests OPTIONAL (only if explicitly requested)
- `[P]` = parallelizable (different files, no dependencies)
- `[USn]` = user story label (required in story phases only)
- Each task must have exact file path
- Within story: Tests → Models → Services → Endpoints → Integration

### `/speckit.implement` — Implementation Execution

**Frontmatter**:
```yaml
description: Execute all tasks from tasks.md.
scripts: {sh: check-prerequisites.sh --json --require-tasks --include-tasks, ps: ...}
```

**Execution Flow**:
1. Run prerequisite check → get FEATURE_DIR, AVAILABLE_DOCS
2. Check checklists status — if incomplete, STOP and ask user to confirm
3. Load tasks.md + plan.md + optional docs
4. **Project Setup Verification**: Create/verify ignore files based on detected tech stack (14 language-specific pattern sets + 5 tool-specific pattern sets)
5. Parse task phases, dependencies, parallel markers
6. Execute phase-by-phase: Setup → Tests → Core → Integration → Polish
7. Follow TDD: test tasks before implementation tasks
8. Mark completed tasks as `[X]` in tasks.md
9. Halt on non-parallel failures, continue successful parallel tasks
10. Completion validation: verify all tasks done, features match spec, tests pass

### `/speckit.clarify` — Structured Clarification

**Frontmatter**:
```yaml
description: Identify underspecified areas using up to 5 targeted questions.
handoffs: [{label: Build Technical Plan, agent: speckit.plan}]
scripts: {sh: check-prerequisites.sh --json --paths-only, ps: ...}
```

**Execution Flow**:
1. Load current spec
2. Structured ambiguity scan using 10-category taxonomy: Functional Scope, Domain & Data Model, Interaction & UX, Non-Functional Quality, Integration & Dependencies, Edge Cases, Constraints & Tradeoffs, Terminology, Completion Signals, Misc/Placeholders
3. Generate prioritized queue (max 5 questions) using Impact x Uncertainty heuristic
4. **Sequential questioning** — ONE question at a time:
   - Multiple choice: present recommended option prominently, option table (A-E), accept by letter/yes/custom
   - Short answer: suggest answer with reasoning, accept by yes/custom (<=5 words)
5. After EACH answer: update spec incrementally (create `## Clarifications` section, apply to appropriate sections, atomic overwrite)
6. Validation after each write: no duplicates, <=5 total questions, no contradictions, valid markdown
7. Report: questions asked, path, sections touched, coverage summary (Resolved/Deferred/Clear/Outstanding)

### `/speckit.analyze` — Cross-Artifact Consistency

**Frontmatter**:
```yaml
description: Non-destructive cross-artifact consistency analysis.
scripts: {sh: check-prerequisites.sh --json --require-tasks --include-tasks, ps: ...}
```

**KEY CONSTRAINT**: **STRICTLY READ-ONLY** — does not modify any files.

**Execution Flow**:
1. Load spec.md, plan.md, tasks.md, constitution
2. Build semantic models: requirements inventory, user story inventory, task coverage mapping, constitution rule set
3. **6 Detection Passes** (max 50 findings):
   - A. Duplication Detection
   - B. Ambiguity Detection (vague adjectives, unresolved placeholders)
   - C. Underspecification (missing outcomes, unaligned acceptance criteria)
   - D. Constitution Alignment (MUST principle violations = always CRITICAL)
   - E. Coverage Gaps (requirements with zero tasks, unmapped tasks)
   - F. Inconsistency (terminology drift, entity mismatches, ordering contradictions)
4. Severity: CRITICAL (constitution/missing artifact) > HIGH (duplicate/conflict) > MEDIUM (drift/coverage) > LOW (style)
5. Output: Findings table, Coverage Summary, Constitution Issues, Unmapped Tasks, Metrics
6. Offer remediation (never apply automatically)

### `/speckit.constitution` — Project Constitution Management

**Frontmatter**:
```yaml
description: Create or update project constitution.
handoffs: [{label: Build Specification, agent: speckit.specify}]
```

**Execution Flow**:
1. Load `.specify/memory/constitution.md`
2. Identify placeholder tokens `[ALL_CAPS_IDENTIFIER]`
3. Collect/derive values (user input > repo context > ask/TODO)
4. Version bump semantically: MAJOR (removals/redefinitions), MINOR (additions), PATCH (clarifications)
5. Draft constitution: replace all placeholders, preserve heading hierarchy
6. **Consistency propagation**: update plan-template.md, spec-template.md, tasks-template.md, command files, runtime docs
7. Produce Sync Impact Report (HTML comment at top of file)
8. Validate: no unexplained brackets, version matches, ISO dates, declarative/testable language
9. Write back, output summary with suggested commit message

### `/speckit.checklist` — Quality Checklists

**KEY CONCEPT**: Checklists are **"Unit Tests for English"** — they validate requirement QUALITY, not implementation behavior.

**Execution Flow**:
1. Run prerequisite check
2. Dynamic clarification (up to 3 initial + 2 follow-up questions max)
3. Combine user input + clarifying answers → derive theme
4. Load feature context (spec.md, plan.md, tasks.md)
5. Generate checklist testing requirements quality across 9 dimensions:
   - Requirement Completeness, Clarity, Consistency
   - Acceptance Criteria Quality, Scenario Coverage, Edge Case Coverage
   - Non-Functional Requirements, Dependencies & Assumptions, Ambiguities & Conflicts
6. File: `checklists/{domain}.md` (e.g., `ux.md`, `api.md`, `security.md`)
7. Append mode: if file exists, continue from last CHK ID
8. Traceability: >=80% items must reference spec section or use markers `[Gap]`, `[Ambiguity]`, `[Conflict]`, `[Assumption]`

**Prohibited**: "Verify", "Test", "Confirm" + implementation behavior. No code execution references.
**Required**: "Are [requirements] defined/specified?", "Is [term] quantified?", "Can [requirement] be measured?"

### `/speckit.taskstoissues` — GitHub Issues from Tasks

**Frontmatter**:
```yaml
description: Convert tasks into GitHub issues.
tools: ['github/github-mcp-server/issue_write']
scripts: {sh: check-prerequisites.sh --json --require-tasks --include-tasks, ps: ...}
```

**Execution Flow**:
1. Parse tasks from tasks.md
2. Get git remote URL
3. **CAUTION**: Only proceed if remote is a GitHub URL
4. Create issues via GitHub MCP server
5. **CAUTION**: NEVER create issues in repositories that don't match the remote URL

---

## 10. Script System — Bash & PowerShell Parity

Source: `scripts/bash/` (5 files) and `scripts/powershell/` (5 files)

### Bash Scripts

#### `common.sh`
Shared utility functions: `get_repo_root()`, `get_current_branch()`, `has_git()`, `is_feature_branch()`, `get_feature_dir()`, `get_feature_paths_env()`, `file_exists()`, `dir_has_files()`

#### `create-new-feature.sh`
- 33 stop words filtered from branch names
- 244-byte GitHub branch name limit
- Finds highest feature number across remote branches, local branches, specs/ directories
- Creates branch `NNN-short-name`, initializes `specs/NNN-short-name/` with spec.md
- Outputs JSON: `BRANCH_NAME`, `SPEC_FILE`, `SPEC_DIR`

#### `setup-plan.sh`
- Copies plan template to feature directory if not exists
- Outputs JSON: `FEATURE_SPEC`, `IMPL_PLAN`, `SPECS_DIR`, `BRANCH`

#### `check-prerequisites.sh`
- Validates feature dir exists, plan.md exists
- Optional: `--require-tasks` checks tasks.md, `--include-tasks` includes task content
- `--paths-only` returns minimal paths
- Discovers design documents (data-model.md, contracts/, research.md, quickstart.md)
- Outputs JSON: `FEATURE_DIR`, `AVAILABLE_DOCS`, optionally task content

#### `update-agent-context.sh`
- 17 functions for agent context management
- 18 agent file path mappings (agent type → output file path)
- Parses `plan.md` for technology stack
- Creates/updates agent-specific context files
- **Cursor .mdc frontmatter handling**: Prepends YAML frontmatter (`description`, `globs: ["**/*"]`, `alwaysApply: true`) to `.mdc` files
- Preserves content between `<!-- MANUAL ADDITIONS START -->` and `<!-- MANUAL ADDITIONS END -->`

### PowerShell Scripts (Full Parity)

All 5 bash scripts have PowerShell equivalents with identical logic:
- `common.ps1` (138 lines, 8 functions)
- `create-new-feature.ps1` (306 lines, 6 functions, same 33 stop words, same 244-byte limit)
- `setup-plan.ps1` (62 lines)
- `check-prerequisites.ps1` (149 lines)
- `update-agent-context.ps1` (464 lines, 17 functions, 18 agent paths, same Cursor frontmatter logic)

---

## 11. CI/CD & Release Pipeline

Source: `.github/workflows/` (7 workflows) and `.github/workflows/scripts/` (8 scripts)

### Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `test.yml` | Push/PR to main | Ruff lint + pytest on Python 3.11/3.12/3.13 |
| `lint.yml` | Push/PR to main | markdownlint-cli2 on all .md (except extensions/) |
| `release.yml` | Tag `v*` | Build packages + create GitHub release |
| `release-trigger.yml` | Manual dispatch | Auto/manual version bump → create branch → tag → PR |
| `codeql.yml` | Push/PR to main, weekly | CodeQL for actions + python |
| `docs.yml` | Push to main (docs/**) | DocFX build → GitHub Pages |
| `stale.yml` | Daily | 150 days stale → 180 days close (exempts pinned/security labels) |

### Release Pipeline (Two-Workflow System)

**release-trigger.yml** (manual dispatch):
1. User triggers with version bump type (auto/major/minor/patch/manual)
2. `get-next-version.sh` calculates next version
3. `update-version.sh` updates `pyproject.toml`
4. Creates release branch, commits, pushes tag
5. Creates PR back to main
6. Uses `RELEASE_PAT` secret

**release.yml** (tag-triggered):
1. Triggered by `v*` tag push
2. Checks out code + full history
3. `generate-release-notes.sh` creates notes from git log
4. `create-release-packages.sh` builds ZIP packages (19 agents x 2 script types = 38 ZIPs)
5. `create-github-release.sh` creates release with all 38 assets
6. Uses `GITHUB_TOKEN`

### Release Scripts

| Script | Lines | Purpose |
|--------|-------|---------|
| `check-release-exists.sh` | 22 | Check if release already exists via `gh` |
| `get-next-version.sh` | 25 | Auto-increment patch version from latest tag |
| `update-version.sh` | 24 | Update version in `pyproject.toml` via sed |
| `generate-release-notes.sh` | 41 | Generate `release_notes.md` from git log |
| `create-release-packages.sh` | 280 | Build per-agent ZIP packages (bash version) |
| `create-release-packages.ps1` | 440 | Build per-agent ZIP packages (PowerShell version) |
| `create-github-release.sh` | 59 | Create GitHub release with 38 ZIP assets |
| `simulate-release.sh` | 162 | Local dry-run of full release pipeline |

### Package Build Logic
Each agent gets two ZIPs (sh + ps), containing:
- `.specify/` directory (config, templates, scripts, memory)
- Agent-specific command directory (e.g., `.claude/commands/`, `.gemini/commands/`)
- `.vscode/settings.json` (for Copilot prompt recommendations)
- Per-agent format conversion (Markdown → TOML for Gemini/Qwen)
- Cursor .mdc frontmatter prepended for cursor-agent packages

---

## 12. Project File Structure

```
spec-kit/
├── src/specify_cli/
│   ├── __init__.py            # 2390 lines — Complete CLI (AGENT_CONFIG, init, check, version, extensions)
│   └── extensions.py          # 1815 lines — Extension system (6 classes)
├── templates/
│   ├── commands/              # 9 slash command definitions (.md)
│   │   ├── specify.md         # Feature specification (262 lines)
│   │   ├── plan.md            # Implementation planning (97 lines)
│   │   ├── tasks.md           # Task generation (141 lines)
│   │   ├── implement.md       # Implementation execution (139 lines)
│   │   ├── constitution.md    # Constitution management (85 lines)
│   │   ├── clarify.md         # Structured clarification (185 lines)
│   │   ├── analyze.md         # Cross-artifact analysis (188 lines)
│   │   ├── checklist.md       # Quality checklists (299 lines)
│   │   └── taskstoissues.md   # GitHub Issues conversion (34 lines)
│   ├── spec-template.md       # Feature spec structure (116 lines)
│   ├── plan-template.md       # Implementation plan structure (105 lines)
│   ├── tasks-template.md      # Task breakdown structure (252 lines)
│   ├── checklist-template.md  # Checklist structure (41 lines)
│   ├── agent-file-template.md # Agent context file (29 lines)
│   └── constitution-template.md # Constitution structure (51 lines)
├── scripts/
│   ├── bash/                  # 5 bash scripts + common.sh
│   └── powershell/            # 5 PowerShell scripts + common.ps1
├── tests/
│   ├── test_ai_skills.py      # 764 lines, 39 tests
│   ├── test_extensions.py     # 1136 lines, 39 tests
│   ├── test_cursor_frontmatter.py # 264 lines, 7 tests
│   └── test_agent_config_consistency.py # 100 lines, 8 tests
├── extensions/
│   ├── catalog.json           # Default catalog (empty)
│   ├── catalog.community.json # 5 community extensions
│   ├── README.md              # Dual catalog documentation
│   ├── templates/             # 8 extension template files
│   └── docs/                  # 5 extension documentation files + RFC
├── .github/
│   ├── workflows/             # 7 CI/CD workflows
│   │   └── scripts/           # 8 release pipeline scripts
│   ├── ISSUE_TEMPLATE/        # 4 issue templates + config.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── CODEOWNERS             # @mnriem owns all
│   └── dependabot.yml         # pip + github-actions weekly
├── .devcontainer/
│   ├── devcontainer.json      # Python 3.13, all AI agents pre-installed
│   └── post-create.sh         # Installs 10 CLI tools + DocFx
├── docs/                      # DocFX documentation site
├── media/                     # 5 image/gif assets
├── spec-driven.md             # SDD philosophy (413 lines)
├── AGENTS.md                  # Agent integration guide (420 lines)
├── README.md                  # Project README (665 lines)
├── CHANGELOG.md               # Version history
├── pyproject.toml             # Build config, v0.1.13
├── LICENSE                    # MIT
├── CONTRIBUTING.md            # AI disclosure required
├── SECURITY.md                # GitHub security policy
├── SUPPORT.md                 # Support channels
└── CODE_OF_CONDUCT.md         # Contributor Covenant v1.4
```

---

## 13. Test Coverage Map

Source: `tests/` (4 test files, 93 total tests)

### test_ai_skills.py (764 lines, 39 tests)

| Test Class | Count | Coverage |
|-----------|-------|---------|
| TestGetSkillsDir | 9 | Override → AGENT_CONFIG → default fallback, all edge cases |
| TestInstallAiSkills | 12 | Template discovery, frontmatter parsing, SKILL.md generation, additive behavior, fallback dirs |
| TestCommandCoexistence | 4 | Skills + commands coexist, no file conflicts |
| TestNewProjectCommandSkip | 4 | End-to-end with CliRunner: commands removed after skills install for new projects |
| TestSkipIfExists | 2 | Existing SKILL.md never overwritten |
| TestSkillDescriptions | 1 | All commands have enhanced descriptions |
| TestCliValidation | 7 | Parameter ordering fix (#1641), --ai-skills requires --ai, mutual exclusivity |

### test_extensions.py (1136 lines, 39 tests)

| Test Class | Count | Coverage |
|-----------|-------|---------|
| TestExtensionManifest | 7 | Valid/invalid manifests, ID pattern, version, command name pattern |
| TestExtensionRegistry | 4 | CRUD operations, persistence, corrupted registry handling |
| TestExtensionManager | 6 | Install from dir/zip, remove with backup, Zip Slip prevention, compatibility |
| TestCommandRegistrar | 8 | Per-agent registration, Copilot .prompt.md companion, TOML conversion, path adjustment |
| TestVersionSatisfies | 4 | PEP 440 specifier matching |
| TestIntegration | 3 | Full install/remove/reinstall workflows |
| TestExtensionCatalog | 7 | HTTPS enforcement, caching, search, custom catalog URL |

### test_cursor_frontmatter.py (264 lines, 7 tests)

| Test Class | Count | Coverage |
|-----------|-------|---------|
| TestScriptFrontmatterPattern | 3 | Static analysis: bash script has mdc logic (2+ occurrences), PowerShell has mdc logic |
| TestCursorFrontmatterIntegration | 4 | New .mdc gets frontmatter, existing without gets it added, existing with not duplicated, non-mdc has no frontmatter |

### test_agent_config_consistency.py (100 lines, 8 tests)

| Test | Coverage |
|------|---------|
| Runtime config uses kiro-cli, excludes q | AGENT_CONFIG sync |
| Extension registrar uses kiro-cli, excludes q | CommandRegistrar.AGENT_CONFIGS sync |
| Release agent lists include kiro-cli, shai, agy, exclude q | Bash + PS release scripts sync |
| PS switch has shai and agy generation | PowerShell release builder |
| CLI help includes roo and kiro alias | AI_ASSISTANT_HELP sync |
| Devcontainer Kiro installer uses pinned SHA256 | Security verification |
| Release output targets .kiro/prompts, not .amazonq | Legacy removal |
| Agent context scripts use kiro-cli, not legacy q | Script sync |

---

## 14. Data Flows Between Commands

### Artifact Creation Chain

```
/speckit.constitution
    └→ .specify/memory/constitution.md

/speckit.specify
    ├→ specs/NNN-name/spec.md           (feature specification)
    └→ specs/NNN-name/checklists/requirements.md (quality validation)

/speckit.clarify
    └→ specs/NNN-name/spec.md           (updated with Clarifications section)

/speckit.plan
    ├→ specs/NNN-name/plan.md           (implementation plan)
    ├→ specs/NNN-name/research.md       (Phase 0 research)
    ├→ specs/NNN-name/data-model.md     (Phase 1 entities)
    ├→ specs/NNN-name/contracts/        (Phase 1 interfaces)
    ├→ specs/NNN-name/quickstart.md     (Phase 1 validation)
    └→ <agent-context-file>             (via update-agent-context.sh)

/speckit.tasks
    └→ specs/NNN-name/tasks.md          (ordered task list)

/speckit.checklist
    └→ specs/NNN-name/checklists/{domain}.md

/speckit.analyze
    └→ (stdout only, no file writes)

/speckit.implement
    ├→ Source code files
    ├→ Test files
    ├→ Ignore files (.gitignore, .dockerignore, etc.)
    └→ specs/NNN-name/tasks.md          (tasks marked [X])

/speckit.taskstoissues
    └→ GitHub Issues (via MCP)
```

### Script Dependency Map

```
specify.md     → create-new-feature.sh   → (creates branch + spec dir)
plan.md        → setup-plan.sh           → (copies plan template)
               → update-agent-context.sh → (updates agent file)
tasks.md       → check-prerequisites.sh  → (validates feature dir + docs)
implement.md   → check-prerequisites.sh --require-tasks --include-tasks
clarify.md     → check-prerequisites.sh --json --paths-only
analyze.md     → check-prerequisites.sh --require-tasks --include-tasks
checklist.md   → check-prerequisites.sh
taskstoissues.md → check-prerequisites.sh --require-tasks --include-tasks
```

### Constitution Propagation
When constitution changes via `/speckit.constitution`:
1. Plan template constitution check section must align
2. Spec template scope/requirements sections checked
3. Tasks template task categorization checked
4. All command files checked for outdated references
5. Runtime guidance docs updated

---

## 15. Adoption Checklist for bumba-agent

### To Use Spec Kit in a New Project

1. **Install**: `uv tool install specify-cli --from git+https://github.com/github/spec-kit.git`
2. **Initialize**: `specify init <project-name> --ai <agent> [--ai-skills]`
3. **Establish principles**: `/speckit.constitution` — define project governing principles
4. **Create spec**: `/speckit.specify <feature description>` — generates spec.md with user stories
5. **(Optional) Clarify**: `/speckit.clarify` — resolve ambiguities before planning
6. **Plan**: `/speckit.plan <tech stack notes>` — generates plan.md, research.md, data-model.md, contracts/
7. **Generate tasks**: `/speckit.tasks` — generates ordered tasks.md
8. **(Optional) Analyze**: `/speckit.analyze` — cross-artifact consistency check
9. **(Optional) Checklist**: `/speckit.checklist <domain>` — quality validation
10. **Implement**: `/speckit.implement` — execute all tasks following TDD approach

### Key Conventions to Follow

- **Branch naming**: `NNN-short-name` (e.g., `001-user-auth`)
- **Spec directory**: `specs/NNN-short-name/` with spec.md, plan.md, tasks.md, etc.
- **Constitution location**: `.specify/memory/constitution.md`
- **Config location**: `.specify/config.yaml`
- **Templates location**: `.specify/templates/`
- **Scripts location**: `.specify/scripts/{bash,powershell}/`
- **Agent commands**: `<agent-folder>/<commands-subdir>/` (varies per agent)
- **Agent skills**: `<agent-folder>/skills/speckit-<command>/SKILL.md`
- **Extensions**: `.specify/extensions/`

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `GH_TOKEN` / `GITHUB_TOKEN` | GitHub API authentication (5000 req/hr vs 60/hr) |
| `SPECIFY_FEATURE` | Override feature detection for non-Git environments |
| `SPECKIT_CATALOG_URL` | Custom extension catalog URL (HTTPS required) |
| `SPECKIT_{EXT_ID}_{KEY}` | Extension configuration overrides |

### What the Agent Must Know

1. **Spec-first always**: Never write code before specification is complete and validated
2. **Constitutional authority**: Constitution principles are non-negotiable — violations require justification in Complexity Tracking
3. **Template-driven**: All artifacts follow template structure — don't improvise sections
4. **Quality gates**: Phase -1 gates must pass before proceeding
5. **TDD when specified**: If Article III applies, tests before implementation is NON-NEGOTIABLE
6. **Additive skills**: SKILL.md files are never overwritten — existing customizations preserved
7. **Read-only analysis**: `/speckit.analyze` never modifies files
8. **Max 3 clarifications**: `/speckit.specify` limits `[NEEDS CLARIFICATION]` to 3 per spec
9. **Max 5 questions**: `/speckit.clarify` limits to 5 total questions, one at a time
10. **Checklists test requirements, not implementation**: "Are requirements defined?" not "Does it work?"

---

*End of audit report. Every file in the github/spec-kit repository has been read at function/method level. This document contains implementation-grade detail sufficient for an AI agent to adopt and operate Spec Kit without ambiguity.*
