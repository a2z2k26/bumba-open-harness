---
name: create-template
description: Create custom sandbox template
---

# /create-sandbox-template Command

Creates a custom Bumba Sandbox template with pre-installed dependencies and optimized configuration for faster startup times.

## Usage

```
/create-sandbox-template <name> [--base <image>] [--runtime <runtime>]
```

## Parameters

- `<name>` (required): Template name (alphanumeric, hyphens allowed)
- `--base <image>` (optional): Base Docker image (default: ubuntu:22.04)
- `--runtime <runtime>` (optional): Primary runtime (node, python, go, rust, java)
- `--interactive` (optional): Interactive configuration wizard
- `--from-current` (optional): Create template from current sandbox state

## Workflow

### Step 1: Template Configuration

**Interactive Mode**:
```
🎨 Sandbox Template Builder
═══════════════════════════════════════════════

Template Name: my-app-template

Base Configuration:
  [1] Ubuntu 22.04 (Recommended)
  [2] Ubuntu 20.04
  [3] Debian 12
  [4] Alpine Linux (minimal)
  [5] Custom Docker image

Select base image (1-5): 1

Runtime Selection:
  [✓] Node.js 20.x
  [ ] Python 3.11
  [ ] Go 1.21
  [ ] Rust latest
  [ ] Java 17

Select runtimes (space to toggle, enter to confirm)

System Packages:
  Common packages to install?
  [✓] git
  [✓] curl
  [✓] build-essential
  [ ] postgresql-client
  [ ] redis-tools

Dependencies:
  Package manager dependencies?
  Node.js: package.json found - install from package.json? (yes/no): yes
  Python: requirements.txt not found

Environment Variables:
  Add environment variables? (yes/no): yes
    NODE_ENV=development
    PORT=3000

Optimization:
  [✓] Layer caching optimization
  [✓] Multi-stage build
  [ ] Health check endpoint
```

### Step 2: Generate Dockerfile

```dockerfile
# Generated Dockerfile for template: my-app-template

FROM ubuntu:22.04

# System packages (cached layer)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Node.js installation (cached layer)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest

# Set working directory
WORKDIR /workspace

# Copy dependency files (cached layer)
COPY package*.json ./

# Install dependencies (cached layer)
RUN npm ci --only=production

# Environment variables
ENV NODE_ENV=development \
    PORT=3000

# Default command
CMD ["/bin/bash"]
```

### Step 3: Build and Register Template

```
🔨 Building Template
═══════════════════════════════════════════════

[1/5] Creating Dockerfile...
      ✓ Dockerfile generated

[2/5] Uploading to Bumba Sandbox...
      ✓ Dockerfile uploaded

[3/5] Building template...
      ⏳ Layer 1/6: Base image (cached)
      ⏳ Layer 2/6: System packages (building...)
      ⏳ Layer 3/6: Node.js runtime (building...)
      ⏳ Layer 4/6: Dependencies (building...)
      ⏳ Layer 5/6: Environment (building...)
      ⏳ Layer 6/6: Finalization (building...)

      Build time: 3m 45s
      ✓ Template built successfully

[4/5] Registering template...
      Template ID: tmpl_abc123xyz
      ✓ Registered with Bumba Sandbox

[5/5] Testing template...
      Creating test sandbox...
      Startup time: 0.8s (vs 120s without template)
      ✓ Template working correctly

✅ Template Created Successfully!
═══════════════════════════════════════════════

Template: my-app-template
Template ID: tmpl_abc123xyz
Base Image: ubuntu:22.04
Size: 1.2 GB
Startup Time: ~0.8 seconds

Installed:
  - Node.js 20.x
  - npm dependencies from package.json
  - git, curl, build-essential

Usage:
  /implement-feature #42 --template my-app-template

Saved to: .claude/templates/my-app-template/
```

## Examples

### Example 1: Interactive Template Creation
```
/create-sandbox-template my-app --interactive
```

### Example 2: Node.js Template
```
/create-sandbox-template node-app --runtime node
```

### Example 3: From Current Sandbox
```
/create-sandbox-template production-ready --from-current
```

## Template Benefits

**Performance**:
- Startup: ~150ms vs ~2 minutes
- Dependencies: Pre-installed
- Layer caching: Optimized rebuilds

**Cost Savings**:
- Faster iteration cycles
- Reduced wait time
- Lower total runtime

## Error Handling

### Common Errors

**Template Name Validation Error**:
```
❌ Error: Invalid template name "my_template@123"

Template names must:
  - Be alphanumeric with hyphens only
  - Start with a letter
  - Be 3-50 characters long

Valid examples:
  - my-app-template
  - node-prod-v2
  - python-ml

Try again with a valid name.
```

**Build Failure**:
```
❌ Error: Template build failed

Build logs:
  Step 4/6: RUN npm install
  npm ERR! Cannot find module 'package.json'

Cause: Missing package.json in Dockerfile context
Solution: Ensure package.json exists before building

Troubleshooting:
  1. Check Dockerfile COPY statements
  2. Verify file paths are correct
  3. Review E2B template documentation
  4. Run /create-sandbox-template --interactive for guided setup

Template files saved to: .claude/templates/my-app-template/
You can manually fix the Dockerfile and retry.
```

**Bumba Sandbox API Error**:
```
❌ Error: Bumba Sandbox API request failed

Status: 429 Too Many Requests
Message: Template build rate limit exceeded

Your account limits:
  - Free tier: 5 builds/day
  - Pro tier: 50 builds/day

Current usage: 5/5 builds today

Solutions:
  1. Wait until tomorrow (resets at midnight UTC)
  2. Upgrade to Pro tier for higher limits
  3. Use existing templates instead of creating new ones

Retry after: 6 hours 23 minutes
```

**Template Already Exists**:
```
⚠️  Warning: Template 'my-app-template' already exists

Existing template:
  ID: tmpl_abc123xyz
  Created: Nov 15, 2025
  Size: 1.1 GB
  Last Used: 2 days ago

Actions:
  [1] Overwrite existing template (rebuilds)
  [2] Create with different name
  [3] Cancel

Select action (1-3): _
```

**Insufficient Permissions**:
```
❌ Error: Bumba Sandbox API authentication failed

Cause: BUMBA_SANDBOX_API_KEY is invalid or expired

Solutions:
  1. Check BUMBA_SANDBOX_API_KEY in .env file
  2. Generate new API key from Bumba Sandbox dashboard
  3. Verify API key has template creation permissions

Bumba Sandbox Dashboard: https://bumba.sandbox/dashboard/api-keys
```

**Template Size Limit Exceeded**:
```
❌ Error: Template size exceeds limits

Template size: 4.2 GB
Account limit: 3.0 GB (Free tier)

Large components:
  - Node modules: 2.1 GB
  - Python packages: 1.8 GB
  - System packages: 0.3 GB

Solutions:
  1. Remove unnecessary dependencies
  2. Use multi-stage builds to reduce size
  3. Upgrade to Pro tier (10 GB limit)
  4. Split into multiple smaller templates

Optimization suggestions:
  - Use npm ci --only=production
  - Remove dev dependencies
  - Clear package manager caches
```

### Recovery Actions

**Automatic Recovery**:
- Template files saved locally even if build fails
- Can retry build after fixing errors
- Partial builds are cleaned up automatically
- Local Dockerfile preserved for manual fixes

**Manual Recovery**:
```bash
# Fix Dockerfile manually
vim .claude/templates/my-app-template/Dockerfile

# Retry build via Bumba Sandbox CLI
bumba-sandbox template build .claude/templates/my-app-template/

# Or recreate via command
/create-sandbox-template my-app-template --interactive
```

## Notes

- Templates are reusable across all issues
- Update template: rebuild with same name
- Templates stored in Bumba Sandbox account
- Free tier: 5 custom templates
- Pro tier: Unlimited templates
- Build failures save Dockerfile locally for debugging
- Template validation happens before build starts
- Bumba Sandbox has rate limits on template builds (5/day free tier)
