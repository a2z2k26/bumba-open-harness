---
name: design-search
description: Search for design tokens, components, and layouts using natural language queries
allowed-tools: Read, Bash, Grep
---

# /search-design - Search Design Assets

Search for tokens, components, and layouts using natural language queries.

## Purpose

Find design assets quickly using keywords, categories, or natural language descriptions. Search across all three asset types:
- **Tokens** - Colors, typography, spacing, shadows, etc.
- **Components** - Buttons, inputs, cards, navigation, etc.
- **Layouts** - Full page compositions, screens, templates

The search system uses a pre-built index with relevance scoring to return the most relevant results.

## Prerequisites

- `.design/` directory exists (run `/design-init` first)
- Assets have been extracted from Figma (tokens, components, and/or layouts)
- Search index exists (auto-built or run build script)

## Instructions

### Step 1: Check if Search Index Exists

```bash
ls .design/.search-index.json
```

If the file doesn't exist, build it first:

```bash
node .claude/scripts/build-search-index.js
```

### Step 2: Run Search Query

Use natural language to search:

```bash
# Search for buttons (component)
node .claude/scripts/search-design.js "button"

# Search by category
node .claude/scripts/search-design.js "form components"

# Natural language
node .claude/scripts/search-design.js "input for email"

# Search tokens
node .claude/scripts/search-design.js "primary color"

# Search layouts
node .claude/scripts/search-design.js "dashboard"
node .claude/scripts/search-design.js "login page"
node .claude/scripts/search-design.js "homepage layout"
```

### Step 3: Review Results

Results are ranked by relevance score (0-100+):
- Exact name match: High score
- Partial match: Medium score
- Category/tag match: Lower score
- Assets with Storybook stories ranked higher (+10 points)
- Assets with tests ranked higher (+10 points)
- Layouts with screenshots ranked higher (+5 points)

### Step 4: Navigate to Asset

Use the path shown in results to open the asset:

```bash
# Example component result:
# Path: .design/extracted-code/react/components/Button
code .design/extracted-code/react/components/Button

# Example layout result:
# Path: .design/layouts/react/DashboardPage
code .design/layouts/react/DashboardPage

# Example token result:
# Path: .design/tokens/colors.json
code .design/tokens/colors.json
```

## Search Features

### Keyword Search
- Search by asset name (component, layout, or token name)
- Search by category (form, layout, navigation, page, etc.)
- Search by token type (color, typography, spacing)
- Search by layout type (page, screen, template)

### Natural Language
- "button for forms" → Finds Button component
- "primary blue color" → Finds primary color token
- "input field" → Finds Input component
- "dashboard page" → Finds Dashboard layout
- "login screen" → Finds Login layout
- "settings with sidebar" → Finds Settings layout

### Scoring Algorithm
Assets are scored based on:
- Name match (exact or partial)
- Search term relevance
- Category/type match
- Has Storybook story (+10 points)
- Has tests (+10 points)
- Layout has screenshot (+5 points)
- Layout dependencies resolved (+5 points)

## Example Searches

### Find Components
```
Query: "button"
Returns: Button, IconButton, ToggleButton (sorted by score)

Query: "form"
Returns: All components in form category

Query: "container"
Returns: Container, Grid, Stack, etc.
```

### Find Tokens
```
Query: "color"
Returns: All color tokens

Query: "typography"
Returns: All typography tokens

Query: "spacing"
Returns: All spacing tokens
```

### Find Layouts
```
Query: "dashboard"
Returns: DashboardPage, AdminDashboard, AnalyticsDashboard

Query: "login"
Returns: LoginPage, LoginScreen

Query: "settings"
Returns: SettingsPage, UserSettings, AccountSettings
```

## Rebuilding the Index

The search index should be rebuilt when:
- New components are extracted
- New layouts are extracted
- Tokens are updated
- Any asset is modified

Rebuild manually:
```bash
node .claude/scripts/build-search-index.js
```

The index is automatically rebuilt after extraction from the Figma plugin.

## Index Location

Default: `.design/.search-index.json`

The index contains:
- All components with metadata
- All layouts with metadata and dependencies
- All tokens with values
- Category/type groupings
- Search terms for fast lookup

## Troubleshooting

**Error: Search index not found**
→ Run `node .claude/scripts/build-search-index.js`

**Error: No results found**
→ Try different keywords
→ Rebuild the index
→ Check that assets exist in `.design/`

**Error: .design/ directory not found**
→ Run `/design-init` first

**Error: Layout not found**
→ Check that layouts have been extracted from Figma
→ Verify layoutManifest.json exists

## Categories

### Component Categories
Components are automatically categorized into:
1. **layout** - Container, Grid, Stack, Flex
2. **navigation** - Link, NavBar, Menu, Breadcrumb
3. **form** - Button, Input, Checkbox, Select
4. **data-display** - Table, List, Card, Badge
5. **feedback** - Alert, Toast, Spinner, Progress
6. **overlay** - Modal, Popover, Tooltip, Drawer

### Layout Categories
Layouts are automatically categorized into:
1. **page** - Full page layouts (HomePage, AboutPage)
2. **screen** - App screens (LoginScreen, SettingsScreen)
3. **template** - Reusable templates (BlogTemplate, ProductTemplate)
4. **dashboard** - Dashboard layouts (AdminDashboard, AnalyticsDashboard)
5. **auth** - Authentication layouts (Login, Register, ForgotPassword)

### Token Categories
Tokens are automatically categorized into:
1. **color** - Colors, gradients, shadows
2. **typography** - Fonts, sizes, weights, line heights
3. **spacing** - Margins, padding, gaps
4. **border** - Border widths, radii, styles
5. **effect** - Shadows, blur, opacity

## Related Commands

- `/design-init` - Initialize .design/ structure
- `/transform-{framework}` - Generate components
- Build index script: `.claude/scripts/build-search-index.js`
- Search script: `.claude/scripts/search-design.js`

## Advanced Usage

### Search by Category
```bash
node .claude/scripts/search-design.js "navigation"
node .claude/scripts/search-design.js "dashboard"
```

### Search by Multiple Terms
```bash
node .claude/scripts/search-design.js "button primary form"
node .claude/scripts/search-design.js "settings page sidebar"
```

### Search by Asset Type
```bash
# Search components only
node .claude/scripts/search-design.js --type=component "button"

# Search layouts only
node .claude/scripts/search-design.js --type=layout "dashboard"

# Search tokens only
node .claude/scripts/search-design.js --type=token "color"
```

### Search Tokens
```bash
# Search for typography tokens
node .claude/scripts/search-design.js "typography heading"

# Search for spacing tokens
node .claude/scripts/search-design.js "spacing medium"
```

### Search Layouts
```bash
# Search for dashboard layouts
node .claude/scripts/search-design.js "dashboard"

# Search layouts with specific components
node .claude/scripts/search-design.js "page with sidebar"
```

## Output Format

```
=== Searching for: "dashboard" ===

Layouts:
1. DashboardPage (dashboard) - Score: 100
   Path: .design/layouts/react/DashboardPage
   Screenshot: ./public/design-assets/layouts/screenshots/DashboardPage.png
   Dependencies: Sidebar, Header, Card, Chart (all resolved ✓)

2. AdminDashboard (dashboard) - Score: 85
   Path: .design/layouts/react/AdminDashboard
   Screenshot: ./public/design-assets/layouts/screenshots/AdminDashboard.png
   Dependencies: Sidebar, Header, Table, Button (all resolved ✓)

Components:
1. DashboardCard (data-display) - Score: 70
   Path: .design/extracted-code/react/components/DashboardCard
   Card component used in dashboard layouts

Tokens:
(no matching tokens)

=== Searching for: "button" ===

Components:
1. Button (form) - Score: 100
   Path: .design/extracted-code/react/components/Button
   Primary button component with multiple variants

2. IconButton (form) - Score: 85
   Path: .design/extracted-code/react/components/IconButton

Tokens:
1. button-primary (color)
   Value: "#3B82F6"
   Path: .design/tokens/colors.json

Layouts:
1. LoginPage (auth) - Score: 40
   Path: .design/layouts/react/LoginPage
   Contains: Button, Input components
```
