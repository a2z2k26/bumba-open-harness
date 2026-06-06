# /transform-{FRAMEWORK} - Transform Design Tokens to {FRAMEWORK_DISPLAY}

Transform design tokens from `.design/tokens/` into {FRAMEWORK_DISPLAY} code.

## Purpose

This skill reads Figma design tokens and transforms them into production-ready {FRAMEWORK_DISPLAY} code with:
- Type-safe token definitions
- Framework-optimized structure
- Component scaffolding (if applicable)
- Storybook stories (if enabled)

## Prerequisites

Before running this skill, ensure:
- `.design/` directory exists (run `/design-init` first)
- `.design/config.json` is configured
- `.design/tokens/` contains Figma tokens
- Project framework matches: {FRAMEWORK}

## Instructions

### Step 1: Verify .design/ Structure

Check that Design Bridge is initialized:

```bash
# Verify .design/ exists
ls -la .design/

# Check for tokens
ls -la .design/tokens/

# Verify config
cat .design/config.json | grep '"framework"'
# Should show: "framework": "{FRAMEWORK}"
```

If `.design/` doesn't exist, stop and tell user to run `/design-init` first.

### Step 2: Read Configuration

Load project configuration to understand:
- Framework settings
- TypeScript enabled?
- Output path preferences
- Feature flags (Storybook, tests, etc.)

Use the shared utility:

```javascript
const { readDesignConfig } = require('./.claude/scripts/read-design-config');
const config = readDesignConfig(process.cwd());

// Verify framework matches
if (config.project.framework !== '{FRAMEWORK}') {
  throw new Error(`Project configured for ${config.project.framework}, not {FRAMEWORK}`);
}
```

### Step 3: Load Design Tokens

Load all design tokens from `.design/tokens/`:

```javascript
const { loadDesignTokens } = require('./.claude/scripts/load-design-tokens');
const tokens = loadDesignTokens(process.cwd());

// Tokens structure:
// {
//   colors: { primary: '#3B82F6', ... },
//   typography: { heading: { fontSize: '24px', ... }, ... },
//   spacing: { unit: '8px', ... },
//   effects: { ... }
// }
```

### Step 4: Execute Transformation

Call the {FRAMEWORK} optimizer with loaded tokens:

```javascript
const {FRAMEWORK}Optimizer = require('./packages/@design-bridge/transformers/optimizers/{FRAMEWORK}-optimizer');

const result = await {FRAMEWORK}Optimizer.transform(tokens, {
  typescript: config.project.typescript,
  outputPath: `.design/extracted-code/{FRAMEWORK}`,
  generateStories: config.transformers.options.{FRAMEWORK}?.generateStories || false,
  // Framework-specific options from config
  ...config.transformers.options.{FRAMEWORK}
});
```

### Step 5: Verify Output

Check that files were created:

```bash
# List generated files
ls -la .design/extracted-code/{FRAMEWORK}/

# Verify tokens generated
ls -la .design/extracted-code/{FRAMEWORK}/tokens/

# Check components (if applicable)
ls -la .design/extracted-code/{FRAMEWORK}/components/ 2>/dev/null || echo "No components generated"
```

### Step 6: Update Metadata

Track this transformation:

```javascript
const { updateMetadata } = require('./.claude/scripts/update-metadata');

await updateMetadata(process.cwd(), {
  type: 'transformation',
  framework: '{FRAMEWORK}',
  timestamp: new Date().toISOString(),
  filesGenerated: result.files.length,
  tokensProcessed: Object.keys(tokens).length
});
```

### Step 7: Report Results

Inform user of transformation results:

**Success Message:**
```
✅ {FRAMEWORK_DISPLAY} Transformation Complete

Generated Files:
- Tokens: {tokenCount} files
- Components: {componentCount} files
- Total: {totalFiles} files

Output Location:
.design/extracted-code/{FRAMEWORK}/

Next Steps:
{NEXT_STEPS}
```

## Expected Output

### Token Files
```
.design/extracted-code/{FRAMEWORK}/
├── tokens/
│   ├── colors.{EXT}
│   ├── typography.{EXT}
│   ├── spacing.{EXT}
│   ├── effects.{EXT}
│   └── index.{EXT}
```

### Component Files (if applicable)
```
.design/extracted-code/{FRAMEWORK}/
└── components/
    └── Button/
        ├── Button.{EXT}
        ├── Button.stories.{EXT} (if Storybook enabled)
        └── index.{EXT}
```

## Configuration Options

From `.design/config.json`:

```json
{
  "transformers": {
    "options": {
      "{FRAMEWORK}": {
        {FRAMEWORK_OPTIONS}
      }
    }
  }
}
```

## Troubleshooting

**Error: .design/ directory not found**
→ Run `/design-init` first

**Error: No tokens found**
→ Run Figma plugin to extract tokens

**Error: Framework mismatch**
→ Check config.json framework setting matches {FRAMEWORK}

**Error: Transform failed**
→ Check token file format is valid JSON
→ Review logs in .design/logs/

## Related Skills

- `/design-init` - Initialize .design/ structure
- Other transform skills for different frameworks
