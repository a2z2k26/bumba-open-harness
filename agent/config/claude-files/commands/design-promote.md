---
name: design-promote
description: Promote staged components and layouts from staging to production source directory
allowed-tools: Read, Write, Bash, Glob, Grep
---

# /promote - Promote Staged Design Code to Production

Promote staged components and layouts from `.design/extracted-code/` to your production source directory.

## Purpose

This command copies validated, staged code from the Design Bridge staging area to your project's source code:
- Promotes generated components to `src/design-system/`
- Maintains registry tracking in both locations
- Supports dry-run mode for preview
- Handles framework-specific output paths

## Usage

Basic usage (promotes all staged code for default framework):
```
/promote
```

Promote specific framework:
```
/promote react
```

Promote only components:
```
/promote react components
```

Promote only layouts:
```
/promote react layouts
```

Preview changes without copying:
```
/promote --dry-run
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `<framework>` | Target framework (react, vue, etc.) | From config |
| `<type>` | What to promote (components, layouts, tokens) | all |
| `--dry-run` | Preview what would be copied | false |
| `--force` | Overwrite existing files without prompt | false |
| `--dest <path>` | Custom destination directory | ./src/design-system |
| `--backup` | Create backup before overwriting | true |

---

## Prerequisites

Before running this command:

1. **Run Transform**: Execute `/transform-<framework>` first
2. **Verify Staged Code**: Check `.design/extracted-code/` has generated files
3. **Review Generated Code**: Optionally inspect staged code before promoting

---

## Step 1: Validate Staging Area

Check that staged code exists:

```javascript
const fs = require('fs');
const path = require('path');

// Parse arguments
const args = process.argv.slice(2);
const framework = args.find(a => !a.startsWith('--')) || 'react';
const type = args.find((a, i) => i > 0 && !a.startsWith('--')) || 'all';
const dryRun = args.includes('--dry-run');
const force = args.includes('--force');
const destArg = args.find((a, i, arr) => arr[i - 1] === '--dest');

// Source paths
const stagingRoot = '.design/extracted-code';
const frameworkDir = path.join(stagingRoot, framework);

// Validate staging exists
if (!fs.existsSync(stagingRoot)) {
  console.error('ERROR: Staging directory not found: .design/extracted-code/');
  console.error('Run /transform-<framework> first to generate code.');
  process.exit(1);
}

if (!fs.existsSync(frameworkDir)) {
  console.error(`ERROR: No staged code for framework: ${framework}`);
  console.error(`Available frameworks: ${fs.readdirSync(stagingRoot).join(', ')}`);
  process.exit(1);
}

console.log(`Framework: ${framework}`);
console.log(`Type: ${type}`);
console.log(`Mode: ${dryRun ? 'DRY RUN' : 'PROMOTE'}`);
```

---

## Step 2: Collect Files to Promote

Build list of files to copy:

```javascript
function collectFiles(dir, base = '') {
  const files = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const relativePath = path.join(base, entry.name);
    const fullPath = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      files.push(...collectFiles(fullPath, relativePath));
    } else {
      files.push({
        source: fullPath,
        relative: relativePath
      });
    }
  }

  return files;
}

// Get files to promote based on type
let filesToPromote = [];

if (type === 'all' || type === 'components') {
  const componentsDir = path.join(frameworkDir, 'components');
  if (fs.existsSync(componentsDir)) {
    const componentFiles = collectFiles(componentsDir);
    filesToPromote.push(...componentFiles.map(f => ({
      ...f,
      category: 'components'
    })));
  }
}

if (type === 'all' || type === 'layouts') {
  const layoutsDir = path.join(frameworkDir, 'layouts');
  if (fs.existsSync(layoutsDir)) {
    const layoutFiles = collectFiles(layoutsDir);
    filesToPromote.push(...layoutFiles.map(f => ({
      ...f,
      category: 'layouts'
    })));
  }
}

if (type === 'all' || type === 'tokens') {
  const tokensDir = path.join(frameworkDir, 'tokens');
  if (fs.existsSync(tokensDir)) {
    const tokenFiles = collectFiles(tokensDir);
    filesToPromote.push(...tokenFiles.map(f => ({
      ...f,
      category: 'tokens'
    })));
  }
}

console.log(`\nFiles to promote: ${filesToPromote.length}`);
```

---

## Step 3: Determine Destinations

Calculate destination paths:

```javascript
// Destination base (configurable)
const destBase = destArg || 'src/design-system';

// Map files to destinations
const promotionPlan = filesToPromote.map(file => {
  const destDir = path.join(destBase, file.category);
  const destPath = path.join(destDir, file.relative);

  return {
    source: file.source,
    destination: destPath,
    category: file.category,
    exists: fs.existsSync(destPath)
  };
});

// Show plan
console.log('\n--- PROMOTION PLAN ---');
for (const item of promotionPlan) {
  const status = item.exists ? '[OVERWRITE]' : '[NEW]';
  console.log(`  ${status} ${item.destination}`);
}

// Summarize
const newFiles = promotionPlan.filter(p => !p.exists).length;
const overwrites = promotionPlan.filter(p => p.exists).length;
console.log(`\nNew files: ${newFiles}`);
console.log(`Overwrites: ${overwrites}`);
```

---

## Step 4: Execute Promotion (if not dry-run)

Copy files to destination:

```javascript
if (dryRun) {
  console.log('\n--- DRY RUN COMPLETE ---');
  console.log('No files were copied. Remove --dry-run to execute.');
  process.exit(0);
}

// Check for overwrites if not forcing
if (overwrites > 0 && !force) {
  console.log('\nWARNING: Some files will be overwritten.');
  console.log('Use --force to proceed or --dry-run to preview.');
  // In interactive mode, would prompt user here
  // For now, proceed with backup
}

// Create backup if overwriting
const backupDir = `.design/backups/promote-${Date.now()}`;
if (overwrites > 0) {
  fs.mkdirSync(backupDir, { recursive: true });
  console.log(`\nCreating backup in: ${backupDir}`);
}

// Execute copy
let copied = 0;
let backed = 0;

for (const item of promotionPlan) {
  // Ensure destination directory exists
  const destDir = path.dirname(item.destination);
  fs.mkdirSync(destDir, { recursive: true });

  // Backup existing file
  if (item.exists) {
    const backupPath = path.join(backupDir, item.destination);
    fs.mkdirSync(path.dirname(backupPath), { recursive: true });
    fs.copyFileSync(item.destination, backupPath);
    backed++;
  }

  // Copy file
  fs.copyFileSync(item.source, item.destination);
  copied++;
}

console.log(`\nPromotion complete!`);
console.log(`  Files copied: ${copied}`);
console.log(`  Files backed up: ${backed}`);
```

---

## Step 5: Update Barrel Exports

Generate index.ts for promoted code:

```javascript
// Update barrel export in destination
const indexPath = path.join(destBase, 'index.ts');

// Collect all exported components
const exports = [];

for (const item of promotionPlan) {
  if (item.category === 'components' && item.destination.endsWith('.tsx')) {
    // Extract component name from path
    const componentName = path.basename(item.destination, '.tsx');
    if (!componentName.includes('.stories') && !componentName.includes('.test')) {
      const relativePath = './' + path.relative(destBase, item.destination)
        .replace(/\.tsx$/, '')
        .replace(/\\/g, '/');
      exports.push(`export * from '${relativePath}';`);
    }
  }
}

if (exports.length > 0) {
  const indexContent = `/**
 * Design System Exports
 * Auto-generated by Design Bridge /promote command
 * Generated: ${new Date().toISOString()}
 */

${exports.join('\n')}
`;

  fs.writeFileSync(indexPath, indexContent);
  console.log(`\nUpdated barrel export: ${indexPath}`);
}
```

---

## Step 6: Post-Promotion Summary

Display final summary:

```javascript
console.log('\n========================================');
console.log('  PROMOTION COMPLETE');
console.log('========================================');
console.log(`  Framework: ${framework}`);
console.log(`  Destination: ${destBase}`);
console.log(`  Components: ${promotionPlan.filter(p => p.category === 'components').length}`);
console.log(`  Layouts: ${promotionPlan.filter(p => p.category === 'layouts').length}`);
console.log(`  Tokens: ${promotionPlan.filter(p => p.category === 'tokens').length}`);
console.log('========================================');

console.log('\nNext steps:');
console.log('  1. Review promoted code in ' + destBase);
console.log('  2. Run npm run storybook to preview');
console.log('  3. Import from your components: import { Button } from "src/design-system"');
```

---

## Output Structure

After running `/promote react`, your project will have:

```
src/
  design-system/
    components/
      Button/
        Button.tsx
        Button.stories.tsx
        Button.module.css
      Card/
        Card.tsx
        Card.stories.tsx
    layouts/
      HomeScreen/
        HomeScreen.tsx
    tokens/
      colors.ts
      typography.ts
    index.ts          # Barrel export
```

---

## Rollback

If you need to revert:

```bash
# Backups are stored in .design/backups/
ls .design/backups/

# Copy backup back
cp -r .design/backups/promote-<timestamp>/* src/design-system/
```

---

## Related Commands

- `/design-init` - Initialize Design Bridge
- `/transform-react` - Generate React code to staging
- `/transform-vue` - Generate Vue code to staging
- `/search-design` - Search design files
