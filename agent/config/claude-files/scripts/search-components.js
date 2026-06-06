#!/usr/bin/env node
/**
 * search-components.js
 * Search for components and tokens with natural language
 */

const fs = require('fs');
const path = require('path');

const query = process.argv[2];
if (!query) {
  console.log('Usage: search-components.js <query>');
  console.log('Example: search-components.js "button for forms"');
  process.exit(1);
}

const projectPath = process.cwd();
const indexPath = path.join(projectPath, '.design', '.search-index.json');

if (!fs.existsSync(indexPath)) {
  console.log('❌ Search index not found');
  console.log('Run: node .claude/scripts/build-search-index.js');
  process.exit(1);
}

const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));

console.log(`=== Searching for: "${query}" ===\n`);

// Search components
const componentResults = searchComponents(query, index.components);
const tokenResults = searchTokens(query, index.tokens);

// Display results
if (componentResults.length > 0) {
  console.log('Components:');
  componentResults.slice(0, 10).forEach((result, i) => {
    console.log(`${i + 1}. ${result.name} (${result.category}) - Score: ${result.score}`);
    console.log(`   Path: ${result.path}`);
    if (result.description) console.log(`   ${result.description}`);
    console.log('');
  });
}

if (tokenResults.length > 0) {
  console.log('Tokens:');
  tokenResults.slice(0, 5).forEach((result, i) => {
    console.log(`${i + 1}. ${result.name} (${result.type})`);
    console.log(`   Value: ${JSON.stringify(result.value)}`);
    console.log(`   Path: ${result.path}`);
    console.log('');
  });
}

if (componentResults.length === 0 && tokenResults.length === 0) {
  console.log('No results found');
  console.log('Try different keywords or rebuild the index');
}

// Helper functions
function searchComponents(query, components) {
  const queryLower = query.toLowerCase();
  const queryTerms = queryLower.split(' ').filter(t => t.length > 2);

  const results = Object.values(components).map(component => {
    let score = 0;

    // Exact name match
    if (component.name.toLowerCase() === queryLower) {
      score += 100;
    }

    // Partial name match
    if (component.name.toLowerCase().includes(queryLower)) {
      score += 50;
    }

    // Search terms match
    queryTerms.forEach(term => {
      if (component.searchTerms.some(st => st.includes(term))) {
        score += 20;
      }
    });

    // Category match
    if (queryTerms.includes(component.category)) {
      score += 30;
    }

    // Tags match
    queryTerms.forEach(term => {
      if (component.tags && component.tags.includes(term)) {
        score += 15;
      }
    });

    // Bonus for having story/tests
    if (component.hasStory) score += 10;
    if (component.hasTests) score += 10;

    return { ...component, score };
  });

  return results
    .filter(r => r.score > 0)
    .sort((a, b) => b.score - a.score);
}

function searchTokens(query, tokens) {
  const queryLower = query.toLowerCase();
  const queryTerms = queryLower.split(' ').filter(t => t.length > 2);

  const results = Object.values(tokens).map(token => {
    let score = 0;

    // Exact name match
    if (token.name.toLowerCase() === queryLower) {
      score += 100;
    }

    // Partial name match
    if (token.name.toLowerCase().includes(queryLower)) {
      score += 50;
    }

    // Search terms match
    queryTerms.forEach(term => {
      if (token.searchTerms.some(st => st.includes(term))) {
        score += 20;
      }
    });

    // Type match
    if (queryTerms.includes(token.type)) {
      score += 30;
    }

    return { ...token, score };
  });

  return results
    .filter(r => r.score > 0)
    .sort((a, b) => b.score - a.score);
}
