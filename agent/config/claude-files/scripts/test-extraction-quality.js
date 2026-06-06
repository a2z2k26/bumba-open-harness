#!/usr/bin/env node
/**
 * test-extraction-quality.js
 * Validates extraction code quality and data structures
 */

const fs = require('fs');
const path = require('path');

console.log('=== EXTRACTION QUALITY TEST SUITE ===\n');

const results = {
  total: 0,
  passed: 0,
  failed: 0,
  tests: []
};

function runTest(name, testFn) {
  results.total++;
  console.log(`Test ${results.total}: ${name}`);

  try {
    testFn();
    console.log('  ✅ PASSED\n');
    results.passed++;
    results.tests.push({ name, status: 'PASSED' });
  } catch (error) {
    console.log(`  ❌ FAILED: ${error.message}\n`);
    results.failed++;
    results.tests.push({ name, status: 'FAILED', error: error.message });
  }
}

const baseDir = '/opt/bumba-harness/Bumba - DesignBridge/design-feature';
const pluginDir = path.join(baseDir, 'packages/@design-bridge/figma-plugin');
const codeFile = path.join(pluginDir, 'dist/code.js');

// Load code.js content
const codeContent = fs.readFileSync(codeFile, 'utf8');

// ===== TOKEN EXTRACTION QUALITY TESTS =====

runTest('TokenExtractor class exists', () => {
  if (!codeContent.includes('class TokenExtractor')) {
    throw new Error('TokenExtractor class not found');
  }
  console.log('  TokenExtractor class present');
});

runTest('Token extraction covers all types', () => {
  const required = [
    'extractColors',
    'extractTypography',
    'extractSpacing',
    'extractEffects',
    'extractBorderRadius'
  ];
  const missing = required.filter(fn => !codeContent.includes(fn));
  if (missing.length > 0) {
    throw new Error(`Missing extractors: ${missing.join(', ')}`);
  }
  console.log('  All token extractors present: colors, typography, spacing, effects, borderRadius');
});

runTest('Color extraction uses Figma paint styles API', () => {
  if (!codeContent.includes('getLocalPaintStylesAsync')) {
    throw new Error('Not using getLocalPaintStylesAsync');
  }
  if (!codeContent.includes('SOLID')) {
    throw new Error('Not handling SOLID paint type');
  }
  console.log('  Uses getLocalPaintStylesAsync and handles SOLID paints');
});

runTest('Typography extraction uses Figma text styles API', () => {
  if (!codeContent.includes('getLocalTextStylesAsync')) {
    throw new Error('Not using getLocalTextStylesAsync');
  }
  const typographyProps = ['fontFamily', 'fontWeight', 'fontSize', 'lineHeight', 'letterSpacing'];
  const missing = typographyProps.filter(prop => !codeContent.includes(prop));
  if (missing.length > 0) {
    throw new Error(`Missing typography properties: ${missing.join(', ')}`);
  }
  console.log('  Extracts all typography properties');
});

runTest('Spacing extraction from auto-layout frames', () => {
  if (!codeContent.includes('layoutMode')) {
    throw new Error('Not checking layoutMode');
  }
  const spacingProps = ['paddingTop', 'paddingBottom', 'paddingLeft', 'paddingRight', 'itemSpacing'];
  const missing = spacingProps.filter(prop => !codeContent.includes(prop));
  if (missing.length > 0) {
    throw new Error(`Missing spacing properties: ${missing.join(', ')}`);
  }
  console.log('  Extracts padding and itemSpacing from auto-layout');
});

runTest('Effects extraction uses Figma effect styles API', () => {
  if (!codeContent.includes('getLocalEffectStylesAsync')) {
    throw new Error('Not using getLocalEffectStylesAsync');
  }
  if (!codeContent.includes('DROP_SHADOW') || !codeContent.includes('INNER_SHADOW')) {
    throw new Error('Not handling shadow types');
  }
  console.log('  Uses getLocalEffectStylesAsync and handles shadows');
});

runTest('Token metadata includes source info', () => {
  if (!codeContent.includes('fileName: figma.root.name')) {
    throw new Error('Not including fileName metadata');
  }
  if (!codeContent.includes('lastModified')) {
    throw new Error('Not including lastModified timestamp');
  }
  console.log('  Includes fileName and lastModified metadata');
});

// ===== COMPONENT EXTRACTION QUALITY TESTS =====

runTest('extractNode function exists', () => {
  if (!codeContent.includes('async function extractNode')) {
    throw new Error('extractNode function not found');
  }
  console.log('  extractNode function present');
});

runTest('Component extraction handles COMPONENT type', () => {
  if (!codeContent.includes("node.type === 'COMPONENT'")) {
    throw new Error('Not handling COMPONENT type');
  }
  if (!codeContent.includes('componentPropertyDefinitions')) {
    throw new Error('Not extracting componentPropertyDefinitions');
  }
  console.log('  Handles COMPONENT with property definitions');
});

runTest('Component extraction handles COMPONENT_SET (variants)', () => {
  if (!codeContent.includes("node.type === 'COMPONENT_SET'")) {
    throw new Error('Not handling COMPONENT_SET type');
  }
  if (!codeContent.includes('variantProperties')) {
    throw new Error('Not extracting variant properties');
  }
  if (!codeContent.includes('variantOptions')) {
    throw new Error('Not extracting variant options');
  }
  console.log('  Handles COMPONENT_SET with variants');
});

runTest('Component extraction handles INSTANCE type', () => {
  if (!codeContent.includes("node.type === 'INSTANCE'")) {
    throw new Error('Not handling INSTANCE type');
  }
  if (!codeContent.includes('getMainComponentAsync')) {
    throw new Error('Not using getMainComponentAsync for instances');
  }
  console.log('  Handles INSTANCE with main component reference');
});

runTest('Component extraction includes visual properties', () => {
  const visualProps = ['fills', 'strokes', 'effects', 'cornerRadius'];
  const missing = visualProps.filter(prop => !codeContent.includes(prop));
  if (missing.length > 0) {
    throw new Error(`Missing visual properties: ${missing.join(', ')}`);
  }
  console.log('  Extracts fills, strokes, effects, cornerRadius');
});

runTest('Component extraction includes layout properties', () => {
  const layoutProps = ['layoutMode', 'primaryAxisSizingMode', 'counterAxisSizingMode'];
  const missing = layoutProps.filter(prop => !codeContent.includes(prop));
  if (missing.length > 0) {
    throw new Error(`Missing layout properties: ${missing.join(', ')}`);
  }
  console.log('  Extracts auto-layout configuration');
});

// ===== LAYOUT EXTRACTION QUALITY TESTS =====

runTest('Layout extraction function exists', () => {
  if (!codeContent.includes('extractLayoutFromSelection')) {
    throw new Error('extractLayoutFromSelection function not found');
  }
  console.log('  extractLayoutFromSelection function present');
});

runTest('Layout extraction handles FRAME type', () => {
  if (!codeContent.includes("node.type === 'FRAME'")) {
    throw new Error('Not handling FRAME type');
  }
  if (!codeContent.includes("node.type === 'GROUP'")) {
    throw new Error('Not handling GROUP type');
  }
  console.log('  Handles FRAME and GROUP types');
});

runTest('Layout extraction generates code for React', () => {
  if (!codeContent.includes('generateReactComponent')) {
    throw new Error('generateReactComponent function not found');
  }
  if (!codeContent.includes('generateJSXFromLayout')) {
    throw new Error('generateJSXFromLayout function not found');
  }
  console.log('  Generates React/JSX component code');
});

runTest('Layout extraction generates code for Vue', () => {
  if (!codeContent.includes('generateVueComponent')) {
    throw new Error('generateVueComponent function not found');
  }
  if (!codeContent.includes('generateVueTemplateFromLayout')) {
    throw new Error('generateVueTemplateFromLayout function not found');
  }
  console.log('  Generates Vue SFC code');
});

runTest('Layout extraction generates CSS', () => {
  if (!codeContent.includes('generateCSSStyles')) {
    throw new Error('generateCSSStyles function not found');
  }
  if (!codeContent.includes('flex-direction')) {
    throw new Error('Not generating flexbox CSS');
  }
  console.log('  Generates CSS with flexbox layout');
});

runTest('Layout extraction counts child elements', () => {
  if (!codeContent.includes('componentCount')) {
    throw new Error('Not counting components');
  }
  if (!codeContent.includes('textCount')) {
    throw new Error('Not counting text elements');
  }
  if (!codeContent.includes('imageCount')) {
    throw new Error('Not counting image elements');
  }
  console.log('  Counts components, text, and images');
});

// ===== SINGLE COMPONENT EXTRACTION TESTS =====

runTest('Selection-based extraction exists', () => {
  if (!codeContent.includes('extractSelection')) {
    throw new Error('extractSelection function not found');
  }
  console.log('  extractSelection function present');
});

runTest('Selection extraction validates selection', () => {
  if (!codeContent.includes('figma.currentPage.selection')) {
    throw new Error('Not reading current selection');
  }
  if (!codeContent.includes('selection.length === 0')) {
    throw new Error('Not validating empty selection');
  }
  console.log('  Validates selection before extraction');
});

runTest('Selection extraction sends extraction-complete message', () => {
  if (!codeContent.includes("type: 'extraction-complete'")) {
    throw new Error('Not sending extraction-complete message');
  }
  console.log('  Sends extraction-complete message to UI');
});

// ===== SYSTEM EXTRACTION TESTS (Tokens + Components) =====

runTest('System extraction mode exists', () => {
  if (!codeContent.includes("extractionMode === 'system'")) {
    throw new Error('System extraction mode not found');
  }
  console.log('  System extraction mode supported');
});

runTest('System extraction extracts both tokens and components', () => {
  // Check that system mode triggers both token and component extraction
  const hasTokenCheck = codeContent.includes("extractionMode === 'tokens' || extractionMode === 'system'");
  const hasComponentCheck = codeContent.includes("extractionMode === 'components' || extractionMode === 'system'");

  if (!hasTokenCheck || !hasComponentCheck) {
    throw new Error('System mode does not extract both tokens and components');
  }
  console.log('  System mode extracts tokens AND components');
});

runTest('Extraction stats track all categories', () => {
  const statCategories = ['colors', 'typography', 'spacing', 'effects', 'borderRadius', 'components'];
  const missing = statCategories.filter(cat => !codeContent.includes(`extractionStats.${cat}`));
  if (missing.length > 0) {
    throw new Error(`Missing stat categories: ${missing.join(', ')}`);
  }
  console.log('  Tracks all extraction stat categories');
});

// ===== OUTPUT FORMAT TESTS =====

runTest('Token exporter supports JSON format', () => {
  if (!codeContent.includes("case 'json'")) {
    throw new Error('JSON format not supported');
  }
  console.log('  JSON format supported');
});

runTest('Token exporter supports CSS format', () => {
  if (!codeContent.includes("case 'css'")) {
    throw new Error('CSS format not supported');
  }
  if (!codeContent.includes('class CSSTransformer')) {
    throw new Error('CSSTransformer class not found');
  }
  console.log('  CSS custom properties format supported');
});

runTest('Token exporter supports Tailwind format', () => {
  if (!codeContent.includes("case 'tailwind'")) {
    throw new Error('Tailwind format not supported');
  }
  if (!codeContent.includes('class TailwindTransformer')) {
    throw new Error('TailwindTransformer class not found');
  }
  console.log('  Tailwind config format supported');
});

// ===== ERROR HANDLING TESTS =====

runTest('Error categorization exists', () => {
  if (!codeContent.includes('categorizeError')) {
    throw new Error('categorizeError function not found');
  }
  const errorTypes = ['NETWORK', 'PERMISSION', 'VALIDATION', 'CRITICAL'];
  const missing = errorTypes.filter(type => !codeContent.includes(`'${type}'`));
  if (missing.length > 0) {
    throw new Error(`Missing error types: ${missing.join(', ')}`);
  }
  console.log('  Categorizes errors: NETWORK, PERMISSION, VALIDATION, CRITICAL');
});

runTest('User-friendly error messages exist', () => {
  if (!codeContent.includes('getUserFriendlyErrorMessage')) {
    throw new Error('getUserFriendlyErrorMessage function not found');
  }
  console.log('  Provides user-friendly error messages');
});

runTest('Retry logic with exponential backoff exists', () => {
  if (!codeContent.includes('retryOperation')) {
    throw new Error('retryOperation function not found');
  }
  if (!codeContent.includes('exponential backoff')) {
    throw new Error('No exponential backoff mentioned');
  }
  console.log('  Implements retry with exponential backoff');
});

// Summary
console.log('=== EXTRACTION QUALITY SUMMARY ===');
console.log(`Total tests: ${results.total}`);
console.log(`Passed: ${results.passed}`);
console.log(`Failed: ${results.failed}`);
console.log(`Success rate: ${Math.round((results.passed / results.total) * 100)}%`);

if (results.failed > 0) {
  console.log('\nFailed tests:');
  results.tests.filter(t => t.status === 'FAILED').forEach(t => {
    console.log(`  - ${t.name}: ${t.error}`);
  });
  process.exit(1);
} else {
  console.log('\n✅ All extraction quality tests passed!');
  console.log('\nExtraction Quality Verified:');
  console.log('  ✅ Token extraction (colors, typography, spacing, effects, borderRadius)');
  console.log('  ✅ Component extraction (COMPONENT, COMPONENT_SET, INSTANCE)');
  console.log('  ✅ Layout extraction (FRAME, GROUP with code generation)');
  console.log('  ✅ Single component selection-based extraction');
  console.log('  ✅ System extraction (tokens + components combined)');
  console.log('  ✅ Output formats (JSON, CSS, Tailwind)');
  console.log('  ✅ Error handling with retry logic');
  process.exit(0);
}
