---
name: design-director-init
description: Initialize Bumba Design Director for product planning specifications
---

You are initializing Bumba Design Director - a CLI-based specification generator that creates detailed product planning documents with Bumba Design System integration.

## Prerequisites Check

First, verify the environment:

1. Check if `.design/` directory exists in the current working directory
   - If NOT found: Display error and instruct user to run `/design-init` first
   - If found: Continue

2. Check if `.design/bumba-design-director/` already exists
   - If found: Ask user "Design Director is already initialized. Do you want to reinitialize? (This will preserve existing product/ files but update utilities and templates)"
     - If user says no: Exit gracefully
     - If user says yes: Continue with update

## Directory Structure Creation

Create the following directory structure in `.design/bumba-design-director/`:

```
.design/bumba-design-director/
├── lib/                    # Utility libraries (copied from source)
├── templates/              # Handlebars templates (copied from source)
├── product/                # Generated specifications (empty, user creates these)
├── .claude/
│   ├── commands/          # Command files (will be copied to project root)
│   ├── skills/            # Skill documents
│   └── hooks/             # Automation hooks
└── .gitignore             # Ignore generated files initially
```

Create each directory using mkdir with recursive option.

## File Copying

The source templates are located at:
`/home/operator/Bumba - Design/Bumba - Design Components/server/design-director-templates/`

Copy the following files/directories:

1. **Utility Libraries** (from `lib/` to `.design/bumba-design-director/lib/`)
   - `bumba-reader.js`
   - `spec-generator.js`
   - `type-generator.js`
   - `export-builder.js`

2. **Templates** (from `templates/` to `.design/bumba-design-director/templates/`)
   - `product-overview.md.tmpl`
   - `product-roadmap.md.tmpl`
   - `data-model.md.tmpl`
   - `shell-spec.md.tmpl`
   - `section-spec.md.tmpl`

3. **Dependencies** (copy `package.json` and run npm install)
   - Copy `package.json` to `.design/bumba-design-director/`
   - Run `npm install` in `.design/bumba-design-director/` directory

4. **Create .gitignore** in `.design/bumba-design-director/product/`
   ```
   # Generated specifications - commit when ready
   *.md
   *.json
   *.ts
   ```

## Bumba Integration Status Check

After setup, check for Bumba Design System integration:

1. **Check for config**: Read `.design/config.json`
   - If found: Extract framework preference (transformers.preferred or first in transformers.enabled)
   - If not found: Set framework to 'react' (default)

2. **Check for tokens**: List files in `.design/tokens/`
   - If found: Count .json files, list them
   - If not found: Note that tokens will be extracted via Bumba features

3. **Check for components**: List files in `.design/components/`
   - If found: Count .json files, display count
   - If not found: Note that components will be extracted via Bumba features

## Display Success Message

Show initialization summary:

```
✓ Bumba Design Director initialized successfully!

Structure created:
   .design/bumba-design-director/
   ├── lib/           # Utility libraries
   ├── templates/     # Specification templates
   ├── product/       # Generated specifications (empty)
   └── .claude/       # Commands, skills, hooks

Bumba Integration Status:
   Config: [✓ Found / ✗ Not found] (framework: [react/vue/angular/etc.])
   Tokens: [✓ Found ([N] files) / ✗ Not found]
   Components: [✓ Found ([N] components) / ✗ Not found]

[If any not found, display:]
Note: Missing Bumba assets will use graceful fallback.
      Run Bumba Design commands to extract tokens and components from Figma.

Next Steps:
   1. Start product planning: /director-vision
   2. Or explore all Director commands in .claude/commands/

Important: Design Director generates SPECIFICATIONS ONLY.
           Tangible design assets (tokens, components, layouts) are created
           via Bumba Design commands (/design-transform-react, etc.)
```

## Error Handling

Handle these error cases:

1. **No .design/ directory**:
   ```
   Error: .design/ directory not found

   Design Director requires Bumba Design System to be initialized first.

   → Run /design-init to set up the .design/ structure
   → Then run /director-init again
   ```

2. **Copy failures**:
   ```
   Error: Failed to copy [filename]

   This may be a permissions issue or the source file is missing.

   → Check file permissions in current directory
   → Verify source templates exist at: [path]
   ```

3. **npm install failure**:
   ```
   Error: Failed to install dependencies

   → Check that npm is installed: npm --version
   → Try manually: cd .design/bumba-design-director && npm install
   ```

## Implementation Notes

- Use absolute paths for source files (hardcoded source template location)
- Use relative paths for destination (within current working directory)
- Preserve existing `product/` directory if reinitializing
- Create directories with `fs.mkdirSync(path, { recursive: true })`
- Copy files with `fs.copyFileSync(source, destination)`
- Use `child_process.execSync('npm install')` for dependency installation
