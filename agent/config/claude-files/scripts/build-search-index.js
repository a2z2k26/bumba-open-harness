#!/usr/bin/env node
/**
 * build-search-index.js
 * Builds searchable index of all components and tokens
 */

const fs = require('fs');
const path = require('path');

console.log('=== Building Search Index ===\n');

const projectPath = process.cwd();
const designDir = path.join(projectPath, '.design');
const extractedCodeDir = path.join(designDir, 'extracted-code');
const tokensDir = path.join(designDir, 'tokens');
const indexPath = path.join(designDir, '.search-index.json');

// Read config to determine framework
const configPath = path.join(designDir, 'config.json');
if (!fs.existsSync(configPath)) {
  console.error('❌ Error: .design/config.json not found');
  console.error('Run /design-init first');
  process.exit(1);
}

const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const framework = config.project.framework;

console.log(`Framework: ${framework}`);
console.log(`Project: ${projectPath}\n`);

// Initialize index
const index = {
  version: '1.0.0',
  generated: new Date().toISOString(),
  projectPath,
  framework,
  components: {},
  tokens: {},
  categories: {
    layout: [],
    navigation: [],
    form: [],
    'data-display': [],
    feedback: [],
    overlay: []
  },
  statistics: {
    totalComponents: 0,
    totalTokens: 0,
    categorized: 0,
    uncategorized: 0
  }
};

// Index components
const frameworkDir = path.join(extractedCodeDir, framework);
if (fs.existsSync(frameworkDir)) {
  const componentsDir = path.join(frameworkDir, 'components');

  if (fs.existsSync(componentsDir)) {
    console.log('Indexing components...');
    const componentDirs = fs.readdirSync(componentsDir, { withFileTypes: true })
      .filter(dirent => dirent.isDirectory())
      .map(dirent => dirent.name);

    componentDirs.forEach(componentName => {
      const componentPath = path.join(componentsDir, componentName);
      const category = categorizeComponent(componentName);

      const searchTerms = generateSearchTerms(componentName, category);

      index.components[componentName] = {
        name: componentName,
        path: `.design/extracted-code/${framework}/components/${componentName}`,
        absolutePath: componentPath,
        category,
        searchTerms,
        tags: [componentName.toLowerCase()],
        hasStory: fs.existsSync(path.join(componentPath, `${componentName}.stories.*`)),
        hasTests: fs.existsSync(path.join(componentPath, `${componentName}.test.*`)),
        score: 50
      };

      index.categories[category].push(componentName);
      index.statistics.totalComponents++;
      if (category !== 'uncategorized') index.statistics.categorized++;
      else index.statistics.uncategorized++;
    });

    console.log(`✓ Indexed ${componentDirs.length} components\n`);
  }
}

// Index tokens
if (fs.existsSync(tokensDir)) {
  console.log('Indexing tokens...');
  const tokenFiles = fs.readdirSync(tokensDir)
    .filter(f => f.endsWith('.json'));

  tokenFiles.forEach(file => {
    const filePath = path.join(tokensDir, file);
    const tokens = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const tokenType = path.basename(file, '.json');

    Object.keys(tokens).forEach(tokenName => {
      const tokenValue = tokens[tokenName];
      const searchTerms = [tokenName.toLowerCase(), tokenType];

      index.tokens[tokenName] = {
        name: tokenName,
        value: tokenValue,
        type: tokenType,
        path: `.design/tokens/${file}`,
        searchTerms,
        usedInComponents: []
      };

      index.statistics.totalTokens++;
    });
  });

  console.log(`✓ Indexed ${index.statistics.totalTokens} tokens\n`);
}

// Write index
fs.writeFileSync(indexPath, JSON.stringify(index, null, 2));

console.log('=== Search Index Built ===');
console.log(`Location: ${indexPath}`);
console.log(`Components: ${index.statistics.totalComponents}`);
console.log(`Tokens: ${index.statistics.totalTokens}`);
console.log(`Categorized: ${index.statistics.categorized}`);
console.log('');

// Helper functions
function categorizeComponent(name) {
  const nameLower = name.toLowerCase();

  // Form components
  if (/button|input|checkbox|radio|select|form|textarea|slider|switch/.test(nameLower)) {
    return 'form';
  }

  // Navigation
  if (/link|nav|menu|breadcrumb|tab|pagination|stepper/.test(nameLower)) {
    return 'navigation';
  }

  // Layout
  if (/container|grid|stack|flex|box|layout|divider|spacer/.test(nameLower)) {
    return 'layout';
  }

  // Data display
  if (/table|list|card|badge|avatar|chip|tag/.test(nameLower)) {
    return 'data-display';
  }

  // Feedback
  if (/alert|toast|spinner|progress|skeleton|snackbar/.test(nameLower)) {
    return 'feedback';
  }

  // Overlay
  if (/modal|dialog|popover|tooltip|drawer|sheet/.test(nameLower)) {
    return 'overlay';
  }

  return 'uncategorized';
}

function generateSearchTerms(name, category) {
  const terms = [];

  // Add component name
  terms.push(name.toLowerCase());

  // Split camelCase
  const words = name.replace(/([A-Z])/g, ' $1').trim().toLowerCase().split(' ');
  terms.push(...words);

  // Add category
  terms.push(category);

  // Add synonyms based on category
  if (category === 'form') {
    terms.push('input', 'interactive', 'control');
  } else if (category === 'navigation') {
    terms.push('link', 'navigate', 'route');
  } else if (category === 'layout') {
    terms.push('container', 'wrapper', 'structure');
  }

  // Remove duplicates
  return [...new Set(terms)];
}
