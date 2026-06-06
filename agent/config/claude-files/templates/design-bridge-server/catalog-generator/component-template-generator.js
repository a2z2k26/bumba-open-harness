/**
 * Component Template Generator for BUMBA Design System
 * Creates shadcn/ui-style component documentation pages
 */

const fs = require('fs').promises;
const path = require('path');

class ComponentTemplateGenerator {
    constructor(config = {}) {
        this.config = {
            projectName: config.projectName || 'BUMBA-CLI-1.0',
            outputDir: config.outputDir || '.design/catalog/catalog',
            componentsDir: config.componentsDir || 'src/components',
            ...config
        };
    }

    /**
     * Generate a component documentation page
     */
    async generateComponentPage(componentData) {
        const {
            name,
            description,
            category,
            installation,
            usage,
            examples,
            props,
            variants,
            accessibility,
            apiReference
        } = componentData;

        const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${name} - BUMBA Design System</title>
    <link rel="stylesheet" href="catalog-enhanced.css">
    <link rel="stylesheet" href="component-page.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css">
    <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-jsx.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-typescript.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-bash.min.js"></script>
</head>
<body class="bumba-dark-theme">
    ${this.generateSidebar(category, name)}

    <main class="component-content">
        <!-- Component Header -->
        <div class="component-header">
            <div class="component-header-content">
                <h1 class="component-title">${name}</h1>
                <p class="component-description">${description}</p>
                <div class="component-badges">
                    ${this.generateBadges(componentData)}
                </div>
            </div>
            <div class="component-actions">
                <button class="btn-view-source" onclick="viewSource()">
                    <i data-lucide="code"></i>
                    View Source
                </button>
                <button class="btn-copy-import" onclick="copyImport()">
                    <i data-lucide="copy"></i>
                    Copy Import
                </button>
            </div>
        </div>

        <!-- Installation Section -->
        <section class="doc-section">
            <h2 class="section-title">Installation</h2>
            <div class="installation-tabs">
                <div class="tab-list">
                    <button class="tab-button active" data-tab="cli">CLI</button>
                    <button class="tab-button" data-tab="manual">Manual</button>
                </div>
                <div class="tab-content">
                    <div id="cli" class="tab-panel active">
                        <pre class="code-block"><code class="language-bash">${installation.cli || `npx bumba-cli add ${name.toLowerCase()}`}</code></pre>
                    </div>
                    <div id="manual" class="tab-panel">
                        <div class="manual-steps">
                            <p class="step-title">1. Install dependencies</p>
                            <pre class="code-block"><code class="language-bash">${installation.dependencies || 'npm install @bumba/ui'}</code></pre>

                            <p class="step-title">2. Copy the component</p>
                            <pre class="code-block"><code class="language-jsx">${installation.component || this.generateDefaultComponent(name)}</code></pre>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- Usage Section -->
        <section class="doc-section">
            <h2 class="section-title">Usage</h2>
            <div class="usage-example">
                <pre class="code-block"><code class="language-jsx">${usage.import || `import { ${name} } from "@/components/ui/${name.toLowerCase()}"`}

${usage.basic || `<${name} />`}</code></pre>
            </div>
        </section>

        <!-- Examples Section -->
        <section class="doc-section">
            <h2 class="section-title">Examples</h2>
            <div class="examples-container">
                ${this.generateExamples(examples)}
            </div>
        </section>

        <!-- API Reference Section -->
        ${props ? this.generatePropsSection(props) : ''}

        <!-- Variants Section -->
        ${variants ? this.generateVariantsSection(variants) : ''}

        <!-- Accessibility Section -->
        ${accessibility ? this.generateAccessibilitySection(accessibility) : ''}

        <!-- API Documentation -->
        ${apiReference ? this.generateAPISection(apiReference) : ''}
    </main>

    <script src="component-page.js"></script>
</body>
</html>`;

        return html;
    }

    /**
     * Generate sidebar navigation
     */
    generateSidebar(activeCategory, activeComponent) {
        return `
    <nav class="sidebar">
        <div class="sidebar-header">
            <div class="sidebar-title">BUMBA CLI 1.0</div>
            <div class="sidebar-project-wrapper">
                <input type="text" class="sidebar-project-input" value="Project Title" readonly>
                <div class="sidebar-status">
                    <span class="status-indicator bumba-active"></span>
                    <span class="status-text">Active</span>
                </div>
            </div>
        </div>
        <ul>
            <li class="nav-section">
                <i data-lucide="book-open" class="section-icon"></i>
                Getting Started
            </li>
            <li><a href="introduction.html"><i data-lucide="info"></i> Introduction</a></li>
            <li><a href="installation.html"><i data-lucide="download"></i> Installation</a></li>
            <li><a href="theming.html"><i data-lucide="palette"></i> Theming</a></li>

            <li class="nav-section">
                <i data-lucide="boxes" class="section-icon"></i>
                Components
            </li>
            ${this.generateComponentLinks(activeComponent)}
        </ul>
    </nav>`;
    }

    /**
     * Generate component navigation links
     */
    generateComponentLinks(activeComponent) {
        const components = [
            'Accordion', 'Alert', 'Alert Dialog', 'Aspect Ratio', 'Avatar',
            'Badge', 'Breadcrumb', 'Button', 'Calendar', 'Card',
            'Carousel', 'Chart', 'Checkbox', 'Collapsible', 'Combobox',
            'Command', 'Context Menu', 'Data Table', 'Date Picker', 'Dialog',
            'Drawer', 'Dropdown Menu', 'Form', 'Hover Card', 'Input',
            'Label', 'Menubar', 'Navigation Menu', 'Pagination', 'Popover',
            'Progress', 'Radio Group', 'Scroll Area', 'Select', 'Separator',
            'Sheet', 'Skeleton', 'Slider', 'Switch', 'Table',
            'Tabs', 'Textarea', 'Toast', 'Toggle', 'Toggle Group',
            'Tooltip'
        ];

        return components.map(comp => {
            const isActive = comp === activeComponent ? 'class="active"' : '';
            const fileName = comp.toLowerCase().replace(/\s+/g, '-');
            return `<li><a href="component-${fileName}.html" ${isActive}><i data-lucide="box"></i> ${comp}</a></li>`;
        }).join('\n            ');
    }

    /**
     * Generate component badges
     */
    generateBadges(componentData) {
        const badges = [];

        if (componentData.status) {
            badges.push(`<span class="badge badge-${componentData.status}">${componentData.status}</span>`);
        }

        if (componentData.version) {
            badges.push(`<span class="badge badge-version">v${componentData.version}</span>`);
        }

        if (componentData.radixUI) {
            badges.push(`<span class="badge badge-radix">Radix UI</span>`);
        }

        return badges.join('');
    }

    /**
     * Generate examples section
     */
    generateExamples(examples = []) {
        if (!examples.length) {
            return this.generateDefaultExample();
        }

        return examples.map(example => `
            <div class="example-card">
                <div class="example-header">
                    <h3 class="example-title">${example.title}</h3>
                    ${example.description ? `<p class="example-description">${example.description}</p>` : ''}
                </div>
                <div class="example-preview">
                    <div class="preview-container">
                        ${example.preview || '<!-- Component preview will render here -->'}
                    </div>
                </div>
                <div class="example-code">
                    <div class="code-header">
                        <span class="code-language">${example.language || 'jsx'}</span>
                        <button class="btn-copy-code" onclick="copyCode(this)">
                            <i data-lucide="copy"></i>
                            Copy
                        </button>
                    </div>
                    <pre class="code-block"><code class="language-${example.language || 'jsx'}">${example.code}</code></pre>
                </div>
            </div>
        `).join('');
    }

    /**
     * Generate props documentation
     */
    generatePropsSection(props) {
        return `
        <section class="doc-section">
            <h2 class="section-title">Props</h2>
            <div class="props-table-container">
                <table class="props-table">
                    <thead>
                        <tr>
                            <th>Prop</th>
                            <th>Type</th>
                            <th>Default</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${props.map(prop => `
                        <tr>
                            <td><code>${prop.name}</code></td>
                            <td><code class="type">${prop.type}</code></td>
                            <td>${prop.default ? `<code>${prop.default}</code>` : '-'}</td>
                            <td>${prop.description}</td>
                        </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </section>`;
    }

    /**
     * Generate variants section
     */
    generateVariantsSection(variants) {
        return `
        <section class="doc-section">
            <h2 class="section-title">Variants</h2>
            <div class="variants-grid">
                ${variants.map(variant => `
                <div class="variant-card">
                    <div class="variant-preview">
                        ${variant.preview}
                    </div>
                    <div class="variant-info">
                        <h4 class="variant-name">${variant.name}</h4>
                        <pre class="code-inline"><code>${variant.code}</code></pre>
                    </div>
                </div>
                `).join('')}
            </div>
        </section>`;
    }

    /**
     * Generate accessibility section
     */
    generateAccessibilitySection(accessibility) {
        return `
        <section class="doc-section">
            <h2 class="section-title">Accessibility</h2>
            <div class="accessibility-content">
                <div class="accessibility-features">
                    <h3>Keyboard Navigation</h3>
                    <table class="keyboard-table">
                        <thead>
                            <tr>
                                <th>Key</th>
                                <th>Description</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${(accessibility.keyboard || []).map(key => `
                            <tr>
                                <td><kbd>${key.key}</kbd></td>
                                <td>${key.description}</td>
                            </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
                ${accessibility.ariaLabel ? `
                <div class="aria-info">
                    <h3>ARIA Attributes</h3>
                    <ul>
                        ${accessibility.ariaLabel.map(aria => `<li>${aria}</li>`).join('')}
                    </ul>
                </div>
                ` : ''}
            </div>
        </section>`;
    }

    /**
     * Generate API documentation section
     */
    generateAPISection(apiReference) {
        return `
        <section class="doc-section">
            <h2 class="section-title">API Reference</h2>
            <div class="api-content">
                ${apiReference.map(api => `
                <div class="api-method">
                    <h3 class="api-method-name">${api.method}</h3>
                    <p class="api-method-description">${api.description}</p>
                    <pre class="code-block"><code class="language-typescript">${api.signature}</code></pre>
                    ${api.example ? `
                    <div class="api-example">
                        <h4>Example</h4>
                        <pre class="code-block"><code class="language-jsx">${api.example}</code></pre>
                    </div>
                    ` : ''}
                </div>
                `).join('')}
            </div>
        </section>`;
    }

    /**
     * Generate default component code
     */
    generateDefaultComponent(name) {
        return `import * as React from "react"
import { cn } from "@/lib/utils"

export interface ${name}Props extends React.HTMLAttributes<HTMLDivElement> {
  // Add component props here
}

const ${name} = React.forwardRef<HTMLDivElement, ${name}Props>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn("", className)}
        {...props}
      />
    )
  }
)
${name}.displayName = "${name}"

export { ${name} }`;
    }

    /**
     * Generate default example
     */
    generateDefaultExample() {
        return `
        <div class="example-card">
            <div class="example-header">
                <h3 class="example-title">Default Example</h3>
            </div>
            <div class="example-preview">
                <div class="preview-container">
                    <!-- Component preview -->
                </div>
            </div>
            <div class="example-code">
                <pre class="code-block"><code class="language-jsx">// Example code here</code></pre>
            </div>
        </div>`;
    }

    /**
     * Generate all component pages
     */
    async generateAllPages(components) {
        const outputPath = path.join(process.cwd(), this.config.outputDir);

        for (const component of components) {
            const html = await this.generateComponentPage(component);
            const fileName = `component-${component.name.toLowerCase().replace(/\s+/g, '-')}.html`;
            const filePath = path.join(outputPath, fileName);

            await fs.writeFile(filePath, html, 'utf8');
            console.log(`✅ Generated: ${fileName}`);
        }
    }
}

module.exports = ComponentTemplateGenerator;