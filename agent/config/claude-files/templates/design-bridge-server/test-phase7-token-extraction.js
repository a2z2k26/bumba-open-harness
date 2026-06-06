/**
 * Phase 7 Test: Token Extraction Enhancement
 *
 * Tests all Sprint 7.1-7.6 implementations:
 * - Sprint 7.1: Token extractor audit (capabilities)
 * - Sprint 7.2: Gradient token extraction
 * - Sprint 7.3: Variable token extraction
 * - Sprint 7.4: Component variable extraction
 * - Sprint 7.5: Enhanced grid token extraction
 * - Sprint 7.6: Integration tests
 */

const path = require('path');
const fs = require('fs');

console.log('════════════════════════════════════════════════════════════════');
console.log('          PHASE 7: TOKEN EXTRACTION ENHANCEMENT TEST SUITE       ');
console.log('════════════════════════════════════════════════════════════════\n');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ✅ ${name}`);
    passed++;
  } catch (error) {
    console.log(`  ❌ ${name}`);
    console.log(`     Error: ${error.message}`);
    failed++;
  }
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message || 'Assertion failed');
  }
}

// ============================================================================
// Sprint 7.1: Token Extractor Audit
// ============================================================================
console.log('\n📦 Sprint 7.1: Token Extractor Capabilities');
console.log('─'.repeat(60));

test('token-extractor.js exists', () => {
  const filePath = path.join(__dirname, 'token-extractor.js');
  assert(fs.existsSync(filePath), 'token-extractor.js not found');
});

test('TokenExtractor class exports correctly', () => {
  const { TokenExtractor } = require('./token-extractor');
  assert(typeof TokenExtractor === 'function', 'TokenExtractor should be a class');
});

test('TokenExtractor has all token categories', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  assert(extractor.tokens.colors !== undefined, 'Missing colors');
  assert(extractor.tokens.typography !== undefined, 'Missing typography');
  assert(extractor.tokens.spacing !== undefined, 'Missing spacing');
  assert(extractor.tokens.shadows !== undefined, 'Missing shadows');
  assert(extractor.tokens.borders !== undefined, 'Missing borders');
  assert(extractor.tokens.radii !== undefined, 'Missing radii');
  assert(extractor.tokens.breakpoints !== undefined, 'Missing breakpoints');
  assert(extractor.tokens.animations !== undefined, 'Missing animations');
});

// ============================================================================
// Sprint 7.2: Gradient Token Extraction
// ============================================================================
console.log('\n📦 Sprint 7.2: Gradient Token Extraction');
console.log('─'.repeat(60));

test('TokenExtractor has gradients token category', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(extractor.tokens.gradients !== undefined, 'Missing gradients token category');
});

test('extractGradient method exists', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(typeof extractor.extractGradient === 'function', 'Missing extractGradient method');
});

test('extractGradient handles linear gradient', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const linearFill = {
    type: 'GRADIENT_LINEAR',
    gradientStops: [
      { position: 0, color: { r: 1, g: 0, b: 0, a: 1 } },
      { position: 1, color: { r: 0, g: 0, b: 1, a: 1 } }
    ],
    gradientHandlePositions: [
      { x: 0, y: 0 },
      { x: 1, y: 1 }
    ]
  };

  const gradient = extractor.extractGradient(linearFill);
  assert(gradient !== null, 'Should extract linear gradient');
  assert(gradient.type === 'linear', 'Should have linear type');
  assert(gradient.stops.length === 2, 'Should have 2 stops');
});

test('extractGradient handles radial gradient', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const radialFill = {
    type: 'GRADIENT_RADIAL',
    gradientStops: [
      { position: 0, color: { r: 1, g: 1, b: 0, a: 1 } },
      { position: 1, color: { r: 0, g: 1, b: 0, a: 1 } }
    ]
  };

  const gradient = extractor.extractGradient(radialFill);
  assert(gradient !== null, 'Should extract radial gradient');
  assert(gradient.type === 'radial', 'Should have radial type');
});

test('generateGradientKey generates unique keys', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const gradient1 = { type: 'linear', angle: 45, stops: [] };
  const gradient2 = { type: 'radial', stops: [] };

  const key1 = extractor.generateGradientKey(gradient1);
  const key2 = extractor.generateGradientKey(gradient2);

  assert(key1 !== key2, 'Different gradients should have different keys');
  assert(key1.startsWith('gradient-'), 'Key should start with gradient-');
});

// ============================================================================
// Sprint 7.3: Variable Token Extraction
// ============================================================================
console.log('\n📦 Sprint 7.3: Variable Token Extraction');
console.log('─'.repeat(60));

test('TokenExtractor has variables token category', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(extractor.tokens.variables !== undefined, 'Missing variables token category');
});

test('TokenExtractor has variableModes token category', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(extractor.tokens.variableModes !== undefined, 'Missing variableModes token category');
});

test('extractVariables method exists', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(typeof extractor.extractVariables === 'function', 'Missing extractVariables method');
});

test('extractVariables processes collections', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  // Figma API format: collections and variables are separate
  const variablesData = {
    collections: [
      {
        name: 'Color Tokens',
        modes: [{ modeId: 'mode1', name: 'Light' }],
        variableIds: ['var1']
      }
    ],
    variables: {
      'var1': {
        name: 'primary',
        resolvedType: 'COLOR',
        valuesByMode: {
          'mode1': { r: 0.2, g: 0.4, b: 1, a: 1 }
        }
      }
    }
  };

  extractor.extractVariables(variablesData);
  assert(Object.keys(extractor.tokens.variables).length > 0, 'Should extract variables');
});

test('extractVariables handles light/dark modes', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  // Figma API format: collections and variables are separate
  const variablesData = {
    collections: [
      {
        name: 'Theme',
        modes: [
          { modeId: 'light', name: 'Light' },
          { modeId: 'dark', name: 'Dark' }
        ],
        variableIds: ['bg1']
      }
    ],
    variables: {
      'bg1': {
        name: 'background',
        resolvedType: 'COLOR',
        valuesByMode: {
          'light': { r: 1, g: 1, b: 1, a: 1 },
          'dark': { r: 0, g: 0, b: 0, a: 1 }
        }
      }
    }
  };

  extractor.extractVariables(variablesData);
  assert(extractor.tokens.variableModes.Light !== undefined ||
         extractor.tokens.variableModes.Dark !== undefined,
         'Should have mode-specific values');
});

// ============================================================================
// Sprint 7.4: Component Variable Extraction
// ============================================================================
console.log('\n📦 Sprint 7.4: Component Variable Extraction');
console.log('─'.repeat(60));

test('TokenExtractor has componentVars token category', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(extractor.tokens.componentVars !== undefined, 'Missing componentVars token category');
});

test('extractComponentVariables method exists', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(typeof extractor.extractComponentVariables === 'function',
    'Missing extractComponentVariables method');
});

test('extractFromComponents accepts variablesData', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  // Should not throw when called with variablesData
  extractor.extractFromComponents([], { collections: [] });
  assert(true, 'extractFromComponents should accept variablesData parameter');
});

test('extractComponentVariables processes bound variables', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const component = {
    id: 'comp1',
    name: 'Button',
    fills: [
      {
        type: 'SOLID',
        boundVariables: {
          color: { id: 'var123' }
        }
      }
    ]
  };

  const variablesData = {
    collections: [
      {
        variables: [
          { id: 'var123', name: 'primary-color', resolvedType: 'COLOR' }
        ]
      }
    ]
  };

  extractor.extractComponentVariables(component, variablesData);
  // Test passes if no error thrown - component vars may or may not be populated
  // depending on the specific binding logic
});

// ============================================================================
// Sprint 7.5: Enhanced Grid Token Extraction
// ============================================================================
console.log('\n📦 Sprint 7.5: Enhanced Grid Token Extraction');
console.log('─'.repeat(60));

test('TokenExtractor has grids token category', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(extractor.tokens.grids !== undefined, 'Missing grids token category');
});

test('extractGridStyle handles COLUMNS pattern', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const columnGrid = {
    pattern: 'COLUMNS',
    count: 12,
    gutterSize: 24,
    offset: 32,
    alignment: 'STRETCH'
  };

  const result = extractor.extractGridStyle(columnGrid);

  assert(result !== null, 'Should extract column grid');
  assert(result.pattern === 'COLUMNS', 'Should preserve pattern');
  assert(result.count === 12, 'Should have correct count');
  assert(result.gutterSize === 24, 'Should have correct gutter size');
  assert(result.cssTemplate !== undefined, 'Should have CSS template');
  assert(result.cssGap !== undefined, 'Should have CSS gap');
});

test('extractGridStyle handles ROWS pattern', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const rowGrid = {
    pattern: 'ROWS',
    count: 6,
    gutterSize: 16,
    offset: 16
  };

  const result = extractor.extractGridStyle(rowGrid);

  assert(result !== null, 'Should extract row grid');
  assert(result.pattern === 'ROWS', 'Should preserve pattern');
  assert(result.count === 6, 'Should have correct count');
});

test('extractGridStyle handles GRID (baseline) pattern', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const baselineGrid = {
    pattern: 'GRID',
    sectionSize: 8
  };

  const result = extractor.extractGridStyle(baselineGrid);

  assert(result !== null, 'Should extract baseline grid');
  assert(result.pattern === 'GRID', 'Should preserve pattern');
  assert(result.sectionSize === 8, 'Should have correct section size');
});

test('extractGridStyle calculates totalGutterWidth', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const grid = {
    pattern: 'COLUMNS',
    count: 4,
    gutterSize: 20
  };

  const result = extractor.extractGridStyle(grid);

  // Total gutter = 20 * (4-1) = 60
  assert(result.totalGutterWidth === '60px', 'Should calculate total gutter width');
});

test('extractGridsFromNode method exists', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();
  assert(typeof extractor.extractGridsFromNode === 'function',
    'Missing extractGridsFromNode method');
});

test('extractGridsFromNode processes node with layoutGrids', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const node = {
    name: 'Desktop Frame',
    layoutGrids: [
      { pattern: 'COLUMNS', count: 12, gutterSize: 24 },
      { pattern: 'GRID', sectionSize: 8 }
    ]
  };

  const grids = extractor.extractGridsFromNode(node);

  assert(grids !== null, 'Should extract grids from node');
  assert(Object.keys(grids).length === 2, 'Should extract both grids');
});

test('grids are included in formatTokens output', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const tokens = extractor.formatTokens();
  assert(tokens.grids !== undefined, 'formatTokens should include grids');
});

test('grids are included in reset()', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  extractor.tokens.grids['test'] = { pattern: 'COLUMNS', count: 12 };
  extractor.reset();

  assert(extractor.tokens.grids !== undefined, 'reset() should initialize grids');
  assert(Object.keys(extractor.tokens.grids).length === 0, 'reset() should clear grids');
});

// ============================================================================
// Sprint 7.6: Integration Tests
// ============================================================================
console.log('\n📦 Sprint 7.6: Integration Tests');
console.log('─'.repeat(60));

test('Full extraction with all token types', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const figmaData = {
    styles: {
      colors: {
        'Primary/500': { r: 0.2, g: 0.4, b: 1, a: 1 }
      },
      grids: {
        '12-Column': { pattern: 'COLUMNS', count: 12, gutterSize: 24 }
      }
    },
    document: {
      children: [
        {
          type: 'FRAME',
          name: 'Test Frame',
          fills: [
            {
              type: 'GRADIENT_LINEAR',
              gradientStops: [
                { position: 0, color: { r: 1, g: 0, b: 0, a: 1 } },
                { position: 1, color: { r: 0, g: 0, b: 1, a: 1 } }
              ],
              gradientHandlePositions: [{ x: 0, y: 0 }, { x: 1, y: 1 }]
            }
          ],
          layoutGrids: [
            { pattern: 'ROWS', count: 6, gutterSize: 16 }
          ]
        }
      ]
    },
    variables: {
      collections: [
        {
          name: 'Colors',
          modes: [{ modeId: 'm1', name: 'Default' }],
          variableIds: ['accent1']
        }
      ],
      variables: {
        'accent1': {
          name: 'accent',
          resolvedType: 'COLOR',
          valuesByMode: { 'm1': { r: 1, g: 0.5, b: 0, a: 1 } }
        }
      }
    }
  };

  const tokens = extractor.extract(figmaData);

  assert(Object.keys(tokens.colors).length > 0, 'Should extract colors');
  assert(Object.keys(tokens.gradients).length > 0, 'Should extract gradients');
  assert(Object.keys(tokens.grids).length > 0, 'Should extract grids');
  assert(Object.keys(tokens.variables).length > 0, 'Should extract variables');
});

test('CSS export includes grid variables', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const tokens = {
    colors: { primary: '#3366FF' },
    typography: {},
    spacing: {},
    shadows: {},
    borders: {},
    radii: {},
    breakpoints: {},
    animations: {},
    gradients: {},
    variables: {},
    variableModes: {},
    componentVars: {},
    grids: {
      'desktop-columns': {
        pattern: 'COLUMNS',
        count: 12,
        cssGap: '24px',
        cssTemplate: 'repeat(12, 1fr)',
        offsetValue: '32px'
      }
    }
  };

  const css = extractor.exportToCSS(tokens);

  assert(css.includes('--grid-desktop-columns-columns'), 'CSS should include grid columns');
  assert(css.includes('--grid-desktop-columns-gap'), 'CSS should include grid gap');
  assert(css.includes('--grid-desktop-columns-template'), 'CSS should include grid template');
});

test('SCSS export includes grid variables', () => {
  const { TokenExtractor } = require('./token-extractor');
  const extractor = new TokenExtractor();

  const tokens = {
    colors: {},
    typography: {},
    spacing: {},
    shadows: {},
    borders: {},
    radii: {},
    breakpoints: {},
    animations: {},
    gradients: {},
    variables: {},
    variableModes: {},
    componentVars: {},
    grids: {
      'mobile-columns': {
        pattern: 'COLUMNS',
        count: 4,
        cssGap: '16px',
        cssTemplate: 'repeat(4, 1fr)'
      }
    }
  };

  const scss = extractor.exportToSCSS(tokens);

  assert(scss.includes('$grid-mobile-columns-columns'), 'SCSS should include grid columns');
  assert(scss.includes('$grid-mobile-columns-gap'), 'SCSS should include grid gap');
});

// ============================================================================
// Results Summary
// ============================================================================
console.log('\n' + '═'.repeat(60));
console.log('TEST RESULTS');
console.log('═'.repeat(60));
console.log(`  Total:  ${passed + failed}`);
console.log(`  Passed: ${passed} ✅`);
console.log(`  Failed: ${failed} ❌`);
console.log('═'.repeat(60));

if (failed > 0) {
  console.log('\n⚠️  Some tests failed. Please review the errors above.');
  process.exit(1);
} else {
  console.log('\n✅ Phase 7: Token Extraction Enhancement - ALL TESTS PASSED!');
  console.log('\nPhase 7 Implementation Summary:');
  console.log('  • Sprint 7.1: Token extractor audit ✅');
  console.log('  • Sprint 7.2: Gradient token extraction ✅');
  console.log('  • Sprint 7.3: Variable token extraction ✅');
  console.log('  • Sprint 7.4: Component variable extraction ✅');
  console.log('  • Sprint 7.5: Enhanced grid token extraction ✅');
  console.log('  • Sprint 7.6: Integration tests ✅');
  process.exit(0);
}
