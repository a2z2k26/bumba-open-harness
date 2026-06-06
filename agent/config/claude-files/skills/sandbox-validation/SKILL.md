---
name: sandbox-validation
description: Run untrusted code safely in E2B sandbox before applying locally
---

# Sandbox Validation Skill

Uses E2B cloud sandboxes to safely test and validate code that could be risky to run locally. Maps to the `bumba-sandbox` MCP server tools.

## When to Sandbox

| Scenario | Why |
|---|---|
| Untrusted dependencies | New npm/pip packages from unknown sources |
| Destructive operations | Database migrations, file system modifications |
| Multi-language projects | Runtime may not be installed locally |
| New frameworks | Unknown side effects during testing |
| Security testing | Isolate potentially malicious code |
| CI simulation | Reproduce CI failures in clean environment |

## Workflow

### Step 1: Initialize Sandbox

Use MCP tool: `sandbox_init`
```json
{
  "template": "python-3.11",  // or node-18, go-1.21, etc.
  "timeout": 300
}
```

Templates available:
- `python-3.11` — Python with pip
- `node-18` — Node.js with npm
- `go-1.21` — Go modules
- `base` — Minimal Linux (for custom setups)

### Step 2: Upload Code

Use MCP tool: `write_file` (one file at a time) or `execute_command` with curl/git clone.

For small projects:
```
write_file(path="/code/main.py", content="...")
write_file(path="/code/tests/test_main.py", content="...")
```

For larger projects:
```
execute_command(command="git clone <repo_url> /code")
```

### Step 3: Install Dependencies

```
execute_command(command="cd /code && pip install -r requirements.txt")
```

### Step 4: Run Tests

```
execute_command(command="cd /code && python -m pytest tests/ -v --tb=short")
```

### Step 5: Read Results

Parse the stdout/stderr from execute_command for pass/fail.

### Step 6: Cleanup

Use MCP tool: `sandbox_kill`

Kill the sandbox promptly to minimize cost (~$0.02/hour).

## Cost Awareness

- Sandboxes cost ~$0.02/hour while running
- Always kill sandboxes after use
- Use appropriate templates (don't use a heavy template for simple validation)
- Set reasonable timeouts (5 min for most tests, 15 min for full suites)
- Prefer local testing when safe — sandbox only when isolation is needed

## Decision: Local vs Sandbox

```
Is the code from a trusted source (our own codebase)?
  YES → Local testing
  NO  → Does it install new dependencies?
    YES → Sandbox
    NO  → Does it modify the filesystem or database?
      YES → Sandbox
      NO  → Local testing
```

## MCP Tool Reference

From `bumba-sandbox` MCP server:

| Tool | Purpose |
|---|---|
| `sandbox_init` | Create new sandbox |
| `execute_command` | Run a command in sandbox |
| `write_file` | Write a file to sandbox |
| `read_file` | Read a file from sandbox |
| `list_files` | List directory contents |
| `sandbox_kill` | Terminate sandbox |
| `sandbox_status` | Check sandbox state |

## Integration

- Called by `/validate --sandbox`
- Part of the validate-fix loop when sandbox mode is selected
- Pre-deploy validation can use sandbox for integration tests
