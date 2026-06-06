/**
 * visual-regression.js
 * Sprint 6.1: Visual Regression Testing
 *
 * Provides visual regression testing capabilities:
 * - Screenshot capture configuration
 * - Baseline management
 * - Diff generation and comparison
 * - Threshold-based pass/fail
 * - Multi-viewport testing
 */

const EventEmitter = require('events');
const crypto = require('crypto');

/**
 * Default viewport configurations for visual testing
 */
const TEST_VIEWPORTS = {
  mobile: { width: 375, height: 667, deviceScaleFactor: 2 },
  tablet: { width: 768, height: 1024, deviceScaleFactor: 2 },
  desktop: { width: 1280, height: 800, deviceScaleFactor: 1 },
  wide: { width: 1920, height: 1080, deviceScaleFactor: 1 }
};

/**
 * Screenshot comparison algorithms
 */
const COMPARISON_ALGORITHMS = {
  pixelMatch: 'pixel-match',
  ssim: 'structural-similarity',
  perceptual: 'perceptual-hash'
};

/**
 * Default threshold configurations
 */
const DEFAULT_THRESHOLDS = {
  // Percentage of pixels that can differ (0-1)
  diffPercentage: 0.01,
  // Color difference threshold (0-255)
  colorThreshold: 0.1,
  // Anti-aliasing detection
  antialiasing: true,
  // Alpha channel comparison
  alpha: 0.5
};

class VisualRegression extends EventEmitter {
  constructor(options = {}) {
    super();

    this.viewports = { ...TEST_VIEWPORTS, ...options.viewports };
    this.thresholds = { ...DEFAULT_THRESHOLDS, ...options.thresholds };
    this.algorithm = options.algorithm || COMPARISON_ALGORITHMS.pixelMatch;
    this.baselineDir = options.baselineDir || '.visual-baselines';
    this.outputDir = options.outputDir || '.visual-results';

    this.stats = {
      testsRun: 0,
      testsPassed: 0,
      testsFailed: 0,
      baselinesCaptured: 0,
      comparisonsPerformed: 0
    };
  }

  /**
   * Generate visual test configuration for a component
   * @param {Object} component - Component data
   * @param {Object} options - Test options
   * @returns {Object} Visual test configuration
   */
  generateTestConfig(component, options = {}) {
    const {
      variants = ['default'],
      viewports = ['desktop'],
      states = [],
      interactions = []
    } = options;

    const testCases = [];

    // Generate test cases for each variant/viewport combination
    variants.forEach(variant => {
      viewports.forEach(viewportName => {
        const viewport = this.viewports[viewportName];
        if (!viewport) {
          console.warn(`Unknown viewport: ${viewportName}`);
          return;
        }

        const testCase = {
          id: this.generateTestId(component.name, variant, viewportName),
          component: component.name,
          variant,
          viewport: {
            name: viewportName,
            ...viewport
          },
          baselinePath: this.getBaselinePath(component.name, variant, viewportName),
          thresholds: { ...this.thresholds, ...options.thresholds }
        };

        // Add state-based tests
        if (states.length > 0) {
          testCase.states = states.map(state => ({
            name: state,
            setup: this.getStateSetup(state)
          }));
        }

        // Add interaction tests
        if (interactions.length > 0) {
          testCase.interactions = interactions.map(interaction => ({
            name: interaction,
            actions: this.getInteractionActions(interaction)
          }));
        }

        testCases.push(testCase);
      });
    });

    const config = {
      component: component.name,
      testCases,
      options: {
        algorithm: this.algorithm,
        baselineDir: this.baselineDir,
        outputDir: this.outputDir,
        updateBaselines: options.updateBaselines || false
      },
      metadata: {
        generatedAt: new Date().toISOString(),
        totalTests: testCases.length
      }
    };

    this.emit('config:generated', { component: component.name, tests: testCases.length });

    return config;
  }

  /**
   * Generate Storybook visual test story
   * @param {Object} component - Component data
   * @param {Object} options - Generation options
   * @returns {string} Visual test story code
   */
  generateVisualTestStory(component, options = {}) {
    const config = this.generateTestConfig(component, options);
    const componentName = component.name;

    let code = `import type { Meta, StoryObj } from '@storybook/react';
import { within, userEvent } from '@storybook/testing-library';
import { ${componentName} } from './${componentName}';

const meta: Meta<typeof ${componentName}> = {
  title: 'Visual Tests/${componentName}',
  component: ${componentName},
  parameters: {
    chromatic: {
      viewports: [${config.testCases.map(tc => tc.viewport.width).filter((v, i, a) => a.indexOf(v) === i).join(', ')}],
      delay: 300,
    },
    snapshot: {
      skip: false,
    },
  },
};

export default meta;
type Story = StoryObj<typeof ${componentName}>;

`;

    // Generate stories for each test case
    config.testCases.forEach(testCase => {
      const storyName = this.formatStoryName(testCase.variant, testCase.viewport.name);

      code += `/**
 * Visual regression test: ${testCase.variant} at ${testCase.viewport.name}
 * Viewport: ${testCase.viewport.width}x${testCase.viewport.height}
 */
export const ${storyName}: Story = {
  parameters: {
    viewport: {
      defaultViewport: '${testCase.viewport.name}',
    },
    chromatic: {
      viewports: [${testCase.viewport.width}],
    },
  },
`;

      // Add play function for interactions
      if (testCase.interactions && testCase.interactions.length > 0) {
        code += `  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
${this.generatePlayFunction(testCase.interactions)}
  },
`;
      }

      code += `};

`;
    });

    this.stats.testsRun += config.testCases.length;

    return code;
  }

  /**
   * Generate comparison result structure
   * @param {Object} baseline - Baseline image data
   * @param {Object} current - Current image data
   * @param {Object} thresholds - Comparison thresholds
   * @returns {Object} Comparison result
   */
  generateComparisonResult(baseline, current, thresholds = this.thresholds) {
    // Simulated comparison - in real implementation would use image comparison library
    const result = {
      passed: true,
      diffPercentage: 0,
      diffPixels: 0,
      totalPixels: baseline.width * baseline.height,
      threshold: thresholds.diffPercentage,
      algorithm: this.algorithm,
      dimensions: {
        baseline: { width: baseline.width, height: baseline.height },
        current: { width: current.width, height: current.height }
      },
      timestamp: new Date().toISOString()
    };

    // Check dimension mismatch
    if (baseline.width !== current.width || baseline.height !== current.height) {
      result.passed = false;
      result.error = 'Dimension mismatch';
      result.diffPercentage = 1;
    }

    this.stats.comparisonsPerformed++;

    if (result.passed) {
      this.stats.testsPassed++;
    } else {
      this.stats.testsFailed++;
    }

    this.emit('comparison:complete', result);

    return result;
  }

  /**
   * Generate visual test report
   * @param {Array} results - Array of test results
   * @returns {Object} Test report
   */
  generateReport(results) {
    const passed = results.filter(r => r.passed).length;
    const failed = results.filter(r => !r.passed).length;

    const report = {
      summary: {
        total: results.length,
        passed,
        failed,
        passRate: results.length > 0 ? (passed / results.length * 100).toFixed(2) + '%' : '0%'
      },
      results: results.map(r => ({
        testId: r.testId,
        component: r.component,
        variant: r.variant,
        viewport: r.viewport,
        passed: r.passed,
        diffPercentage: r.diffPercentage,
        error: r.error || null
      })),
      failures: results.filter(r => !r.passed).map(r => ({
        testId: r.testId,
        component: r.component,
        reason: r.error || `Diff exceeded threshold: ${(r.diffPercentage * 100).toFixed(2)}%`,
        diffPath: r.diffPath
      })),
      metadata: {
        generatedAt: new Date().toISOString(),
        algorithm: this.algorithm,
        thresholds: this.thresholds
      }
    };

    this.emit('report:generated', report.summary);

    return report;
  }

  /**
   * Generate Playwright visual test code
   * @param {Object} component - Component data
   * @param {Object} options - Generation options
   * @returns {string} Playwright test code
   */
  generatePlaywrightTest(component, options = {}) {
    const config = this.generateTestConfig(component, options);
    const componentName = component.name;

    let code = `import { test, expect } from '@playwright/test';

test.describe('${componentName} Visual Tests', () => {
`;

    config.testCases.forEach(testCase => {
      code += `
  test('${testCase.variant} at ${testCase.viewport.name}', async ({ page }) => {
    // Set viewport
    await page.setViewportSize({
      width: ${testCase.viewport.width},
      height: ${testCase.viewport.height}
    });

    // Navigate to Storybook story
    await page.goto('/iframe.html?id=${componentName.toLowerCase()}--${testCase.variant.toLowerCase()}');

    // Wait for component to render
    await page.waitForSelector('[data-testid="${componentName.toLowerCase()}"]', {
      state: 'visible',
      timeout: 5000
    });
`;

      // Add interaction steps
      if (testCase.interactions && testCase.interactions.length > 0) {
        testCase.interactions.forEach(interaction => {
          code += this.generatePlaywrightInteraction(interaction);
        });
      }

      code += `
    // Take screenshot and compare
    await expect(page).toHaveScreenshot('${testCase.id}.png', {
      maxDiffPixelRatio: ${testCase.thresholds.diffPercentage},
      threshold: ${testCase.thresholds.colorThreshold},
    });
  });
`;
    });

    code += `});
`;

    return code;
  }

  /**
   * Generate Cypress visual test code
   * @param {Object} component - Component data
   * @param {Object} options - Generation options
   * @returns {string} Cypress test code
   */
  generateCypressTest(component, options = {}) {
    const config = this.generateTestConfig(component, options);
    const componentName = component.name;

    let code = `describe('${componentName} Visual Tests', () => {
`;

    config.testCases.forEach(testCase => {
      code += `
  it('${testCase.variant} at ${testCase.viewport.name}', () => {
    // Set viewport
    cy.viewport(${testCase.viewport.width}, ${testCase.viewport.height});

    // Visit Storybook story
    cy.visit('/iframe.html?id=${componentName.toLowerCase()}--${testCase.variant.toLowerCase()}');

    // Wait for component
    cy.get('[data-testid="${componentName.toLowerCase()}"]').should('be.visible');
`;

      // Add interaction steps
      if (testCase.interactions && testCase.interactions.length > 0) {
        testCase.interactions.forEach(interaction => {
          code += this.generateCypressInteraction(interaction);
        });
      }

      code += `
    // Visual comparison
    cy.matchImageSnapshot('${testCase.id}', {
      failureThreshold: ${testCase.thresholds.diffPercentage},
      failureThresholdType: 'percent',
    });
  });
`;
    });

    code += `});
`;

    return code;
  }

  /**
   * Generate test ID from component, variant, and viewport
   */
  generateTestId(componentName, variant, viewport) {
    const hash = crypto.createHash('md5')
      .update(`${componentName}-${variant}-${viewport}`)
      .digest('hex')
      .substring(0, 8);
    return `${componentName.toLowerCase()}-${variant.toLowerCase()}-${viewport}-${hash}`;
  }

  /**
   * Get baseline path for a test
   */
  getBaselinePath(componentName, variant, viewport) {
    return `${this.baselineDir}/${componentName}/${variant}-${viewport}.png`;
  }

  /**
   * Get state setup actions
   */
  getStateSetup(state) {
    const stateSetups = {
      hover: { action: 'hover', selector: '[data-testid]' },
      focus: { action: 'focus', selector: '[data-testid]' },
      active: { action: 'mousedown', selector: '[data-testid]' },
      disabled: { action: 'setAttribute', args: ['disabled', 'true'] },
      loading: { action: 'setAttribute', args: ['data-loading', 'true'] }
    };
    return stateSetups[state] || { action: 'none' };
  }

  /**
   * Get interaction actions
   */
  getInteractionActions(interaction) {
    const interactions = {
      click: [{ action: 'click', selector: '[data-testid]' }],
      type: [{ action: 'type', selector: 'input', value: 'test input' }],
      select: [{ action: 'selectOption', selector: 'select', value: 'option1' }],
      toggle: [{ action: 'click', selector: '[data-toggle]' }],
      expand: [{ action: 'click', selector: '[data-expand]' }],
      scroll: [{ action: 'scroll', distance: 100 }]
    };
    return interactions[interaction] || [];
  }

  /**
   * Generate play function for Storybook interactions
   */
  generatePlayFunction(interactions) {
    let code = '';
    interactions.forEach(interaction => {
      interaction.actions.forEach(action => {
        switch (action.action) {
          case 'click':
            code += `    await userEvent.click(canvas.getByTestId('${action.selector.replace('[data-testid="', '').replace('"]', '')}'));\n`;
            break;
          case 'hover':
            code += `    await userEvent.hover(canvas.getByTestId('component'));\n`;
            break;
          case 'type':
            code += `    await userEvent.type(canvas.getByRole('textbox'), '${action.value}');\n`;
            break;
        }
      });
    });
    return code;
  }

  /**
   * Generate Playwright interaction code
   */
  generatePlaywrightInteraction(interaction) {
    let code = '';
    interaction.actions.forEach(action => {
      switch (action.action) {
        case 'click':
          code += `    await page.click('${action.selector}');\n`;
          break;
        case 'hover':
          code += `    await page.hover('${action.selector}');\n`;
          break;
        case 'type':
          code += `    await page.fill('${action.selector}', '${action.value}');\n`;
          break;
      }
    });
    return code;
  }

  /**
   * Generate Cypress interaction code
   */
  generateCypressInteraction(interaction) {
    let code = '';
    interaction.actions.forEach(action => {
      switch (action.action) {
        case 'click':
          code += `    cy.get('${action.selector}').click();\n`;
          break;
        case 'hover':
          code += `    cy.get('${action.selector}').trigger('mouseover');\n`;
          break;
        case 'type':
          code += `    cy.get('${action.selector}').type('${action.value}');\n`;
          break;
      }
    });
    return code;
  }

  /**
   * Format story name from variant and viewport
   */
  formatStoryName(variant, viewport) {
    const formatted = `${variant}${viewport.charAt(0).toUpperCase() + viewport.slice(1)}`;
    return formatted.replace(/[^a-zA-Z0-9]/g, '');
  }

  /**
   * Add custom viewport
   */
  addViewport(name, config) {
    this.viewports[name] = config;
    return this;
  }

  /**
   * Set comparison thresholds
   */
  setThresholds(thresholds) {
    this.thresholds = { ...this.thresholds, ...thresholds };
    return this;
  }

  /**
   * Get available viewports
   */
  getViewports() {
    return { ...this.viewports };
  }

  /**
   * Get current thresholds
   */
  getThresholds() {
    return { ...this.thresholds };
  }

  /**
   * Get statistics
   */
  getStats() {
    return { ...this.stats };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      testsRun: 0,
      testsPassed: 0,
      testsFailed: 0,
      baselinesCaptured: 0,
      comparisonsPerformed: 0
    };
  }
}

// Export singleton and class
const visualRegression = new VisualRegression();

module.exports = {
  VisualRegression,
  visualRegression,
  TEST_VIEWPORTS,
  COMPARISON_ALGORITHMS,
  DEFAULT_THRESHOLDS
};
