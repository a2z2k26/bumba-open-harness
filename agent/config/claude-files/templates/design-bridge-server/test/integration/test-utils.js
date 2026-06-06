/**
 * Test Utilities
 * Helper functions for integration testing
 */

const path = require('path');
const fs = require('fs').promises;

const TestUtils = {
  /**
   * Assert equality
   */
  assertEqual(actual, expected, message = '') {
    if (actual !== expected) {
      throw new Error(
        message || `Expected ${expected}, got ${actual}`
      );
    }
  },

  /**
   * Assert truthy value
   */
  assertTrue(value, message = '') {
    if (!value) {
      throw new Error(message || `Expected truthy value, got ${value}`);
    }
  },

  /**
   * Assert object has property
   */
  assertHasProperty(obj, prop, message = '') {
    if (!(prop in obj)) {
      throw new Error(message || `Expected object to have property: ${prop}`);
    }
  },

  /**
   * Assert array length
   */
  assertLength(arr, length, message = '') {
    if (arr.length !== length) {
      throw new Error(
        message || `Expected array length ${length}, got ${arr.length}`
      );
    }
  },

  /**
   * Assert string contains
   */
  assertContains(str, substring, message = '') {
    if (!str.includes(substring)) {
      throw new Error(
        message || `Expected "${str.substring(0, 50)}..." to contain "${substring}"`
      );
    }
  },

  /**
   * Assert code is valid JavaScript
   */
  assertValidJS(code) {
    try {
      new Function(code);
    } catch (e) {
      throw new Error(`Invalid JavaScript: ${e.message}`);
    }
  },

  /**
   * Assert code is valid TypeScript (basic check)
   */
  assertValidTS(code) {
    // Basic structural checks for TypeScript
    const hasExport = code.includes('export');

    if (!hasExport) {
      throw new Error('TypeScript code should have exports');
    }

    // Check for syntax errors by looking for common issues
    const openBraces = (code.match(/{/g) || []).length;
    const closeBraces = (code.match(/}/g) || []).length;

    if (openBraces !== closeBraces) {
      throw new Error('Mismatched braces in TypeScript code');
    }
  },

  /**
   * Create test fixture directory
   */
  async createFixtureDir(name) {
    const fixtureDir = path.join(__dirname, 'fixtures', name);
    await fs.mkdir(fixtureDir, { recursive: true });
    return fixtureDir;
  },

  /**
   * Clean up test fixture
   */
  async cleanupFixture(dir) {
    try {
      await fs.rm(dir, { recursive: true, force: true });
    } catch (e) {
      // Ignore cleanup errors
    }
  },

  /**
   * Load test fixture data
   */
  async loadFixture(name) {
    const fixturePath = path.join(__dirname, 'fixtures', `${name}.json`);
    const content = await fs.readFile(fixturePath, 'utf-8');
    return JSON.parse(content);
  },

  /**
   * Create mock component data
   */
  createMockComponent(overrides = {}) {
    return {
      id: 'test-component-001',
      name: 'TestComponent',
      type: 'COMPONENT',
      props: {
        variant: { type: 'string', default: 'primary' },
        size: { type: 'string', default: 'medium' },
        disabled: { type: 'boolean', default: false }
      },
      state: {
        isLoading: false,
        isHovered: false
      },
      styles: {
        backgroundColor: '#3B82F6',
        color: '#FFFFFF',
        padding: '12px 24px',
        borderRadius: '8px'
      },
      variants: [
        { name: 'primary', styles: { backgroundColor: '#3B82F6' } },
        { name: 'secondary', styles: { backgroundColor: '#6B7280' } }
      ],
      children: [],
      ...overrides
    };
  },

  /**
   * Create mock token data
   */
  createMockTokens(overrides = {}) {
    return {
      colors: {
        primary: { value: '#3B82F6', type: 'color' },
        secondary: { value: '#6B7280', type: 'color' },
        success: { value: '#10B981', type: 'color' },
        error: { value: '#EF4444', type: 'color' }
      },
      typography: {
        heading: {
          fontFamily: 'Inter',
          fontSize: '24px',
          fontWeight: 700,
          lineHeight: 1.2
        },
        body: {
          fontFamily: 'Inter',
          fontSize: '16px',
          fontWeight: 400,
          lineHeight: 1.5
        }
      },
      spacing: {
        xs: '4px',
        sm: '8px',
        md: '16px',
        lg: '24px',
        xl: '32px'
      },
      ...overrides
    };
  }
};

module.exports = TestUtils;
