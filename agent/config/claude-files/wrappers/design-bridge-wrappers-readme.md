# Design Bridge Transformer Wrappers

Executable Node.js scripts that wrap BUMBA optimizers for use with Claude Code skills.

## Available Wrappers

### Web Frameworks
- `transform-react.js` - React + TypeScript transformation
- `transform-vue.js` - Vue 3 Composition API transformation
- `transform-angular.js` - Angular standalone components transformation
- `transform-svelte.js` - Svelte + TypeScript transformation

### Mobile Frameworks
- `transform-react-native.js` - React Native transformation
- `transform-flutter.js` - Flutter/Dart transformation
- `transform-swiftui.js` - SwiftUI transformation
- `transform-jetpack-compose.js` - Jetpack Compose transformation

## Architecture

Each wrapper:

```
1. Read .design/config.json          (readDesignConfig)
2. Load .design/tokens/*.json        (loadDesignTokens)
3. Call BUMBA optimizer              (packages/@design-bridge/transformers/optimizers/)
4. Write .design/extracted-code/     (optimizer.transform())
5. Update .design/metadata.json      (updateMetadata)
```

## Usage

Wrappers are called from Claude Code skills:

```javascript
// From a skill.md file
const { exec } = require('child_process');

exec('node ./.claude/wrappers/transform-react.js', (error, stdout, stderr) => {
  if (error) {
    console.error('Transformation failed:', error);
    return;
  }
  console.log(stdout);
});
```

Or directly from command line:

```bash
node ./.claude/wrappers/transform-react.js
```

## Dependencies

Wrappers use:
- **Shared Utilities** (from .claude/scripts/):
  - `read-design-config.js` - Configuration loader
  - `load-design-tokens.js` - Token loader
  - `update-metadata.js` - Metadata updater

- **BUMBA Optimizers** (from packages/@design-bridge/transformers/optimizers/):
  - Framework-specific transformation logic
  - Production-tested code from BUMBA CLI 1.0

## Error Handling

Each wrapper includes comprehensive error handling:

- **Missing .design/**: Prompts user to run `/design-init`
- **Framework mismatch**: Verifies config.json framework setting
- **No tokens**: Checks for tokens in .design/tokens/
- **Transform failure**: Logs error details to .design/logs/

## Output

All wrappers follow the same output structure:

```
.design/extracted-code/{framework}/
├── tokens/
│   ├── colors.{ext}
│   ├── typography.{ext}
│   ├── spacing.{ext}
│   └── index.{ext}
└── components/ (if applicable)
```

## Template

`transform-wrapper-template.js` serves as the base template for all wrappers. To create a new wrapper:

1. Copy template: `cp transform-wrapper-template.js transform-{framework}.js`
2. Replace variables: `{FRAMEWORK}`, `{FRAMEWORK_DISPLAY}`, `{NEXT_STEPS_CODE}`
3. Make executable: `chmod +x transform-{framework}.js`
4. Test: `node transform-{framework}.js`

## Execution Flow

```
User: /transform-react
  ↓
skill.md (instructions for Claude)
  ↓
Claude executes: node ./.claude/wrappers/transform-react.js
  ↓
Wrapper reads config + tokens
  ↓
Wrapper calls packages/@design-bridge/transformers/optimizers/react-optimizer.js
  ↓
Optimizer transforms tokens → React code
  ↓
Wrapper writes output + updates metadata
  ↓
Success message to user
```

## Testing

Test a wrapper directly:

```bash
# Ensure .design/ structure exists
ls .design/config.json .design/tokens/

# Run wrapper
node ./.claude/wrappers/transform-react.js

# Verify output
ls .design/extracted-code/react/
```

## Maintenance

All wrappers are generated from `transform-wrapper-template.js`. To update all wrappers:

1. Modify template
2. Regenerate wrappers using creation script
3. Test each wrapper
4. Commit changes

## Integration with Skills

Skills reference wrappers in Step 4 of their instructions:

```markdown
### Step 4: Execute Transformation

Run the transformation wrapper:

```bash
node ./.claude/wrappers/transform-{framework}.js
```
```

This allows Claude Code to execute the transformation programmatically.
