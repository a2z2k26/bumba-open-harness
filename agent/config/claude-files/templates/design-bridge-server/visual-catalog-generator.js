/**
 * Visual Catalog Generator
 * Generates interactive HTML catalog from design tokens
 */

const fs = require('fs').promises;
const path = require('path');
const chalk = require('chalk');

class VisualCatalogGenerator {
  constructor(options = {}) {
    this.outputDir = options.outputDir || './design-catalog';
    this.title = options.title || 'Design System Catalog';
    this.projectName = options.projectName || 'Design System';
    this.theme = options.theme || 'bumba-dark';
    this.includePlayground = options.includePlayground !== false;

    // BUMBA Brand Colors for UI wrapper only
    this.bumbaUI = {
      gradient: {
        green: '#00AA00',
        yellowGreen: '#66BB00',
        yellow: '#FFDD00',
        orangeYellow: '#FFAA00',
        orangeRed: '#FF6600',
        red: '#DD0000'
      },
      accent: {
        gold: '#D4AF37',
        wheat: '#F5DEB3',
        border: '#FFDD00'
      },
      dark: {
        background: '#0A0A0A',
        surface: '#1A1A1A',
        surfaceLight: '#2A2A2A',
        text: '#FFFFFF',
        textSecondary: '#A0A0A0'
      }
    };
  }

  /**
   * Generate complete visual catalog
   */
  async generate(tokens, metadata = {}) {
    console.log(chalk.blue('🎨 Generating Visual Catalog...'));

    try {
      // Ensure output directory exists
      await fs.mkdir(this.outputDir, { recursive: true });

      // Generate HTML pages
      const pages = {
        index: await this.generateIndexPage(tokens, metadata),
        colors: await this.generateColorsPage(tokens.colors),
        typography: await this.generateTypographyPage(tokens.typography),
        spacing: await this.generateSpacingPage(tokens.spacing),
        shadows: await this.generateShadowsPage(tokens.shadows),
        forms: await this.generateFormsPage(),
        'data-display': await this.generateDataDisplayPage(),
        feedback: await this.generateFeedbackPage(),
        navigation: await this.generateNavigationPage(),
        overlays: await this.generateOverlaysPage(),
        playground: this.includePlayground ? await this.generatePlayground(tokens) : null
      };

      // Generate individual component pages
      const componentPages = await this.generateAllComponentPages(tokens);
      Object.assign(pages, componentPages);

      // Generate CSS
      const styles = await this.generateStyles(tokens);

      // Generate JavaScript
      const scripts = await this.generateScripts();

      // Write files
      for (const [name, content] of Object.entries(pages)) {
        if (content) {
          await fs.writeFile(
            path.join(this.outputDir, `${name}.html`),
            content
          );
        }
      }

      await fs.writeFile(
        path.join(this.outputDir, 'catalog.css'),
        styles
      );

      await fs.writeFile(
        path.join(this.outputDir, 'catalog.js'),
        scripts
      );

      // Copy token files
      await this.copyTokenFiles(tokens);

      console.log(chalk.green('✅ Visual Catalog generated successfully'));
      console.log(chalk.gray(`   Open ${path.join(this.outputDir, 'index.html')} to view`));

      return {
        success: true,
        path: this.outputDir,
        pages: Object.keys(pages).filter(p => pages[p])
      };
    } catch (error) {
      console.error(chalk.red('❌ Catalog generation failed:'), error.message);
      throw error;
    }
  }


  /**
   * Get sidebar header HTML
   */
  getSidebarHeaderHTML() {
    return `        <div class="sidebar-header">
            <div class="sidebar-title">BUMBA CLI 1.0</div>
            <div class="sidebar-project">${this.projectName || 'Project Title'}</div>
        </div>`;
  }

  /**
   * Generate full navigation menu
   */
  getShadcnComponents() {
    return [
      'Accordion', 'Alert', 'Alert Dialog', 'Aspect Ratio', 'Avatar', 'Badge',
      'Breadcrumb', 'Button', 'Calendar', 'Card', 'Carousel', 'Chart',
      'Checkbox', 'Collapsible', 'Combobox', 'Command', 'Context Menu', 'Data Table',
      'Date Picker', 'Dialog', 'Drawer', 'Dropdown Menu', 'React Hook Form', 'Hover Card',
      'Input', 'Input OTP', 'Label', 'Menubar', 'Navigation Menu', 'Pagination',
      'Popover', 'Progress', 'Radio Group', 'Resizable', 'Scroll-area', 'Select',
      'Separator', 'Sheet', 'Sidebar', 'Skeleton', 'Slider', 'Sonner',
      'Switch', 'Table', 'Tabs', 'Textarea', 'Toast', 'Toggle',
      'Toggle Group', 'Tooltip', 'Typography'
    ];
  }

  getFullNavigationHTML(activePage = '') {
    const componentItems = this.getShadcnComponents().map(comp => {
      const slug = comp.toLowerCase().replace(/\s+/g, '-');
      return `            <li><a href="component-${slug}.html"${activePage === `component-${slug}` ? ' class="active"' : ''}>${comp}</a></li>`;
    }).join('\n');

    return `        <ul>
            <li class="nav-section">Overview</li>
            <li><a href="index.html"${activePage === 'index' ? ' class="active"' : ''}>Dashboard</a></li>
            <li class="nav-section">Tokens</li>
            <li><a href="colors.html"${activePage === 'colors' ? ' class="active"' : ''}>Colors</a></li>
            <li><a href="typography.html"${activePage === 'typography' ? ' class="active"' : ''}>Typography</a></li>
            <li><a href="spacing.html"${activePage === 'spacing' ? ' class="active"' : ''}>Spacing</a></li>
            <li><a href="shadows.html"${activePage === 'shadows' ? ' class="active"' : ''}>Shadows</a></li>
            <li class="nav-section">Patterns</li>
            <li><a href="forms.html"${activePage === 'forms' ? ' class="active"' : ''}>Forms</a></li>
            <li><a href="data-display.html"${activePage === 'data-display' ? ' class="active"' : ''}>Data Display</a></li>
            <li><a href="feedback.html"${activePage === 'feedback' ? ' class="active"' : ''}>Feedback</a></li>
            <li><a href="navigation.html"${activePage === 'navigation' ? ' class="active"' : ''}>Navigation</a></li>
            <li><a href="overlays.html"${activePage === 'overlays' ? ' class="active"' : ''}>Overlays</a></li>
            <li class="nav-section">Components</li>
${componentItems}
            ${this.includePlayground ? `<li class="nav-section">Tools</li>\n            <li><a href="playground.html"${activePage === 'playground' ? ' class="active"' : ''}>Playground</a></li>` : ''}
        </ul>`;
  }

  /**
   * Generate index page
   */
  async generateIndexPage(tokens, metadata) {
    const tokenCount = this.countTokens(tokens);

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('index')}
    </nav>

    <main class="content">
        <header>
            <h2>Design System Dashboard</h2>
            <p>Last updated: ${new Date().toLocaleDateString()}</p>
        </header>

        <div class="stats-grid">
            <div class="stat-card">
                <span class="stat-value">${tokenCount.colors}</span>
                <span class="stat-label">Colors</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${tokenCount.typography}</span>
                <span class="stat-label">Typography</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${tokenCount.spacing}</span>
                <span class="stat-label">Spacing</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${tokenCount.total}</span>
                <span class="stat-label">Total Tokens</span>
            </div>
        </div>

        <section class="component-library">
            <h3 style="white-space: nowrap;">All Components</h3>
            <div class="component-grid">
                ${this.getShadcnComponents().map(comp => {
                  const slug = comp.toLowerCase().replace(/\s+/g, '-');
                  return `<a href="component-${slug}.html" class="component-item">${comp}</a>`;
                }).join('\n                ')}
            </div>
        </section>

        <section class="metadata">
            <h3>Metadata</h3>
            <pre>${JSON.stringify(metadata, null, 2)}</pre>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate forms page
   */
  async generateFormsPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Forms - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('forms')}
    </nav>

    <main class="content">
        <header>
            <h2>Form Components</h2>
            <p>Input fields, checkboxes, radios, selects, and other form controls</p>
        </header>

        <section class="component-showcase">
            <h3>Input Fields</h3>
            <div class="component-preview">
                <p class="component-note">→ TextField, NumberField, PasswordField, SearchField</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Selection Controls</h3>
            <div class="component-preview">
                <p class="component-note">→ Checkbox, Radio, Switch, Toggle</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Dropdowns & Pickers</h3>
            <div class="component-preview">
                <p class="component-note">→ Select, Combobox, DatePicker, TimePicker, ColorPicker</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Text Areas & Editors</h3>
            <div class="component-preview">
                <p class="component-note">→ Textarea, RichTextEditor, CodeEditor</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Form Layout</h3>
            <div class="component-preview">
                <p class="component-note">→ Form, FormField, FormLabel, FormDescription, FormMessage</p>
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate data display page
   */
  async generateDataDisplayPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Data Display - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('data-display')}
    </nav>

    <main class="content">
        <header>
            <h2>Data Display Components</h2>
            <p>Tables, lists, cards, and other data presentation patterns</p>
        </header>

        <section class="component-showcase">
            <h3>Tables & Grids</h3>
            <div class="component-preview">
                <p class="component-note">→ Table, DataTable, Grid, TreeTable</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Lists</h3>
            <div class="component-preview">
                <p class="component-note">→ List, ListItem, DescriptionList, Timeline</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Cards & Tiles</h3>
            <div class="component-preview">
                <p class="component-note">→ Card, CardHeader, CardContent, CardFooter</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Stats & Metrics</h3>
            <div class="component-preview">
                <p class="component-note">→ Stat, StatGroup, KPI, ProgressBar, Charts</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Media</h3>
            <div class="component-preview">
                <p class="component-note">→ Avatar, Image, Video, Gallery, Carousel</p>
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate feedback page
   */
  async generateFeedbackPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Feedback - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('feedback')}
    </nav>

    <main class="content">
        <header>
            <h2>Feedback Components</h2>
            <p>Alerts, toasts, loading states, and user feedback patterns</p>
        </header>

        <section class="component-showcase">
            <h3>Alerts & Notifications</h3>
            <div class="component-preview">
                <p class="component-note">→ Alert, AlertDialog, Toast, Notification</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Loading & Progress</h3>
            <div class="component-preview">
                <p class="component-note">→ Spinner, Skeleton, ProgressBar, LoadingDots</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Empty States</h3>
            <div class="component-preview">
                <p class="component-note">→ EmptyState, NoResults, Error404, Placeholder</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Badges & Tags</h3>
            <div class="component-preview">
                <p class="component-note">→ Badge, Tag, Chip, Label, Status</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Tooltips & Popovers</h3>
            <div class="component-preview">
                <p class="component-note">→ Tooltip, Popover, HoverCard, ContextMenu</p>
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate navigation page
   */
  async generateNavigationPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Navigation - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('navigation')}
    </nav>

    <main class="content">
        <header>
            <h2>Navigation Components</h2>
            <p>Menus, breadcrumbs, tabs, and navigation patterns</p>
        </header>

        <section class="component-showcase">
            <h3>Menus</h3>
            <div class="component-preview">
                <p class="component-note">→ Menu, MenuBar, DropdownMenu, ContextMenu</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Navigation Bars</h3>
            <div class="component-preview">
                <p class="component-note">→ NavigationMenu, Navbar, Sidebar, MobileNav</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Tabs & Segments</h3>
            <div class="component-preview">
                <p class="component-note">→ Tabs, SegmentedControl, ButtonGroup, Stepper</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Breadcrumbs & Pagination</h3>
            <div class="component-preview">
                <p class="component-note">→ Breadcrumb, Pagination, PageIndicator</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Links & Anchors</h3>
            <div class="component-preview">
                <p class="component-note">→ Link, Anchor, ScrollSpy, BackToTop</p>
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate overlays page
   */
  async generateOverlaysPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Overlays - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('overlays')}
    </nav>

    <main class="content">
        <header>
            <h2>Overlay Components</h2>
            <p>Modals, dialogs, sheets, and overlay patterns</p>
        </header>

        <section class="component-showcase">
            <h3>Modals & Dialogs</h3>
            <div class="component-preview">
                <p class="component-note">→ Dialog, Modal, AlertDialog, ConfirmDialog</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Sheets & Drawers</h3>
            <div class="component-preview">
                <p class="component-note">→ Sheet, Drawer, SidePanel, BottomSheet</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Dropdowns</h3>
            <div class="component-preview">
                <p class="component-note">→ Dropdown, Select, Autocomplete, CommandPalette</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Accordions & Collapsibles</h3>
            <div class="component-preview">
                <p class="component-note">→ Accordion, Collapsible, Disclosure, ExpansionPanel</p>
            </div>
        </section>

        <section class="component-showcase">
            <h3>Floating Elements</h3>
            <div class="component-preview">
                <p class="component-note">→ Tooltip, Popover, FloatingActionButton, Spotlight</p>
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate colors page
   */
  async generateColorsPage(colors) {
    const colorGroups = this.groupColors(colors);

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Colors - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('colors')}
    </nav>

    <main class="content">
        <header>
            <h2>Color Palette</h2>
            <div class="view-toggle">
                <button class="active" data-view="grid">Grid</button>
                <button data-view="list">List</button>
                <button data-view="contrast">Contrast</button>
            </div>
        </header>

        ${Object.entries(colorGroups).map(([group, colors]) => `
            <section class="color-group">
                <h3>${this.formatGroupName(group)}</h3>
                <div class="color-grid" data-view="grid">
                    ${Object.entries(colors).map(([name, value]) => `
                        <div class="color-card" data-color="${value}">
                            <div class="color-swatch" style="background-color: ${value}"></div>
                            <div class="color-info">
                                <span class="color-name">${name}</span>
                                <span class="color-value">${value}</span>
                                <button class="copy-btn" data-value="${value}">Copy</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </section>
        `).join('')}

        <section class="color-accessibility">
            <h3>Accessibility</h3>
            <div id="contrast-checker">
                <div class="contrast-input">
                    <label>Foreground: <input type="color" id="fg-color"></label>
                    <label>Background: <input type="color" id="bg-color"></label>
                </div>
                <div class="contrast-results">
                    <div class="wcag-aa">AA: <span id="aa-result">-</span></div>
                    <div class="wcag-aaa">AAA: <span id="aaa-result">-</span></div>
                    <div class="ratio">Ratio: <span id="ratio-result">-</span></div>
                </div>
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate typography page
   */
  async generateTypographyPage(typography) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Typography - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('typography')}
    </nav>

    <main class="content">
        <header>
            <h2>Typography Scale</h2>
        </header>

        <section class="type-specimens">
            ${Object.entries(typography || {}).map(([name, styles]) => `
                <div class="type-specimen">
                    <div class="type-preview" style="${this.styleObjectToCSS(styles)}">
                        The quick brown fox jumps over the lazy dog
                    </div>
                    <div class="type-details">
                        <h4>${this.formatTypeName(name)}</h4>
                        <ul>
                            <li>Size: ${styles.fontSize || 'inherit'}</li>
                            <li>Weight: ${styles.fontWeight || 'normal'}</li>
                            <li>Line Height: ${styles.lineHeight || 'normal'}</li>
                            <li>Letter Spacing: ${styles.letterSpacing || 'normal'}</li>
                            <li>Font Family: ${styles.fontFamily || 'inherit'}</li>
                        </ul>
                        <button class="copy-btn" data-styles='${JSON.stringify(styles)}'>Copy CSS</button>
                    </div>
                </div>
            `).join('')}
        </section>

        <section class="type-playground">
            <h3>Typography Playground</h3>
            <div class="playground-controls">
                <textarea id="type-text" placeholder="Enter your text here...">The quick brown fox jumps over the lazy dog</textarea>
                <select id="type-style">
                    ${Object.keys(typography || {}).map(name =>
                        `<option value="${name}">${this.formatTypeName(name)}</option>`
                    ).join('')}
                </select>
                <button id="apply-type">Apply Style</button>
            </div>
            <div id="type-preview" class="type-preview-area"></div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate spacing page
   */
  async generateSpacingPage(spacing) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spacing - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('spacing')}
    </nav>

    <main class="content">
        <header>
            <h2>Spacing System</h2>
        </header>

        <section class="spacing-scale">
            <h3>Spacing Scale</h3>
            <div class="spacing-grid">
                ${Object.entries(spacing || {}).map(([name, value]) => `
                    <div class="spacing-item">
                        <span class="spacing-label">${name}</span>
                        <div class="spacing-visual">
                            <div class="spacing-bar" style="width: ${value}; height: ${value}"></div>
                        </div>
                        <span class="spacing-value">${value}</span>
                    </div>
                `).join('')}
            </div>
        </section>

        <section class="spacing-demo">
            <h3>Spacing in Context</h3>
            <div class="demo-container">
                <div class="demo-card">
                    <h4>Card with spacing</h4>
                    <p>This card demonstrates various spacing values in a real component.</p>
                    <div class="spacing-examples">
                        ${Object.entries(spacing || {}).slice(0, 5).map(([name, value]) => `
                            <div class="spacing-example" style="padding: ${value}; margin-bottom: 8px; background: rgba(0,0,0,0.05)">
                                Padding: ${name} (${value})
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate shadows page
   */
  async generateShadowsPage(shadows) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shadows - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('shadows')}
    </nav>

    <main class="content">
        <header>
            <h2>Shadow Effects</h2>
        </header>

        <section class="shadow-showcase">
            <div class="shadow-grid">
                ${Object.entries(shadows || {}).map(([name, value]) => `
                    <div class="shadow-card">
                        <div class="shadow-preview" style="box-shadow: ${value}">
                            <h4>${this.formatShadowName(name)}</h4>
                        </div>
                        <div class="shadow-details">
                            <code>${value}</code>
                            <button class="copy-btn" data-value="${value}">Copy</button>
                        </div>
                    </div>
                `).join('')}
            </div>
        </section>

        <section class="shadow-layers">
            <h3>Layered Shadows</h3>
            <div class="layer-demo">
                <div class="layer-stack">
                    ${Object.entries(shadows || {}).map(([name, value], index) => `
                        <div class="layer-item" style="
                            box-shadow: ${value};
                            z-index: ${index + 1};
                            transform: translate(${index * 20}px, ${index * 20}px);
                        ">
                            Layer ${index + 1}: ${name}
                        </div>
                    `).join('')}
                </div>
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate all component pages
   */
  async generateAllComponentPages(tokens) {
    const pages = {};
    const components = this.getShadcnComponents();

    for (const component of components) {
      const slug = component.toLowerCase().replace(/\s+/g, '-');
      pages[`component-${slug}`] = await this.generateComponentPage(component, tokens);
    }

    return pages;
  }

  /**
   * Generate individual component page
   */
  async generateComponentPage(componentName, tokens) {
    const slug = componentName.toLowerCase().replace(/\s+/g, '-');
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${componentName} - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
    <style>
        .component-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2rem;
        }

        .copy-page-btn {
            padding: 0.5rem 1rem;
            background: var(--card);
            border: 1px solid var(--border);
            color: var(--foreground);
            border-radius: var(--radius);
            cursor: pointer;
            font-size: 0.875rem;
            font-weight: 500;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }

        .copy-page-btn:hover {
            background: var(--accent);
            border-color: var(--accent);
        }

        .nav-controls {
            display: flex;
            gap: 0.5rem;
        }

        .nav-btn {
            padding: 0.5rem 0.75rem;
            background: var(--card);
            border: 1px solid var(--border);
            color: var(--muted-foreground);
            border-radius: var(--radius);
            cursor: pointer;
            font-size: 0.875rem;
            transition: all 0.2s ease;
        }

        .nav-btn:hover:not(:disabled) {
            background: var(--accent);
            color: var(--foreground);
        }

        .nav-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .component-showcase {
            margin-top: 3rem;
            padding: 3rem;
            background: var(--card);
            border-radius: var(--radius);
            border: 1px solid var(--border);
        }

        .component-example {
            padding: 3rem;
            background: var(--background);
            border-radius: var(--radius);
            margin-bottom: 2.5rem;
            border: 1px solid var(--border);
        }

        .component-docs {
            margin-top: 3rem;
        }

        .component-props {
            background: var(--muted);
            border-radius: var(--radius);
            padding: 2rem;
            margin-top: 1.5rem;
        }

        .prop-item {
            padding: 1rem 0;
            border-bottom: 1px solid var(--border);
        }

        .prop-item:last-child {
            border-bottom: none;
        }

        .prop-name {
            font-family: monospace;
            font-weight: 600;
            color: var(--primary);
        }

        .prop-type {
            font-family: monospace;
            font-size: 0.875rem;
            color: var(--muted-foreground);
            margin-left: 1rem;
        }

        .prop-description {
            margin-top: 0.5rem;
            font-size: 0.875rem;
            color: var(--muted-foreground);
            line-height: 1.5;
        }
    </style>
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML(`component-${slug}`)}
    </nav>

    <main class="content">
        <header class="component-header">
            <div>
                <h2>${componentName}</h2>
            </div>
            <div style="display: flex; align-items: center; gap: 1rem;">
                <button class="copy-page-btn" onclick="navigator.clipboard.writeText(window.location.href)">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                    Copy Page
                </button>
                <div class="nav-controls">
                    ${this.getComponentNavigation(componentName)}
                </div>
            </div>
        </header>

        <p style="margin-bottom: 2rem; color: var(--muted-foreground);">
            ${this.getComponentDescription(componentName)}
        </p>

        <section class="component-showcase">
            <h3>Example</h3>
            <div class="component-example">
                ${this.getComponentExample(componentName)}
            </div>
        </section>

        <section class="component-docs">
            <h3>Usage</h3>
            <pre class="code-block"><code>${this.getComponentUsage(componentName)}</code></pre>

            <h3 style="margin-top: 2rem;">Properties</h3>
            <div class="component-props">
                ${this.getComponentProps(componentName)}
            </div>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate playground page
   */
  async generatePlayground(tokens) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Playground - ${this.title}</title>
    <link rel="stylesheet" href="catalog.css">
    <style id="playground-styles"></style>
</head>
<body class="bumba-dark-theme">
    <nav class="sidebar">
${this.getSidebarHeaderHTML()}
${this.getFullNavigationHTML('playground')}
    </nav>

    <main class="content">
        <header>
            <h2>Token Playground</h2>
            <p>Experiment with design tokens in real-time</p>
        </header>

        <div class="playground-container">
            <div class="playground-editor">
                <h3>HTML</h3>
                <textarea id="html-editor" class="code-editor">
<div class="playground-component">
    <h1 class="title">Hello Design System</h1>
    <p class="description">Build something amazing</p>
    <button class="action-btn">Get Started</button>
</div>
                </textarea>

                <h3>CSS</h3>
                <textarea id="css-editor" class="code-editor">
.playground-component {
    padding: var(--spacing-6);
    background: var(--colors-bg-primary);
    border-radius: var(--borderradius-lg);
    box-shadow: var(--shadows-md);
}

.title {
    color: var(--colors-text-primary);
    font-size: var(--typography-heading-1-fontsize);
    font-weight: var(--typography-heading-1-fontweight);
    margin-bottom: var(--spacing-3);
}

.description {
    color: var(--colors-text-secondary);
    margin-bottom: var(--spacing-4);
}

.action-btn {
    background: var(--colors-brand-primary);
    color: var(--colors-text-inverse);
    padding: var(--spacing-2) var(--spacing-4);
    border: none;
    border-radius: var(--borderradius-md);
    cursor: pointer;
    transition: opacity 0.2s;
}

.action-btn:hover {
    opacity: 0.9;
}
                </textarea>

                <button id="run-playground" class="btn btn-primary">Run</button>
            </div>

            <div class="playground-preview">
                <h3>Preview</h3>
                <iframe id="preview-frame" class="preview-frame"></iframe>
            </div>
        </div>

        <section class="token-reference">
            <h3>Available Tokens</h3>
            <details>
                <summary>Colors (${Object.keys(tokens.colors || {}).length})</summary>
                <ul class="token-list">
                    ${Object.keys(tokens.colors || {}).map(name =>
                        `<li><code>--colors-${name}</code></li>`
                    ).join('')}
                </ul>
            </details>

            <details>
                <summary>Typography (${Object.keys(tokens.typography || {}).length})</summary>
                <ul class="token-list">
                    ${Object.keys(tokens.typography || {}).map(name =>
                        `<li><code>--typography-${name}-*</code></li>`
                    ).join('')}
                </ul>
            </details>

            <details>
                <summary>Spacing (${Object.keys(tokens.spacing || {}).length})</summary>
                <ul class="token-list">
                    ${Object.keys(tokens.spacing || {}).map(name =>
                        `<li><code>--spacing-${name}</code></li>`
                    ).join('')}
                </ul>
            </details>
        </section>
    </main>

    <script src="catalog.js"></script>
</body>
</html>`;
  }

  /**
   * Generate CSS styles
   */
  async generateStyles(tokens) {
    return `/* Design System Catalog - BUMBA x shadcn/ui Theme */

/* Figma Design Tokens as CSS Variables */
:root {
${this.generateCSSVariables(tokens)}
}

/* BUMBA Branded Theme with shadcn/ui Structure */
:root {
    /* BUMBA Core Colors */
    --bumba-green: #00AA00;
    --bumba-yellow-green: #66BB00;
    --bumba-yellow: #FFDD00;
    --bumba-orange-yellow: #FFAA00;
    --bumba-orange-red: #FF6600;
    --bumba-red: #DD0000;
    --bumba-gold: #D4AF37;
    --bumba-wheat: #F5DEB3;

    /* Dark Theme Base */
    --background: #0A0A0A;
    --foreground: #FAFAFA;
    --card: #0F0F0F;
    --card-foreground: #FAFAFA;
    --popover: #0F0F0F;
    --popover-foreground: #FAFAFA;

    /* BUMBA Branded Accents */
    --primary: var(--bumba-yellow);
    --primary-foreground: #000000;
    --secondary: #1A1A1A;
    --secondary-foreground: #FAFAFA;
    --muted: #1A1A1A;
    --muted-foreground: #A0A0A0;
    --accent: var(--bumba-gold);
    --accent-foreground: #000000;
    --destructive: var(--bumba-red);
    --destructive-foreground: #FAFAFA;

    /* BUMBA Borders and UI */
    --border: rgba(255, 221, 0, 0.1);
    --input: #1A1A1A;
    --ring: var(--bumba-yellow);
    --radius: 0.5rem;

    /* BUMBA Gradient */
    --bumba-gradient: linear-gradient(135deg, var(--bumba-green) 0%, var(--bumba-yellow) 50%, var(--bumba-red) 100%);
    --bumba-gradient-subtle: linear-gradient(135deg, rgba(0,170,0,0.1) 0%, rgba(255,221,0,0.1) 50%, rgba(221,0,0,0.1) 100%);
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    display: flex;
    min-height: 100vh;
    background: var(--background);
    background-image: var(--bumba-gradient-subtle);
    color: var(--foreground);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* BUMBA Branded Sidebar */
.sidebar {
    width: 240px;
    background: linear-gradient(180deg, #0F0F0F 0%, #0A0A0A 100%);
    border-right: 1px solid var(--border);
    padding: 2rem;
    position: fixed;
    height: 100vh;
    overflow-y: auto;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.4);
}

.sidebar-header {
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid rgba(255, 221, 0, 0.1);
}

.sidebar-title {
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--bumba-wheat);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.25rem;
}

.sidebar-project {
    font-size: 1.25rem;
    font-weight: 700;
    background: var(--bumba-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.025em;
}

.sidebar ul {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
}

.sidebar li {
    margin: 0;
}

.sidebar a {
    display: flex;
    align-items: center;
    padding: 0.5rem 0.75rem;
    color: var(--muted-foreground);
    text-decoration: none;
    border-radius: var(--radius);
    transition: all 0.15s ease;
    font-size: 0.875rem;
    position: relative;
}

.sidebar a::before {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 3px;
    height: 0;
    background: var(--bumba-gradient);
    border-radius: 0 2px 2px 0;
    transition: height 0.2s ease;
}

.sidebar a:hover {
    background: rgba(255, 221, 0, 0.05);
    color: var(--bumba-wheat);
}

.sidebar a:hover::before {
    height: 70%;
}

.sidebar a.active {
    background: linear-gradient(90deg, rgba(255, 221, 0, 0.15) 0%, rgba(255, 221, 0, 0.05) 100%);
    color: var(--bumba-yellow);
    font-weight: 500;
}

.sidebar a.active::before {
    height: 100%;
}

.nav-section {
    font-weight: 600;
    color: var(--muted-foreground);
    padding: 1rem 0.75rem 0.5rem;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 1.5rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    padding-top: 1.5rem;
}

.nav-section:first-of-type {
    border-top: none;
    margin-top: 0.5rem;
    padding-top: 0.75rem;
}

.content {
    margin-left: 240px;
    padding: 2rem;
    width: calc(100% - 240px);
    max-width: 1400px;
}

header {
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
}

header h2 {
    font-size: 1.875rem;
    font-weight: 700;
    color: var(--foreground);
    margin-bottom: 0.5rem;
    letter-spacing: -0.025em;
}

header p {
    color: var(--muted-foreground);
    font-size: 0.875rem;
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}

.stat-card {
    background: var(--card);
    padding: 1.5rem;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    text-align: left;
    position: relative;
    overflow: hidden;
    transition: all 0.3s ease;
}

.stat-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--bumba-gradient);
    opacity: 0;
    transition: opacity 0.3s ease;
}

.stat-card:hover {
    transform: translateY(-2px);
    border-color: rgba(255, 221, 0, 0.2);
}

.stat-card:hover::before {
    opacity: 1;
}

.stat-value {
    display: block;
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(135deg, var(--bumba-wheat) 0%, var(--bumba-gold) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.25rem;
    letter-spacing: -0.025em;
}

.stat-label {
    color: var(--muted-foreground);
    font-size: 0.875rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.color-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 1.5rem;
    margin-bottom: 3rem;
}

.color-card {
    background: var(--card);
    border-radius: var(--radius);
    overflow: hidden;
    border: 1px solid var(--border);
    transition: all 0.15s ease;
}

.color-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.color-swatch {
    height: 140px;
    width: 100%;
}

.color-info {
    padding: 1.25rem;
    background: var(--card);
}

.color-name {
    display: block;
    font-weight: 600;
    margin-bottom: 0.25rem;
    color: var(--foreground);
    font-size: 0.875rem;
}

.color-value {
    display: block;
    color: var(--muted-foreground);
    font-size: 0.75rem;
    margin-bottom: 0.75rem;
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
}

.copy-btn {
    background: linear-gradient(135deg, #1A1A1A 0%, #0F0F0F 100%);
    color: var(--bumba-wheat);
    border: 1px solid rgba(255, 221, 0, 0.1);
    padding: 0.375rem 0.75rem;
    border-radius: calc(var(--radius) - 2px);
    cursor: pointer;
    font-size: 0.75rem;
    font-weight: 500;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;
}

.copy-btn::before {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 0;
    height: 0;
    border-radius: 50%;
    background: radial-gradient(circle, var(--bumba-yellow) 0%, transparent 70%);
    transform: translate(-50%, -50%);
    transition: width 0.4s ease, height 0.4s ease;
}

.copy-btn:hover {
    background: var(--bumba-yellow);
    color: #000000;
    border-color: var(--bumba-yellow);
    transform: translateY(-1px);
}

.copy-btn:hover::before {
    width: 100px;
    height: 100px;
}

/* Component Grid Styles */
.component-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--card);
    margin-top: 2rem;
}

.component-item {
    padding: 1.25rem 1.75rem;
    border-right: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    color: var(--foreground);
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.2s ease;
    cursor: pointer;
    text-decoration: none;
    display: block;
}

.component-item:hover {
    background: var(--accent);
    color: var(--accent-foreground);
}

.component-item:nth-child(3n) {
    border-right: none;
}

.component-item:nth-last-child(-n+3):nth-child(3n+1),
.component-item:nth-last-child(-n+2):nth-child(3n+2),
.component-item:nth-last-child(1):nth-child(3n) {
    border-bottom: none;
}

@media (max-width: 1024px) {
    .component-grid {
        grid-template-columns: repeat(2, 1fr);
    }
    .component-item:nth-child(3n) {
        border-right: 1px solid var(--border);
    }
    .component-item:nth-child(2n) {
        border-right: none;
    }
}

@media (max-width: 640px) {
    .component-grid {
        grid-template-columns: 1fr;
    }
    .component-item {
        border-right: none !important;
    }
    .component-item:last-child {
        border-bottom: none;
    }
}

.type-specimen {
    background: var(--card);
    padding: 2.5rem;
    border-radius: var(--radius);
    margin-bottom: 2rem;
    border: 1px solid var(--border);
}

.type-preview {
    margin-bottom: 1.5rem;
    padding: 1.5rem;
    background: var(--background);
    border-radius: calc(var(--radius) - 2px);
    border: 1px solid var(--border);
}

.spacing-grid {
    display: grid;
    gap: 1.5rem;
}

.spacing-item {
    display: flex;
    align-items: center;
    gap: 1.5rem;
    padding: 1.5rem;
    background: var(--card);
    border-radius: var(--radius);
    border: 1px solid var(--border);
}

.spacing-bar {
    background: var(--primary);
    min-height: 24px;
    border-radius: calc(var(--radius) - 4px);
}

.shadow-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 2rem;
}

.shadow-card {
    text-align: center;
}

.shadow-preview {
    background: var(--card);
    padding: 2.5rem;
    border-radius: var(--radius);
    margin-bottom: 1.5rem;
    min-height: 160px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border);
}

.component-showcase {
    margin-bottom: 3rem;
}

.component-showcase h3 {
    margin-bottom: 1.5rem;
    color: var(--foreground);
    font-size: 1.25rem;
    font-weight: 600;
}

.playground-container {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2rem;
    height: 650px;
    margin-top: 2rem;
}

.code-editor {
    width: 100%;
    height: 250px;
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
    font-size: 0.875rem;
    padding: 1rem;
    background: var(--background);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 1rem;
    color: var(--foreground);
}

.preview-frame {
    width: 100%;
    height: 100%;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card);
}

/* Modern Component Styles */
.btn {
    padding: 0.5rem 1rem;
    border: none;
    border-radius: var(--radius);
    font-weight: 500;
    font-size: 0.875rem;
    cursor: pointer;
    transition: all 0.15s ease;
    margin-right: 0.5rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
}

.btn-primary {
    background: var(--bumba-gradient);
    color: #000000;
    font-weight: 600;
    border: 1px solid transparent;
    position: relative;
}

.btn-primary:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(255, 221, 0, 0.3);
}

.btn-secondary {
    background: linear-gradient(135deg, #1A1A1A 0%, #0F0F0F 100%);
    color: var(--bumba-wheat);
    border: 1px solid rgba(255, 221, 0, 0.1);
}

.btn-secondary:hover {
    background: linear-gradient(135deg, #2A2A2A 0%, #1A1A1A 100%);
    border-color: rgba(255, 221, 0, 0.3);
}

.btn-success {
    background: hsl(142.1 76.2% 36.3%);
    color: white;
}

.btn-danger {
    background: var(--destructive);
    color: var(--destructive-foreground);
}

.btn-outline {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--foreground);
}

.btn-outline:hover {
    background: var(--accent);
    color: var(--accent-foreground);
}

.card {
    background: var(--card);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    overflow: hidden;
}

.card-elevated {
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
}

.card-header {
    padding: 1.75rem;
    font-weight: 600;
    border-bottom: 1px solid var(--border);
    background: var(--muted);
}

.card-body {
    padding: 2rem;
}

.card-footer {
    padding: 1.25rem 1.75rem;
    border-top: 1px solid var(--border);
    background: var(--muted);
}

.alert {
    padding: 1.25rem 1.5rem;
    border-radius: var(--radius);
    margin-bottom: 1.5rem;
    border: 1px solid;
}

.alert-info {
    background: hsl(214.3 31.8% 91.4% / 0.1);
    border-color: hsl(214.3 31.8% 91.4% / 0.3);
    color: var(--foreground);
}

.alert-success {
    background: hsl(142.1 76.2% 36.3% / 0.1);
    border-color: hsl(142.1 76.2% 36.3% / 0.3);
    color: var(--foreground);
}

.alert-warning {
    background: hsl(47.9 95.8% 53.1% / 0.1);
    border-color: hsl(47.9 95.8% 53.1% / 0.3);
    color: var(--foreground);
}

.alert-error {
    background: var(--destructive) / 0.1;
    border-color: var(--destructive) / 0.3;
    color: var(--foreground);
}

/* Scrollbar Styling */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}

::-webkit-scrollbar-track {
    background: var(--background);
}

::-webkit-scrollbar-thumb {
    background: var(--muted);
    border-radius: var(--radius);
}

::-webkit-scrollbar-thumb:hover {
    background: var(--muted-foreground);
}

/* Component Preview Sections */
.component-preview {
    padding: 2rem;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 1.5rem;
}

.component-note {
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
    font-size: 0.875rem;
    color: var(--muted-foreground);
    margin: 0;
    padding: 0.75rem 1rem;
    background: var(--background);
    border-left: 3px solid var(--bumba-yellow);
    border-radius: 0.25rem;
}

/* View toggle buttons */
.view-toggle {
    display: inline-flex;
    gap: 0.25rem;
    padding: 0.25rem;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-left: auto;
}

.view-toggle button {
    padding: 0.375rem 0.75rem;
    background: var(--background);
    border: 1px solid transparent;
    color: var(--muted-foreground);
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: calc(var(--radius) - 2px);
    cursor: pointer;
    transition: all 0.2s ease;
}

.view-toggle button:hover {
    background: var(--muted);
    color: var(--foreground);
    border-color: rgba(255, 221, 0, 0.1);
}

.view-toggle button.active {
    background: linear-gradient(135deg, #1A1A1A 0%, #0F0F0F 100%);
    color: var(--bumba-wheat);
    border-color: rgba(255, 221, 0, 0.2);
    font-weight: 600;
}`;
  }

  /**
   * Generate JavaScript
   */
  async generateScripts() {
    return `// Catalog Interactive Scripts

document.addEventListener('DOMContentLoaded', function() {
    // Copy button functionality
    document.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const value = this.dataset.value || this.dataset.styles;
            navigator.clipboard.writeText(value).then(() => {
                const originalText = this.textContent;
                this.textContent = 'Copied!';
                setTimeout(() => {
                    this.textContent = originalText;
                }, 2000);
            });
        });
    });

    // View toggle for colors
    const viewToggle = document.querySelector('.view-toggle');
    if (viewToggle) {
        viewToggle.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', function() {
                viewToggle.querySelectorAll('button').forEach(b => b.classList.remove('active'));
                this.classList.add('active');

                const view = this.dataset.view;
                const colorGroups = document.querySelectorAll('.color-group');

                colorGroups.forEach(group => {
                    const grid = group.querySelector('.color-grid');
                    if (grid) {
                        // Reset all views
                        grid.classList.remove('list-view', 'contrast-view');

                        // Apply selected view
                        if (view === 'list') {
                            grid.classList.add('list-view');
                        } else if (view === 'contrast') {
                            grid.classList.add('contrast-view');
                        }
                    }
                });
            });
        });
    }

    // Contrast checker
    const fgInput = document.getElementById('fg-color');
    const bgInput = document.getElementById('bg-color');
    if (fgInput && bgInput) {
        function updateContrast() {
            const fg = fgInput.value;
            const bg = bgInput.value;
            const ratio = calculateContrastRatio(fg, bg);
            document.getElementById('ratio-result').textContent = ratio.toFixed(2);
            document.getElementById('aa-result').textContent = ratio >= 4.5 ? 'PASS' : 'FAIL';
            document.getElementById('aaa-result').textContent = ratio >= 7 ? 'PASS' : 'FAIL';
        }

        fgInput.addEventListener('input', updateContrast);
        bgInput.addEventListener('input', updateContrast);
    }

    // Playground functionality
    const runBtn = document.getElementById('run-playground');
    if (runBtn) {
        runBtn.addEventListener('click', function() {
            const html = document.getElementById('html-editor').value;
            const css = document.getElementById('css-editor').value;
            const frame = document.getElementById('preview-frame');

            const content = \`
                <!DOCTYPE html>
                <html>
                <head>
                    <link rel="stylesheet" href="catalog.css">
                    <style>\${css}</style>
                </head>
                <body>
                    \${html}
                </body>
                </html>
            \`;

            frame.srcdoc = content;
        });

        // Auto-run on load
        runBtn.click();
    }
});

function calculateContrastRatio(fg, bg) {
    // Convert hex to RGB
    const fgRgb = hexToRgb(fg);
    const bgRgb = hexToRgb(bg);

    // Calculate relative luminance
    const fgLum = getLuminance(fgRgb);
    const bgLum = getLuminance(bgRgb);

    // Calculate contrast ratio
    const lighter = Math.max(fgLum, bgLum);
    const darker = Math.min(fgLum, bgLum);

    return (lighter + 0.05) / (darker + 0.05);
}

function hexToRgb(hex) {
    const result = /^#?([a-f\\d]{2})([a-f\\d]{2})([a-f\\d]{2})$/i.exec(hex);
    return result ? {
        r: parseInt(result[1], 16),
        g: parseInt(result[2], 16),
        b: parseInt(result[3], 16)
    } : null;
}

function getLuminance(rgb) {
    const sRGB = [rgb.r / 255, rgb.g / 255, rgb.b / 255];
    const linearRGB = sRGB.map(val => {
        if (val <= 0.03928) {
            return val / 12.92;
        }
        return Math.pow((val + 0.055) / 1.055, 2.4);
    });

    return linearRGB[0] * 0.2126 + linearRGB[1] * 0.7152 + linearRGB[2] * 0.0722;
}`;
  }

  // Helper methods
  countTokens(tokens) {
    if (!tokens) {
      return {
        colors: 0,
        typography: 0,
        spacing: 0,
        shadows: 0,
        total: 0
      };
    }
    return {
      colors: Object.keys(tokens.colors || {}).length,
      typography: Object.keys(tokens.typography || {}).length,
      spacing: Object.keys(tokens.spacing || {}).length,
      shadows: Object.keys(tokens.shadows || {}).length,
      total: Object.values(tokens).reduce((acc, category) =>
        acc + (typeof category === 'object' ? Object.keys(category).length : 0), 0)
    };
  }

  groupColors(colors) {
    const groups = {};
    Object.entries(colors || {}).forEach(([name, value]) => {
      const group = name.split('-')[0] || 'misc';
      if (!groups[group]) groups[group] = {};
      groups[group][name] = value;
    });
    return groups;
  }

  formatGroupName(name) {
    return name.charAt(0).toUpperCase() + name.slice(1).replace(/-/g, ' ');
  }

  formatTypeName(name) {
    return name.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  }

  formatShadowName(name) {
    return name.replace(/-/g, ' ').toUpperCase();
  }

  styleObjectToCSS(styles) {
    return Object.entries(styles)
      .map(([prop, value]) => {
        const cssProp = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
        return `${cssProp}: ${value}`;
      })
      .join('; ');
  }

  generateCSSVariables(tokens) {
    const vars = [];

    Object.entries(tokens).forEach(([category, items]) => {
      if (typeof items === 'object') {
        Object.entries(items).forEach(([name, value]) => {
          if (typeof value === 'object') {
            // Handle complex values like typography
            Object.entries(value).forEach(([prop, val]) => {
              vars.push(`  --${category}-${name}-${prop}: ${val};`);
            });
          } else {
            vars.push(`  --${category}-${name}: ${value};`);
          }
        });
      }
    });

    return vars.join('\n');
  }

  generateQuickPreview(tokens) {
    const previews = [];

    // Add color swatches
    if (tokens.colors) {
      const primaryColors = Object.entries(tokens.colors).slice(0, 4);
      primaryColors.forEach(([name, value]) => {
        previews.push(`<div class="preview-item color-preview" style="background: ${value}" title="${name}"></div>`);
      });
    }

    return previews.join('');
  }

  generateComponentStyles(tokens) {
    // Generate CSS using design tokens for components
    return `
      .btn-primary {
        background: ${tokens.colors?.['brand-primary'] || '#5B21B6'};
      }
      .card {
        box-shadow: ${tokens.shadows?.md || '0 4px 6px rgba(0,0,0,0.1)'};
      }
    `;
  }

  async copyTokenFiles(tokens) {
    // Copy token JSON for reference
    await fs.writeFile(
      path.join(this.outputDir, 'tokens.json'),
      JSON.stringify(tokens, null, 2)
    );
  }

  getComponentNavigation(componentName) {
    const components = this.getShadcnComponents();
    const currentIndex = components.indexOf(componentName);
    const prevComponent = currentIndex > 0 ? components[currentIndex - 1] : null;
    const nextComponent = currentIndex < components.length - 1 ? components[currentIndex + 1] : null;

    const prevSlug = prevComponent ? prevComponent.toLowerCase().replace(/\s+/g, '-') : null;
    const nextSlug = nextComponent ? nextComponent.toLowerCase().replace(/\s+/g, '-') : null;

    return `
      ${prevComponent ?
        `<a href="component-${prevSlug}.html" class="nav-btn" title="${prevComponent}">←</a>` :
        '<button class="nav-btn" disabled>←</button>'}
      ${nextComponent ?
        `<a href="component-${nextSlug}.html" class="nav-btn" title="${nextComponent}">→</a>` :
        '<button class="nav-btn" disabled>→</button>'}
    `;
  }

  getComponentDescription(componentName) {
    const descriptions = {
      'Accordion': 'A vertically stacked set of interactive headings that each reveal an associated section of content.',
      'Alert': 'Displays a callout for user attention.',
      'Alert Dialog': 'A modal dialog that interrupts the user with important content and expects a response.',
      'Aspect Ratio': 'Displays content within a desired ratio.',
      'Avatar': 'An image element with a fallback for representing the user.',
      'Badge': 'Displays a badge or a component that looks like a badge.',
      'Breadcrumb': 'Displays the path to the current resource using a hierarchy of links.',
      'Button': 'Displays a button or a component that looks like a button.',
      'Calendar': 'A date field component that allows users to enter and edit date.',
      'Card': 'Displays a card with header, content, and footer.',
      'Carousel': 'A carousel with motion and swipe built using Embla.',
      'Chart': 'Beautiful charts using Recharts.',
      'Checkbox': 'A control that allows the user to toggle between checked and not checked.',
      'Collapsible': 'An interactive component which expands/collapses a panel.',
      'Combobox': 'Autocomplete input and command palette with a list of suggestions.',
      'Command': 'Fast, composable command menu for React.',
      'Context Menu': 'Displays a menu to the user on right click.',
      'Data Table': 'Powerful table and datagrid built using TanStack Table.',
      'Date Picker': 'A date picker component with range and presets.',
      'Dialog': 'A window overlaid on either the primary window or another dialog window.',
      'Drawer': 'A drawer component built on top of Vaul.',
      'Dropdown Menu': 'Displays a menu to the user.',
      'React Hook Form': 'Building forms with React Hook Form and Zod.',
      'Hover Card': 'For sighted users to preview content available behind a link.',
      'Input': 'Displays a form input field or a component that looks like an input field.',
      'Input OTP': 'Accessible one-time password component with copy paste functionality.',
      'Label': 'Renders an accessible label associated with controls.',
      'Menubar': 'A visually persistent menu common in desktop applications.',
      'Navigation Menu': 'A collection of links for navigating websites.',
      'Pagination': 'Pagination with page navigation, next and previous links.',
      'Popover': 'Displays rich content in a portal, triggered by a button.',
      'Progress': 'Displays an indicator showing the completion progress of a task.',
      'Radio Group': 'A set of checkable buttons where no more than one can be checked at a time.',
      'Resizable': 'Accessible resizable panel groups and layouts with keyboard support.',
      'Scroll-area': 'Augments native scroll functionality for custom, cross-browser styling.',
      'Select': 'Displays a list of options for the user to pick from.',
      'Separator': 'Visually or semantically separates content.',
      'Sheet': 'Extends the Dialog component to display content that complements the main content of the screen.',
      'Sidebar': 'A composable sidebar component for navigation.',
      'Skeleton': 'Use to show a placeholder while content is loading.',
      'Slider': 'An input where the user selects a value from within a given range.',
      'Sonner': 'An opinionated toast component for React.',
      'Switch': 'A control that allows the user to toggle between checked and not checked.',
      'Table': 'A responsive table component.',
      'Tabs': 'A set of layered sections of content known as tab panels.',
      'Textarea': 'Displays a form textarea or a component that looks like a textarea.',
      'Toast': 'A succinct message that is displayed temporarily.',
      'Toggle': 'A two-state button that can be either on or off.',
      'Toggle Group': 'A set of two-state buttons that can be toggled on or off.',
      'Tooltip': 'A popup that displays information related to an element.',
      'Typography': 'Styles for headings, paragraphs, lists...etc'
    };
    return descriptions[componentName] || 'Component documentation and examples.';
  }

  getComponentExample(componentName) {
    // Return a basic example structure for each component
    const examples = {
      'Button': '<button class="btn btn-primary">Click me</button>',
      'Input': '<input type="text" class="input" placeholder="Enter text..." />',
      'Card': `<div class="card">
        <div class="card-header">Card Title</div>
        <div class="card-body">Card content goes here</div>
      </div>`,
      'Alert': '<div class="alert alert-info">This is an alert message</div>',
      'Badge': '<span class="badge badge-primary">New</span>',
      'Switch': '<label class="switch"><input type="checkbox" /><span class="slider"></span></label>',
      'Checkbox': '<label><input type="checkbox" /> Check me</label>',
      'Radio Group': `<div class="radio-group">
        <label><input type="radio" name="option" value="1" /> Option 1</label>
        <label><input type="radio" name="option" value="2" /> Option 2</label>
      </div>`,
      'Select': `<select class="select">
        <option>Option 1</option>
        <option>Option 2</option>
        <option>Option 3</option>
      </select>`,
      'Textarea': '<textarea class="textarea" placeholder="Enter your message..."></textarea>',
      'Label': '<label for="email">Email Address</label>',
      'Separator': '<hr class="separator" />',
      'Avatar': '<img class="avatar" src="/placeholder.jpg" alt="User" />',
      'Skeleton': '<div class="skeleton skeleton-text"></div>',
      'Progress': '<progress class="progress" value="70" max="100">70%</progress>',
      'Slider': '<input type="range" class="slider" min="0" max="100" value="50" />',
      'Toggle': '<button class="toggle" aria-pressed="false">Toggle</button>',
      'Tabs': `<div class="tabs">
        <div class="tab-list">
          <button class="tab active">Tab 1</button>
          <button class="tab">Tab 2</button>
        </div>
        <div class="tab-panel">Tab 1 Content</div>
      </div>`
    };
    return examples[componentName] || '<div class="component-placeholder">Component example will be shown here</div>';
  }

  getComponentUsage(componentName) {
    const slug = componentName.toLowerCase().replace(/\s+/g, '-');
    return `import { ${componentName.replace(/\s+/g, '')} } from '@/components/ui/${slug}'

export function Example() {
  return (
    <${componentName.replace(/\s+/g, '')} />
  )
}`;
  }

  getComponentProps(componentName) {
    // Return basic props structure
    const commonProps = `
      <div class="prop-item">
        <span class="prop-name">className</span>
        <span class="prop-type">string</span>
        <div class="prop-description">Additional CSS classes to apply</div>
      </div>
      <div class="prop-item">
        <span class="prop-name">children</span>
        <span class="prop-type">ReactNode</span>
        <div class="prop-description">Content to render inside the component</div>
      </div>
      <div class="prop-item">
        <span class="prop-name">disabled</span>
        <span class="prop-type">boolean</span>
        <div class="prop-description">Whether the component is disabled</div>
      </div>
    `;
    return commonProps;
  }
}

module.exports = VisualCatalogGenerator;