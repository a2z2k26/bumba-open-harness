---
name: design-transform-react
description: Transform design tokens and components into production-ready React code with automatic batch processing
allowed-tools: Read, Write, Bash, Glob
---

# /transform-react - Transform Design Tokens to React

Transform extracted design tokens and ALL components into production-ready React code.

## Purpose

This command transforms your `.design/` directory into React-compatible code:
- **Design Tokens** → TypeScript constants with CSS-in-JS
- **ALL Components** → React + TypeScript components (batch processed)
- **Theme System** → ThemeProvider with useTheme hook
- **Documentation** → Auto-generated STYLES.md brand guide

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-react
```

With options:
```
/transform-react --typescript --styled-components
```

Force regeneration:
```
/transform-react --force
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--typescript` | Generate TypeScript definitions | Auto-detected |
| `--css-modules` | Use CSS Modules instead of CSS-in-JS | false |
| `--styled-components` | Generate styled-components theme | true |
| `--emotion` | Generate Emotion theme | false |
| `--output <path>` | Custom output directory | ./src/design-system |
| `--force` | Regenerate even if unchanged | false |
| `--watch` | Watch for token changes | false |
| `--storybook` | Generate Storybook stories | true |
| `--skip-styles-md` | Skip STYLES.md generation | false |

---

## ⭐ Enhanced Transformation Pipeline (v2.0)

This skill uses an **enhanced transformation pipeline** with four key improvements:

### 1. Hybrid Token System 🆕
**Manual tokens take PRIORITY** over extracted tokens with graceful fallback:

```
Order: Manual Tokens (priority) → Component Extraction (fallback) → Merge → Transform
```

**How it works:**
1. Checks `.design/tokens/` for manually created JSON files
2. Extracts tokens from components (as fallback)
3. Merges with manual tokens taking priority
4. Warns about overrides and conflicts

**Example:**
```json
// .design/tokens/brand-colors.json (you create this)
{
  "colors": {
    "primary": "#007bff",     // ← YOUR brand color (takes priority)
    "secondary": "#6c757d"
  }
}
```

Component has `primary: "#00aa00"` but YOUR manual `#007bff` is used!

### 2. Token-First Architecture
Tokens are **always** extracted and transformed BEFORE components to prevent missing dependency errors.

```
Complete Flow: Manual Load → Component Extract → Merge → Transform → Components
```

### 3. JavaScript Identifier Sanitization
All Figma property names are automatically sanitized to valid JavaScript identifiers:
- Removes spaces and special characters
- Handles reserved keywords
- Ensures valid camelCase/PascalCase

**Example:** `"Property 1"` → sanitized identifier

### 4. Smart Variant Detection ⭐⭐⭐
Automatically detects semantic property names from value patterns:

| Figma Name | Values | Detected Prop |
|------------|--------|---------------|
| Property 1 | primary, secondary, tertiary | `variant` |
| Property 2 | small, medium, large | `size` |
| State | active, disabled, hover | `state` |
| Property 3 | filled, outlined, ghost | `appearance` |

**Benefits:**
- ✅ No more syntax errors from invalid identifiers
- ✅ Meaningful prop names instead of `property1`
- ✅ Automatic validation of token dependencies
- ✅ Clear warnings for missing tokens

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Extract Components**: Ensure `.design/components/` contains components

---

## Step 1: Validate Environment

Check that all prerequisites are met:

```javascript
// Verify .design/ structure exists
const designDir = path.join(process.cwd(), '.design');
if (!fs.existsSync(designDir)) {
  console.error('Error: .design/ directory not found');
  console.error('Please run /design-init first');
  process.exit(1);
}

// Count components and tokens
const componentsDir = path.join(designDir, 'components');
const tokensDir = path.join(designDir, 'tokens');

const componentsCount = fs.existsSync(componentsDir)
  ? fs.readdirSync(componentsDir).filter(f => f.endsWith('.json')).length
  : 0;

const tokenFiles = fs.existsSync(tokensDir)
  ? fs.readdirSync(tokensDir).filter(f => f.endsWith('.json'))
  : [];

console.log(`Found ${componentsCount} components to transform`);
console.log(`Found ${tokenFiles.length} token files`);
```

---

## Step 2: Load Design Tokens

Load all token files from `.design/tokens/`:

Read the primary token file (usually named after the Figma file):
- `[Design System Name].json` (contains all token categories)

Or individual token files:
- `colors.json` - Color palette and semantic colors
- `typography.json` - Font families, sizes, weights
- `spacing.json` - Spacing scale values
- `shadows.json` - Box shadow definitions
- `borders.json` - Border radii and widths

Extract all token categories from the files.

---

## Step 3: Transform Design Tokens

Generate TypeScript files for each token category:

**Create output directory:**
```bash
mkdir -p src/design-system/tokens
```

**Generate token files:**

1. `colors.ts` - Color constants with TypeScript types
2. `typography.ts` - Typography styles with interfaces
3. `spacing.ts` - Spacing scale with type unions
4. `effects.ts` - Shadow effects with helper functions
5. `borderRadius.ts` - Border radius values
6. `index.ts` - Barrel export for all tokens

**Example Output:**

```typescript
// src/design-system/tokens/colors.ts
export const colors = {
  imagePlaceholder: '#e3e3e3',
  primary: '#007bff',
  secondary: '#6c757d',
} as const;

export type ColorToken = keyof typeof colors;

export const getColor = (token: ColorToken): string => colors[token];
```

---

## Step 4: Transform ALL Components (Batch Processing)

**IMPORTANT:** This step automatically transforms ALL components at once.

### Automatic Batch Transformation

Create and execute transformation script:

```javascript
#!/usr/bin/env node
/**
 * Batch Component Transformation Script
 * Automatically transforms all Figma components to React
 */

const fs = require('fs');
const path = require('path');

const COMPONENTS_DIR = path.join(process.cwd(), '.design/components');
const OUTPUT_DIR = path.join(process.cwd(), 'src/design-system/components');

// Helper: Convert to PascalCase
function toPascalCase(str) {
  return str
    .replace(/[-_]([a-z])/g, (_, letter) => letter.toUpperCase())
    .replace(/^[a-z]/, letter => letter.toUpperCase());
}

// Generate React component from Figma JSON
function generateComponent(componentData, componentName) {
  const pascalName = toPascalCase(componentName);
  const hasVariants = componentData.variants && Object.keys(componentData.variants).length > 0;

  // Extract variant props
  let variantProps = '';
  let defaultProps = '';

  if (hasVariants) {
    variantProps = Object.entries(componentData.variants).map(([key, values]) => {
      const propName = key.toLowerCase().replace(/\s+/g, '');
      const unionType = values.map(v => `'${v.toLowerCase()}'`).join(' | ');
      const defaultValue = values[0] ? `'${values[0].toLowerCase()}'` : "''";

      defaultProps += `  ${propName} = ${defaultValue},\n`;

      return `  /**
   * ${key} variant
   */
  ${propName}?: ${unionType};`;
    }).join('\n\n');
  }

  const template = `/**
 * ${pascalName} Component
 * Generated from Figma Design System
 * Extracted: ${componentData.source?.extractedAt || new Date().toISOString()}
 */

import React from 'react';
import styled from 'styled-components';
import { useTheme } from '../theme';

export interface ${pascalName}Props {
${variantProps ? variantProps + '\n\n' : ''}  /**
   * Component content
   */
  children?: React.ReactNode;
}

const Styled${pascalName} = styled.div<${pascalName}Props>\`
  /* Base styles */
  display: flex;
  font-family: \${({ theme }) => theme.typography.bodyBase.fontFamily};

  /* Add component-specific styles here */
\`;

/**
 * ${pascalName} component
 *
 * @example
 * \`\`\`tsx
 * <${pascalName}${hasVariants ? ' variant="default"' : ''}>
 *   Content
 * </${pascalName}>
 * \`\`\`
 */
export const ${pascalName}: React.FC<${pascalName}Props> = ({
${defaultProps ? defaultProps : ''}  children,
  ...props
}) => {
  return (
    <Styled${pascalName} {...props}>
      {children}
    </Styled${pascalName}>
  );
};

${pascalName}.displayName = '${pascalName}';
`;

  return template;
}

// Main transformation
async function transformAllComponents() {
  console.log('🚀 Starting component transformation...\n');

  if (!fs.existsSync(COMPONENTS_DIR)) {
    console.error('❌ Components directory not found:', COMPONENTS_DIR);
    process.exit(1);
  }

  const files = fs.readdirSync(COMPONENTS_DIR).filter(f => f.endsWith('.json'));
  console.log(`📦 Found ${files.length} components to transform\n`);

  // Ensure output directory exists
  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  const componentExports = [];

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const componentName = file.replace('.json', '');
    const pascalName = toPascalCase(componentName);

    try {
      const componentPath = path.join(COMPONENTS_DIR, file);
      const componentData = JSON.parse(fs.readFileSync(componentPath, 'utf8'));
      const componentCode = generateComponent(componentData, componentName);
      const outputPath = path.join(OUTPUT_DIR, `${pascalName}.tsx`);

      fs.writeFileSync(outputPath, componentCode);
      componentExports.push({ name: pascalName, file: pascalName });

      console.log(`✅ [${i + 1}/${files.length}] Transformed: ${pascalName}`);
    } catch (error) {
      console.error(`❌ Error transforming ${componentName}:`, error.message);
    }
  }

  // Generate index.ts
  console.log('\n📝 Generating component index...');
  const indexContent = `/**
 * Design System Components
 * Total components: ${componentExports.length}
 */

${componentExports.map(c =>
  `export { ${c.name} } from './${c.file}';\nexport type { ${c.name}Props } from './${c.file}';`
).join('\n')}
`;

  fs.writeFileSync(path.join(OUTPUT_DIR, 'index.ts'), indexContent);
  console.log('✅ Component index generated\n');

  console.log('═══════════════════════════════════════');
  console.log('🎉 Transformation Complete!');
  console.log('═══════════════════════════════════════');
  console.log(`📊 Components transformed: ${componentExports.length}`);
  console.log(`📁 Output directory: ${OUTPUT_DIR}\n`);

  return componentExports.length;
}

// Execute
if (require.main === module) {
  transformAllComponents().catch(console.error);
}

module.exports = { transformAllComponents };
```

**Execute the batch transformation:**

```bash
node transform-all-components.js
```

**Expected Output:**
```
🚀 Starting component transformation...

📦 Found 112 components to transform

✅ [1/112] Transformed: Button
✅ [2/112] Transformed: Avatar
✅ [3/112] Transformed: Card
...
✅ [112/112] Transformed: Tooltip

📝 Generating component index...
✅ Component index generated

═══════════════════════════════════════
🎉 Transformation Complete!
═══════════════════════════════════════
📊 Components transformed: 112
📁 Output directory: src/design-system/components
```

### Why Batch Processing?

| Benefit | Impact |
|---------|--------|
| **Speed** | Transform 100+ components in seconds |
| **Consistency** | All components use identical patterns |
| **Scalability** | Works with any number of components |
| **Maintainability** | Easy to re-run when design updates |

---

## Step 5: Create Theme System

Generate theme infrastructure:

**Create theme directory:**
```bash
mkdir -p src/design-system/theme
```

**Generate theme files:**

1. **theme.ts** - Combined theme object
   ```typescript
   import { colors } from '../tokens/colors';
   import { typography } from '../tokens/typography';
   import { spacing } from '../tokens/spacing';
   import { effects } from '../tokens/effects';
   import { borderRadius } from '../tokens/borderRadius';

   export const theme = {
     colors,
     typography,
     spacing,
     effects,
     borderRadius,
   } as const;

   export type Theme = typeof theme;
   ```

2. **ThemeProvider.tsx** - React Context provider
   ```typescript
   import React, { createContext, useContext, ReactNode } from 'react';
   import { theme, Theme } from './theme';

   const ThemeContext = createContext<Theme>(theme);

   export interface ThemeProviderProps {
     children: ReactNode;
     customTheme?: Partial<Theme>;
   }

   export const ThemeProvider: React.FC<ThemeProviderProps> = ({
     children,
     customTheme
   }) => {
     const mergedTheme = customTheme ? { ...theme, ...customTheme } : theme;

     return (
       <ThemeContext.Provider value={mergedTheme}>
         {children}
       </ThemeContext.Provider>
     );
   };

   export const useTheme = (): Theme => {
     const context = useContext(ThemeContext);
     if (!context) {
       throw new Error('useTheme must be used within a ThemeProvider');
     }
     return context;
   };
   ```

3. **index.ts** - Barrel export
   ```typescript
   export { theme } from './theme';
   export type { Theme } from './theme';
   export { ThemeProvider, useTheme } from './ThemeProvider';
   export type { ThemeProviderProps } from './ThemeProvider';
   ```

---

## Step 6: Generate Storybook Stories (Optional)

If `--storybook` flag is enabled (default):

Create story files for key components:

```bash
mkdir -p src/stories
```

Generate stories:
- `Button.stories.tsx` - Button component variants
- `Avatar.stories.tsx` - Avatar configurations
- `Card.stories.tsx` - Card layouts
- `DesignTokens.stories.tsx` - Token documentation

---

## Step 7: Generate STYLES.md Brand Guide (Automatic)

**IMPORTANT:** This step runs automatically after transformation.

Generate comprehensive brand style guide:

```bash
node server/styles-md-generator.js
```

**What it creates:**

`.design/STYLES.md` containing:
- Complete color palette with usage guidelines
- Typography scale with font stacks
- Spacing system reference
- Shadow effects catalog
- Border radius values
- Complete component list with variants
- CSS variables reference
- Usage best practices

**Output:**
```
✓ Generated: /path/to/project/.design/STYLES.md
  Colors: 1
  Typography: 16
  Spacing: 5
  Effects: 12
  Components: 112
```

**Why Auto-generate STYLES.md?**

1. ✅ **Documentation completeness** - Design system includes reference docs
2. ✅ **AI context** - Perfect input for AI-assisted design work
3. ✅ **Team onboarding** - Single source of truth for new developers
4. ✅ **Design QA** - Easy to review what was extracted/transformed
5. ✅ **Sync verification** - Confirms transformation captured everything

**To skip STYLES.md generation:**
```
/transform-react --skip-styles-md
```

---

## Step 8: Update Metadata

Update `.design/metadata.json` with transformation details:

```javascript
const metadata = JSON.parse(fs.readFileSync('.design/metadata.json'));

metadata.lastTransform = new Date().toISOString();
metadata.transformHistory.push({
  timestamp: new Date().toISOString(),
  framework: 'react',
  tokensTransformed: totalTokens,
  componentsTransformed: totalComponents,
  outputPath: 'src/design-system',
  storybookGenerated: true,
  stylesMdGenerated: !skipStylesMd
});

fs.writeFileSync('.design/metadata.json', JSON.stringify(metadata, null, 2));
```

---

## Complete Output Structure

```
src/design-system/
├── tokens/                    (6 files)
│   ├── colors.ts
│   ├── typography.ts
│   ├── spacing.ts
│   ├── effects.ts
│   ├── borderRadius.ts
│   └── index.ts
├── theme/                     (3 files)
│   ├── theme.ts
│   ├── ThemeProvider.tsx
│   └── index.ts
├── components/                (113 files)
│   ├── [ALL COMPONENTS].tsx  ← Batch transformed
│   └── index.ts
├── index.ts
└── README.md

.design/
├── STYLES.md                  ← Auto-generated
├── metadata.json              ← Updated
└── config.json

src/stories/                   (4 files)
└── *.stories.tsx
```

---

## Example Workflow

```bash
# 1. Initialize Design Bridge (one-time)
/design-init

# 2. Extract from Figma (using plugin)
# → Creates .design/tokens/*.json
# → Creates .design/components/*.json

# 3. Transform to React (runs ALL steps automatically)
/transform-react

# Behind the scenes (automatic):
# ✅ Step 1: Validate environment
# ✅ Step 2: Load all tokens
# ✅ Step 3: Transform tokens to TypeScript
# ✅ Step 4: Batch transform ALL components
# ✅ Step 5: Create theme system
# ✅ Step 6: Generate Storybook stories
# ✅ Step 7: Auto-generate STYLES.md
# ✅ Step 8: Update metadata

# Result: Complete design system ready to use!
```

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

### "Error: No tokens found"
Extract tokens from Figma using the Figma plugin or manually add tokens to `.design/tokens/`.

### "Error: No components found"
Extract components from Figma or verify `.design/components/` contains JSON files.

### "Error: Project configured for different framework"
Update `.design/config.json` to set `project.framework` to `"react"`.

### "STYLES.md not generated"
- Check that `server/styles-md-generator.js` exists
- Run manually: `node server/styles-md-generator.js`
- Use `--skip-styles-md` if not needed

### "Batch transformation failed"
- Verify component JSON files are valid
- Check Node.js version (14+ required)
- Review error logs for specific component issues

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-generate-styles` - Manually regenerate STYLES.md
- `/transform-vue` - Transform to Vue
- `/transform-angular` - Transform to Angular
