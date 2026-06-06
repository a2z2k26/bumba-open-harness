/**
 * Error Handling and Logging Test Suite
 * Phase 3 - Sprints 125-140: Unified Logger and Custom Error Types
 */

const path = require('path');

// Modules under test
const {
  Logger,
  getLogger,
  createLogger,
  resetLogger,
  LOG_LEVELS,
  formatDuration,
  formatTimestamp,
  safeStringify
} = require('../../unified-logger');

const {
  DesignBridgeError,
  ValidationError,
  SchemaValidationError,
  RequiredFieldError,
  ComponentNotFoundError,
  ComponentGenerationError,
  RegistryReadError,
  TokenNotFoundError,
  FigmaApiError,
  FigmaRateLimitError,
  UnsupportedFrameworkError,
  FileNotFoundError,
  SyncConflictError,
  ConfigurationError,
  wrapError,
  isErrorType,
  isRecoverable,
  getErrorCode
} = require('../../error-types');

// Test configuration
const ROOT_DIR = path.join(__dirname, '..', '..');

// Results tracking
const results = {
  passed: 0,
  failed: 0,
  tests: []
};

// ANSI colors
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
  dim: '\x1b[2m',
  bold: '\x1b[1m'
};

/**
 * Test runner helper
 */
function test(name, fn) {
  try {
    const result = fn();
    if (result === true || result === undefined) {
      results.passed++;
      results.tests.push({ name, status: 'PASS' });
      console.log(`  ${colors.green}✓${colors.reset} ${name}`);
    } else {
      results.failed++;
      results.tests.push({ name, status: 'FAIL', error: `Returned: ${JSON.stringify(result)}` });
      console.log(`  ${colors.red}✗${colors.reset} ${name}`);
    }
  } catch (error) {
    results.failed++;
    results.tests.push({ name, status: 'FAIL', error: error.message });
    console.log(`  ${colors.red}✗${colors.reset} ${name}`);
    console.log(`    ${colors.dim}Error: ${error.message}${colors.reset}`);
  }
}

// =============================================================================
// UNIFIED LOGGER TESTS
// =============================================================================

function runLoggerTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 1: Unified Logger${colors.reset}                             ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  // Reset before tests
  resetLogger();

  test('Logger class exists', () => {
    return typeof Logger === 'function';
  });

  test('getLogger returns a Logger instance', () => {
    const logger = getLogger();
    return logger instanceof Logger;
  });

  test('createLogger creates named logger', () => {
    const logger = createLogger('test-module');
    return logger.name === 'test-module';
  });

  test('Logger has all log level methods', () => {
    const logger = createLogger('test');
    return typeof logger.trace === 'function' &&
           typeof logger.debug === 'function' &&
           typeof logger.info === 'function' &&
           typeof logger.warn === 'function' &&
           typeof logger.error === 'function' &&
           typeof logger.fatal === 'function';
  });

  test('LOG_LEVELS has correct values', () => {
    return LOG_LEVELS.TRACE === 0 &&
           LOG_LEVELS.DEBUG === 1 &&
           LOG_LEVELS.INFO === 2 &&
           LOG_LEVELS.WARN === 3 &&
           LOG_LEVELS.ERROR === 4 &&
           LOG_LEVELS.FATAL === 5;
  });

  test('formatDuration formats milliseconds', () => {
    return formatDuration(500) === '500ms';
  });

  test('formatDuration formats seconds', () => {
    const result = formatDuration(2500);
    return result.includes('s') && result.includes('2.5');
  });

  test('formatTimestamp returns ISO string', () => {
    const ts = formatTimestamp();
    return ts.includes('T') && ts.includes('Z');
  });

  test('safeStringify handles circular references', () => {
    const obj = { a: 1 };
    obj.self = obj;
    const result = safeStringify(obj);
    return result.includes('[Circular]');
  });

  test('safeStringify handles Error objects', () => {
    const err = new Error('test error');
    const result = safeStringify({ error: err });
    return result.includes('test error') && result.includes('stack');
  });

  test('Logger.child creates child logger', () => {
    const parent = createLogger('parent');
    const child = parent.child({ name: 'parent:child' });
    return child.name === 'parent:child' && child.parent === parent;
  });

  test('Logger.setLevel updates log level', () => {
    const logger = createLogger('test');
    logger.setLevel('DEBUG');
    return logger.level === LOG_LEVELS.DEBUG;
  });

  test('Logger.time returns timer object', () => {
    const logger = createLogger('test');
    const timer = logger.time('operation');
    return typeof timer.end === 'function';
  });

  test('Logger.getMetrics returns metrics object', () => {
    const logger = createLogger('test');
    logger.info('test message');
    const metrics = logger.getMetrics();
    return metrics.logged.INFO >= 0 && typeof metrics.uptime === 'number';
  });
}

// =============================================================================
// ERROR TYPES TESTS
// =============================================================================

function runErrorTypesTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 2: Error Types${colors.reset}                                ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('DesignBridgeError extends Error', () => {
    const err = new DesignBridgeError('test');
    return err instanceof Error && err instanceof DesignBridgeError;
  });

  test('DesignBridgeError has required properties', () => {
    const err = new DesignBridgeError('test', { code: 'TEST_CODE' });
    return err.code === 'TEST_CODE' &&
           err.statusCode === 500 &&
           typeof err.timestamp === 'string' &&
           err.recoverable === true;
  });

  test('DesignBridgeError.toJSON returns object', () => {
    const err = new DesignBridgeError('test');
    const json = err.toJSON();
    return json.name === 'DesignBridgeError' && json.message === 'test';
  });

  test('ValidationError has correct statusCode', () => {
    const err = new ValidationError('invalid input');
    return err.statusCode === 400 && err.code === 'VALIDATION_ERROR';
  });

  test('ValidationError with field context', () => {
    const err = new ValidationError('must be positive', { field: 'count' });
    return err.field === 'count' && err.getUserMessage().includes('count');
  });

  test('SchemaValidationError has errors array', () => {
    const err = new SchemaValidationError('schema failed', {
      errors: [{ message: 'field1 invalid' }]
    });
    return err.errors.length === 1;
  });

  test('RequiredFieldError sets correct message', () => {
    const err = new RequiredFieldError('username');
    return err.message.includes('username') && err.field === 'username';
  });

  test('ComponentNotFoundError has componentId', () => {
    const err = new ComponentNotFoundError('btn-123');
    return err.componentId === 'btn-123' && err.statusCode === 404;
  });

  test('ComponentGenerationError tracks phase', () => {
    const err = new ComponentGenerationError('failed', {
      componentName: 'Button',
      framework: 'react',
      phase: 'optimization'
    });
    return err.phase === 'optimization' && err.framework === 'react';
  });

  test('TokenNotFoundError has tokenPath', () => {
    const err = new TokenNotFoundError('colors.primary');
    return err.tokenPath === 'colors.primary';
  });

  test('FigmaRateLimitError has retryAfter', () => {
    const err = new FigmaRateLimitError({ retryAfter: 30 });
    return err.retryAfter === 30 && err.statusCode === 429;
  });

  test('UnsupportedFrameworkError lists supported', () => {
    const err = new UnsupportedFrameworkError('invalid', {
      supportedFrameworks: ['react', 'vue']
    });
    return err.supportedFrameworks.includes('react');
  });

  test('SyncConflictError is recoverable', () => {
    const err = new SyncConflictError('conflict detected');
    return err.statusCode === 409 && err.recoverable === true;
  });

  test('FileNotFoundError has filePath', () => {
    const err = new FileNotFoundError('/path/to/file.ts');
    return err.filePath === '/path/to/file.ts';
  });
}

// =============================================================================
// ERROR UTILITIES TESTS
// =============================================================================

function runErrorUtilitiesTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 3: Error Utilities${colors.reset}                            ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('wrapError wraps native Error', () => {
    const native = new Error('native error');
    const wrapped = wrapError(native);
    return wrapped instanceof DesignBridgeError && wrapped.cause === native;
  });

  test('wrapError returns DesignBridgeError as-is', () => {
    const err = new ValidationError('already wrapped');
    const wrapped = wrapError(err);
    return wrapped === err;
  });

  test('isErrorType checks type correctly', () => {
    const err = new ValidationError('test');
    return isErrorType(err, ValidationError) === true &&
           isErrorType(err, ComponentNotFoundError) === false;
  });

  test('isRecoverable returns error recoverable status', () => {
    const recoverable = new ValidationError('test');
    const unrecoverable = new DesignBridgeError('test', { recoverable: false });
    return isRecoverable(recoverable) === true &&
           isRecoverable(unrecoverable) === false;
  });

  test('isRecoverable defaults to true for unknown errors', () => {
    const native = new Error('native');
    return isRecoverable(native) === true;
  });

  test('getErrorCode returns correct code', () => {
    const err = new ValidationError('test');
    return getErrorCode(err) === 'VALIDATION_ERROR';
  });

  test('getErrorCode returns UNKNOWN_ERROR for native errors', () => {
    const err = new Error('native');
    return getErrorCode(err) === 'UNKNOWN_ERROR';
  });

  test('Error cause chain preserved', () => {
    const cause = new Error('root cause');
    const err = new ComponentGenerationError('failed', { cause });
    return err.cause === cause;
  });
}

// =============================================================================
// INTEGRATION TESTS
// =============================================================================

function runIntegrationTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 4: Logger + Error Integration${colors.reset}                 ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('Logger logs Error objects correctly', () => {
    const logger = createLogger('test', { level: 'DEBUG' });
    const err = new ValidationError('test error');
    const entry = logger.error(err);
    return entry.level === 'ERROR' && entry.error !== undefined;
  });

  test('Logger metrics track errors', () => {
    const logger = createLogger('error-tracker');
    logger.error('error 1');
    logger.error('error 2');
    const metrics = logger.getMetrics();
    return metrics.logged.ERROR >= 2;
  });

  test('Error getUserMessage provides friendly message', () => {
    const err = new FigmaRateLimitError({ retryAfter: 30 });
    const msg = err.getUserMessage();
    return msg.includes('30 seconds');
  });

  test('Error toJSON is serializable', () => {
    const err = new ComponentNotFoundError('btn-123');
    const json = err.toJSON();
    const str = JSON.stringify(json);
    const parsed = JSON.parse(str);
    return parsed.context.componentId === 'btn-123' && parsed.code === 'COMPONENT_NOT_FOUND';
  });
}

// =============================================================================
// MAIN TEST RUNNER
// =============================================================================

async function runAllTests() {
  console.log(`${colors.bold}${colors.cyan}`);
  console.log('╔═══════════════════════════════════════════════════════════╗');
  console.log('║     ERROR HANDLING & LOGGING TEST SUITE                   ║');
  console.log('║              Phase 3: Sprints 125-140                     ║');
  console.log('╚═══════════════════════════════════════════════════════════╝');
  console.log(`${colors.reset}`);

  const startTime = Date.now();

  // Run all test suites
  runLoggerTests();
  runErrorTypesTests();
  runErrorUtilitiesTests();
  runIntegrationTests();

  const duration = Date.now() - startTime;

  // Summary
  console.log(`\n${colors.cyan}╔═══════════════════════════════════════════════════════════╗${colors.reset}`);
  console.log(`${colors.cyan}║${colors.reset}${colors.bold}                    TEST SUMMARY                           ${colors.reset}${colors.cyan}║${colors.reset}`);
  console.log(`${colors.cyan}╚═══════════════════════════════════════════════════════════╝${colors.reset}`);
  console.log('');
  console.log(`  ${colors.bold}Total Tests:${colors.reset}   ${results.passed + results.failed}`);
  console.log(`  ${colors.green}Passed:${colors.reset}        ${results.passed}`);
  console.log(`  ${colors.red}Failed:${colors.reset}        ${results.failed}`);
  console.log(`  ${colors.dim}Duration:${colors.reset}      ${duration}ms`);
  console.log('');

  if (results.failed === 0) {
    console.log(`  ${colors.green}${colors.bold}✓ All error/logging tests passed!${colors.reset}`);
  } else {
    console.log(`  ${colors.red}${colors.bold}✗ ${results.failed} test(s) failed${colors.reset}`);
    console.log('');
    console.log(`  ${colors.dim}Failed tests:${colors.reset}`);
    results.tests
      .filter(t => t.status === 'FAIL')
      .forEach(t => console.log(`    - ${t.name}: ${t.error}`));
  }

  console.log('');

  return {
    passed: results.passed,
    failed: results.failed,
    total: results.passed + results.failed,
    duration
  };
}

// Export for use as module
module.exports = { run: runAllTests, runAllTests };

// Run if called directly
if (require.main === module) {
  runAllTests()
    .then(results => {
      process.exit(results.failed > 0 ? 1 : 0);
    })
    .catch(err => {
      console.error(`${colors.red}Fatal error:${colors.reset}`, err);
      process.exit(1);
    });
}
