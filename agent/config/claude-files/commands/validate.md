---
name: validate
description: Run tests against the current codebase or a specific project
---

# /validate — Run Tests and Report Results

Runs the appropriate test suite for the current project, parses results, and reports pass/fail status. Optionally enters a fix loop for failures.

## Usage

```
/validate [--sandbox] [--fix] [--project <name>]
```

## Parameters

- `--sandbox` (optional): Run tests in an E2B sandbox instead of locally
- `--fix` (optional): Enter the validate-fix loop (max 3 iterations)
- `--project <name>` (optional): Validate a specific project (reads registry for test config)

## Workflow

### Step 1: Detect Test Framework

Auto-detect based on project files:

| File | Framework | Command |
|------|-----------|---------|
| `pytest.ini`, `pyproject.toml` (with pytest), `tests/*.py` | pytest | `python -m pytest tests/ -v --tb=short` |
| `package.json` (with jest) | jest | `npx jest --verbose` |
| `package.json` (with vitest) | vitest | `npx vitest run` |
| `go.mod` | go test | `go test ./... -v` |
| `Cargo.toml` | cargo test | `cargo test` |

For bumba-open-harness (this project):
```bash
python -m pytest tests/ -v --tb=short
```

### Step 2: Execute Tests

**Local mode (default):**
```bash
cd <project_root>
<test_command>
```

**Sandbox mode (`--sandbox`):**
Use bumba-sandbox MCP tools:
1. `sandbox_init` with appropriate template
2. Upload project files
3. `execute_command` with the test command
4. Read results
5. `sandbox_kill` to clean up

### Step 3: Parse Results

Extract from test output:
- **Total tests**: number discovered
- **Passed**: count
- **Failed**: count with names
- **Errors**: count with error messages
- **Skipped**: count

### Step 4: Report

**All passing:**
```
Validation: PASSED
  Tests: 196 passed, 0 failed
  Time: 12.3s
```

**Failures:**
```
Validation: FAILED
  Tests: 190 passed, 6 failed
  Time: 15.1s

  Failed:
    - test_email_service.py::TestEmailDigest::test_compile_with_messages
      AttributeError: module has no attribute 'get_unread_count'

    - test_calendar_service.py::TestConflictDetection::test_detects_overlap
      AssertionError: 0 != 1
```

### Step 5: Fix Loop (if `--fix`)

If failures exist and `--fix` is specified:
1. Analyze each failure — read the test, read the source, identify the fix
2. Apply the fix
3. Re-run `/validate`
4. If still failing after 3 iterations: stop and report to operator with analysis
5. If passing: suggest commit and optionally `/deploy`

## Integration

- Pre-deploy: `/validate` should pass before `/deploy`
- Fix loop: uses the validate-fix-loop skill (Sprint 28)
- Sandbox: uses bumba-sandbox MCP for isolated execution

## Notes

- For bumba-open-harness, tests are in `agent/tests/` and use pytest + pytest-asyncio
- Some tests require the `migrated_db` fixture (from conftest.py)
- Test discovery: `pytest --collect-only` to list available tests
- The deploy helper runs `/validate` automatically for Python file deploys
