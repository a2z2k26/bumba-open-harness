---
name: sandbox/init
description: Initialize a new cloud sandbox for isolated code execution
arguments:
  - name: template
    description: "Sandbox template: base, node, python, go, rust, java (default: base)"
    required: false
  - name: timeout
    description: "Sandbox timeout in minutes (default: 60)"
    required: false
---

# /sandbox/init — Initialize Cloud Sandbox

Creates a new E2B cloud sandbox for isolated code execution.

## Usage

```
/sandbox/init [template] [--timeout minutes]
```

## Implementation

When the user runs this command, execute the following steps:

### Step 1: Parse Arguments

Extract from `$ARGUMENTS`:
- `template`: Optional. One of `base`, `node`, `python`, `go`, `rust`, `java`. Default: `base`
- `--timeout`: Optional. Minutes (converted to seconds for API). Default: 60

### Step 2: Create Sandbox

Call `bumba-sandbox:sandbox_init` with:
- `template`: the parsed template name
- `timeout`: parsed minutes × 60 (convert to seconds)

### Step 3: Display Result

On success, display:

```
Sandbox Created
  ID:       <sandboxId>
  Template: <template>
  Timeout:  <minutes> minutes
  Status:   running

Quick commands:
  /sandbox/exec <sandboxId> echo "hello world"
  /sandbox/exec <sandboxId> ls -la

Remember to kill the sandbox when done:
  bumba-sandbox:sandbox_kill { sandboxId: "<sandboxId>" }
```

On failure, display the error message and suggest:
- Checking the template name is valid
- Trying again with `base` template
- Verifying E2B API connectivity
