---
name: track-switching
description: Switch between project tracks and system work
---

# Track Switching Skill

Implements the track switching protocol from zone-plan.md. Enables seamless context switching between projects and system work while preserving continuity.

## Commands

### 1. "Switch to System"

Resume system work (zone infrastructure, agent improvements).

**Steps:**
1. Save current project state (if any active project):
   - Update `last_worked` to today's date in current project YAML
   - Update `where_we_left_off` with summary of current progress
2. Read `config/zone1/zone-plan.md` for system context
3. Read `config/system-prompt.md` for current zone status
4. Display system status:
   ```
   Switched to: System Track
   Zone Status: [read from system-prompt.md]
   Last System Work: [date]
   ```

### 2. "Switch to [ProjectName]"

Resume work on a registered project.

**Steps:**
1. Save current context (same as step 1 above)
2. Read `data/projects/<ProjectName>.yaml`
   - If not found: suggest `/project/register` or list available projects
3. Update the project's `last_worked` to today
4. Display project context:
   ```
   Switched to: <project>
   Status: <status>
   Stack: <stack>
   Where we left off: <where_we_left_off>

   Next steps:
   1. <next_step_1>
   2. <next_step_2>
   ...

   Key files:
   - <file_1>
   - <file_2>
   ...

   Recent decisions:
   - <last 3 decisions>
   ```
5. Load project context — read key files if they exist on disk

### 3. "New project: [Name]"

Create and activate a new project track.

**Steps:**
1. Save current context (same as step 1 above)
2. Run `/project/register <Name>` flow:
   - Gather description, stack via interactive prompts
   - Create `data/projects/<name>.yaml`
3. Set new project as active
4. Display confirmation and next steps

### 4. "Suspend [ProjectName]"

Mark a project as suspended, preserving all state.

**Steps:**
1. Read `data/projects/<ProjectName>.yaml`
   - If not found: list available projects
2. Update fields:
   - `status: suspended`
   - `last_worked: <today>`
   - `where_we_left_off: <current summary>`
3. Display:
   ```
   Suspended: <project>
   State preserved in: data/projects/<project>.yaml
   Resume with: "Switch to <project>"
   ```

## State Management

- **On switch-out**: Always update `last_worked` and `where_we_left_off` before leaving
- **On switch-in**: Always read full YAML and display context
- **Persistence**: All state lives in YAML files — survives restarts, session boundaries
- **No pollution**: Suspended projects consume no context — only loaded on explicit switch

## Trigger Detection

Activate this skill when the operator says any of:
- "Switch to System" / "system track" / "work on system"
- "Switch to [Name]" / "work on [name]" / "open [name]"
- "New project: [Name]" / "start project [name]" / "register [name]"
- "Suspend [Name]" / "pause [name]" / "shelve [name]"

## Integration

- Uses `/project/register` for new project creation
- Uses `/project/status` for listing available projects
- Uses `/project/config` for field updates
- Registry files: `data/projects/*.yaml` (Tier A — agent-writable)
