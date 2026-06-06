---
name: design-transform-web-components
description: Transform design tokens into Custom Elements with Shadow DOM and CSS custom properties
allowed-tools: Read, Write, Bash, Glob
---

# /transform-web-components - Transform Design Tokens to Web Components

Transform extracted design tokens into production-ready Web Components with CSS custom properties.

## Purpose

This command transforms your `.design/tokens/` into Web Components-compatible code:
- Native Custom Elements with Shadow DOM
- CSS custom properties (variables)
- Lit Element support (optional)
- Stencil.js support (optional)
- TypeScript definitions

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-web-components
```

With Lit Element:
```
/transform-web-components --lit
```

With Stencil.js:
```
/transform-web-components --stencil
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--lit` | Generate Lit Element components | false |
| `--stencil` | Generate Stencil.js components | false |
| `--typescript` | Generate TypeScript definitions | Auto-detected |
| `--shadow-dom` | Use Shadow DOM encapsulation | true |
| `--output <path>` | Custom output directory | ./src/design-system |
| `--force` | Regenerate even if tokens unchanged | false |

---

## ⭐ Enhanced Transformation Pipeline (v2.0)

**Hybrid Token System 🆕** - Manual tokens in `.design/tokens/*.json` take PRIORITY over extracted tokens. Automatic merging with smart variant detection and Web Components attribute conventions.

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Verify Config**: Check `.design/config.json` has `framework: "web-components"`

---

## Step 1: Validate Environment

```javascript
const designDir = path.join(process.cwd(), '.design');
if (!fs.existsSync(designDir)) {
  console.error('Error: .design/ directory not found');
  process.exit(1);
}
```

---

## Step 2: Load Design Tokens

Load all token files from `.design/tokens/`.

---

## Step 3: Execute Transformation

Run the Web Components transformation wrapper:

```bash
node .claude/wrappers/transform-web-components.js
```

### Output Files

```
src/design-system/
├── tokens/
│   ├── design-tokens.css      # CSS custom properties
│   ├── design-tokens.js       # JavaScript token object
│   └── design-tokens.d.ts     # TypeScript definitions
├── components/
│   ├── theme-provider.js      # Theme provider element
│   ├── design-token-base.js   # Base class for themed components
│   └── index.js               # Barrel export
├── styles/
│   ├── global.css             # Global styles
│   ├── reset.css              # CSS reset
│   └── utilities.css          # Utility classes
└── index.js                   # Main entry point
```

---

## Example Output

### tokens/design-tokens.css
```css
:root {
  /* Primary colors */
  --color-primary: #007AFF;
  --color-primary-light: #5AC8FA;
  --color-primary-dark: #0051A8;

  /* Secondary colors */
  --color-secondary: #5856D6;

  /* Semantic colors */
  --color-background: #FFFFFF;
  --color-surface: #F2F2F7;
  --color-error: #FF3B30;
  --color-success: #34C759;

  /* Text colors */
  --color-text-primary: #000000;
  --color-text-secondary: #8E8E93;

  /* Typography */
  --font-family-base: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-size-h1: 32px;
  --font-size-h2: 24px;
  --font-size-body: 16px;
  --font-size-caption: 12px;
  --font-weight-regular: 400;
  --font-weight-semibold: 600;
  --font-weight-bold: 700;
  --line-height-tight: 1.25;
  --line-height-normal: 1.5;

  /* Spacing */
  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;
  --spacing-xxl: 48px;

  /* Border radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-full: 9999px;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
  --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
}

/* Dark theme */
[data-theme="dark"] {
  --color-background: #000000;
  --color-surface: #1C1C1E;
  --color-text-primary: #FFFFFF;
  --color-text-secondary: #8E8E93;
}
```

### tokens/design-tokens.js
```javascript
export const tokens = {
  colors: {
    primary: 'var(--color-primary)',
    primaryLight: 'var(--color-primary-light)',
    primaryDark: 'var(--color-primary-dark)',
    secondary: 'var(--color-secondary)',
    background: 'var(--color-background)',
    surface: 'var(--color-surface)',
    error: 'var(--color-error)',
    success: 'var(--color-success)',
    textPrimary: 'var(--color-text-primary)',
    textSecondary: 'var(--color-text-secondary)',
  },
  typography: {
    fontFamily: 'var(--font-family-base)',
    h1: {
      fontSize: 'var(--font-size-h1)',
      fontWeight: 'var(--font-weight-bold)',
      lineHeight: 'var(--line-height-tight)',
    },
    h2: {
      fontSize: 'var(--font-size-h2)',
      fontWeight: 'var(--font-weight-semibold)',
      lineHeight: 'var(--line-height-tight)',
    },
    body: {
      fontSize: 'var(--font-size-body)',
      fontWeight: 'var(--font-weight-regular)',
      lineHeight: 'var(--line-height-normal)',
    },
  },
  spacing: {
    xs: 'var(--spacing-xs)',
    sm: 'var(--spacing-sm)',
    md: 'var(--spacing-md)',
    lg: 'var(--spacing-lg)',
    xl: 'var(--spacing-xl)',
    xxl: 'var(--spacing-xxl)',
  },
};
```

### components/theme-provider.js
```javascript
const template = document.createElement('template');
template.innerHTML = `
  <style>
    :host {
      display: contents;
    }
  </style>
  <slot></slot>
`;

export class ThemeProvider extends HTMLElement {
  static get observedAttributes() {
    return ['theme'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.appendChild(template.content.cloneNode(true));
  }

  connectedCallback() {
    this._updateTheme();
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (name === 'theme' && oldValue !== newValue) {
      this._updateTheme();
    }
  }

  _updateTheme() {
    const theme = this.getAttribute('theme') || 'light';
    document.documentElement.setAttribute('data-theme', theme);
  }

  get theme() {
    return this.getAttribute('theme') || 'light';
  }

  set theme(value) {
    this.setAttribute('theme', value);
  }

  toggleTheme() {
    this.theme = this.theme === 'light' ? 'dark' : 'light';
  }
}

customElements.define('theme-provider', ThemeProvider);
```

### components/design-token-base.js
```javascript
import { tokens } from '../tokens/design-tokens.js';

export class DesignTokenBase extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  get tokens() {
    return tokens;
  }

  applyTokenStyles(styles) {
    const styleSheet = new CSSStyleSheet();
    styleSheet.replaceSync(styles);
    this.shadowRoot.adoptedStyleSheets = [styleSheet];
  }
}
```

---

## Lit Element Example

When using `--lit`:

### components/themed-button.js
```javascript
import { LitElement, html, css } from 'lit';
import { tokens } from '../tokens/design-tokens.js';

export class ThemedButton extends LitElement {
  static properties = {
    variant: { type: String },
  };

  static styles = css`
    :host {
      display: inline-block;
    }

    button {
      font-family: var(--font-family-base);
      font-size: var(--font-size-body);
      padding: var(--spacing-sm) var(--spacing-md);
      border-radius: var(--radius-md);
      border: none;
      cursor: pointer;
      transition: background-color 0.2s ease;
    }

    button.primary {
      background-color: var(--color-primary);
      color: white;
    }

    button.primary:hover {
      background-color: var(--color-primary-dark);
    }

    button.secondary {
      background-color: var(--color-secondary);
      color: white;
    }
  `;

  constructor() {
    super();
    this.variant = 'primary';
  }

  render() {
    return html`
      <button class="${this.variant}">
        <slot></slot>
      </button>
    `;
  }
}

customElements.define('themed-button', ThemedButton);
```

---

## Usage in HTML

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <link rel="stylesheet" href="./design-system/tokens/design-tokens.css">
  <script type="module" src="./design-system/index.js"></script>
</head>
<body>
  <theme-provider theme="light">
    <h1 style="font-size: var(--font-size-h1); color: var(--color-text-primary);">
      Hello, World!
    </h1>
    <p style="font-size: var(--font-size-body); color: var(--color-text-secondary);">
      Design tokens as CSS custom properties.
    </p>
    <themed-button variant="primary">Click Me</themed-button>
  </theme-provider>

  <script>
    // Toggle theme
    document.querySelector('theme-provider').toggleTheme();
  </script>
</body>
</html>
```

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

### "Custom element not defined"
Ensure the component script is loaded before usage.

### "CSS variables not applying"
Check that `design-tokens.css` is linked in your HTML.

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-extract` - Extract tokens from Figma
- `/transform-react` - Transform to React
- `/transform-vue` - Transform to Vue
