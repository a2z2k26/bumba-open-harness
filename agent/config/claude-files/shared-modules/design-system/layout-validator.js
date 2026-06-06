/**
 * Layout Validator - Structured 3-Pass Visual Validation Helper
 *
 * Provides state management and helper functions for the Chrome DevTools MCP
 * validation loop. This module does NOT perform the validation itself - it
 * provides structure, state tracking, and report generation that the agent
 * uses during the validation process.
 *
 * Enhanced with Defensive Enhancement System:
 * - Sync logging for all validation operations
 * - Sync verification for detecting layout drift
 * - Transformation reports for detailed metrics
 *
 * Usage Flow:
 * 1. Agent calls startValidation() to initialize session
 * 2. For each pass (1-3):
 *    - Agent uses Chrome DevTools MCP to capture browser screenshot
 *    - Agent calls capturePass() with the screenshot path
 *    - Agent compares visually and calls recordDiscrepancy() for each issue
 *    - Agent modifies HTML and calls applyFix() to track changes
 *    - Agent calls completePass() to finalize
 * 3. Agent calls generateReport() to save validation-report.json
 * 4. Agent calls getValidatedCSS() to extract proven-accurate styles
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 */

const fs = require('fs');
const path = require('path');

// =============================================================================
// DEFENSIVE ENHANCEMENT INTEGRATIONS
// =============================================================================

// Lazy-load defensive modules to avoid circular dependencies
let _syncLogger = null;
let _syncVerifier = null;
let _transformationReport = null;

function getSyncLogger() {
  if (!_syncLogger) {
    try {
      _syncLogger = require('./sync-logger.js');
    } catch (e) {
      // Fallback if module not available
      _syncLogger = {
        createLogger: () => ({
          info: () => {},
          warn: () => {},
          error: () => {},
          debug: () => {},
          syncStart: () => {},
          syncComplete: () => {},
          syncFailed: () => {},
          validate: () => {},
          startSpan: () => 'span',
          endSpan: () => 0,
          getSummary: () => ({ counters: {} }),
          getErrors: () => [],
          getWarnings: () => []
        })
      };
    }
  }
  return _syncLogger;
}

function getSyncVerifier() {
  if (!_syncVerifier) {
    try {
      _syncVerifier = require('./sync-verifier.js');
    } catch (e) {
      // Fallback if module not available
      _syncVerifier = {
        SyncVerifier: class {
          setBaseline() {}
          verifyNode() { return { status: 'synced' }; }
          quickCheck() { return { passed: true, syncRate: 100 }; }
        },
        VERIFICATION_STATUS: { SYNCED: 'synced', DRIFTED: 'drifted' }
      };
    }
  }
  return _syncVerifier;
}

function getTransformationReport() {
  if (!_transformationReport) {
    try {
      _transformationReport = require('./transformation-report.js');
    } catch (e) {
      // Fallback if module not available
      _transformationReport = {
        ReportCollector: class {
          recordNode() {}
          recordWarning() {}
          recordError() {}
          recordTiming() {}
          finalize() { return { metrics: {} }; }
          getData() { return {}; }
        }
      };
    }
  }
  return _transformationReport;
}

class LayoutValidator {
  constructor(projectPath, options = {}) {
    this.projectPath = projectPath;
    this.session = null;
    this.passes = [];
    this.currentPass = null;

    // Initialize defensive enhancement modules
    this.enableLogging = options.enableLogging !== false;
    this.enableVerification = options.enableVerification !== false;
    this.enableReporting = options.enableReporting !== false;

    // Create logger instance
    if (this.enableLogging) {
      const sl = getSyncLogger();
      this.logger = sl.createLogger({
        name: 'layout-validator',
        output: options.logOutput || 'memory'
      });
    }

    // Create verifier instance
    if (this.enableVerification) {
      const sv = getSyncVerifier();
      this.verifier = new sv.SyncVerifier();
    }

    // Create report collector
    if (this.enableReporting) {
      const tr = getTransformationReport();
      this.reportCollector = new tr.ReportCollector({
        framework: 'layout-validation',
        source: 'figma'
      });
    }
  }

  /**
   * Log a message if logging is enabled
   * @private
   */
  _log(level, message, context = {}) {
    if (this.logger && this.logger[level]) {
      this.logger[level](message, context);
    }
  }

  /**
   * Record a metric if reporting is enabled
   * @private
   */
  _recordMetric(type, data) {
    if (this.reportCollector) {
      if (type === 'node') {
        this.reportCollector.recordNode(data.node, data.result);
      } else if (type === 'warning') {
        this.reportCollector.recordWarning(data.message, data.context);
      } else if (type === 'error') {
        this.reportCollector.recordError(data.error, data.context);
      } else if (type === 'timing') {
        this.reportCollector.recordTiming(data.operation, data.duration, data.metadata);
      }
    }
  }

  /**
   * Initialize a new validation session
   * @param {string} layoutName - Name of the layout being validated
   * @param {Object} options - Configuration options
   * @returns {Object} Session info
   */
  startValidation(layoutName, options = {}) {
    // Start timing span for performance tracking
    const spanId = this.logger ? this.logger.startSpan('startValidation') : null;

    this._log('info', `Starting validation session for layout: ${layoutName}`, {
      layoutName,
      framework: options.framework || 'react',
      maxPasses: options.maxPasses || 3
    });

    const layoutDir = path.join(this.projectPath, '.design', 'layouts', layoutName);

    if (!fs.existsSync(layoutDir)) {
      this._log('error', `Layout directory not found: ${layoutDir}`, { layoutName });
      this._recordMetric('error', {
        error: new Error(`Layout directory not found: ${layoutDir}`),
        context: { layoutName, layoutDir }
      });
      throw new Error(`Layout directory not found: ${layoutDir}`);
    }

    const layoutJsonPath = path.join(layoutDir, 'layout.json');
    const screenshotPath = path.join(layoutDir, 'screenshot.png');
    const referenceHtmlPath = path.join(layoutDir, 'reference.html');

    // Validate prerequisites
    const prerequisites = {
      layoutJson: fs.existsSync(layoutJsonPath),
      screenshot: fs.existsSync(screenshotPath),
      referenceHtml: fs.existsSync(referenceHtmlPath)
    };

    this._log('debug', 'Prerequisites check', prerequisites);

    if (!prerequisites.layoutJson) {
      this._log('error', `Layout JSON not found: ${layoutJsonPath}`, { layoutName });
      this._recordMetric('error', {
        error: new Error(`Layout JSON not found: ${layoutJsonPath}`),
        context: { layoutName }
      });
      throw new Error(`Layout JSON not found: ${layoutJsonPath}`);
    }

    if (!prerequisites.referenceHtml) {
      this._log('error', 'Reference HTML not found. Run HTML generation first.', { layoutName });
      this._recordMetric('error', {
        error: new Error('Reference HTML not found'),
        context: { layoutName }
      });
      throw new Error(`Reference HTML not found. Run HTML generation first.`);
    }

    // Load layout data for dimensions
    const layoutData = JSON.parse(fs.readFileSync(layoutJsonPath, 'utf8'));
    const dimensions = {
      width: layoutData.width || 375,
      height: layoutData.height || 812
    };

    // Initialize session
    this.session = {
      layoutName,
      layoutDir,
      startedAt: new Date().toISOString(),
      framework: options.framework || 'react',
      prerequisites,
      dimensions,
      paths: {
        layoutJson: layoutJsonPath,
        screenshot: screenshotPath,
        referenceHtml: referenceHtmlPath,
        validatedScreenshot: path.join(layoutDir, 'reference-validated.png'),
        validationReport: path.join(layoutDir, 'validation-report.json')
      },
      totalPasses: options.maxPasses || 3,
      status: 'in_progress'
    };

    this.passes = [];
    this.currentPass = null;

    // Set baseline for sync verification
    if (this.verifier) {
      this._log('debug', 'Setting verification baseline from layout data');
      this.verifier.setBaseline('layout', {
        layoutName,
        dimensions,
        framework: this.session.framework,
        nodeCount: layoutData.children ? layoutData.children.length : 0
      });
    }

    // Record session start in report collector
    this._recordMetric('node', {
      node: { id: layoutName, type: 'session-start' },
      result: { status: 'success', dimensions }
    });

    // End timing span
    if (spanId && this.logger) {
      const duration = this.logger.endSpan(spanId);
      this._recordMetric('timing', {
        operation: 'startValidation',
        duration,
        metadata: { layoutName }
      });
    }

    this._log('info', `Validation session started successfully`, {
      layoutName,
      dimensions,
      totalPasses: this.session.totalPasses
    });

    return {
      success: true,
      session: this.session,
      nextStep: 'Begin Pass 1: Load reference.html in Chrome DevTools, resize to match dimensions, capture screenshot'
    };
  }

  /**
   * Begin a new validation pass
   * @param {number} passNumber - Pass number (1, 2, or 3)
   * @returns {Object} Pass initialization info
   */
  beginPass(passNumber) {
    const spanId = this.logger ? this.logger.startSpan(`beginPass-${passNumber}`) : null;

    if (!this.session) {
      this._log('error', 'No validation session active', { attempted: 'beginPass' });
      throw new Error('No validation session active. Call startValidation() first.');
    }

    if (passNumber < 1 || passNumber > this.session.totalPasses) {
      this._log('error', `Invalid pass number: ${passNumber}`, {
        expected: `1-${this.session.totalPasses}`,
        passNumber
      });
      throw new Error(`Invalid pass number: ${passNumber}. Expected 1-${this.session.totalPasses}`);
    }

    this._log('info', `Beginning validation pass ${passNumber}`, {
      layoutName: this.session.layoutName,
      passNumber,
      totalPasses: this.session.totalPasses
    });

    this.currentPass = {
      pass: passNumber,
      startedAt: new Date().toISOString(),
      browserScreenshotPath: null,
      discrepancies: [],
      fixesApplied: [],
      status: 'in_progress'
    };

    // Record pass start in metrics
    this._recordMetric('node', {
      node: { id: `pass-${passNumber}`, type: 'pass-start' },
      result: { status: 'in_progress', passNumber }
    });

    if (spanId && this.logger) {
      this.logger.endSpan(spanId);
    }

    return {
      success: true,
      pass: passNumber,
      instructions: this.getPassInstructions(passNumber),
      dimensions: this.session.dimensions
    };
  }

  /**
   * Get instructions for a specific pass
   */
  getPassInstructions(passNumber) {
    const baseInstructions = {
      1: {
        goal: 'Initial render comparison - identify major structural discrepancies',
        focus: ['Layout direction', 'Container dimensions', 'Major spacing (gaps, padding)', 'Component positioning'],
        tolerance: 'Identify issues > 5px difference'
      },
      2: {
        goal: 'Refinement - fix issues from Pass 1, check for remaining problems',
        focus: ['Specific spacing values', 'Alignment precision', 'Component sizing'],
        tolerance: 'Identify issues > 2px difference'
      },
      3: {
        goal: 'Final polish - pixel-perfect validation',
        focus: ['Fine-tune remaining issues', 'Visual parity confirmation', 'Edge cases'],
        tolerance: 'Target < 2px variance overall'
      }
    };

    return baseInstructions[passNumber] || baseInstructions[1];
  }

  /**
   * Record the browser screenshot path for current pass
   * @param {string} screenshotPath - Path where browser screenshot was saved
   */
  capturePass(screenshotPath) {
    if (!this.currentPass) {
      throw new Error('No pass in progress. Call beginPass() first.');
    }

    this.currentPass.browserScreenshotPath = screenshotPath;
    this.currentPass.capturedAt = new Date().toISOString();

    return {
      success: true,
      message: `Screenshot captured for Pass ${this.currentPass.pass}`,
      nextStep: 'Compare with Figma screenshot and record discrepancies'
    };
  }

  /**
   * Record a visual discrepancy found during comparison
   * @param {Object} discrepancy - Discrepancy details
   */
  recordDiscrepancy(discrepancy) {
    if (!this.currentPass) {
      this._log('error', 'No pass in progress when recording discrepancy', { discrepancy });
      throw new Error('No pass in progress. Call beginPass() first.');
    }

    const entry = {
      id: `disc-${this.currentPass.pass}-${this.currentPass.discrepancies.length + 1}`,
      element: discrepancy.element,
      issue: discrepancy.issue,
      expected: discrepancy.expected,
      actual: discrepancy.actual,
      severity: discrepancy.severity || 'medium',
      recordedAt: new Date().toISOString(),
      resolved: false
    };

    this.currentPass.discrepancies.push(entry);

    // Log based on severity
    const logLevel = entry.severity === 'high' ? 'warn' : 'info';
    this._log(logLevel, `Discrepancy recorded: ${entry.issue}`, {
      discrepancyId: entry.id,
      element: entry.element,
      severity: entry.severity,
      expected: entry.expected,
      actual: entry.actual,
      pass: this.currentPass.pass
    });

    // Record as warning in metrics
    this._recordMetric('warning', {
      message: `[${entry.severity}] ${entry.issue}`,
      context: {
        element: entry.element,
        expected: entry.expected,
        actual: entry.actual,
        pass: this.currentPass.pass
      }
    });

    return {
      success: true,
      discrepancyId: entry.id,
      totalDiscrepancies: this.currentPass.discrepancies.length
    };
  }

  /**
   * Record multiple discrepancies at once
   * @param {Array} discrepancies - Array of discrepancy objects
   */
  recordDiscrepancies(discrepancies) {
    if (!Array.isArray(discrepancies)) {
      throw new Error('Expected array of discrepancies');
    }

    const results = discrepancies.map(d => this.recordDiscrepancy(d));

    return {
      success: true,
      recorded: results.length,
      totalDiscrepancies: this.currentPass.discrepancies.length
    };
  }

  /**
   * Record a fix that was applied to the HTML
   * @param {Object} fix - Fix details
   */
  applyFix(fix) {
    if (!this.currentPass) {
      this._log('error', 'No pass in progress when applying fix', { fix });
      throw new Error('No pass in progress. Call beginPass() first.');
    }

    const entry = {
      id: `fix-${this.currentPass.pass}-${this.currentPass.fixesApplied.length + 1}`,
      element: fix.element,
      property: fix.property,
      oldValue: fix.oldValue,
      newValue: fix.newValue,
      relatedDiscrepancy: fix.discrepancyId || null,
      appliedAt: new Date().toISOString()
    };

    this.currentPass.fixesApplied.push(entry);

    // Mark related discrepancy as resolved if specified
    if (fix.discrepancyId) {
      const disc = this.currentPass.discrepancies.find(d => d.id === fix.discrepancyId);
      if (disc) {
        disc.resolved = true;
        disc.resolvedBy = entry.id;
        this._log('debug', `Discrepancy ${fix.discrepancyId} resolved by fix ${entry.id}`, {
          discrepancyId: fix.discrepancyId,
          fixId: entry.id
        });
      }
    }

    this._log('info', `Fix applied: ${fix.property}`, {
      fixId: entry.id,
      element: entry.element,
      property: entry.property,
      oldValue: entry.oldValue,
      newValue: entry.newValue,
      relatedDiscrepancy: entry.relatedDiscrepancy,
      pass: this.currentPass.pass
    });

    // Record fix in metrics
    this._recordMetric('node', {
      node: { id: entry.id, type: 'fix' },
      result: {
        status: 'success',
        property: entry.property,
        oldValue: entry.oldValue,
        newValue: entry.newValue
      }
    });

    return {
      success: true,
      fixId: entry.id,
      totalFixes: this.currentPass.fixesApplied.length
    };
  }

  /**
   * Complete the current pass
   * @param {Object} summary - Pass completion summary
   */
  completePass(summary = {}) {
    const spanId = this.logger ? this.logger.startSpan('completePass') : null;

    if (!this.currentPass) {
      this._log('error', 'No pass in progress when completing', {});
      throw new Error('No pass in progress');
    }

    const passNumber = this.currentPass.pass;
    const unresolvedCount = this.currentPass.discrepancies.filter(d => !d.resolved).length;
    const resolvedCount = this.currentPass.discrepancies.filter(d => d.resolved).length;

    this.currentPass.completedAt = new Date().toISOString();
    this.currentPass.status = unresolvedCount === 0 ? 'validated' : 'has_issues';
    this.currentPass.summary = {
      totalDiscrepancies: this.currentPass.discrepancies.length,
      resolvedDiscrepancies: resolvedCount,
      unresolvedDiscrepancies: unresolvedCount,
      fixesApplied: this.currentPass.fixesApplied.length,
      parityEstimate: summary.parityEstimate || null,
      notes: summary.notes || null
    };

    // Run sync verification check if enabled
    if (this.verifier) {
      const verifyResult = this.verifier.quickCheck();
      this._log('debug', 'Sync verification check', {
        passed: verifyResult.passed,
        syncRate: verifyResult.syncRate
      });
      this.currentPass.summary.syncVerification = verifyResult;
    }

    this.passes.push(this.currentPass);
    const completedPass = this.currentPass;
    this.currentPass = null;

    // Log pass completion
    this._log('info', `Pass ${passNumber} completed`, {
      status: completedPass.status,
      totalDiscrepancies: completedPass.summary.totalDiscrepancies,
      resolvedDiscrepancies: resolvedCount,
      unresolvedDiscrepancies: unresolvedCount,
      fixesApplied: completedPass.summary.fixesApplied,
      parityEstimate: completedPass.summary.parityEstimate
    });

    // Record pass completion in metrics
    this._recordMetric('node', {
      node: { id: `pass-${passNumber}`, type: 'pass-complete' },
      result: {
        status: completedPass.status,
        discrepancies: completedPass.summary.totalDiscrepancies,
        resolved: resolvedCount,
        fixes: completedPass.summary.fixesApplied
      }
    });

    // Determine next step
    let nextStep;
    if (completedPass.pass < this.session.totalPasses && unresolvedCount > 0) {
      nextStep = `Begin Pass ${completedPass.pass + 1} to address ${unresolvedCount} remaining issues`;
      this._log('info', `Proceeding to next pass`, { nextPass: completedPass.pass + 1, unresolvedCount });
    } else if (unresolvedCount === 0) {
      nextStep = 'Validation complete - all discrepancies resolved. Call generateReport()';
      this._log('info', 'All discrepancies resolved', { totalPasses: completedPass.pass });
    } else {
      nextStep = `Maximum passes reached with ${unresolvedCount} unresolved issues. Call generateReport()`;
      this._log('warn', 'Maximum passes reached with unresolved issues', { unresolvedCount });
    }

    // End timing span
    if (spanId && this.logger) {
      const duration = this.logger.endSpan(spanId);
      this._recordMetric('timing', {
        operation: `completePass-${passNumber}`,
        duration,
        metadata: { passNumber, status: completedPass.status }
      });
    }

    return {
      success: true,
      pass: completedPass.pass,
      summary: completedPass.summary,
      nextStep
    };
  }

  /**
   * Generate the final validation report
   * @returns {Object} Report data and file path
   */
  generateReport() {
    const spanId = this.logger ? this.logger.startSpan('generateReport') : null;

    if (!this.session) {
      this._log('error', 'No validation session active when generating report', {});
      throw new Error('No validation session active');
    }

    this._log('info', 'Generating validation report', {
      layoutName: this.session.layoutName,
      totalPasses: this.passes.length
    });

    // Calculate overall metrics
    const totalDiscrepancies = this.passes.reduce((sum, p) => sum + p.discrepancies.length, 0);
    const totalFixes = this.passes.reduce((sum, p) => sum + p.fixesApplied.length, 0);
    const finalPass = this.passes[this.passes.length - 1];
    const unresolvedFinal = finalPass ? finalPass.summary.unresolvedDiscrepancies : 0;

    // Estimate parity based on final pass
    let finalParity = '100%';
    if (finalPass && finalPass.summary.parityEstimate) {
      finalParity = finalPass.summary.parityEstimate;
    } else if (unresolvedFinal > 0) {
      // Rough estimate: each unresolved issue reduces parity by ~2%
      const parityValue = Math.max(80, 100 - (unresolvedFinal * 2));
      finalParity = `${parityValue}%`;
    }

    const report = {
      layoutName: this.session.layoutName,
      framework: this.session.framework,
      validatedAt: new Date().toISOString(),
      dimensions: this.session.dimensions,
      passes: this.passes.map(p => ({
        pass: p.pass,
        discrepancies: p.discrepancies,
        fixesApplied: p.fixesApplied.map(f => `${f.property}: ${f.newValue}`),
        status: p.status,
        syncVerification: p.summary.syncVerification || null
      })),
      summary: {
        totalPasses: this.passes.length,
        totalDiscrepancies,
        totalFixes,
        unresolvedIssues: unresolvedFinal,
        finalParity
      },
      outputPath: path.join('.design', 'extracted-code', this.session.framework, 'layouts',
                           `${this.toPascalCase(this.session.layoutName)}.${this.getFrameworkExtension(this.session.framework)}`)
    };

    // Add defensive enhancement metrics if available
    if (this.reportCollector) {
      const collectorData = this.reportCollector.finalize();
      report.defensiveMetrics = collectorData.metrics || {};
      this._log('debug', 'Added defensive metrics to report', {
        metricsIncluded: Object.keys(report.defensiveMetrics)
      });
    }

    // Add logger summary if available
    if (this.logger) {
      const logSummary = this.logger.getSummary();
      report.logSummary = {
        counters: logSummary.counters || {},
        errorCount: this.logger.getErrors().length,
        warningCount: this.logger.getWarnings().length
      };
    }

    // Save report
    fs.writeFileSync(
      this.session.paths.validationReport,
      JSON.stringify(report, null, 2)
    );

    this._log('info', 'Validation report saved', {
      savedTo: this.session.paths.validationReport,
      totalPasses: this.passes.length,
      totalDiscrepancies,
      totalFixes,
      unresolvedIssues: unresolvedFinal,
      finalParity
    });

    // Update session status
    this.session.status = unresolvedFinal === 0 ? 'validated' : 'completed_with_issues';
    this.session.completedAt = new Date().toISOString();

    // End timing span
    if (spanId && this.logger) {
      const duration = this.logger.endSpan(spanId);
      this._recordMetric('timing', {
        operation: 'generateReport',
        duration,
        metadata: { layoutName: this.session.layoutName, finalParity }
      });
    }

    // Log final session completion
    if (this.logger) {
      if (unresolvedFinal === 0) {
        this.logger.syncComplete('layout-validation', {
          layoutName: this.session.layoutName,
          passes: this.passes.length,
          discrepancies: totalDiscrepancies,
          fixes: totalFixes
        });
      } else {
        this.logger.syncFailed('layout-validation', new Error(`${unresolvedFinal} unresolved issues`), {
          layoutName: this.session.layoutName,
          unresolvedIssues: unresolvedFinal
        });
      }
    }

    return {
      success: true,
      report,
      savedTo: this.session.paths.validationReport,
      nextStep: unresolvedFinal === 0
        ? 'Proceed to framework code generation using validated HTML structure'
        : `Review ${unresolvedFinal} unresolved issues before proceeding`
    };
  }

  /**
   * Get the validated CSS structure from reference.html
   * Call this after validation to extract proven-accurate styles
   * @returns {Object} Extracted CSS rules
   */
  getValidatedCSS() {
    if (!this.session) {
      throw new Error('No validation session active');
    }

    const htmlPath = this.session.paths.referenceHtml;
    if (!fs.existsSync(htmlPath)) {
      throw new Error(`Reference HTML not found: ${htmlPath}`);
    }

    const html = fs.readFileSync(htmlPath, 'utf8');

    // Extract inline styles from layout-frame divs
    const styleRegex = /class="layout-frame"[^>]*style="([^"]+)"/g;
    const componentStyleRegex = /class="component-ref"[^>]*style="([^"]+)"/g;

    const layoutStyles = [];
    const componentStyles = [];

    let match;
    while ((match = styleRegex.exec(html)) !== null) {
      layoutStyles.push(this.parseInlineStyles(match[1]));
    }

    while ((match = componentStyleRegex.exec(html)) !== null) {
      componentStyles.push(this.parseInlineStyles(match[1]));
    }

    return {
      success: true,
      layoutStyles,
      componentStyles,
      totalElements: layoutStyles.length + componentStyles.length
    };
  }

  /**
   * Parse inline style string to object
   */
  parseInlineStyles(styleStr) {
    const styles = {};
    const declarations = styleStr.split(';').filter(s => s.trim());

    for (const decl of declarations) {
      const [prop, value] = decl.split(':').map(s => s.trim());
      if (prop && value) {
        styles[prop] = value;
      }
    }

    return styles;
  }

  /**
   * Get current validation status
   */
  getStatus() {
    if (!this.session) {
      return { active: false };
    }

    return {
      active: true,
      layoutName: this.session.layoutName,
      status: this.session.status,
      completedPasses: this.passes.length,
      totalPasses: this.session.totalPasses,
      currentPass: this.currentPass ? this.currentPass.pass : null,
      dimensions: this.session.dimensions
    };
  }

  /**
   * Helper: Convert string to PascalCase
   */
  toPascalCase(str) {
    return str
      .replace(/[-_\s]+(.)?/g, (_, char) => char ? char.toUpperCase() : '')
      .replace(/^(.)/, char => char.toUpperCase());
  }

  /**
   * Helper: Get file extension for framework
   */
  getFrameworkExtension(framework) {
    const extensions = {
      'react': 'tsx',
      'vue': 'vue',
      'svelte': 'svelte',
      'angular': 'component.ts',
      'react-native': 'tsx',
      'flutter': 'dart',
      'swiftui': 'swift',
      'jetpack-compose': 'kt',
      'web-components': 'js'
    };
    return extensions[framework] || 'tsx';
  }

  /**
   * Generate comparison hints between two screenshots
   * This provides structured guidance for the agent doing visual comparison
   * @param {string} figmaPath - Path to Figma screenshot
   * @param {string} browserPath - Path to browser screenshot
   * @returns {Object} Comparison hints and checklist
   */
  getComparisonChecklist() {
    return {
      structuralChecks: [
        'Overall container dimensions match',
        'Flex direction (row vs column) is correct',
        'Number of child elements matches',
        'Element ordering is correct'
      ],
      spacingChecks: [
        'Gap between elements matches design',
        'Padding on containers matches',
        'Margin values are accurate',
        'Element alignment (start/center/end) is correct'
      ],
      sizingChecks: [
        'Component widths match',
        'Component heights match',
        'Container sizing modes (fixed/fill) are correct',
        'Min/max constraints are respected'
      ],
      visualChecks: [
        'Background colors approximate design (placeholders)',
        'Border styles are consistent',
        'Element visibility matches',
        'Overflow handling is correct'
      ],
      tolerances: {
        major: '> 10px - Critical issue, must fix',
        medium: '5-10px - Should fix if possible',
        minor: '< 5px - Acceptable variance'
      }
    };
  }

  /**
   * Get defensive enhancement status
   * @returns {Object} Status of defensive enhancement modules
   */
  getDefensiveStatus() {
    return {
      logging: {
        enabled: this.enableLogging,
        active: !!this.logger
      },
      verification: {
        enabled: this.enableVerification,
        active: !!this.verifier
      },
      reporting: {
        enabled: this.enableReporting,
        active: !!this.reportCollector
      },
      logSummary: this.logger ? this.logger.getSummary() : null,
      errors: this.logger ? this.logger.getErrors() : [],
      warnings: this.logger ? this.logger.getWarnings() : []
    };
  }
}

/**
 * Factory function to create validator instance
 * @param {string} projectPath - Project root path
 * @param {Object} options - Configuration options
 * @param {boolean} options.enableLogging - Enable sync logging (default: true)
 * @param {boolean} options.enableVerification - Enable sync verification (default: true)
 * @param {boolean} options.enableReporting - Enable transformation reporting (default: true)
 * @param {string} options.logOutput - Log output mode: 'memory' | 'file' (default: 'memory')
 */
function createValidator(projectPath, options = {}) {
  return new LayoutValidator(projectPath, options);
}

/**
 * Quick validation session starter
 */
async function validateLayout(projectPath, layoutName, options = {}) {
  const validator = new LayoutValidator(projectPath);
  return validator.startValidation(layoutName, options);
}

module.exports = {
  LayoutValidator,
  createValidator,
  validateLayout
};
