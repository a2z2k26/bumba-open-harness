# design-layout-to-jsx - Transform Figma Layouts to React/JSX Components

Generate production-ready React/JSX components from extracted Figma layout data.

## Purpose

Convert Figma layouts into React components with:
- React inline styles (camelCase)
- TypeScript interfaces
- Design system component imports
- Production-ready code
- .tsx/.jsx output files

## Prerequisites

- Layout data extracted from Figma (`.design/layouts/`)
- Component registry populated (`.design/componentRegistry.json`)
- Design system components available for imports

## Usage

### Transform Single Layout

```bash
node ~/.claude/shared-modules/design-system/layout-to-jsx-transformer.js \
  --layout=PricingPage \
  --typescript \
  --export-default
```

### Transform All Layouts

```bash
for layout in .design/layouts/*.json; do
  node ~/.claude/shared-modules/design-system/layout-to-jsx-transformer.js \
    --layout=$(basename "$layout" .json) \
    --typescript
done
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--layout` | (required) | Layout name or file path |
| `--typescript` | `true` | Generate TypeScript (.tsx) |
| `--import-path` | `'../components'` | Path to design system components |
| `--export-default` | `true` | Use default export |
| `--output-dir` | `.design/extracted-code/react/layouts` | Output directory |

## Output

### File Structure

```
.design/extracted-code/react/layouts/
├── PricingPage.tsx
├── Homepage.tsx
└── DashboardLayout.tsx
```

### Generated Component Example

```tsx
/**
 * PricingPage Layout Component
 * Generated from Figma layout extraction
 *
 * This component uses transformed design system components.
 * Generated: 2026-01-08T...
 */

import React from 'react';
import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { PricingTier } from '../components/PricingTier';

export interface PricingPageProps {
  // Add custom props here if needed
}

const PricingPage: React.FC<PricingPageProps> = (props) => {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '32px',
      padding: '64px 32px 64px 32px'
    }}>
      <PricingTier primary={true} />
      <PricingTier />
      <PricingTier featured={true} />
    </div>
  );
};

PricingPage.displayName = 'PricingPage';

export default PricingPage;
```

## Key Features

### React Inline Styles

Figma auto-layout properties convert to React style objects:

```javascript
{
  display: 'flex',
  flexDirection: 'column',  // camelCase
  justifyContent: 'center',
  alignItems: 'flex-start',
  gap: '16px',
  padding: '24px 16px 24px 16px'
}
```

### Component References

Nested components are imported and rendered:

```tsx
import { Button } from '../components/Button';
import { Card } from '../components/Card';

// Usage with props
<Button primary={true} />
<Card title="Welcome" />
```

### TypeScript Support

Generated components include TypeScript interfaces:

```tsx
export interface LayoutNameProps {
  // Add custom props here if needed
}

const LayoutName: React.FC<LayoutNameProps> = (props) => {
  // ...
};
```

## Differences from design-layout-to-html

| Aspect | HTML | JSX |
|--------|------|-----|
| Purpose | Visual reference | Production code |
| Output | `.html` files | `.tsx`/`.jsx` files |
| Styling | CSS strings | React inline styles |
| Components | HTML comments | React component imports |
| Validation | 3-pass visual check | Ready for use |
| Integration | Standalone preview | Integrates with app |

## Workflow

### 1. Extract Layout from Figma

Use the Figma plugin to extract layout data:

```
Figma Plugin → Extract Layout
→ Saves to .design/layouts/pricing-page.json
```

### 2. Transform to JSX

```bash
node ~/.claude/shared-modules/design-system/layout-to-jsx-transformer.js \
  --layout=pricing-page
```

### 3. Import in Application

```tsx
import PricingPage from '@/design-system/layouts/PricingPage';

export default function Pricing() {
  return <PricingPage />;
}
```

### 4. Customize as Needed

The generated component is a starting point. You can:
- Add custom props
- Connect to state management
- Add event handlers
- Override styles
- Add animations

## Component Resolution

The transformer resolves component references from the registry:

```json
{
  "type": "INSTANCE",
  "componentRef": {
    "name": "Button",
    "props": {
      "primary": true,
      "text": "Get Started"
    }
  }
}
```

Becomes:

```tsx
<Button primary={true} text="Get Started" />
```

## Programmatic API

### transformLayoutToJSX

```javascript
const { transformLayoutToJSX } = require('layout-to-jsx-transformer');

const result = await transformLayoutToJSX(layoutData, {
  outputDir: '.design/extracted-code/react/layouts',
  typescript: true,
  importPath: '../components',
  exportDefault: true
});

// result = {
//   success: true,
//   layoutName: 'PricingPage',
//   componentName: 'PricingPage',
//   outputPath: '.design/extracted-code/react/layouts/PricingPage.tsx',
//   fileExtension: 'tsx',
//   dependencies: ['Button', 'Card', 'PricingTier'],
//   typescript: true
// }
```

### transformLayoutFile

```javascript
const { transformLayoutFile } = require('layout-to-jsx-transformer');

const result = await transformLayoutFile(
  '.design/layouts/pricing-page.json',
  {
    typescript: true,
    exportDefault: true
  }
);
```

## Troubleshooting

### Missing Component Imports

**Problem**: Generated JSX references components that don't exist

**Solution**: Transform missing components first:

```bash
# Check dependencies
cat .design/extracted-code/react/layouts/PricingPage.tsx | grep "import {"

# Transform missing components
node ~/.claude/wrappers/transform-react.js --component=PricingTier
```

### Invalid Component Names

**Problem**: Component names don't match imports

**Solution**: Verify canonical names in registry:

```bash
cat .design/componentRegistry.json | jq '.components | keys'
```

### Style Conflicts

**Problem**: React inline styles override design system styles

**Solution**: Use CSS modules or styled-components instead:

```tsx
// Option 1: CSS Modules
import styles from './PricingPage.module.css';
<div className={styles.container}>

// Option 2: Styled Components
import styled from 'styled-components';
const Container = styled.div`...`;
```

## Related Commands

- `/design-extract` - Extract components and layouts from Figma
- `/design-layout-to-html` - Generate HTML reference files
- `/design-transform-react` - Transform individual components
- `/design-generate-styles` - Generate design tokens

## Notes

- Generated components are production-ready but should be reviewed
- Customize imports path to match your project structure
- Add prop validation (PropTypes or TypeScript) as needed
- Consider extracting styles to CSS modules for better organization
- Test components in Storybook before integrating into app
