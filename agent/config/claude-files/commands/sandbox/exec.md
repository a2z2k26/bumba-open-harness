---
name: sandbox/exec
description: Execute a command in a cloud sandbox
arguments:
  - name: sandboxId
    description: "The sandbox ID (from /sandbox/init)"
    required: true
  - name: command
    description: "Shell command to execute"
    required: true
  - name: cwd
    description: "Working directory inside the sandbox"
    required: false
  - name: env
    description: "Environment variables as KEY=VAL pairs"
    required: false
---

# /sandbox/exec — Execute Command in Sandbox

Runs a shell command inside an existing cloud sandbox.

## Usage

```
/sandbox/exec <sandboxId> <command> [--cwd path] [--env KEY=VAL]
```

## Implementation

When the user runs this command, execute the following steps:

### Step 1: Parse Arguments

Extract from `$ARGUMENTS`:
- `sandboxId`: Required. The sandbox identifier.
- `command`: Required. Everything after the sandboxId (unless prefixed with `--`).
- `--cwd`: Optional. Working directory path inside the sandbox.
- `--env`: Optional. One or more `KEY=VAL` pairs, parsed into an object.

### Step 2: Execute Command

Call `bumba-sandbox:execute_command` with:
- `sandboxId`: parsed sandbox ID
- `command`: the shell command string
- `cwd`: if provided
- `envVars`: if `--env` provided, convert `KEY=VAL` pairs to object

### Step 3: Display Result

On success (exitCode 0):
```
Exit: 0
stdout:
<stdout output>
```

If stderr is non-empty, also show:
```
stderr:
<stderr output>
```

On failure (exitCode non-zero):
```
Exit: <exitCode>
stdout:
<stdout if any>

stderr:
<stderr if any>

Tip: Check that the command exists in the sandbox template.
     Use /sandbox/exec <id> which <command> to verify.
```

### Step 4: Handle Errors

If the sandbox doesn't exist or has been killed:
- Suggest creating a new sandbox with `/sandbox/init`

If the command times out:
- Suggest using a longer timeout via the `timeout` parameter
- Or running with `background: true` for long-running processes
