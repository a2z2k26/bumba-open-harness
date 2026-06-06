/**
 * Layout Validator Tests
 *
 * Tests the structured 3-pass validation helper module.
 */

const path = require('path');
const fs = require('fs');
const { LayoutValidator, createValidator, validateLayout } = require('./layout-validator');

// Test project path (use current directory for testing)
const TEST_PROJECT_PATH = process.cwd();

// Helper to create test layout structure
function createTestLayout(layoutName) {
  const layoutDir = path.join(TEST_PROJECT_PATH, '.design', 'layouts', layoutName);

  // Ensure directory exists
  if (!fs.existsSync(layoutDir)) {
    fs.mkdirSync(layoutDir, { recursive: true });
  }

  // Create minimal layout.json
  const layoutData = {
    name: layoutName,
    width: 375,
    height: 812,
    layoutMode: 'VERTICAL',
    itemSpacing: 16,
    paddingTop: 24,
    paddingBottom: 24,
    children: []
  };

  fs.writeFileSync(
    path.join(layoutDir, 'layout.json'),
    JSON.stringify(layoutData, null, 2)
  );

  // Create reference.html
  const html = `<!DOCTYPE html>
<html>
<head><title>${layoutName} Reference</title></head>
<body>
  <div class="layout-frame" style="display: flex; flex-direction: column; gap: 16px;">
    <div class="component-ref" data-component="TestComponent" style="width: 100px; height: 40px;">TestComponent</div>
  </div>
</body>
</html>`;

  fs.writeFileSync(path.join(layoutDir, 'reference.html'), html);

  return layoutDir;
}

// Helper to cleanup test layout
function cleanupTestLayout(layoutName) {
  const layoutDir = path.join(TEST_PROJECT_PATH, '.design', 'layouts', layoutName);
  if (fs.existsSync(layoutDir)) {
    fs.rmSync(layoutDir, { recursive: true, force: true });
  }
}

// Test suite
async function runTests() {
  console.log('\n  Layout Validator Tests\n');
  console.log('  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

  let passed = 0;
  let failed = 0;
  const testLayoutName = 'test-layout-validator';

  try {
    // Setup
    createTestLayout(testLayoutName);

    // Test 1: Create validator instance
    console.log('  ▸ Test 1: Create validator instance');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      console.log('    ✓ Validator created successfully');
      passed++;
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 2: Start validation session
    console.log('\n  ▸ Test 2: Start validation session');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      const session = validator.startValidation(testLayoutName, { framework: 'react' });

      if (session.success && session.session.layoutName === testLayoutName) {
        console.log('    ✓ Session started successfully');
        console.log(`      Layout: ${session.session.layoutName}`);
        console.log(`      Dimensions: ${session.session.dimensions.width}×${session.session.dimensions.height}`);
        passed++;
      } else {
        throw new Error('Invalid session data');
      }
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 3: Begin and complete a pass
    console.log('\n  ▸ Test 3: Begin and complete a pass');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      validator.startValidation(testLayoutName, { framework: 'react' });

      const passInfo = validator.beginPass(1);
      if (passInfo.success && passInfo.pass === 1) {
        console.log('    ✓ Pass 1 started');
      }

      validator.capturePass('/tmp/test-screenshot.png');
      console.log('    ✓ Screenshot captured');

      const result = validator.completePass({ parityEstimate: '100%' });
      if (result.success) {
        console.log('    ✓ Pass 1 completed');
        passed++;
      }
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 4: Record discrepancies
    console.log('\n  ▸ Test 4: Record discrepancies');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      validator.startValidation(testLayoutName, { framework: 'react' });
      validator.beginPass(1);
      validator.capturePass('/tmp/test.png');

      const discResult = validator.recordDiscrepancy({
        element: 'container',
        issue: 'gap',
        expected: '24px',
        actual: '16px',
        severity: 'medium'
      });

      if (discResult.success && discResult.totalDiscrepancies === 1) {
        console.log('    ✓ Discrepancy recorded');
        console.log(`      ID: ${discResult.discrepancyId}`);
        passed++;
      }
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 5: Apply fixes
    console.log('\n  ▸ Test 5: Apply fixes');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      validator.startValidation(testLayoutName, { framework: 'react' });
      validator.beginPass(1);
      validator.capturePass('/tmp/test.png');

      const discResult = validator.recordDiscrepancy({
        element: 'container',
        issue: 'gap',
        expected: '24px',
        actual: '16px'
      });

      const fixResult = validator.applyFix({
        element: 'container',
        property: 'gap',
        oldValue: '16px',
        newValue: '24px',
        discrepancyId: discResult.discrepancyId
      });

      if (fixResult.success) {
        console.log('    ✓ Fix applied and linked to discrepancy');
        passed++;
      }
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 6: Generate report
    console.log('\n  ▸ Test 6: Generate report');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      validator.startValidation(testLayoutName, { framework: 'react' });

      // Pass 1
      validator.beginPass(1);
      validator.capturePass('/tmp/p1.png');
      validator.recordDiscrepancy({ element: 'test', issue: 'gap', expected: '20px', actual: '10px' });
      validator.completePass({ parityEstimate: '90%' });

      // Pass 2
      validator.beginPass(2);
      validator.capturePass('/tmp/p2.png');
      validator.applyFix({ element: 'test', property: 'gap', oldValue: '10px', newValue: '20px' });
      validator.completePass({ parityEstimate: '98%' });

      // Generate report
      const reportResult = validator.generateReport();

      if (reportResult.success && reportResult.report.summary.totalPasses === 2) {
        console.log('    ✓ Report generated');
        console.log(`      Passes: ${reportResult.report.summary.totalPasses}`);
        console.log(`      Final Parity: ${reportResult.report.summary.finalParity}`);
        console.log(`      Saved to: ${path.basename(reportResult.savedTo)}`);
        passed++;
      }
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 7: Get comparison checklist
    console.log('\n  ▸ Test 7: Get comparison checklist');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      const checklist = validator.getComparisonChecklist();

      if (checklist.structuralChecks && checklist.spacingChecks && checklist.tolerances) {
        console.log('    ✓ Checklist retrieved');
        console.log(`      Structural checks: ${checklist.structuralChecks.length}`);
        console.log(`      Spacing checks: ${checklist.spacingChecks.length}`);
        passed++;
      }
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 8: Get validated CSS
    console.log('\n  ▸ Test 8: Get validated CSS from HTML');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      validator.startValidation(testLayoutName, { framework: 'react' });

      const cssResult = validator.getValidatedCSS();

      if (cssResult.success && cssResult.layoutStyles.length > 0) {
        console.log('    ✓ CSS extracted from reference HTML');
        console.log(`      Layout styles: ${cssResult.layoutStyles.length}`);
        console.log(`      Component styles: ${cssResult.componentStyles.length}`);
        passed++;
      }
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 9: Factory function
    console.log('\n  ▸ Test 9: Factory function');
    try {
      const validator = createValidator(TEST_PROJECT_PATH);
      if (validator instanceof LayoutValidator) {
        console.log('    ✓ Factory function works');
        passed++;
      }
    } catch (e) {
      console.log(`    ✗ Failed: ${e.message}`);
      failed++;
    }

    // Test 10: Error handling - no session
    console.log('\n  ▸ Test 10: Error handling - no session');
    try {
      const validator = new LayoutValidator(TEST_PROJECT_PATH);
      validator.beginPass(1);
      console.log('    ✗ Should have thrown error');
      failed++;
    } catch (e) {
      if (e.message.includes('No validation session active')) {
        console.log('    ✓ Correct error thrown for missing session');
        passed++;
      } else {
        console.log(`    ✗ Wrong error: ${e.message}`);
        failed++;
      }
    }

  } finally {
    // Cleanup
    cleanupTestLayout(testLayoutName);
  }

  // Summary
  console.log('\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log(`\n  Results: ${passed} passed, ${failed} failed\n`);

  return failed === 0;
}

// Run tests
runTests()
  .then(success => {
    process.exit(success ? 0 : 1);
  })
  .catch(err => {
    console.error('Test error:', err);
    process.exit(1);
  });
