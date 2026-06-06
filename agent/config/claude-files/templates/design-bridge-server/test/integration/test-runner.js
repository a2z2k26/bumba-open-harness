/**
 * Integration Test Runner
 * Executes end-to-end tests for Design Bridge pipelines
 */

class IntegrationTestRunner {
  constructor() {
    this.tests = [];
    this.results = {
      passed: 0,
      failed: 0,
      skipped: 0,
      errors: []
    };
    this.startTime = null;
  }

  /**
   * Register a test
   */
  test(name, testFn, options = {}) {
    this.tests.push({
      name,
      testFn,
      timeout: options.timeout || 5000,
      skip: options.skip || false,
      only: options.only || false
    });
    return this;
  }

  /**
   * Run all registered tests
   */
  async run() {
    this.startTime = Date.now();
    console.log('\n🧪 Running Integration Tests\n');
    console.log('='.repeat(50));

    // Filter to only tests if any are marked
    const hasOnly = this.tests.some(t => t.only);
    const testsToRun = hasOnly
      ? this.tests.filter(t => t.only)
      : this.tests;

    for (const test of testsToRun) {
      await this.runTest(test);
    }

    this.printSummary();
    return this.results;
  }

  /**
   * Run a single test
   */
  async runTest(test) {
    const { name, testFn, timeout, skip } = test;

    if (skip) {
      console.log(`⏭️  SKIP: ${name}`);
      this.results.skipped++;
      return;
    }

    process.stdout.write(`🔄 ${name}...`);

    try {
      // Run with timeout
      await Promise.race([
        testFn(),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Test timeout')), timeout)
        )
      ]);

      console.log(` ✅ PASS`);
      this.results.passed++;

    } catch (error) {
      console.log(` ❌ FAIL`);
      console.log(`   Error: ${error.message}`);
      this.results.failed++;
      this.results.errors.push({ test: name, error: error.message });
    }
  }

  /**
   * Print test summary
   */
  printSummary() {
    const duration = Date.now() - this.startTime;
    const total = this.results.passed + this.results.failed + this.results.skipped;

    console.log('\n' + '='.repeat(50));
    console.log('📊 Test Summary');
    console.log('='.repeat(50));
    console.log(`Total:   ${total}`);
    console.log(`Passed:  ${this.results.passed} ✅`);
    console.log(`Failed:  ${this.results.failed} ❌`);
    console.log(`Skipped: ${this.results.skipped} ⏭️`);
    console.log(`Duration: ${duration}ms`);
    console.log('='.repeat(50));

    if (this.results.errors.length > 0) {
      console.log('\n❌ Failed Tests:');
      this.results.errors.forEach(({ test, error }) => {
        console.log(`  • ${test}: ${error}`);
      });
    }

    const status = this.results.failed === 0 ? '✅ ALL TESTS PASSED' : '❌ TESTS FAILED';
    console.log(`\n${status}\n`);
  }
}

module.exports = IntegrationTestRunner;
