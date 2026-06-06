/**
 * figma-state-detector.test.js
 * Unit tests for the Figma state detector
 */

const {
  detectInteractiveStates,
  computeStateDiff,
  findVariantByState,
  matchesAnyStatePattern,
  generateStateCss,
  formatStateAsCss,
  extractPrimaryColor,
  rgbToHex,
  formatEffectsAsCss,
  formatStateResults,
  STATE_PATTERNS
} = require('./figma-state-detector');

let passed = 0;
let failed = 0;

function test(name, condition) {
  if (condition) {
    console.log(`  [PASS] ${name}`);
    passed++;
  } else {
    console.log(`  [FAIL] ${name}`);
    failed++;
  }
}

// Mock component sets
const mockComponentSetWithStates = {
  type: 'COMPONENT_SET',
  children: [
    {
      name: 'State=Default, Size=Medium',
      fills: [{ type: 'SOLID', color: { r: 0.2, g: 0.4, b: 0.8 } }],
      effects: [],
      opacity: 1
    },
    {
      name: 'State=Hover, Size=Medium',
      fills: [{ type: 'SOLID', color: { r: 0.3, g: 0.5, b: 0.9 } }],
      effects: [{ type: 'DROP_SHADOW', radius: 4, offset: { x: 0, y: 2 }, color: { r: 0, g: 0, b: 0, a: 0.1 } }],
      opacity: 1
    },
    {
      name: 'State=Pressed, Size=Medium',
      fills: [{ type: 'SOLID', color: { r: 0.1, g: 0.3, b: 0.7 } }],
      effects: [],
      opacity: 0.9
    },
    {
      name: 'State=Disabled, Size=Medium',
      fills: [{ type: 'SOLID', color: { r: 0.5, g: 0.5, b: 0.5 } }],
      effects: [],
      opacity: 0.5
    },
    {
      name: 'State=Focus, Size=Medium',
      fills: [{ type: 'SOLID', color: { r: 0.2, g: 0.4, b: 0.8 } }],
      effects: [{ type: 'DROP_SHADOW', radius: 0, spread: 2, offset: { x: 0, y: 0 }, color: { r: 0.2, g: 0.4, b: 0.8, a: 0.5 } }],
      opacity: 1
    }
  ]
};

const mockSimpleVariants = {
  type: 'COMPONENT_SET',
  children: [
    { name: 'Default', fills: [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }] },
    { name: 'Hover', fills: [{ type: 'SOLID', color: { r: 0, g: 1, b: 0 } }] },
    { name: 'Active', fills: [{ type: 'SOLID', color: { r: 0, g: 0, b: 1 } }] }
  ]
};

const mockNoStateVariants = {
  type: 'COMPONENT_SET',
  children: [
    { name: 'Small', fills: [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }] },
    { name: 'Medium', fills: [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }] },
    { name: 'Large', fills: [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }] }
  ]
};

function runTests() {
  console.log('\n=== Figma State Detector Tests ===\n');

  // Test rgbToHex
  console.log('rgbToHex:');

  test('converts red', rgbToHex(1, 0, 0) === '#FF0000');
  test('converts green', rgbToHex(0, 1, 0) === '#00FF00');
  test('converts blue', rgbToHex(0, 0, 1) === '#0000FF');
  test('converts black', rgbToHex(0, 0, 0) === '#000000');
  test('converts white', rgbToHex(1, 1, 1) === '#FFFFFF');
  test('converts mid-gray', rgbToHex(0.5, 0.5, 0.5) === '#808080');

  // Test extractPrimaryColor
  console.log('\nextractPrimaryColor:');

  const solidFill = [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }];
  test('extracts solid color', extractPrimaryColor(solidFill) === '#FF0000');

  const withAlpha = [{ type: 'SOLID', color: { r: 1, g: 0, b: 0, a: 0.5 } }];
  test('extracts rgba color', extractPrimaryColor(withAlpha).startsWith('rgba'));
  test('includes alpha', extractPrimaryColor(withAlpha).includes('0.5'));

  const emptyFills = [];
  test('returns null for empty', extractPrimaryColor(emptyFills) === null);

  const hiddenFill = [{ type: 'SOLID', visible: false, color: { r: 1, g: 0, b: 0 } }];
  test('ignores hidden fills', extractPrimaryColor(hiddenFill) === null);

  const gradientFill = [{ type: 'GRADIENT_LINEAR' }];
  test('returns null for gradient', extractPrimaryColor(gradientFill) === null);

  // Test formatEffectsAsCss
  console.log('\nformatEffectsAsCss:');

  const dropShadow = [{ type: 'DROP_SHADOW', offset: { x: 0, y: 2 }, radius: 4, spread: 0, color: { r: 0, g: 0, b: 0, a: 0.25 } }];
  const shadowCss = formatEffectsAsCss(dropShadow);
  test('formats drop shadow', shadowCss.includes('0px 2px 4px'));

  const innerShadow = [{ type: 'INNER_SHADOW', offset: { x: 0, y: 1 }, radius: 2, spread: 0, color: { r: 0, g: 0, b: 0, a: 0.1 } }];
  const innerCss = formatEffectsAsCss(innerShadow);
  test('formats inner shadow with inset', innerCss.includes('inset'));

  const multipleEffects = [...dropShadow, ...innerShadow];
  const multipleCss = formatEffectsAsCss(multipleEffects);
  test('joins multiple shadows', multipleCss.includes(','));

  const emptyEffects = [];
  test('returns none for empty', formatEffectsAsCss(emptyEffects) === 'none');

  const hiddenEffect = [{ type: 'DROP_SHADOW', visible: false }];
  test('ignores hidden effects', formatEffectsAsCss(hiddenEffect) === 'none');

  // Test matchesAnyStatePattern
  console.log('\nmatchesAnyStatePattern:');

  test('matches State=Default', matchesAnyStatePattern('State=Default', STATE_PATTERNS.default));
  test('matches Default', matchesAnyStatePattern('Default', STATE_PATTERNS.default));
  test('matches State=Hover', matchesAnyStatePattern('State=Hover', STATE_PATTERNS.hover));
  test('matches Hover', matchesAnyStatePattern('Hover', STATE_PATTERNS.hover));
  test('matches hovered', matchesAnyStatePattern('hovered', STATE_PATTERNS.hover));
  test('matches State=Pressed', matchesAnyStatePattern('State=Pressed', STATE_PATTERNS.pressed));
  test('matches active', matchesAnyStatePattern('active', STATE_PATTERNS.pressed));
  test('matches State=Focus', matchesAnyStatePattern('State=Focus', STATE_PATTERNS.focused));
  test('matches focused', matchesAnyStatePattern('focused', STATE_PATTERNS.focused));
  test('matches State=Disabled', matchesAnyStatePattern('State=Disabled', STATE_PATTERNS.disabled));
  test('matches disabled', matchesAnyStatePattern('disabled', STATE_PATTERNS.disabled));

  test('does not match Size=Medium', !matchesAnyStatePattern('Size=Medium', STATE_PATTERNS.hover));

  // Test findVariantByState
  console.log('\nfindVariantByState:');

  const variants = mockComponentSetWithStates.children;
  const defaultV = findVariantByState(variants, 'default');
  test('finds default variant', defaultV !== null);
  test('default variant matches name', defaultV.name.includes('Default'));

  const hoverV = findVariantByState(variants, 'hover');
  test('finds hover variant', hoverV !== null);
  test('hover variant matches name', hoverV.name.includes('Hover'));

  const pressedV = findVariantByState(variants, 'pressed');
  test('finds pressed variant', pressedV !== null);

  const disabledV = findVariantByState(variants, 'disabled');
  test('finds disabled variant', disabledV !== null);

  const focusedV = findVariantByState(variants, 'focused');
  test('finds focused variant', focusedV !== null);

  test('returns null for unknown state', findVariantByState(variants, 'unknown') === null);

  // Test computeStateDiff
  console.log('\ncomputeStateDiff:');

  const base = { fills: [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }], opacity: 1 };
  const hoverState = { fills: [{ type: 'SOLID', color: { r: 0, g: 1, b: 0 } }], opacity: 1 };

  const fillDiff = computeStateDiff(base, hoverState);
  test('detects fill change', fillDiff.backgroundColor !== undefined);
  test('fill color is hex', fillDiff.backgroundColor.startsWith('#'));

  const opacityState = { fills: base.fills, opacity: 0.5 };
  const opacityDiff = computeStateDiff(base, opacityState);
  test('detects opacity change', opacityDiff.opacity === 0.5);

  const effectBase = { fills: [], effects: [] };
  const effectState = { fills: [], effects: [{ type: 'DROP_SHADOW', offset: { x: 0, y: 2 }, radius: 4 }] };
  const effectDiff = computeStateDiff(effectBase, effectState);
  test('detects effect change', effectDiff.boxShadow !== undefined);

  const radiusBase = { cornerRadius: 4 };
  const radiusState = { cornerRadius: 8 };
  const radiusDiff = computeStateDiff(radiusBase, radiusState);
  test('detects radius change', radiusDiff.borderRadius === '8px');

  const noDiff = computeStateDiff(base, base);
  test('returns empty for no change', Object.keys(noDiff).length === 0);

  // Test detectInteractiveStates
  console.log('\ndetectInteractiveStates:');

  const states = detectInteractiveStates(mockComponentSetWithStates);

  test('detects hover state', states.hover !== undefined);
  test('detects pressed state', states.pressed !== undefined);
  test('detects disabled state', states.disabled !== undefined);
  test('detects focused state', states.focused !== undefined);

  test('hover has backgroundColor', states.hover.backgroundColor !== undefined);
  test('hover has boxShadow', states.hover.boxShadow !== undefined);
  test('pressed has opacity', states.pressed.opacity !== undefined);
  test('disabled has opacity', states.disabled.opacity === 0.5);

  const simpleStates = detectInteractiveStates(mockSimpleVariants);
  test('handles simple naming', simpleStates.hover !== undefined);
  test('detects active as pressed', simpleStates.pressed !== undefined);

  const noStates = detectInteractiveStates(mockNoStateVariants);
  test('returns empty for size-only variants', Object.keys(noStates).length === 0);

  const notComponentSet = { type: 'FRAME', children: [] };
  test('returns empty for non-COMPONENT_SET', Object.keys(detectInteractiveStates(notComponentSet)).length === 0);

  const noChildren = { type: 'COMPONENT_SET' };
  test('returns empty for no children', Object.keys(detectInteractiveStates(noChildren)).length === 0);

  // Test formatStateAsCss
  console.log('\nformatStateAsCss:');

  const stateCss = formatStateAsCss({
    backgroundColor: '#FF0000',
    borderColor: '#00FF00',
    boxShadow: '0px 2px 4px rgba(0,0,0,0.25)',
    opacity: 0.8,
    borderRadius: '8px',
    transform: 'scale(1.05)'
  });

  test('includes background-color', stateCss.includes('background-color'));
  test('includes border-color', stateCss.includes('border-color'));
  test('includes box-shadow', stateCss.includes('box-shadow'));
  test('includes opacity', stateCss.includes('opacity'));
  test('includes border-radius', stateCss.includes('border-radius'));
  test('includes transform', stateCss.includes('transform'));

  // Test generateStateCss
  console.log('\ngenerateStateCss:');

  const css = generateStateCss(states, '.button');

  test('generates :hover selector', css.includes('.button:hover'));
  test('generates :active selector', css.includes('.button:active'));
  test('generates :focus selector', css.includes('.button:focus'));
  test('generates :disabled selector', css.includes('.button:disabled'));

  const emptyCss = generateStateCss({});
  test('returns empty for no states', emptyCss === '');

  // Test formatStateResults
  console.log('\nformatStateResults:');

  const results = formatStateResults(states);

  test('includes state count', results.includes('4'));
  test('includes hover', results.includes('hover'));
  test('includes pressed', results.includes('pressed'));

  const emptyResults = formatStateResults({});
  test('handles no states', emptyResults.includes('No interactive states'));

  // Summary
  console.log('\n=============================');
  console.log(`Results: ${passed} passed, ${failed} failed`);
  console.log('=============================\n');

  return { passed, failed };
}

// Run tests
if (require.main === module) {
  const result = runTests();
  process.exit(result.failed > 0 ? 1 : 0);
}

module.exports = { runTests };
