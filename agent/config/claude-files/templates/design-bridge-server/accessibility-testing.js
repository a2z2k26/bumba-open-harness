/**
 * accessibility-testing.js
 * Sprint 6.2: Accessibility Testing Integration
 *
 * Provides automated accessibility testing:
 * - WCAG guideline validation
 * - ARIA attribute checking
 * - Color contrast analysis
 * - Keyboard navigation testing
 * - Screen reader compatibility
 */

const EventEmitter = require('events');

/**
 * WCAG 2.1 Guidelines mapping
 */
const WCAG_GUIDELINES = {
  perceivable: {
    '1.1.1': { name: 'Non-text Content', level: 'A' },
    '1.2.1': { name: 'Audio-only and Video-only', level: 'A' },
    '1.3.1': { name: 'Info and Relationships', level: 'A' },
    '1.3.2': { name: 'Meaningful Sequence', level: 'A' },
    '1.3.3': { name: 'Sensory Characteristics', level: 'A' },
    '1.4.1': { name: 'Use of Color', level: 'A' },
    '1.4.2': { name: 'Audio Control', level: 'A' },
    '1.4.3': { name: 'Contrast (Minimum)', level: 'AA' },
    '1.4.4': { name: 'Resize Text', level: 'AA' },
    '1.4.5': { name: 'Images of Text', level: 'AA' },
    '1.4.6': { name: 'Contrast (Enhanced)', level: 'AAA' },
    '1.4.10': { name: 'Reflow', level: 'AA' },
    '1.4.11': { name: 'Non-text Contrast', level: 'AA' },
    '1.4.12': { name: 'Text Spacing', level: 'AA' },
    '1.4.13': { name: 'Content on Hover or Focus', level: 'AA' }
  },
  operable: {
    '2.1.1': { name: 'Keyboard', level: 'A' },
    '2.1.2': { name: 'No Keyboard Trap', level: 'A' },
    '2.1.4': { name: 'Character Key Shortcuts', level: 'A' },
    '2.2.1': { name: 'Timing Adjustable', level: 'A' },
    '2.2.2': { name: 'Pause, Stop, Hide', level: 'A' },
    '2.3.1': { name: 'Three Flashes or Below', level: 'A' },
    '2.4.1': { name: 'Bypass Blocks', level: 'A' },
    '2.4.2': { name: 'Page Titled', level: 'A' },
    '2.4.3': { name: 'Focus Order', level: 'A' },
    '2.4.4': { name: 'Link Purpose', level: 'A' },
    '2.4.6': { name: 'Headings and Labels', level: 'AA' },
    '2.4.7': { name: 'Focus Visible', level: 'AA' },
    '2.5.1': { name: 'Pointer Gestures', level: 'A' },
    '2.5.2': { name: 'Pointer Cancellation', level: 'A' },
    '2.5.3': { name: 'Label in Name', level: 'A' },
    '2.5.4': { name: 'Motion Actuation', level: 'A' }
  },
  understandable: {
    '3.1.1': { name: 'Language of Page', level: 'A' },
    '3.1.2': { name: 'Language of Parts', level: 'AA' },
    '3.2.1': { name: 'On Focus', level: 'A' },
    '3.2.2': { name: 'On Input', level: 'A' },
    '3.2.3': { name: 'Consistent Navigation', level: 'AA' },
    '3.2.4': { name: 'Consistent Identification', level: 'AA' },
    '3.3.1': { name: 'Error Identification', level: 'A' },
    '3.3.2': { name: 'Labels or Instructions', level: 'A' },
    '3.3.3': { name: 'Error Suggestion', level: 'AA' },
    '3.3.4': { name: 'Error Prevention', level: 'AA' }
  },
  robust: {
    '4.1.1': { name: 'Parsing', level: 'A' },
    '4.1.2': { name: 'Name, Role, Value', level: 'A' },
    '4.1.3': { name: 'Status Messages', level: 'AA' }
  }
};

/**
 * ARIA roles and their requirements
 */
const ARIA_ROLES = {
  button: {
    required: [],
    supported: ['aria-pressed', 'aria-expanded', 'aria-haspopup', 'aria-disabled'],
    focusable: true,
    keyboard: ['Enter', 'Space']
  },
  checkbox: {
    required: ['aria-checked'],
    supported: ['aria-readonly', 'aria-required'],
    focusable: true,
    keyboard: ['Space']
  },
  combobox: {
    required: ['aria-expanded'],
    supported: ['aria-autocomplete', 'aria-haspopup', 'aria-activedescendant'],
    focusable: true,
    keyboard: ['ArrowDown', 'ArrowUp', 'Enter', 'Escape']
  },
  dialog: {
    required: [],
    supported: ['aria-modal', 'aria-labelledby', 'aria-describedby'],
    focusable: true,
    keyboard: ['Escape', 'Tab']
  },
  link: {
    required: [],
    supported: ['aria-expanded', 'aria-haspopup'],
    focusable: true,
    keyboard: ['Enter']
  },
  listbox: {
    required: [],
    supported: ['aria-multiselectable', 'aria-activedescendant', 'aria-required'],
    focusable: true,
    keyboard: ['ArrowDown', 'ArrowUp', 'Home', 'End']
  },
  menu: {
    required: [],
    supported: ['aria-activedescendant', 'aria-orientation'],
    focusable: true,
    keyboard: ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Escape']
  },
  menuitem: {
    required: [],
    supported: ['aria-haspopup', 'aria-expanded'],
    focusable: true,
    keyboard: ['Enter', 'Space']
  },
  progressbar: {
    required: [],
    supported: ['aria-valuenow', 'aria-valuemin', 'aria-valuemax', 'aria-valuetext'],
    focusable: false,
    keyboard: []
  },
  radio: {
    required: ['aria-checked'],
    supported: ['aria-posinset', 'aria-setsize'],
    focusable: true,
    keyboard: ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight']
  },
  slider: {
    required: ['aria-valuenow', 'aria-valuemin', 'aria-valuemax'],
    supported: ['aria-valuetext', 'aria-orientation'],
    focusable: true,
    keyboard: ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End']
  },
  switch: {
    required: ['aria-checked'],
    supported: ['aria-readonly'],
    focusable: true,
    keyboard: ['Space']
  },
  tab: {
    required: ['aria-selected'],
    supported: ['aria-controls', 'aria-haspopup'],
    focusable: true,
    keyboard: ['ArrowLeft', 'ArrowRight', 'Home', 'End']
  },
  tabpanel: {
    required: [],
    supported: ['aria-labelledby'],
    focusable: true,
    keyboard: ['Tab']
  },
  textbox: {
    required: [],
    supported: ['aria-multiline', 'aria-placeholder', 'aria-readonly', 'aria-required'],
    focusable: true,
    keyboard: []
  },
  tooltip: {
    required: [],
    supported: [],
    focusable: false,
    keyboard: ['Escape']
  }
};

/**
 * Color contrast requirements
 */
const CONTRAST_REQUIREMENTS = {
  normal: {
    AA: 4.5,
    AAA: 7.0
  },
  large: {
    AA: 3.0,
    AAA: 4.5
  },
  ui: {
    AA: 3.0
  }
};

class AccessibilityTesting extends EventEmitter {
  constructor(options = {}) {
    super();

    this.wcagLevel = options.wcagLevel || 'AA';
    this.guidelines = WCAG_GUIDELINES;
    this.ariaRoles = ARIA_ROLES;
    this.contrastRequirements = CONTRAST_REQUIREMENTS;

    this.stats = {
      testsRun: 0,
      passed: 0,
      failed: 0,
      warnings: 0
    };
  }

  /**
   * Generate accessibility test configuration for a component
   * @param {Object} component - Component data
   * @param {Object} options - Test options
   * @returns {Object} Test configuration
   */
  generateTestConfig(component, options = {}) {
    const {
      role = 'generic',
      interactiveElements = [],
      formElements = []
    } = options;

    const roleConfig = this.ariaRoles[role] || {};

    const config = {
      component: component.name,
      role,
      tests: {
        aria: this.generateAriaTests(component, role, roleConfig),
        keyboard: this.generateKeyboardTests(component, role, roleConfig),
        contrast: this.generateContrastTests(component),
        structure: this.generateStructureTests(component),
        focus: this.generateFocusTests(component, roleConfig)
      },
      wcagCoverage: this.getWCAGCoverage(role),
      metadata: {
        generatedAt: new Date().toISOString(),
        wcagLevel: this.wcagLevel
      }
    };

    this.emit('config:generated', { component: component.name });
    return config;
  }

  /**
   * Generate ARIA attribute tests
   */
  generateAriaTests(component, role, roleConfig) {
    const tests = [];

    // Test for required ARIA attributes
    if (roleConfig.required && roleConfig.required.length > 0) {
      roleConfig.required.forEach(attr => {
        tests.push({
          name: `has required ${attr}`,
          type: 'aria-required',
          attribute: attr,
          severity: 'error',
          wcag: '4.1.2'
        });
      });
    }

    // Test for role attribute
    if (role !== 'generic') {
      tests.push({
        name: `has role="${role}"`,
        type: 'aria-role',
        expectedRole: role,
        severity: 'error',
        wcag: '4.1.2'
      });
    }

    // Test for accessible name
    tests.push({
      name: 'has accessible name',
      type: 'accessible-name',
      severity: 'error',
      wcag: '4.1.2'
    });

    // Test for proper labeling
    tests.push({
      name: 'has associated label or aria-label',
      type: 'labeling',
      severity: 'error',
      wcag: '3.3.2'
    });

    return tests;
  }

  /**
   * Generate keyboard accessibility tests
   */
  generateKeyboardTests(component, role, roleConfig) {
    const tests = [];

    // Focusability test
    if (roleConfig.focusable !== false) {
      tests.push({
        name: 'is focusable via keyboard',
        type: 'focusable',
        severity: 'error',
        wcag: '2.1.1'
      });
    }

    // Key handler tests
    if (roleConfig.keyboard && roleConfig.keyboard.length > 0) {
      roleConfig.keyboard.forEach(key => {
        tests.push({
          name: `responds to ${key} key`,
          type: 'keyboard-handler',
          key,
          severity: 'error',
          wcag: '2.1.1'
        });
      });
    }

    // No keyboard trap test
    tests.push({
      name: 'does not trap keyboard focus',
      type: 'no-trap',
      severity: 'critical',
      wcag: '2.1.2'
    });

    // Focus visible test
    tests.push({
      name: 'has visible focus indicator',
      type: 'focus-visible',
      severity: 'error',
      wcag: '2.4.7'
    });

    return tests;
  }

  /**
   * Generate color contrast tests
   */
  generateContrastTests(component) {
    const requirement = this.contrastRequirements.normal[this.wcagLevel];

    return [
      {
        name: `text has ${requirement}:1 contrast ratio`,
        type: 'contrast-text',
        minRatio: requirement,
        severity: 'error',
        wcag: this.wcagLevel === 'AAA' ? '1.4.6' : '1.4.3'
      },
      {
        name: 'UI components have 3:1 contrast ratio',
        type: 'contrast-ui',
        minRatio: 3.0,
        severity: 'error',
        wcag: '1.4.11'
      },
      {
        name: 'focus indicator has sufficient contrast',
        type: 'contrast-focus',
        minRatio: 3.0,
        severity: 'error',
        wcag: '1.4.11'
      }
    ];
  }

  /**
   * Generate structure tests
   */
  generateStructureTests(component) {
    return [
      {
        name: 'has valid HTML structure',
        type: 'valid-html',
        severity: 'error',
        wcag: '4.1.1'
      },
      {
        name: 'uses semantic HTML elements',
        type: 'semantic-html',
        severity: 'warning',
        wcag: '1.3.1'
      },
      {
        name: 'maintains meaningful sequence',
        type: 'meaningful-sequence',
        severity: 'error',
        wcag: '1.3.2'
      },
      {
        name: 'has logical heading hierarchy',
        type: 'heading-hierarchy',
        severity: 'warning',
        wcag: '2.4.6'
      }
    ];
  }

  /**
   * Generate focus management tests
   */
  generateFocusTests(component, roleConfig) {
    const tests = [
      {
        name: 'follows logical focus order',
        type: 'focus-order',
        severity: 'error',
        wcag: '2.4.3'
      }
    ];

    if (roleConfig.focusable !== false) {
      tests.push({
        name: 'included in tab sequence',
        type: 'tab-sequence',
        severity: 'error',
        wcag: '2.1.1'
      });
    }

    return tests;
  }

  /**
   * Get WCAG coverage for a role
   */
  getWCAGCoverage(role) {
    const coverage = [];

    // Map role to relevant WCAG criteria
    const roleCoverage = {
      button: ['1.3.1', '2.1.1', '4.1.2'],
      checkbox: ['1.3.1', '2.1.1', '3.3.2', '4.1.2'],
      combobox: ['1.3.1', '2.1.1', '2.1.2', '3.3.2', '4.1.2'],
      dialog: ['1.3.1', '2.1.1', '2.1.2', '2.4.3', '4.1.2'],
      link: ['1.3.1', '2.1.1', '2.4.4', '4.1.2'],
      listbox: ['1.3.1', '2.1.1', '4.1.2'],
      menu: ['1.3.1', '2.1.1', '2.1.2', '4.1.2'],
      slider: ['1.3.1', '2.1.1', '3.3.2', '4.1.2'],
      tab: ['1.3.1', '2.1.1', '4.1.2'],
      textbox: ['1.3.1', '2.1.1', '3.3.2', '4.1.2']
    };

    const criteria = roleCoverage[role] || ['1.3.1', '4.1.2'];

    criteria.forEach(criterion => {
      for (const [principle, guidelines] of Object.entries(this.guidelines)) {
        if (guidelines[criterion]) {
          coverage.push({
            criterion,
            ...guidelines[criterion],
            principle
          });
        }
      }
    });

    return coverage;
  }

  /**
   * Generate Jest/Testing Library accessibility tests
   * @param {Object} component - Component data
   * @param {Object} options - Generation options
   * @returns {string} Test code
   */
  generateA11yTestCode(component, options = {}) {
    const config = this.generateTestConfig(component, options);
    const componentName = component.name;

    let code = `import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';
import { ${componentName} } from './${componentName}';

expect.extend(toHaveNoViolations);

describe('${componentName} Accessibility', () => {
  // Automated axe-core tests
  describe('Automated a11y checks', () => {
    it('has no accessibility violations', async () => {
      const { container } = render(<${componentName} />);
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    });
  });

`;

    // Add ARIA tests
    code += `  // ARIA attribute tests
  describe('ARIA attributes', () => {
`;
    config.tests.aria.forEach(test => {
      code += this.generateJestTest(test, componentName);
    });
    code += `  });

`;

    // Add keyboard tests
    code += `  // Keyboard accessibility tests
  describe('Keyboard navigation', () => {
`;
    config.tests.keyboard.forEach(test => {
      code += this.generateJestTest(test, componentName);
    });
    code += `  });

`;

    // Add focus tests
    code += `  // Focus management tests
  describe('Focus management', () => {
`;
    config.tests.focus.forEach(test => {
      code += this.generateJestTest(test, componentName);
    });
    code += `  });
});
`;

    this.stats.testsRun += config.tests.aria.length +
      config.tests.keyboard.length +
      config.tests.focus.length;

    return code;
  }

  /**
   * Generate individual Jest test
   */
  generateJestTest(test, componentName) {
    let testCode = '';

    switch (test.type) {
      case 'aria-role':
        testCode = `    it('${test.name}', () => {
      render(<${componentName} />);
      const element = screen.getByRole('${test.expectedRole}');
      expect(element).toBeInTheDocument();
    });

`;
        break;

      case 'aria-required':
        testCode = `    it('${test.name}', () => {
      render(<${componentName} />);
      const element = screen.getByRole('${componentName.toLowerCase()}');
      expect(element).toHaveAttribute('${test.attribute}');
    });

`;
        break;

      case 'accessible-name':
        testCode = `    it('${test.name}', () => {
      render(<${componentName} label="Test Label" />);
      const element = screen.getByRole('${componentName.toLowerCase()}', { name: /test label/i });
      expect(element).toBeInTheDocument();
    });

`;
        break;

      case 'focusable':
        testCode = `    it('${test.name}', () => {
      render(<${componentName} />);
      const element = screen.getByRole('${componentName.toLowerCase()}');
      element.focus();
      expect(element).toHaveFocus();
    });

`;
        break;

      case 'keyboard-handler':
        testCode = `    it('${test.name}', () => {
      const handleAction = jest.fn();
      render(<${componentName} onClick={handleAction} />);
      const element = screen.getByRole('${componentName.toLowerCase()}');
      fireEvent.keyDown(element, { key: '${test.key}' });
      expect(handleAction).toHaveBeenCalled();
    });

`;
        break;

      case 'focus-visible':
        testCode = `    it('${test.name}', () => {
      render(<${componentName} />);
      const element = screen.getByRole('${componentName.toLowerCase()}');
      element.focus();
      // Check for focus-visible styles
      expect(element).toHaveClass('focus-visible');
    });

`;
        break;

      case 'focus-order':
        testCode = `    it('${test.name}', () => {
      render(
        <>
          <${componentName} data-testid="first" />
          <${componentName} data-testid="second" />
        </>
      );
      const first = screen.getByTestId('first');
      const second = screen.getByTestId('second');
      first.focus();
      expect(first).toHaveFocus();
      fireEvent.keyDown(first, { key: 'Tab' });
      expect(second).toHaveFocus();
    });

`;
        break;

      default:
        testCode = `    it.todo('${test.name}');

`;
    }

    return testCode;
  }

  /**
   * Generate Storybook accessibility story
   * @param {Object} component - Component data
   * @param {Object} options - Generation options
   * @returns {string} Story code
   */
  generateA11yStory(component, options = {}) {
    const componentName = component.name;
    const config = this.generateTestConfig(component, options);

    return `import type { Meta, StoryObj } from '@storybook/react';
import { within, userEvent, waitFor } from '@storybook/testing-library';
import { expect } from '@storybook/jest';
import { ${componentName} } from './${componentName}';

const meta: Meta<typeof ${componentName}> = {
  title: 'Accessibility/${componentName}',
  component: ${componentName},
  parameters: {
    a11y: {
      // axe-core configuration
      config: {
        rules: [
          { id: 'color-contrast', enabled: true },
          { id: 'valid-aria-role', enabled: true },
          { id: 'aria-required-attr', enabled: true },
        ],
      },
    },
    docs: {
      description: {
        component: 'Accessibility tests for ${componentName}. WCAG ${this.wcagLevel} compliant.',
      },
    },
  },
};

export default meta;
type Story = StoryObj<typeof ${componentName}>;

/**
 * Default accessible component
 */
export const Accessible: Story = {
  args: {
    label: '${componentName}',
  },
};

/**
 * Keyboard navigation test
 */
export const KeyboardNavigation: Story = {
  args: {
    label: 'Focus me',
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const element = canvas.getByRole('${options.role || componentName.toLowerCase()}');

    // Test focus
    await userEvent.tab();
    await expect(element).toHaveFocus();

${config.tests.keyboard.filter(t => t.type === 'keyboard-handler').map(t => `    // Test ${t.key} key
    await userEvent.keyboard('{${t.key}}');`).join('\n')}
  },
};

/**
 * Screen reader test - demonstrates proper labeling
 */
export const ScreenReaderFriendly: Story = {
  args: {
    label: 'Accessible ${componentName}',
    'aria-describedby': 'help-text',
  },
  decorators: [
    (Story) => (
      <>
        <Story />
        <span id="help-text" className="sr-only">
          Additional context for screen readers
        </span>
      </>
    ),
  ],
};

/**
 * High contrast mode test
 */
export const HighContrast: Story = {
  args: {
    label: 'High Contrast ${componentName}',
  },
  parameters: {
    backgrounds: { default: 'dark' },
  },
};

/**
 * Reduced motion test
 */
export const ReducedMotion: Story = {
  args: {
    label: 'Reduced Motion',
  },
  parameters: {
    chromatic: { prefersReducedMotion: 'reduce' },
  },
  decorators: [
    (Story) => (
      <div style={{ '--motion-duration': '0s' } as React.CSSProperties}>
        <Story />
      </div>
    ),
  ],
};
`;
  }

  /**
   * Generate accessibility report
   * @param {Array} results - Test results
   * @returns {Object} Accessibility report
   */
  generateReport(results) {
    const violations = results.filter(r => r.severity === 'error' && !r.passed);
    const warnings = results.filter(r => r.severity === 'warning' && !r.passed);
    const passed = results.filter(r => r.passed);

    const report = {
      summary: {
        total: results.length,
        passed: passed.length,
        violations: violations.length,
        warnings: warnings.length,
        wcagLevel: this.wcagLevel,
        score: Math.round((passed.length / results.length) * 100)
      },
      violations: violations.map(v => ({
        test: v.name,
        wcag: v.wcag,
        severity: v.severity,
        message: v.message || `Failed: ${v.name}`,
        element: v.element || null
      })),
      warnings: warnings.map(w => ({
        test: w.name,
        wcag: w.wcag,
        message: w.message || `Warning: ${w.name}`
      })),
      wcagCoverage: this.calculateWCAGCoverage(results),
      recommendations: this.generateRecommendations(violations, warnings),
      metadata: {
        generatedAt: new Date().toISOString(),
        wcagLevel: this.wcagLevel
      }
    };

    this.stats.passed = passed.length;
    this.stats.failed = violations.length;
    this.stats.warnings = warnings.length;

    this.emit('report:generated', report.summary);
    return report;
  }

  /**
   * Calculate WCAG coverage
   */
  calculateWCAGCoverage(results) {
    const covered = new Set();
    const partial = new Set();
    const missing = new Set();

    results.forEach(result => {
      if (result.wcag) {
        if (result.passed) {
          covered.add(result.wcag);
        } else {
          partial.add(result.wcag);
        }
      }
    });

    // Check for missing criteria based on level
    const allCriteria = [];
    Object.values(this.guidelines).forEach(principle => {
      Object.entries(principle).forEach(([criterion, config]) => {
        if (this.wcagLevel === 'AAA' ||
          (this.wcagLevel === 'AA' && config.level !== 'AAA') ||
          (this.wcagLevel === 'A' && config.level === 'A')) {
          allCriteria.push(criterion);
        }
      });
    });

    allCriteria.forEach(criterion => {
      if (!covered.has(criterion) && !partial.has(criterion)) {
        missing.add(criterion);
      }
    });

    return {
      covered: Array.from(covered),
      partial: Array.from(partial),
      missing: Array.from(missing),
      percentage: Math.round((covered.size / allCriteria.length) * 100)
    };
  }

  /**
   * Generate recommendations based on failures
   */
  generateRecommendations(violations, warnings) {
    const recommendations = [];

    violations.forEach(v => {
      switch (v.type) {
        case 'contrast-text':
          recommendations.push({
            priority: 'high',
            issue: 'Insufficient text contrast',
            fix: 'Increase contrast ratio to at least 4.5:1 for normal text',
            wcag: '1.4.3'
          });
          break;
        case 'aria-required':
          recommendations.push({
            priority: 'high',
            issue: `Missing required ARIA attribute: ${v.attribute}`,
            fix: `Add ${v.attribute} attribute to the element`,
            wcag: '4.1.2'
          });
          break;
        case 'focusable':
          recommendations.push({
            priority: 'high',
            issue: 'Element not keyboard focusable',
            fix: 'Ensure interactive elements have tabindex="0" or are natively focusable',
            wcag: '2.1.1'
          });
          break;
        case 'focus-visible':
          recommendations.push({
            priority: 'medium',
            issue: 'Focus indicator not visible',
            fix: 'Add :focus-visible styles or outline to interactive elements',
            wcag: '2.4.7'
          });
          break;
      }
    });

    return recommendations;
  }

  /**
   * Generate Playwright accessibility test
   * @param {Object} component - Component data
   * @param {Object} options - Generation options
   * @returns {string} Playwright test code
   */
  generatePlaywrightA11yTest(component, options = {}) {
    const componentName = component.name;

    return `import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.describe('${componentName} Accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/iframe.html?id=${componentName.toLowerCase()}--default');
  });

  test('should pass axe accessibility scan', async ({ page }) => {
    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test('should be keyboard navigable', async ({ page }) => {
    // Tab to the component
    await page.keyboard.press('Tab');

    // Verify focus
    const activeElement = await page.evaluate(() => document.activeElement?.tagName);
    expect(activeElement).not.toBe('BODY');
  });

  test('should have visible focus indicator', async ({ page }) => {
    await page.keyboard.press('Tab');

    const focused = page.locator(':focus');
    await expect(focused).toBeVisible();

    // Check for focus outline
    const outline = await focused.evaluate(el => {
      const style = window.getComputedStyle(el);
      return style.outline || style.boxShadow;
    });

    expect(outline).not.toBe('none');
  });

  test('should have proper ARIA attributes', async ({ page }) => {
    const component = page.locator('[data-testid="${componentName.toLowerCase()}"]');

    // Check for role
    await expect(component).toHaveAttribute('role');

    // Check for accessible name
    const name = await component.evaluate(el => {
      return el.getAttribute('aria-label') ||
             el.getAttribute('aria-labelledby') ||
             el.textContent?.trim();
    });

    expect(name).toBeTruthy();
  });

  test('should support reduced motion', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });

    // Check that animations are disabled
    const component = page.locator('[data-testid="${componentName.toLowerCase()}"]');
    const animationDuration = await component.evaluate(el => {
      const style = window.getComputedStyle(el);
      return style.animationDuration;
    });

    expect(animationDuration).toBe('0s');
  });
});
`;
  }

  /**
   * Get WCAG guidelines
   */
  getGuidelines() {
    return { ...this.guidelines };
  }

  /**
   * Get ARIA roles
   */
  getAriaRoles() {
    return { ...this.ariaRoles };
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
      passed: 0,
      failed: 0,
      warnings: 0
    };
  }
}

// Export singleton and class
const accessibilityTesting = new AccessibilityTesting();

module.exports = {
  AccessibilityTesting,
  accessibilityTesting,
  WCAG_GUIDELINES,
  ARIA_ROLES,
  CONTRAST_REQUIREMENTS
};
