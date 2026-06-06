# design layout-to-html

## Purpose

Transforms an extracted Figma layout into production-ready framework code through a validated HTML intermediate step. This is a **single, unified command** that handles the complete pipeline from layout JSON to final framework output.

## Command

```
design layout-to-html <layout-name>
```

No flags. The skill automatically:
- Uses both layout JSON and screenshot as reference
- Reads project framework from `.design/config.json`
- Validates output through 3-pass Chrome DevTools comparison
- Generates final framework code using existing transformed components
- Previews result in browser

## Prerequisites

1. **Layout extracted from Figma** - Run extraction from Figma plugin first
2. **Components transformed** - Components referenced in layout should be transformed to target framework
3. **Chrome DevTools MCP** - Required for visual validation loop

## Input

The skill expects:
```
.design/layouts/[layout-name]/
├── layout.json       # Extracted layout structure
└── screenshot.png    # Figma screenshot reference
```

## Pipeline Stages

The layout goes through 5 stages tracked in `.design/layoutManifest.json`:

| Stage | Status | Artifacts Created |
|-------|--------|-------------------|
| 1 | `extracted` | `layout.json`, `screenshot.png` (from Figma) |
| 2 | `screenshot` | Original screenshot validated/present |
| 3 | `html-generated` | `reference.html` created |
| 4 | `validated` | `reference-validated.png`, `validation-report.json` |
| 5 | `code-generated` | `[LayoutName].[ext]` in framework directory |

### Screenshot Storage Convention

Screenshots are stored in a predictable location for each stage:

```
.design/layouts/[layout-name]/
├── screenshot.png            # Stage 1-2: Original Figma reference
├── pass1-browser.png         # Stage 4: Pass 1 browser capture
├── pass2-browser.png         # Stage 4: Pass 2 browser capture
├── pass3-browser.png         # Stage 4: Pass 3 browser capture
└── reference-validated.png   # Stage 4: Final validated screenshot
```

The system uses these paths consistently:
- **Figma screenshot**: Always `screenshot.png` in layout directory
- **Pass screenshots**: `pass[N]-browser.png` pattern
- **Final validated**: Always `reference-validated.png`

## Output

After completion:
```
.design/layouts/[layout-name]/
├── layout.json                    # Original + metadata updates
├── screenshot.png                 # Figma reference
├── reference.html                 # Validated HTML intermediate
├── reference-validated.png        # Browser screenshot after validation
├── validation-report.json         # 3-pass diff report
└── ...

.design/extracted-code/[framework]/layouts/
└── [LayoutName].[ext]             # Final framework code
```

## Workflow

### Phase 1: Context Loading

1. Load `.design/config.json` to determine target framework
2. Load `.design/layouts/[layout-name]/layout.json`
3. Load `.design/layouts/[layout-name]/screenshot.png`
4. Load `.design/componentRegistry.json` to find component imports

### Phase 2: Component Resolution

For each `componentRef` in the layout:

1. **Recognize** component name from layout JSON
2. **Lookup** in `.design/componentRegistry.json`
3. **Locate** transformed code in `.design/extracted-code/[framework]/`
4. **DO NOT REBUILD** - Use existing transformed component

```
Layout JSON: componentRef.name = "PrimaryButton"
                    ↓
Registry: PrimaryButton → source: figma, transformedTo: [react]
                    ↓
Import: .design/extracted-code/react/PrimaryButton.tsx
                    ↓
Use in layout composition (not rebuilt)
```

### Phase 3: HTML Reference Generation

Generate `reference.html` using:
- Layout structure from JSON (flex direction, gap, padding, alignment)
- Component placeholders with actual dimensions
- Figma screenshot embedded for comparison

### Phase 4: 3-Pass Visual Validation (Chrome DevTools MCP + LayoutValidator)

The validation loop uses two components:
1. **Chrome DevTools MCP** - Browser automation for screenshots
2. **LayoutValidator** - State management and report generation

```javascript
// Initialize validator (already done by CLI)
const { LayoutValidator } = require('./layout-validator');
const validator = new LayoutValidator(projectPath);
const session = validator.startValidation(layoutName, { framework });
```

**Pass 1: Initial Render**
```javascript
// 1. Start pass
validator.beginPass(1);

// 2. Load and resize browser
mcp__chrome-devtools__navigate_page({ url: 'file://.../reference.html' });
mcp__chrome-devtools__resize_page({ width: session.dimensions.width, height: session.dimensions.height });

// 3. Capture screenshot
mcp__chrome-devtools__take_screenshot({ filePath: '.../pass1-browser.png' });
validator.capturePass('.../pass1-browser.png');

// 4. Compare screenshots visually and record discrepancies
validator.recordDiscrepancy({
  element: 'container',
  issue: 'gap',
  expected: '24px',
  actual: '16px',
  severity: 'medium'
});

// 5. Complete pass
validator.completePass({ parityEstimate: '85%' });
```

**Pass 2: Refinement**
```javascript
// 1. Start pass
validator.beginPass(2);

// 2. Apply fixes to reference.html (edit inline styles)
// ... edit HTML file ...

// 3. Record fix
validator.applyFix({
  element: 'container',
  property: 'gap',
  oldValue: '16px',
  newValue: '24px',
  discrepancyId: 'disc-1-1'  // Links to discrepancy from Pass 1
});

// 4. Reload and capture
mcp__chrome-devtools__navigate_page({ type: 'reload' });
mcp__chrome-devtools__take_screenshot({ filePath: '.../pass2-browser.png' });
validator.capturePass('.../pass2-browser.png');

// 5. Compare again, record any remaining issues
// 6. Complete pass
validator.completePass({ parityEstimate: '95%' });
```

**Pass 3: Final Polish**
```javascript
// 1. Start pass
validator.beginPass(3);

// 2. Apply any final tweaks
// 3. Capture final screenshot
mcp__chrome-devtools__take_screenshot({ filePath: '.../reference-validated.png' });
validator.capturePass('.../reference-validated.png');

// 4. Complete pass
validator.completePass({ parityEstimate: '98%' });

// 5. Generate final report
const report = validator.generateReport();
// Saves to .../validation-report.json
```

**Comparison Checklist**
```javascript
const checklist = validator.getComparisonChecklist();
// Returns structured checklist for visual comparison:
// - structuralChecks: dimensions, flex direction, element count
// - spacingChecks: gap, padding, margin, alignment
// - sizingChecks: component widths/heights
// - visualChecks: colors, borders, overflow
// - tolerances: major (>10px), medium (5-10px), minor (<5px)
```

### Phase 5: Framework Code Generation

Using the validated HTML structure as proven reference:

1. Read validated CSS (now confirmed accurate)
2. Generate framework-specific layout code
3. Import existing transformed components (not rebuild)
4. Apply validated spatial structure
5. Save to `.design/extracted-code/[framework]/layouts/`

### Phase 6: Preview

Open final HTML in browser for visual confirmation.

## Validation Report Structure

```json
{
  "layoutName": "LoginScreen",
  "framework": "react",
  "passes": [
    {
      "pass": 1,
      "discrepancies": [
        { "element": "container", "issue": "gap", "expected": "24px", "actual": "16px" },
        { "element": "Button", "issue": "width", "expected": "280px", "actual": "100%" }
      ],
      "fixesApplied": []
    },
    {
      "pass": 2,
      "discrepancies": [
        { "element": "Button", "issue": "width", "expected": "280px", "actual": "280px", "resolved": true }
      ],
      "fixesApplied": ["gap: 24px", "width: 280px"]
    },
    {
      "pass": 3,
      "discrepancies": [],
      "fixesApplied": [],
      "status": "validated"
    }
  ],
  "finalParity": "98%",
  "outputPath": ".design/extracted-code/react/layouts/LoginScreen.tsx"
}
```

## Component Registry Integration

The skill reads from `.design/componentRegistry.json`:

```json
{
  "components": [
    {
      "id": "figma-btn-123",
      "name": "PrimaryButton",
      "source": "figma",
      "transformedTo": ["react", "vue"],
      "outputPaths": {
        "react": ".design/extracted-code/react/PrimaryButton.tsx"
      }
    }
  ]
}
```

When generating layout code:
- Components with `transformedTo` including target framework → import and use
- Components missing transformation → add TODO comment, warn user

## Framework Output Examples

### React
```tsx
import React from 'react';
import { PrimaryButton } from '../PrimaryButton';
import { TextField } from '../TextField';
import { Logo } from '../Logo';

export const LoginScreen: React.FC = () => {
  return (
    <div style={styles.container}>
      <Logo />
      <TextField />
      <PrimaryButton />
    </div>
  );
};

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '24px',
    padding: '48px 0',
  },
};
```

### SwiftUI
```swift
import SwiftUI

struct LoginScreen: View {
    var body: some View {
        VStack(alignment: .center, spacing: 24) {
            Logo()
            TextField()
            PrimaryButton()
        }
        .padding(.vertical, 48)
    }
}
```

### Flutter
```dart
import 'package:flutter/material.dart';

class LoginScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Logo(),
        SizedBox(height: 24),
        TextField(),
        SizedBox(height: 24),
        PrimaryButton(),
      ],
    );
  }
}
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Layout not found | Error with list of available layouts |
| Screenshot missing | Warn, proceed without visual validation |
| Component not transformed | TODO comment in output, warning to user |
| Chrome DevTools unavailable | Skip validation loop, generate best-effort |
| Config missing framework | Default to React |

## Implementation

- **Layout Transformer**: `server/layout-transformer.js`
- **HTML Generator**: `server/layout-to-html-transformer.js`
- **Layout Validator**: `server/layout-validator.js`
- **Design Structure**: `server/design-structure.js`
- **CLI Command**: `design layout-to-html` in `server/cli.js`

## Key Constraints

1. **NEVER rebuild components** - Always use existing transformed code
2. **ALWAYS validate visually** - 3-pass loop ensures accuracy
3. **ALWAYS read framework from config** - No flags, automatic detection
4. **ALWAYS preview** - Browser opens on completion
5. **ALWAYS save artifacts** - Validation report, validated screenshot, final code
