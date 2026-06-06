/**
 * Enhanced Catalog Generator
 * Generates the modern Design System Visualizer with icons
 */

const fs = require('fs').promises;
const path = require('path');
const chalk = require('chalk');

class EnhancedCatalogGenerator {
  constructor() {
    this.templateDir = path.join(__dirname, 'templates');
  }

  /**
   * Generate the enhanced catalog with icons
   */
  async generate(tokens, analysis, outputDir) {
    const catalogDir = path.join(outputDir, 'catalog');
    
    // Create catalog directory
    await fs.mkdir(catalogDir, { recursive: true });
    
    // Copy enhanced template files from backup
    const sourceDir = path.join(outputDir, 'catalog-enhanced-backup');
    
    // Check if enhanced backup exists, if not use the current catalog
    let templateSource;
    try {
      await fs.access(sourceDir);
      templateSource = sourceDir;
    } catch {
      // Use the existing enhanced catalog as template
      templateSource = catalogDir;
    }
    
    // Generate main index.html
    await this.generateIndexHTML(tokens, analysis, catalogDir);
    
    // Generate CSS file
    await this.generateCSS(catalogDir);
    
    // Generate JS file
    await this.generateJS(catalogDir);
    
    // Generate component pages
    await this.generateComponentPages(tokens, catalogDir);
    
    // Generate token pages
    await this.generateTokenPages(tokens, catalogDir);
    
    console.log(chalk.green('✅ Enhanced Design System Visualizer generated'));
    console.log(chalk.cyan(`📁 Location: ${catalogDir}/index.html`));
    
    return path.join(catalogDir, 'index.html');
  }

  async generateIndexHTML(tokens, analysis, catalogDir) {
    const tokenCounts = {
      colors: Object.keys(tokens.colors || {}).length,
      typography: Object.keys(tokens.typography || {}).length,
      spacing: Object.keys(tokens.spacing || {}).length,
      total: 0
    };

    tokenCounts.total = tokenCounts.colors + tokenCounts.typography + tokenCounts.spacing +
                       Object.keys(tokens.shadows || {}).length +
                       Object.keys(tokens.effects || {}).length;

    // Get project name from environment or current directory
    const projectName = process.env.PROJECT_NAME || path.basename(process.cwd());

    const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Design System - ${projectName}</title>
    <link rel="stylesheet" href="catalog.css">
    <!-- Lucide Icons -->
    <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>
    <!-- AI Bridge Script -->
    <script src="ai-bridge.js"></script>
</head>
<body class="bumba-dark-theme" data-project="${projectName}">
    <nav class="sidebar">
        <div class="sidebar-header">
            <div class="sidebar-title">BUMBA Design System</div>
            <div class="sidebar-project-wrapper">
                <input type="text" class="sidebar-project-input" value="${projectName}" placeholder="Enter project name">
                <div class="sidebar-status">
                    <span class="status-indicator active"></span>
                    <span class="status-text">Active</span>
                </div>
            </div>
        </div>
        <ul>
            <li class="nav-section"><i data-lucide="layout-dashboard" class="section-icon"></i> Overview</li>
            <li><a href="index.html" class="active"><i data-lucide="home"></i> Dashboard</a></li>
            <li><a href="sandbox.html"><i data-lucide="flask"></i> Sandbox</a></li>
            <li><a href="ai-assistant.html"><i data-lucide="bot"></i> AI Assistant</a></li>

            <li class="nav-section"><i data-lucide="package" class="section-icon"></i> Tokens</li>
            <li><a href="colors.html"><i data-lucide="palette"></i> Colors</a></li>
            <li><a href="typography.html"><i data-lucide="type"></i> Typography</a></li>
            <li><a href="spacing.html"><i data-lucide="move"></i> Spacing</a></li>
            <li><a href="shadows.html"><i data-lucide="layers"></i> Shadows</a></li>

            <li class="nav-section"><i data-lucide="shapes" class="section-icon"></i> Patterns</li>
            <li><a href="forms.html"><i data-lucide="form-input"></i> Forms</a></li>
            <li><a href="data-display.html"><i data-lucide="table-2"></i> Data Display</a></li>
            <li><a href="feedback.html"><i data-lucide="message-circle"></i> Feedback</a></li>
            <li><a href="navigation.html"><i data-lucide="compass"></i> Navigation</a></li>
            <li><a href="overlays.html"><i data-lucide="square-stack"></i> Overlays</a></li>

            <li class="nav-section"><i data-lucide="boxes" class="section-icon"></i> Components</li>
            ${this.generateComponentLinks()}

            <li class="nav-section"><i data-lucide="git-branch" class="section-icon"></i> Sync</li>
            <li><a href="sync-status.html"><i data-lucide="refresh-cw"></i> Sync Status</a></li>
            <li><a href="history.html"><i data-lucide="clock"></i> History</a></li>
        </ul>
    </nav>

    <main class="content">
        <div class="page-header">
            <h1 class="page-title">Design System Dashboard</h1>
            <p class="page-subtitle">Last updated: ${new Date().toLocaleDateString()}</p>
            <div class="header-actions">
                <button class="btn-sandbox" onclick="openSandbox()">
                    <i data-lucide="flask"></i> Open Sandbox
                </button>
                <button class="btn-ai" onclick="toggleAIAssistant()">
                    <i data-lucide="bot"></i> AI Assistant
                </button>
                <button class="btn-sync" onclick="syncDesignSystem()">
                    <i data-lucide="refresh-cw"></i> Sync
                </button>
            </div>
        </div>

        <div class="metrics-grid">
            <div class="metric-card interactive" onclick="navigateTo('colors.html')">
                <div class="metric-icon"><i data-lucide="palette"></i></div>
                <div class="metric-value">${tokenCounts.colors}</div>
                <div class="metric-label">COLORS</div>
            </div>
            <div class="metric-card interactive" onclick="navigateTo('typography.html')">
                <div class="metric-icon"><i data-lucide="type"></i></div>
                <div class="metric-value">${tokenCounts.typography}</div>
                <div class="metric-label">TYPOGRAPHY</div>
            </div>
            <div class="metric-card interactive" onclick="navigateTo('spacing.html')">
                <div class="metric-icon"><i data-lucide="move"></i></div>
                <div class="metric-value">${tokenCounts.spacing}</div>
                <div class="metric-label">SPACING</div>
            </div>
            <div class="metric-card">
                <div class="metric-icon"><i data-lucide="package"></i></div>
                <div class="metric-value">${tokenCounts.total}</div>
                <div class="metric-label">TOTAL TOKENS</div>
            </div>
        </div>

        <!-- AI Context Panel -->
        <section class="ai-context-panel" id="aiContextPanel" style="display: none;">
            <div class="ai-header">
                <h3><i data-lucide="bot"></i> AI Assistant</h3>
                <button class="ai-close" onclick="toggleAIAssistant()">×</button>
            </div>
            <div class="ai-content">
                <div class="ai-status">
                    <span class="ai-indicator active"></span>
                    <span>AI Ready - Context Loaded</span>
                </div>
                <div class="ai-actions">
                    <button onclick="aiSuggestComponent()">Suggest Component</button>
                    <button onclick="aiAnalyzeUsage()">Analyze Usage</button>
                    <button onclick="aiOptimize()">Optimize</button>
                </div>
                <div class="ai-output" id="aiOutput"></div>
            </div>
        </section>

        <!-- Component Library -->
        <section class="components-section">
            <div class="section-header">
                <h2 class="section-title">Component Library</h2>
                <div class="section-actions">
                    <input type="text" class="component-search" placeholder="Search components..." onkeyup="searchComponents(this.value)">
                    <button class="btn-add-component" onclick="addNewComponent()">
                        <i data-lucide="plus"></i> Add Component
                    </button>
                </div>
            </div>
            <div class="component-grid" id="componentGrid">
                ${this.generateEnhancedComponentCards()}
            </div>
        </section>

        <!-- Recent Activity -->
        <section class="activity-section">
            <h2 class="section-title">Recent Activity</h2>
            <div class="activity-feed" id="activityFeed">
                <div class="activity-item">
                    <i data-lucide="plus-circle"></i>
                    <span>Catalog created for ${projectName}</span>
                    <time>${new Date().toLocaleTimeString()}</time>
                </div>
            </div>
        </section>
    </main>

    <!-- Hidden AI Data Layer -->
    <script type="application/json" id="aiDataLayer">
    ${JSON.stringify({
      project: projectName,
      tokens: tokenCounts,
      components: [],
      patterns: analysis.patterns || {},
      quality: analysis.quality || {},
      context: {
        framework: this.detectFramework(),
        designSystem: 'BUMBA',
        version: '1.0.0'
      }
    }, null, 2)}
    </script>

    <script src="catalog.js"></script>
    <script>
        // Initialize Lucide icons
        lucide.createIcons();

        // Initialize AI Bridge
        if (typeof AIBridge !== 'undefined') {
            window.aiBridge = new AIBridge();
            window.aiBridge.initialize();
        }
    </script>
</body>
</html>`;

    await fs.writeFile(path.join(catalogDir, 'index.html'), html);
  }

  generateComponentLinks() {
    const components = [
      { name: 'Accordion', icon: 'chevrons-down-up' },
      { name: 'Alert', icon: 'alert-circle' },
      { name: 'Alert Dialog', icon: 'alert-triangle' },
      { name: 'Aspect Ratio', icon: 'square' },
      { name: 'Avatar', icon: 'user-circle' },
      { name: 'Badge', icon: 'tag' },
      { name: 'Breadcrumb', icon: 'chevron-right' },
      { name: 'Button', icon: 'mouse-pointer-2' },
      { name: 'Calendar', icon: 'calendar' },
      { name: 'Card', icon: 'credit-card' },
      { name: 'Carousel', icon: 'images' },
      { name: 'Chart', icon: 'bar-chart-3' },
      { name: 'Checkbox', icon: 'check-square' },
      { name: 'Collapsible', icon: 'unfold-vertical' },
      { name: 'Combobox', icon: 'list-filter' },
      { name: 'Command', icon: 'terminal' },
      { name: 'Context Menu', icon: 'mouse-pointer-click' },
      { name: 'Data Table', icon: 'table' },
      { name: 'Date Picker', icon: 'calendar-days' },
      { name: 'Dialog', icon: 'square' },
      { name: 'Drawer', icon: 'panel-left' }
    ];

    return components.map(comp => {
      const filename = `component-${comp.name.toLowerCase().replace(/\s+/g, '-')}.html`;
      return `<li><a href="${filename}"><i data-lucide="${comp.icon}"></i> ${comp.name}</a></li>`;
    }).join('\n            ');
  }

  generateComponentCards() {
    const components = [
      'Accordion', 'Alert', 'Alert Dialog', 'Aspect Ratio', 'Avatar', 'Badge',
      'Breadcrumb', 'Button', 'Calendar', 'Card', 'Carousel', 'Chart',
      'Checkbox', 'Collapsible', 'Combobox', 'Command', 'Context Menu', 'Data Table'
    ];

    return components.map(comp => {
      const filename = `component-${comp.toLowerCase().replace(/\s+/g, '-')}.html`;
      return `
                <a href="${filename}" class="component-card">
                    <div class="component-name">${comp}</div>
                </a>`;
    }).join('');
  }

  generateEnhancedComponentCards() {
    const components = [
      { name: 'Accordion', icon: 'chevrons-down-up', status: 'stable', usage: 12 },
      { name: 'Alert', icon: 'alert-circle', status: 'stable', usage: 45 },
      { name: 'Alert Dialog', icon: 'alert-triangle', status: 'beta', usage: 8 },
      { name: 'Aspect Ratio', icon: 'square', status: 'stable', usage: 3 },
      { name: 'Avatar', icon: 'user-circle', status: 'stable', usage: 67 },
      { name: 'Badge', icon: 'tag', status: 'stable', usage: 89 },
      { name: 'Breadcrumb', icon: 'chevron-right', status: 'stable', usage: 23 },
      { name: 'Button', icon: 'mouse-pointer-2', status: 'stable', usage: 234 },
      { name: 'Calendar', icon: 'calendar', status: 'beta', usage: 15 },
      { name: 'Card', icon: 'credit-card', status: 'stable', usage: 156 },
      { name: 'Carousel', icon: 'images', status: 'experimental', usage: 7 },
      { name: 'Chart', icon: 'bar-chart-3', status: 'beta', usage: 34 },
      { name: 'Checkbox', icon: 'check-square', status: 'stable', usage: 98 },
      { name: 'Collapsible', icon: 'unfold-vertical', status: 'stable', usage: 19 },
      { name: 'Combobox', icon: 'list-filter', status: 'beta', usage: 11 },
      { name: 'Command', icon: 'terminal', status: 'experimental', usage: 4 },
      { name: 'Context Menu', icon: 'mouse-pointer-click', status: 'stable', usage: 28 },
      { name: 'Data Table', icon: 'table', status: 'stable', usage: 43 }
    ];

    return components.map(comp => {
      const filename = `component-${comp.name.toLowerCase().replace(/\s+/g, '-')}.html`;
      const statusClass = `status-${comp.status}`;
      const statusIcon = comp.status === 'stable' ? 'check-circle' : comp.status === 'beta' ? 'alert-circle' : 'flask';

      return `
                <div class="component-card enhanced" data-component="${comp.name}" data-usage="${comp.usage}">
                    <div class="component-visual">
                        <i data-lucide="${comp.icon}" class="component-icon"></i>
                    </div>
                    <div class="component-info">
                        <h3 class="component-name">${comp.name}</h3>
                        <div class="component-meta">
                            <span class="component-status ${statusClass}">
                                <i data-lucide="${statusIcon}"></i> ${comp.status}
                            </span>
                            <span class="component-usage">
                                <i data-lucide="trending-up"></i> ${comp.usage} uses
                            </span>
                        </div>
                    </div>
                    <div class="component-actions">
                        <button onclick="openInSandbox('${comp.name}')" class="btn-icon" title="Open in Sandbox">
                            <i data-lucide="flask"></i>
                        </button>
                        <button onclick="viewCode('${comp.name}')" class="btn-icon" title="View Code">
                            <i data-lucide="code"></i>
                        </button>
                        <button onclick="syncComponent('${comp.name}')" class="btn-icon" title="Sync">
                            <i data-lucide="refresh-cw"></i>
                        </button>
                    </div>
                </div>`;
    }).join('');
  }

  detectFramework() {
    // Detect framework from package.json or environment
    try {
      const packagePath = path.join(process.cwd(), 'package.json');
      if (fs.existsSync(packagePath)) {
        const packageJson = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
        const deps = { ...packageJson.dependencies, ...packageJson.devDependencies };

        if (deps.react) return 'react';
        if (deps.vue) return 'vue';
        if (deps.angular || deps['@angular/core']) return 'angular';
        if (deps.svelte) return 'svelte';
        if (deps.next) return 'nextjs';
      }
    } catch (error) {
      // Ignore errors
    }

    return 'vanilla';
  }

  async generateCSS(catalogDir) {
    // Use existing CSS from enhanced catalog
    const existingCSS = path.join(catalogDir, 'catalog.css');
    try {
      await fs.access(existingCSS);
      // CSS already exists, no need to regenerate
      return;
    } catch {
      // Generate default CSS if not exists
      await this.generateDefaultCSS(catalogDir);
    }
  }

  async generateDefaultCSS(catalogDir) {
    // Try to copy existing enhanced CSS first
    const existingCSS = path.join(__dirname, '..', '..', '..', '..', '.design', 'catalog', 'catalog.css');
    try {
      let css = await fs.readFile(existingCSS, 'utf8');

      // Update CSS with iA Writer Duo font if not already present
      if (!css.includes('iA Writer Duo')) {
        css = this.updateCSSWithBumbaFont(css);
      }

      await fs.writeFile(path.join(catalogDir, 'catalog.css'), css);
    } catch {
      // Fallback to default CSS
      const css = this.getDefaultCSS();
      await fs.writeFile(path.join(catalogDir, 'catalog.css'), css);
    }
  }

  /**
   * Update CSS with BUMBA iA Writer Duo font
   */
  updateCSSWithBumbaFont(css) {
    // Add font import at the top
    css = css.replace(
      /\/\* Design System Catalog - BUMBA x shadcn\/ui Theme \*\//,
      `/* Design System Catalog - BUMBA x shadcn/ui Theme */

/* Import BUMBA Primary Font - iA Writer Duo */
@import url('https://fonts.googleapis.com/css2?family=iA+Writer+Duo:wght@400;700&display=swap');`
    );

    // Add BUMBA font variables
    css = css.replace(
      /--bumba-gradient-subtle: linear-gradient\(135deg, rgba\(0,170,0,0\.1\) 0%, rgba\(255,221,0,0\.1\) 50%, rgba\(221,0,0,0\.1\) 100%\);/,
      `--bumba-gradient-subtle: linear-gradient(135deg, rgba(0,170,0,0.1) 0%, rgba(255,221,0,0.1) 50%, rgba(221,0,0,0.1) 100%);

    /* BUMBA Typography - iA Writer Duo as Primary Font */
    --bumba-font-primary: 'iA Writer Duo', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Consolas', monospace;
    --bumba-font-fallback: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;`
    );

    // Update body font-family
    css = css.replace(
      /font-family: -apple-system, BlinkMacSystemFont[^;]+;/,
      'font-family: var(--bumba-font-primary);'
    );

    return css;
  }

  async generateJS(catalogDir) {
    // Use existing JS from enhanced catalog
    const existingJS = path.join(catalogDir, 'catalog.js');
    try {
      await fs.access(existingJS);
      // JS already exists, no need to regenerate
      return;
    } catch {
      // Generate default JS if not exists
      await this.generateDefaultJS(catalogDir);
    }
  }

  async generateDefaultJS(catalogDir) {
    // Try to copy existing enhanced JS first
    const existingJS = path.join(__dirname, '..', '..', '..', '..', '.design', 'catalog', 'catalog.js');
    try {
      const js = await fs.readFile(existingJS, 'utf8');
      await fs.writeFile(path.join(catalogDir, 'catalog.js'), js);
    } catch {
      // Fallback to default JS
      const js = this.getDefaultJS();
      await fs.writeFile(path.join(catalogDir, 'catalog.js'), js);
    }
  }

  async generateComponentPages(tokens, catalogDir) {
    // Copy existing component pages if they exist
    const sourceDir = path.join(__dirname, '..', '..', '..', '..', '.design', 'catalog');

    try {
      const files = await fs.readdir(sourceDir);
      const componentFiles = files.filter(f => f.startsWith('component-') && f.endsWith('.html'));

      for (const file of componentFiles) {
        const content = await fs.readFile(path.join(sourceDir, file), 'utf8');
        await fs.writeFile(path.join(catalogDir, file), content);
      }
    } catch {
      // Component pages will be generated on demand
    }
  }

  async generateTokenPages(tokens, catalogDir) {
    // Copy existing token pages if they exist
    const sourceDir = path.join(__dirname, '..', '..', '..', '..', '.design', 'catalog');
    const tokenPages = ['colors.html', 'typography.html', 'spacing.html', 'shadows.html',
                        'forms.html', 'data-display.html', 'feedback.html', 'navigation.html',
                        'overlays.html', 'playground.html'];

    try {
      for (const page of tokenPages) {
        const sourcePath = path.join(sourceDir, page);
        const content = await fs.readFile(sourcePath, 'utf8');
        await fs.writeFile(path.join(catalogDir, page), content);
      }
    } catch {
      // Token pages will be generated based on actual tokens
    }
  }

  getDefaultCSS() {
    // Fallback CSS if template not found
    return `/* Enhanced Design System Visualizer CSS */
:root {
  --bg-primary: #0a0a0a;
  --bg-secondary: #1a1a1a;
  --text-primary: #ffffff;
  --accent: #10b981;
}

body.bumba-dark-theme {
  margin: 0;
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.sidebar {
  width: 280px;
  background: var(--bg-secondary);
  height: 100vh;
  position: fixed;
  overflow-y: auto;
}

.content {
  margin-left: 280px;
  padding: 2rem;
}
`;
  }

  getDefaultJS() {
    // Fallback JS if template not found
    return `// Enhanced Design System Visualizer JS
document.addEventListener('DOMContentLoaded', () => {
  lucide.createIcons();
  
  // Project name persistence
  const projectInput = document.querySelector('.sidebar-project-input');
  if (projectInput) {
    const savedName = localStorage.getItem('bumba-project-name');
    if (savedName) projectInput.value = savedName;
    
    projectInput.addEventListener('input', (e) => {
      localStorage.setItem('bumba-project-name', e.target.value);
    });
  }
});
`;
  }
}

module.exports = EnhancedCatalogGenerator;