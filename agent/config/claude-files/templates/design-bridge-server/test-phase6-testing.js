/**
 * test-phase6-testing.js
 * Phase 6: Advanced Testing & Analytics - Comprehensive Test Suite
 *
 * Tests all Phase 6 modules:
 * - Sprint 6.1: Visual Regression Testing
 * - Sprint 6.2: Accessibility Testing Integration
 * - Sprint 6.3: Component Analytics & Metrics
 * - Sprint 6.4: Design Token Synchronization
 */

const { VisualRegression, visualRegression, TEST_VIEWPORTS, COMPARISON_ALGORITHMS, DEFAULT_THRESHOLDS } = require('./visual-regression');
const { AccessibilityTesting, accessibilityTesting, WCAG_GUIDELINES, ARIA_ROLES, CONTRAST_REQUIREMENTS } = require('./accessibility-testing');
const { ComponentAnalytics, componentAnalytics, METRIC_CATEGORIES, QUALITY_THRESHOLDS } = require('./component-analytics');
const { DesignTokenSync, designTokenSync, EXPORT_FORMATS } = require('./design-token-sync');

// Test utilities
let testsPassed = 0;
let testsFailed = 0;

function test(name, fn) {
  try {
    fn();
    testsPassed++;
    console.log(`  ✓ ${name}`);
  } catch (error) {
    testsFailed++;
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${error.message}`);
  }
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

function assertTrue(value, message) {
  if (!value) {
    throw new Error(`${message}: expected truthy value`);
  }
}

function assertFalse(value, message) {
  if (value) {
    throw new Error(`${message}: expected falsy value`);
  }
}

function assertContains(str, substr, message) {
  if (!str.includes(substr)) {
    throw new Error(`${message}: expected to contain "${substr}"`);
  }
}

function assertDefined(value, message) {
  if (value === undefined || value === null) {
    throw new Error(`${message}: expected defined value`);
  }
}

function assertType(value, type, message) {
  if (typeof value !== type) {
    throw new Error(`${message}: expected type ${type}, got ${typeof value}`);
  }
}

// Mock component data
const mockComponent = {
  name: 'Button',
  type: 'component',
  props: [
    { name: 'variant', type: 'string', default: 'primary', options: ['primary', 'secondary', 'outline'] },
    { name: 'size', type: 'string', default: 'medium', options: ['small', 'medium', 'large'] },
    { name: 'disabled', type: 'boolean', default: false },
    { name: 'loading', type: 'boolean', default: false },
    { name: 'onClick', type: 'function' },
    { name: 'children', type: 'node' }
  ],
  description: 'A reusable button component',
  category: 'inputs'
};

const mockFormComponent = {
  name: 'Form',
  type: 'component',
  props: [
    { name: 'onSubmit', type: 'function' },
    { name: 'children', type: 'node' },
    { name: 'validation', type: 'object' }
  ],
  description: 'A form container component',
  category: 'forms'
};

// Mock design tokens
const mockTokens = {
  colors: {
    primary: '#0066CC',
    secondary: '#6B7280',
    success: '#10B981',
    error: '#EF4444',
    warning: '#F59E0B'
  },
  spacing: {
    xs: '4px',
    sm: '8px',
    md: '16px',
    lg: '24px',
    xl: '32px'
  },
  borderRadius: {
    sm: '4px',
    md: '8px',
    lg: '16px'
  }
};

// ============================================
// Sprint 6.1: Visual Regression Testing Tests
// ============================================

console.log('\n========================================');
console.log('Sprint 6.1: Visual Regression Testing');
console.log('========================================\n');

test('VisualRegression class instantiation', () => {
  const vr = new VisualRegression();
  assertDefined(vr, 'VisualRegression instance');
  assertDefined(vr.viewports, 'viewports defined');
  assertDefined(vr.thresholds, 'thresholds defined');
});

test('Singleton instance exists', () => {
  assertDefined(visualRegression, 'Singleton exists');
  assertTrue(visualRegression instanceof VisualRegression, 'Correct instance type');
});

test('TEST_VIEWPORTS constants defined', () => {
  assertDefined(TEST_VIEWPORTS.mobile, 'Mobile viewport');
  assertDefined(TEST_VIEWPORTS.tablet, 'Tablet viewport');
  assertDefined(TEST_VIEWPORTS.desktop, 'Desktop viewport');
  assertDefined(TEST_VIEWPORTS.wide, 'Wide viewport');
  assertEqual(TEST_VIEWPORTS.mobile.width, 375, 'Mobile width');
  assertEqual(TEST_VIEWPORTS.desktop.width, 1280, 'Desktop width');
});

test('COMPARISON_ALGORITHMS constants defined', () => {
  assertDefined(COMPARISON_ALGORITHMS.pixelMatch, 'pixelMatch algorithm');
  assertDefined(COMPARISON_ALGORITHMS.ssim, 'SSIM algorithm');
  assertDefined(COMPARISON_ALGORITHMS.perceptual, 'Perceptual algorithm');
});

test('DEFAULT_THRESHOLDS constants defined', () => {
  assertDefined(DEFAULT_THRESHOLDS.diffPercentage, 'diffPercentage');
  assertDefined(DEFAULT_THRESHOLDS.colorThreshold, 'colorThreshold');
  assertEqual(DEFAULT_THRESHOLDS.diffPercentage, 0.01, 'Default diff percentage');
});

test('generateTestConfig creates valid config', () => {
  const vr = new VisualRegression();
  const config = vr.generateTestConfig(mockComponent, {
    variants: ['default', 'loading'],
    viewports: ['mobile', 'desktop']
  });
  assertDefined(config, 'Config created');
  assertEqual(config.component, 'Button', 'Component name');
  assertEqual(config.testCases.length, 4, 'Test cases count (2 variants x 2 viewports)');
});

test('generateTestConfig includes states', () => {
  const vr = new VisualRegression();
  const config = vr.generateTestConfig(mockComponent, {
    variants: ['default'],
    viewports: ['desktop'],
    states: ['hover', 'focus']
  });
  assertEqual(config.testCases[0].states.length, 2, 'States included');
});

test('generateTestConfig includes interactions', () => {
  const vr = new VisualRegression();
  const config = vr.generateTestConfig(mockComponent, {
    variants: ['default'],
    viewports: ['desktop'],
    interactions: ['click', 'type']
  });
  assertEqual(config.testCases[0].interactions.length, 2, 'Interactions included');
});

test('generateVisualTestStory generates Storybook code', () => {
  const vr = new VisualRegression();
  const code = vr.generateVisualTestStory(mockComponent, {
    variants: ['default'],
    viewports: ['desktop']
  });
  assertContains(code, 'Visual Tests/Button', 'Story title');
  assertContains(code, 'chromatic', 'Chromatic config');
  assertContains(code, 'export const', 'Story export');
});

test('generatePlaywrightTest generates Playwright code', () => {
  const vr = new VisualRegression();
  const code = vr.generatePlaywrightTest(mockComponent, {
    variants: ['default'],
    viewports: ['mobile', 'desktop']
  });
  assertContains(code, '@playwright/test', 'Playwright import');
  assertContains(code, 'setViewportSize', 'Viewport setting');
  assertContains(code, 'toHaveScreenshot', 'Screenshot assertion');
});

test('generateCypressTest generates Cypress code', () => {
  const vr = new VisualRegression();
  const code = vr.generateCypressTest(mockComponent, {
    variants: ['default'],
    viewports: ['desktop']
  });
  assertContains(code, 'cy.viewport', 'Cypress viewport');
  assertContains(code, 'matchImageSnapshot', 'Snapshot matcher');
});

test('generateComparisonResult returns valid result', () => {
  const vr = new VisualRegression();
  const result = vr.generateComparisonResult(
    { width: 1280, height: 800 },
    { width: 1280, height: 800 }
  );
  assertTrue(result.passed, 'Comparison passed');
  assertEqual(result.diffPercentage, 0, 'No diff');
});

test('generateComparisonResult detects dimension mismatch', () => {
  const vr = new VisualRegression();
  const result = vr.generateComparisonResult(
    { width: 1280, height: 800 },
    { width: 1920, height: 1080 }
  );
  assertFalse(result.passed, 'Comparison failed');
  assertContains(result.error, 'mismatch', 'Dimension mismatch error');
});

test('generateReport creates summary', () => {
  const vr = new VisualRegression();
  const results = [
    { testId: 'test1', component: 'Button', passed: true, diffPercentage: 0 },
    { testId: 'test2', component: 'Button', passed: false, diffPercentage: 0.05 }
  ];
  const report = vr.generateReport(results);
  assertEqual(report.summary.total, 2, 'Total tests');
  assertEqual(report.summary.passed, 1, 'Passed tests');
  assertEqual(report.summary.failed, 1, 'Failed tests');
  assertEqual(report.failures.length, 1, 'Failures listed');
});

test('addViewport adds custom viewport', () => {
  const vr = new VisualRegression();
  vr.addViewport('custom', { width: 1440, height: 900, deviceScaleFactor: 1 });
  assertDefined(vr.getViewports().custom, 'Custom viewport added');
});

test('setThresholds updates thresholds', () => {
  const vr = new VisualRegression();
  vr.setThresholds({ diffPercentage: 0.05 });
  assertEqual(vr.getThresholds().diffPercentage, 0.05, 'Threshold updated');
});

test('getStats returns statistics', () => {
  const vr = new VisualRegression();
  const stats = vr.getStats();
  assertDefined(stats.testsRun, 'testsRun defined');
  assertDefined(stats.testsPassed, 'testsPassed defined');
  assertDefined(stats.testsFailed, 'testsFailed defined');
});

test('resetStats clears statistics', () => {
  const vr = new VisualRegression();
  vr.generateComparisonResult({ width: 100, height: 100 }, { width: 100, height: 100 });
  vr.resetStats();
  assertEqual(vr.getStats().comparisonsPerformed, 0, 'Stats reset');
});

test('Event emission on config generation', () => {
  const vr = new VisualRegression();
  let emitted = false;
  vr.on('config:generated', () => { emitted = true; });
  vr.generateTestConfig(mockComponent, { variants: ['default'], viewports: ['desktop'] });
  assertTrue(emitted, 'Event emitted');
});

// ============================================
// Sprint 6.2: Accessibility Testing Tests
// ============================================

console.log('\n========================================');
console.log('Sprint 6.2: Accessibility Testing');
console.log('========================================\n');

test('AccessibilityTesting class instantiation', () => {
  const at = new AccessibilityTesting();
  assertDefined(at, 'AccessibilityTesting instance');
  assertDefined(at.wcagLevel, 'WCAG level defined');
});

test('Singleton instance exists', () => {
  assertDefined(accessibilityTesting, 'Singleton exists');
  assertTrue(accessibilityTesting instanceof AccessibilityTesting, 'Correct instance type');
});

test('WCAG_GUIDELINES constants defined', () => {
  assertDefined(WCAG_GUIDELINES.perceivable, 'Perceivable guidelines');
  assertDefined(WCAG_GUIDELINES.operable, 'Operable guidelines');
  assertDefined(WCAG_GUIDELINES.understandable, 'Understandable guidelines');
  assertDefined(WCAG_GUIDELINES.robust, 'Robust guidelines');
});

test('ARIA_ROLES constants defined', () => {
  assertDefined(ARIA_ROLES.button, 'Button role');
  assertDefined(ARIA_ROLES.checkbox, 'Checkbox role');
  assertDefined(ARIA_ROLES.dialog, 'Dialog role');
  assertTrue(ARIA_ROLES.button.focusable, 'Button is focusable');
});

test('CONTRAST_REQUIREMENTS constants defined', () => {
  assertDefined(CONTRAST_REQUIREMENTS.normal, 'Normal contrast');
  assertDefined(CONTRAST_REQUIREMENTS.large, 'Large contrast');
  assertDefined(CONTRAST_REQUIREMENTS.ui, 'UI contrast');
  assertEqual(CONTRAST_REQUIREMENTS.normal.AA, 4.5, 'AA normal text ratio');
});

test('generateTestConfig creates valid a11y config', () => {
  const at = new AccessibilityTesting();
  const config = at.generateTestConfig(mockComponent, {
    role: 'button'
  });
  assertDefined(config, 'Config created');
  assertEqual(config.component, 'Button', 'Component name');
  assertDefined(config.tests, 'Tests defined');
});

test('generateTestConfig includes ARIA tests', () => {
  const at = new AccessibilityTesting();
  const config = at.generateTestConfig(mockComponent, { role: 'button' });
  assertDefined(config.tests.aria, 'ARIA tests');
  assertTrue(config.tests.aria.length > 0, 'Has ARIA tests');
});

test('generateTestConfig includes keyboard tests', () => {
  const at = new AccessibilityTesting();
  const config = at.generateTestConfig(mockComponent, { role: 'button' });
  assertDefined(config.tests.keyboard, 'Keyboard tests');
  assertTrue(config.tests.keyboard.length > 0, 'Has keyboard tests');
});

test('generateTestConfig includes contrast tests', () => {
  const at = new AccessibilityTesting();
  const config = at.generateTestConfig(mockComponent, { role: 'button' });
  assertDefined(config.tests.contrast, 'Contrast tests');
  assertTrue(config.tests.contrast.length > 0, 'Has contrast tests');
});

test('generateA11yTestCode generates Jest test code', () => {
  const at = new AccessibilityTesting();
  const code = at.generateA11yTestCode(mockComponent, { role: 'button' });
  assertContains(code, 'jest-axe', 'jest-axe import');
  assertContains(code, 'toHaveNoViolations', 'Axe assertion');
});

test('generateA11yStory generates Storybook story', () => {
  const at = new AccessibilityTesting();
  const code = at.generateA11yStory(mockComponent, { role: 'button' });
  assertContains(code, 'Accessibility', 'A11y story title');
  assertContains(code, 'a11y:', 'A11y parameters');
});

test('generatePlaywrightA11yTest generates Playwright code', () => {
  const at = new AccessibilityTesting();
  const code = at.generatePlaywrightA11yTest(mockComponent, { role: 'button' });
  assertContains(code, '@axe-core/playwright', 'Axe import');
  assertContains(code, 'AxeBuilder', 'AxeBuilder usage');
});

test('generateReport creates a11y report', () => {
  const at = new AccessibilityTesting();
  const results = [
    { name: 'Test 1', passed: true, severity: 'error', wcag: '1.4.3' },
    { name: 'Test 2', passed: false, severity: 'error', wcag: '2.1.1' }
  ];
  const report = at.generateReport(results);
  assertEqual(report.summary.total, 2, 'Total tests');
  assertEqual(report.summary.passed, 1, 'Passed tests');
});

test('getGuidelines returns WCAG guidelines', () => {
  const at = new AccessibilityTesting();
  const guidelines = at.getGuidelines();
  assertDefined(guidelines.perceivable, 'Perceivable');
  assertDefined(guidelines.operable, 'Operable');
});

test('getAriaRoles returns ARIA roles', () => {
  const at = new AccessibilityTesting();
  const roles = at.getAriaRoles();
  assertDefined(roles.button, 'Button role');
  assertDefined(roles.dialog, 'Dialog role');
});

test('getStats returns statistics', () => {
  const at = new AccessibilityTesting();
  const stats = at.getStats();
  assertDefined(stats.testsRun, 'testsRun defined');
  assertDefined(stats.passed, 'passed defined');
  assertDefined(stats.failed, 'failed defined');
});

test('resetStats clears statistics', () => {
  const at = new AccessibilityTesting();
  at.resetStats();
  assertEqual(at.getStats().testsRun, 0, 'Stats reset');
});

test('Event emission on config generation', () => {
  const at = new AccessibilityTesting();
  let emitted = false;
  at.on('config:generated', () => { emitted = true; });
  at.generateTestConfig(mockComponent, { role: 'button' });
  assertTrue(emitted, 'Event emitted');
});

// ============================================
// Sprint 6.3: Component Analytics Tests
// ============================================

console.log('\n========================================');
console.log('Sprint 6.3: Component Analytics');
console.log('========================================\n');

test('ComponentAnalytics class instantiation', () => {
  const ca = new ComponentAnalytics();
  assertDefined(ca, 'ComponentAnalytics instance');
});

test('Singleton instance exists', () => {
  assertDefined(componentAnalytics, 'Singleton exists');
  assertTrue(componentAnalytics instanceof ComponentAnalytics, 'Correct instance type');
});

test('METRIC_CATEGORIES constants defined', () => {
  assertDefined(METRIC_CATEGORIES.usage, 'Usage metrics');
  assertDefined(METRIC_CATEGORIES.performance, 'Performance metrics');
  assertDefined(METRIC_CATEGORIES.quality, 'Quality metrics');
  assertDefined(METRIC_CATEGORIES.accessibility, 'Accessibility metrics');
});

test('QUALITY_THRESHOLDS constants defined', () => {
  assertEqual(QUALITY_THRESHOLDS.excellent, 90, 'Excellent threshold');
  assertEqual(QUALITY_THRESHOLDS.good, 75, 'Good threshold');
  assertEqual(QUALITY_THRESHOLDS.acceptable, 60, 'Acceptable threshold');
});

test('analyzeComponent returns analysis', () => {
  const ca = new ComponentAnalytics();
  const analysis = ca.analyzeComponent(mockComponent);
  assertDefined(analysis, 'Analysis returned');
  assertDefined(analysis.component, 'Component name');
});

test('analyzeComponent includes metrics', () => {
  const ca = new ComponentAnalytics();
  const analysis = ca.analyzeComponent(mockComponent);
  assertDefined(analysis.metrics.usage, 'Usage metrics');
  assertDefined(analysis.metrics.performance, 'Performance metrics');
  assertDefined(analysis.metrics.quality, 'Quality metrics');
});

test('generateDashboard creates dashboard data', () => {
  const ca = new ComponentAnalytics();
  ca.analyzeComponent(mockComponent);
  ca.analyzeComponent(mockFormComponent);
  const dashboard = ca.generateDashboard();
  assertDefined(dashboard, 'Dashboard created');
  assertDefined(dashboard.summary, 'Summary exists');
});

test('generateComponentReport creates detailed report', () => {
  const ca = new ComponentAnalytics();
  ca.analyzeComponent(mockComponent);
  const report = ca.generateComponentReport(mockComponent.name);
  assertDefined(report, 'Report created');
  assertDefined(report.component, 'Component info');
});

test('exportAnalytics exports in JSON format', () => {
  const ca = new ComponentAnalytics();
  ca.analyzeComponent(mockComponent);
  const jsonExport = ca.exportAnalytics('json');
  assertType(jsonExport, 'string', 'JSON export is string');
  assertTrue(jsonExport.startsWith('{'), 'Valid JSON');
});

test('getStats returns statistics', () => {
  const ca = new ComponentAnalytics();
  const stats = ca.getStats();
  assertDefined(stats, 'Stats returned');
});

test('reset clears statistics', () => {
  const ca = new ComponentAnalytics();
  ca.analyzeComponent(mockComponent);
  ca.reset();
  const stats = ca.getStats();
  assertEqual(stats.componentsAnalyzed, 0, 'Stats reset');
});

test('Event emission on analysis', () => {
  const ca = new ComponentAnalytics();
  let emitted = false;
  ca.on('component:analyzed', () => { emitted = true; });
  ca.analyzeComponent(mockComponent);
  assertTrue(emitted, 'Event emitted');
});

// ============================================
// Sprint 6.4: Design Token Sync Tests
// ============================================

console.log('\n========================================');
console.log('Sprint 6.4: Design Token Synchronization');
console.log('========================================\n');

test('DesignTokenSync class instantiation', () => {
  const dts = new DesignTokenSync();
  assertDefined(dts, 'DesignTokenSync instance');
  assertDefined(dts.tokens, 'tokens defined');
});

test('Singleton instance exists', () => {
  assertDefined(designTokenSync, 'Singleton exists');
  assertTrue(designTokenSync instanceof DesignTokenSync, 'Correct instance type');
});

test('EXPORT_FORMATS constants defined', () => {
  assertEqual(EXPORT_FORMATS.css, 'css', 'CSS format');
  assertEqual(EXPORT_FORMATS.scss, 'scss', 'SCSS format');
  assertEqual(EXPORT_FORMATS.js, 'javascript', 'JS format');
  assertEqual(EXPORT_FORMATS.json, 'json', 'JSON format');
  assertEqual(EXPORT_FORMATS.tailwind, 'tailwind', 'Tailwind format');
});

test('processTokens stores tokens', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);
  const tokens = dts.getTokens();
  assertDefined(tokens.colors, 'Colors processed');
  assertDefined(tokens.spacing, 'Spacing processed');
});

test('exportTokens to CSS format', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);
  const css = dts.exportTokens('css');
  assertContains(css, ':root', 'CSS root selector');
  assertContains(css, '--', 'CSS custom properties');
});

test('exportTokens to SCSS format', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);
  const scss = dts.exportTokens('scss');
  assertContains(scss, '$', 'SCSS variables');
});

test('exportTokens to JSON format', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);
  const json = dts.exportTokens('json');
  assertTrue(json.startsWith('{'), 'Valid JSON');
  const parsed = JSON.parse(json);
  assertDefined(parsed, 'Parseable JSON');
});

test('exportTokens to Tailwind format', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);
  const tailwind = dts.exportTokens('tailwind');
  assertContains(tailwind, 'module.exports', 'Tailwind config');
  assertContains(tailwind, 'theme:', 'Theme key');
});

test('createTheme generates theme config', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);
  const theme = dts.createTheme('dark', {
    colors: {
      primary: '#1a1a2e',
      secondary: '#4a4e69'
    }
  });
  assertDefined(theme, 'Theme created');
});

test('diffTokens compares token sets', () => {
  const dts = new DesignTokenSync();
  const oldTokens = { colors: { primary: '#0066CC' } };
  const newTokens = { colors: { primary: '#0077DD', secondary: '#6B7280' } };
  const diff = dts.diffTokens(oldTokens, newTokens);
  assertDefined(diff, 'Diff returned');
  assertDefined(diff.added, 'Added tokens');
});

test('getStats returns statistics', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);
  const stats = dts.getStats();
  assertDefined(stats, 'Stats returned');
});

test('reset clears statistics', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);
  dts.reset();
  const stats = dts.getStats();
  assertEqual(stats.tokensProcessed, 0, 'Stats reset');
});

test('Event emission on token processing', () => {
  const dts = new DesignTokenSync();
  let emitted = false;
  dts.on('tokens:processed', () => { emitted = true; });
  dts.processTokens(mockTokens);
  assertTrue(emitted, 'Event emitted');
});

// ============================================
// Integration Tests
// ============================================

console.log('\n========================================');
console.log('Integration Tests');
console.log('========================================\n');

test('Visual Regression with Accessibility integration', () => {
  const vr = new VisualRegression();
  const at = new AccessibilityTesting();

  // Generate visual test config
  const visualConfig = vr.generateTestConfig(mockComponent, {
    variants: ['default'],
    viewports: ['desktop']
  });

  // Generate a11y config for same component
  const a11yConfig = at.generateTestConfig(mockComponent, {
    role: 'button'
  });

  // Both should reference same component
  assertEqual(visualConfig.component, a11yConfig.component, 'Same component');
});

test('Component Analytics with Design Token analysis', () => {
  const ca = new ComponentAnalytics();
  const dts = new DesignTokenSync();

  // Process tokens
  dts.processTokens(mockTokens);

  // Analyze component
  const analysis = ca.analyzeComponent(mockComponent);

  // Both should work together
  assertDefined(analysis, 'Analysis completed');
  assertDefined(dts.getTokens(), 'Tokens available');
});

test('Full pipeline integration', () => {
  const vr = new VisualRegression();
  const at = new AccessibilityTesting();
  const ca = new ComponentAnalytics();
  const dts = new DesignTokenSync();

  // Process design tokens
  dts.processTokens(mockTokens);

  // Analyze component
  const analysis = ca.analyzeComponent(mockComponent);

  // Generate visual regression tests
  const visualTests = vr.generateTestConfig(mockComponent, {
    variants: ['default', 'disabled'],
    viewports: ['mobile', 'desktop']
  });

  // Generate accessibility tests
  const a11yTests = at.generateTestConfig(mockComponent, {
    role: 'button'
  });

  // Export tokens for tests
  const cssTokens = dts.exportTokens('css');

  // Verify all outputs
  assertDefined(analysis, 'Quality analysis');
  assertEqual(visualTests.testCases.length, 4, 'Visual test cases');
  assertDefined(a11yTests.tests, 'A11y tests');
  assertContains(cssTokens, '--', 'CSS tokens');
});

test('Cross-module event handling', () => {
  const vr = new VisualRegression();
  const at = new AccessibilityTesting();
  const ca = new ComponentAnalytics();

  let visualEvents = 0;
  let a11yEvents = 0;
  let analyticsEvents = 0;

  vr.on('config:generated', () => { visualEvents++; });
  at.on('config:generated', () => { a11yEvents++; });
  ca.on('component:analyzed', () => { analyticsEvents++; });

  vr.generateTestConfig(mockComponent, { variants: ['default'], viewports: ['desktop'] });
  at.generateTestConfig(mockComponent, { role: 'button' });
  ca.analyzeComponent(mockComponent);

  assertEqual(visualEvents, 1, 'Visual events');
  assertEqual(a11yEvents, 1, 'A11y events');
  assertEqual(analyticsEvents, 1, 'Analytics events');
});

test('Token export for multiple formats', () => {
  const dts = new DesignTokenSync();
  dts.processTokens(mockTokens);

  const exports = {
    css: dts.exportTokens('css'),
    scss: dts.exportTokens('scss'),
    json: dts.exportTokens('json'),
    tailwind: dts.exportTokens('tailwind')
  };

  Object.entries(exports).forEach(([format, content]) => {
    assertTrue(content.length > 0, `${format} export has content`);
  });
});

// ============================================
// Test Summary
// ============================================

console.log('\n========================================');
console.log('Test Summary');
console.log('========================================\n');

const total = testsPassed + testsFailed;
console.log(`Total Tests: ${total}`);
console.log(`Passed: ${testsPassed}`);
console.log(`Failed: ${testsFailed}`);
console.log(`Pass Rate: ${((testsPassed / total) * 100).toFixed(1)}%`);

if (testsFailed === 0) {
  console.log('\n All Phase 6 tests passed successfully!');
} else {
  console.log(`\n ${testsFailed} test(s) failed. Please review.`);
  process.exit(1);
}
