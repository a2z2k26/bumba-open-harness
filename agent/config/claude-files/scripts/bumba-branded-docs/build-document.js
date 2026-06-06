#!/usr/bin/env node
/**
 * build-document.js
 * Main orchestrator for building branded HTML documents
 *
 * Usage:
 *   node build-document.js --template presentation --content content.html --output output.html --title "My Pitch"
 *   node build-document.js --template document --content content.html --title "Proposal"
 *
 * Options:
 *   --template    Template type: presentation, document, one-pager
 *   --content     Path to HTML content file (body content only)
 *   --output      Output path (default: .design/docs/[type]/[title]-[date].html)
 *   --title       Document title
 *   --project     Project path (default: current directory)
 */

const fs = require('fs');
const path = require('path');
const { generateBrandCSS, getTokenSummary } = require('./inject-tokens');
const { loadDesignTokens } = require('./load-design-tokens');

// Parse command line arguments
function parseArgs() {
  const args = {};
  const argv = process.argv.slice(2);

  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const value = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
      args[key] = value;
    }
  }

  return args;
}

// Get template path
function getTemplatePath(templateName) {
  const templatesDir = path.join(process.env.HOME, '.claude', 'templates', 'bumba-branded-docs');
  return path.join(templatesDir, `${templateName}.html`);
}

// Get base CSS path
function getBaseCSSPath() {
  return path.join(process.env.HOME, '.claude', 'templates', 'bumba-branded-docs', 'shared', 'base.css');
}

// Generate output path
function generateOutputPath(projectPath, templateType, title) {
  const date = new Date().toISOString().split('T')[0];
  const safeName = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');

  const typeDir = templateType === 'presentation' ? 'presentations'
    : templateType === 'one-pager' ? 'one-pagers'
    : 'documents';

  const docsDir = path.join(projectPath, '.design', 'docs', typeDir);

  // Create directory if it doesn't exist
  if (!fs.existsSync(docsDir)) {
    fs.mkdirSync(docsDir, { recursive: true });
  }

  return path.join(docsDir, `${safeName}-${date}.html`);
}

// Load template file
function loadTemplate(templatePath) {
  if (!fs.existsSync(templatePath)) {
    // Return a basic template if file doesn't exist
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{TITLE}}</title>
  <style>
{{BRAND_CSS}}
{{BASE_CSS}}
  </style>
</head>
<body>
{{CONTENT}}
</body>
</html>`;
  }

  return fs.readFileSync(templatePath, 'utf8');
}

// Load base CSS
function loadBaseCSS() {
  const baseCSSPath = getBaseCSSPath();
  if (!fs.existsSync(baseCSSPath)) {
    return '';
  }
  return fs.readFileSync(baseCSSPath, 'utf8');
}

// Build the document
function buildDocument(options) {
  const {
    template = 'document',
    content = '',
    title = 'Untitled Document',
    project = process.cwd(),
    output
  } = options;

  // Load design tokens and generate CSS
  let brandCSS;
  let tokenSummary;
  try {
    brandCSS = generateBrandCSS(project);
    tokenSummary = getTokenSummary(loadDesignTokens(project));
  } catch (error) {
    console.error(`Error loading design tokens: ${error.message}`);
    console.error('Make sure .design/tokens/ exists with token files.');
    process.exit(1);
  }

  // Load template
  const templatePath = getTemplatePath(template);
  let html = loadTemplate(templatePath);

  // Load base CSS
  const baseCSS = loadBaseCSS();

  // Load content if it's a file path
  let contentHTML = content;
  if (content && fs.existsSync(content)) {
    contentHTML = fs.readFileSync(content, 'utf8');
  }

  // Replace placeholders
  html = html
    .replace('{{TITLE}}', title)
    .replace('{{BRAND_CSS}}', brandCSS)
    .replace('{{BASE_CSS}}', baseCSS)
    .replace('{{CONTENT}}', contentHTML)
    .replace('{{DATE}}', new Date().toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    }));

  // Determine output path
  const outputPath = output || generateOutputPath(project, template, title);

  // Ensure output directory exists
  const outputDir = path.dirname(outputPath);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  // Write the file
  fs.writeFileSync(outputPath, html, 'utf8');

  return {
    outputPath,
    tokenSummary,
    template
  };
}

// Main CLI execution
if (require.main === module) {
  const args = parseArgs();

  if (args.help) {
    console.log(`
build-document.js - Build branded HTML documents

Usage:
  node build-document.js [options]

Options:
  --template    Template type: presentation, document, one-pager (default: document)
  --content     HTML content or path to content file
  --output      Output file path (default: .design/docs/[type]/[title]-[date].html)
  --title       Document title (default: "Untitled Document")
  --project     Project path (default: current directory)
  --help        Show this help message

Example:
  node build-document.js --template presentation --title "Investor Pitch" --content slides.html
`);
    process.exit(0);
  }

  try {
    const result = buildDocument({
      template: args.template,
      content: args.content,
      title: args.title,
      project: args.project,
      output: args.output
    });

    console.log(`\nCreated: ${result.outputPath}`);
    console.log('\nBrand applied:');

    if (result.tokenSummary.colors.primary) {
      console.log(`  Primary: ${result.tokenSummary.colors.primary}`);
    }
    if (result.tokenSummary.colors.secondary) {
      console.log(`  Secondary: ${result.tokenSummary.colors.secondary}`);
    }
    if (result.tokenSummary.typography.heading) {
      console.log(`  Heading font: ${result.tokenSummary.typography.heading}`);
    }
    if (result.tokenSummary.typography.body) {
      console.log(`  Body font: ${result.tokenSummary.typography.body}`);
    }

    console.log('\nTo create PDF: Open in browser → Print (Cmd+P) → Save as PDF');

  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

module.exports = {
  buildDocument,
  generateOutputPath,
  loadTemplate
};
