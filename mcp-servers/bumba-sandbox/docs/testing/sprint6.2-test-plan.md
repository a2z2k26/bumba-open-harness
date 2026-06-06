# Sprint 6.2: Simple Feature Workflow (Local Mode) - Test Plan

**Phase**: 6 - Integration, Testing & Deployment
**Sprint**: 6.2
**Duration**: 30-45 minutes
**Mode**: Local (no sandboxes)

---

## Objective

Test a complete end-to-end workflow for implementing a simple feature in local mode, verifying that all MCP tools work correctly when called through Claude Code.

---

## Prerequisites

- [x] MCP server configured in Claude Code
- [x] MCP server builds successfully
- [x] Server registers 23 tools
- [ ] E2B API key configured (for future sprints)
- [ ] Test repository available

---

## Test Workflow Overview

This test simulates a realistic feature implementation workflow:

1. Initialize a simple test project
2. Use MCP tools to inspect the project
3. Create a simple feature specification
4. Implement the feature using file operations
5. Execute commands to verify the implementation
6. Clean up

---

## Test Steps

### Step 1: Verify MCP Tool Availability

**Goal**: Confirm all 23 tools are accessible from Claude Code

**Actions**:
- Ask Claude to list available E2B orchestrator tools
- Verify tool categories appear:
  - Lifecycle (4 tools)
  - File Operations (5 tools)
  - Command Execution (3 tools)
  - Orchestration (8 tools)
  - Metadata (3 tools)

**Expected Result**:
```
Available E2B Orchestrator Tools (23 total):

Lifecycle Management:
  - sandbox_init
  - sandbox_create
  - sandbox_kill
  - sandbox_list

File Operations:
  - file_read
  - file_write
  - file_list
  - file_upload
  - file_download

[... etc ...]
```

**Success Criteria**: All 23 tools listed

---

### Step 2: Test File Operations (Local)

**Goal**: Verify file operations work in local mode

**Test 2a: Create Test Project Structure**

Create a simple test project:
```
test-project/
├── package.json
├── src/
│   └── index.js
└── README.md
```

**Actions**:
1. Ask Claude to create test project directory structure
2. Use Write tool to create package.json
3. Use Write tool to create src/index.js
4. Use Write tool to create README.md

**Expected Result**: All files created successfully

**Test 2b: Read Files Back**

**Actions**:
1. Ask Claude to read package.json using Read tool
2. Verify contents match what was written

**Success Criteria**: File contents match expected

---

### Step 3: Test Command Execution

**Goal**: Verify local command execution works

**Test 3a: Simple Commands**

**Actions**:
1. Run `ls -la` in test project directory
2. Run `node --version`
3. Run `npm --version`

**Expected Result**: Commands execute and return output

**Test 3b: Command with Output Parsing**

**Actions**:
1. Run `cat package.json`
2. Ask Claude to parse the JSON output

**Success Criteria**: Commands execute successfully, output is readable

---

### Step 4: Test Metadata Tools

**Goal**: Verify metadata and template tools

**Test 4a: List Sandbox Templates**

**Actions**:
1. Call `list_templates` tool
2. Verify official templates are listed (node, python, base, etc.)

**Expected Result**:
```
Available E2B Sandbox Templates:

Official Templates (24):
  - node (Node.js environment)
  - python (Python environment)
  - base (Base Linux environment)
  [... etc ...]
```

**Success Criteria**: Templates list appears, includes common templates

---

### Step 5: Test Error Handling

**Goal**: Verify tools handle errors gracefully

**Test 5a: Read Non-Existent File**

**Actions**:
1. Try to read a file that doesn't exist
2. Verify error message is clear

**Expected Result**: Clear error message, no crash

**Test 5b: Invalid Command**

**Actions**:
1. Try to execute an invalid command
2. Verify error is reported

**Success Criteria**: Errors handled gracefully with clear messages

---

### Step 6: Test Tool Chaining

**Goal**: Verify multiple tools can be called in sequence

**Workflow**: Create → Read → Modify → Read

**Actions**:
1. Create a file with initial content
2. Read the file to verify
3. Modify the file (append text)
4. Read again to verify modification

**Expected Result**: All steps succeed, file contains expected final content

**Success Criteria**: Multi-step workflow completes successfully

---

### Step 7: Clean Up

**Actions**:
1. Remove test project directory
2. Verify cleanup successful

---

## Success Metrics

### Must Pass (Critical)
- [ ] All 23 tools are accessible
- [ ] File operations work (read/write/list)
- [ ] Command execution works
- [ ] Template listing works
- [ ] Errors handled gracefully

### Should Pass (Important)
- [ ] Multi-tool workflows succeed
- [ ] Output parsing works correctly
- [ ] Performance is acceptable (<5s per tool call)

### Nice to Have
- [ ] Tool responses are well-formatted
- [ ] Help text is clear and useful

---

## Known Limitations (Sprint 6.2)

Since this is **local mode only**, the following are expected:

- ❌ No sandbox creation (testing in Sprint 6.3)
- ❌ No orchestration (testing in Sprint 6.4)
- ❌ No parallel execution (testing in Sprint 6.4)
- ❌ No hook logging (testing in Sprint 6.5)

These are EXPECTED limitations for this sprint.

---

## Issue Tracking

Document any issues found:

### Issue Template
```markdown
**Issue**: [Brief description]
**Tool**: [Tool name]
**Steps to Reproduce**: 
1. ...
2. ...
**Expected**: ...
**Actual**: ...
**Severity**: Critical / High / Medium / Low
**Workaround**: [If any]
```

---

## Test Results Documentation

After completing tests, document:

1. **Tools Tested**: X/23 tested
2. **Pass Rate**: X% passed
3. **Issues Found**: X issues
4. **Blockers**: [List any blockers]
5. **Ready for Sprint 6.3**: YES/NO

---

## Next Steps

If Sprint 6.2 passes:
- ✅ Proceed to Sprint 6.3 (Sandbox workflows)
- ✅ Proceed to Sprint 6.4 (Parallel execution)

If Sprint 6.2 fails:
- ❌ Document issues
- ❌ Fix critical blockers
- ❌ Re-test before proceeding

---

**Test Plan Status**: Ready for Execution
**Estimated Duration**: 30-45 minutes
**Prerequisites**: All met ✅

---

**Last Updated**: 2025-01-18 22:35 PST
