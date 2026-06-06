/**
 * Transformation Report Generator
 *
 * Generates comprehensive reports for design-to-code transformations.
 * Captures metrics, warnings, degradations, and recommendations for
 * each transformation session.
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 *
 * @module transformation-report
 */

'use strict';

const path = require('path');
const fs = require('fs');

// =============================================================================
// CONSTANTS
// =============================================================================

/**
 * Report formats
 */
const REPORT_FORMATS = {
  JSON: 'json',
  MARKDOWN: 'markdown',
  HTML: 'html',
  TEXT: 'text'
};

/**
 * Report sections
 */
const REPORT_SECTIONS = {
  SUMMARY: 'summary',
  METRICS: 'metrics',
  WARNINGS: 'warnings',
  ERRORS: 'errors',
  DEGRADATIONS: 'degradations',
  SYNC_STATUS: 'sync_status',
  RECOMMENDATIONS: 'recommendations',
  TIMING: 'timing',
  FILES: 'files'
};

/**
 * Status indicators
 */
const STATUS = {
  SUCCESS: 'success',
  PARTIAL: 'partial',
  FAILED: 'failed',
  SKIPPED: 'skipped'
};

// =============================================================================
// REPORT COLLECTOR
// =============================================================================

/**
 * Collects data during transformation for report generation
 */
class ReportCollector {
  /**
   * Create a report collector
   * @param {Object} options - Collector options
   */
  constructor(options = {}) {
    this.options = {
      sessionId: options.sessionId || this._generateSessionId(),
      framework: options.framework || 'unknown',
      source: options.source || 'unknown',
      ...options
    };

    this.reset();
  }

  /**
   * Generate session ID
   * @returns {string} Session ID
   * @private
   */
  _generateSessionId() {
    return `tx-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;
  }

  /**
   * Reset collector state
   */
  reset() {
    this.startTime = Date.now();
    this.endTime = null;

    this.data = {
      // Counts
      nodesProcessed: 0,
      nodesSuccessful: 0,
      nodesFailed: 0,
      nodesSkipped: 0,
      nodesDegraded: 0,

      // Collections
      warnings: [],
      errors: [],
      degradations: [],
      recommendations: [],
      timings: [],
      files: [],

      // Sync data
      syncResults: null,
      driftInfo: null,

      // Metrics
      metrics: {
        complexity: null,
        coverage: 0,
        degradationRate: 0
      }
    };
  }

  /**
   * Record a processed node
   * @param {Object} node - Node that was processed
   * @param {Object} result - Processing result
   */
  recordNode(node, result) {
    this.data.nodesProcessed++;

    if (result.success) {
      this.data.nodesSuccessful++;
    } else if (result.skipped) {
      this.data.nodesSkipped++;
    } else {
      this.data.nodesFailed++;
    }

    if (result.degraded) {
      this.data.nodesDegraded++;
      this.data.degradations.push({
        nodeId: node.id,
        nodeName: node.name,
        level: result.degradationLevel,
        reason: result.degradationReason,
        timestamp: Date.now()
      });
    }
  }

  /**
   * Record a warning
   * @param {string} message - Warning message
   * @param {Object} context - Warning context
   */
  recordWarning(message, context = {}) {
    this.data.warnings.push({
      message,
      context,
      timestamp: Date.now()
    });
  }

  /**
   * Record an error
   * @param {Error|string} error - Error object or message
   * @param {Object} context - Error context
   */
  recordError(error, context = {}) {
    this.data.errors.push({
      message: error instanceof Error ? error.message : error,
      stack: error instanceof Error ? error.stack : null,
      context,
      timestamp: Date.now()
    });
  }

  /**
   * Record a recommendation
   * @param {string} recommendation - Recommendation text
   * @param {string} priority - Priority level
   * @param {Object} context - Additional context
   */
  recordRecommendation(recommendation, priority = 'medium', context = {}) {
    this.data.recommendations.push({
      text: recommendation,
      priority,
      context,
      timestamp: Date.now()
    });
  }

  /**
   * Record a timing measurement
   * @param {string} operation - Operation name
   * @param {number} durationMs - Duration in milliseconds
   * @param {Object} metadata - Additional metadata
   */
  recordTiming(operation, durationMs, metadata = {}) {
    this.data.timings.push({
      operation,
      durationMs,
      metadata,
      timestamp: Date.now()
    });
  }

  /**
   * Record a generated file
   * @param {string} filePath - File path
   * @param {Object} metadata - File metadata
   */
  recordFile(filePath, metadata = {}) {
    this.data.files.push({
      path: filePath,
      ...metadata,
      timestamp: Date.now()
    });
  }

  /**
   * Set complexity metrics
   * @param {Object} complexity - Complexity analysis result
   */
  setComplexity(complexity) {
    this.data.metrics.complexity = complexity;
  }

  /**
   * Set sync results
   * @param {Object} syncResults - Sync verification results
   */
  setSyncResults(syncResults) {
    this.data.syncResults = syncResults;
  }

  /**
   * Set drift information
   * @param {Object} driftInfo - Drift detection results
   */
  setDriftInfo(driftInfo) {
    this.data.driftInfo = driftInfo;
  }

  /**
   * Finalize collection
   * @returns {Object} Collected data
   */
  finalize() {
    this.endTime = Date.now();

    // Calculate final metrics
    const total = this.data.nodesProcessed;
    if (total > 0) {
      this.data.metrics.coverage =
        (this.data.nodesSuccessful / total) * 100;
      this.data.metrics.degradationRate =
        (this.data.nodesDegraded / total) * 100;
    }

    return this.getData();
  }

  /**
   * Get collected data
   * @returns {Object} All collected data
   */
  getData() {
    return {
      sessionId: this.options.sessionId,
      framework: this.options.framework,
      source: this.options.source,
      startTime: this.startTime,
      endTime: this.endTime,
      duration: this.endTime ? this.endTime - this.startTime : null,
      ...this.data
    };
  }
}

// =============================================================================
// REPORT GENERATOR
// =============================================================================

/**
 * Generates formatted reports from collected data
 */
class ReportGenerator {
  /**
   * Create a report generator
   * @param {Object} options - Generator options
   */
  constructor(options = {}) {
    this.options = {
      includeTimestamps: true,
      includeTiming: true,
      includeRecommendations: true,
      maxWarnings: 50,
      maxErrors: 50,
      ...options
    };
  }

  /**
   * Generate report in specified format
   * @param {Object} data - Collected data
   * @param {string} format - Output format
   * @returns {string} Formatted report
   */
  generate(data, format = REPORT_FORMATS.MARKDOWN) {
    switch (format) {
      case REPORT_FORMATS.JSON:
        return this._generateJson(data);
      case REPORT_FORMATS.MARKDOWN:
        return this._generateMarkdown(data);
      case REPORT_FORMATS.HTML:
        return this._generateHtml(data);
      case REPORT_FORMATS.TEXT:
        return this._generateText(data);
      default:
        return this._generateMarkdown(data);
    }
  }

  /**
   * Generate JSON report
   * @param {Object} data - Report data
   * @returns {string} JSON string
   * @private
   */
  _generateJson(data) {
    return JSON.stringify({
      report: {
        generatedAt: new Date().toISOString(),
        version: '1.0.0',
        ...data
      }
    }, null, 2);
  }

  /**
   * Generate Markdown report
   * @param {Object} data - Report data
   * @returns {string} Markdown string
   * @private
   */
  _generateMarkdown(data) {
    const lines = [];

    // Header
    lines.push('# Transformation Report');
    lines.push('');
    lines.push(`**Session:** ${data.sessionId}`);
    lines.push(`**Framework:** ${data.framework}`);
    lines.push(`**Source:** ${data.source}`);
    lines.push(`**Generated:** ${new Date().toISOString()}`);
    lines.push('');

    // Summary
    lines.push('## Summary');
    lines.push('');
    lines.push(`| Metric | Value |`);
    lines.push(`|--------|-------|`);
    lines.push(`| Total Nodes | ${data.nodesProcessed} |`);
    lines.push(`| Successful | ${data.nodesSuccessful} |`);
    lines.push(`| Failed | ${data.nodesFailed} |`);
    lines.push(`| Skipped | ${data.nodesSkipped} |`);
    lines.push(`| Degraded | ${data.nodesDegraded} |`);
    lines.push(`| Coverage | ${data.metrics.coverage.toFixed(1)}% |`);
    lines.push(`| Degradation Rate | ${data.metrics.degradationRate.toFixed(1)}% |`);
    if (data.duration) {
      lines.push(`| Duration | ${data.duration}ms |`);
    }
    lines.push('');

    // Status
    const status = this._determineStatus(data);
    lines.push(`**Status:** ${this._getStatusEmoji(status)} ${status.toUpperCase()}`);
    lines.push('');

    // Errors
    if (data.errors.length > 0) {
      lines.push('## Errors');
      lines.push('');
      const errors = data.errors.slice(0, this.options.maxErrors);
      for (const error of errors) {
        lines.push(`- **${error.message}**`);
        if (error.context.nodeId) {
          lines.push(`  - Node: ${error.context.nodeName || error.context.nodeId}`);
        }
      }
      if (data.errors.length > this.options.maxErrors) {
        lines.push(`- ... and ${data.errors.length - this.options.maxErrors} more errors`);
      }
      lines.push('');
    }

    // Warnings
    if (data.warnings.length > 0) {
      lines.push('## Warnings');
      lines.push('');
      const warnings = data.warnings.slice(0, this.options.maxWarnings);
      for (const warning of warnings) {
        lines.push(`- ${warning.message}`);
      }
      if (data.warnings.length > this.options.maxWarnings) {
        lines.push(`- ... and ${data.warnings.length - this.options.maxWarnings} more warnings`);
      }
      lines.push('');
    }

    // Degradations
    if (data.degradations.length > 0) {
      lines.push('## Degradations');
      lines.push('');
      lines.push('| Node | Level | Reason |');
      lines.push('|------|-------|--------|');
      for (const deg of data.degradations.slice(0, 20)) {
        lines.push(`| ${deg.nodeName || deg.nodeId} | ${deg.level} | ${deg.reason || '-'} |`);
      }
      if (data.degradations.length > 20) {
        lines.push(`| ... | ${data.degradations.length - 20} more | |`);
      }
      lines.push('');
    }

    // Sync Status
    if (data.syncResults) {
      lines.push('## Sync Status');
      lines.push('');
      lines.push(`- Sync Rate: ${data.syncResults.syncRate?.toFixed(1) || 'N/A'}%`);
      lines.push(`- Synced: ${data.syncResults.synced || 0}`);
      lines.push(`- Drifted: ${data.syncResults.drifted || 0}`);
      lines.push(`- Missing: ${data.syncResults.missing || 0}`);
      lines.push('');
    }

    // Recommendations
    if (this.options.includeRecommendations && data.recommendations.length > 0) {
      lines.push('## Recommendations');
      lines.push('');
      const sorted = data.recommendations.sort((a, b) => {
        const order = { high: 0, medium: 1, low: 2 };
        return (order[a.priority] || 2) - (order[b.priority] || 2);
      });
      for (const rec of sorted) {
        const priority = rec.priority === 'high' ? '🔴' : rec.priority === 'medium' ? '🟡' : '🟢';
        lines.push(`- ${priority} ${rec.text}`);
      }
      lines.push('');
    }

    // Timing
    if (this.options.includeTiming && data.timings.length > 0) {
      lines.push('## Timing');
      lines.push('');
      lines.push('| Operation | Duration |');
      lines.push('|-----------|----------|');
      for (const timing of data.timings) {
        lines.push(`| ${timing.operation} | ${timing.durationMs}ms |`);
      }
      lines.push('');
    }

    // Files
    if (data.files.length > 0) {
      lines.push('## Generated Files');
      lines.push('');
      for (const file of data.files) {
        lines.push(`- \`${file.path}\``);
      }
      lines.push('');
    }

    return lines.join('\n');
  }

  /**
   * Generate HTML report
   * @param {Object} data - Report data
   * @returns {string} HTML string
   * @private
   */
  _generateHtml(data) {
    const status = this._determineStatus(data);
    const statusColor = status === STATUS.SUCCESS ? '#22c55e' :
                        status === STATUS.PARTIAL ? '#eab308' :
                        status === STATUS.FAILED ? '#ef4444' : '#6b7280';

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Transformation Report - ${data.sessionId}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f9fafb; }
    .container { max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    h1 { color: #111827; margin-bottom: 10px; }
    h2 { color: #374151; margin-top: 30px; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; }
    .meta { color: #6b7280; font-size: 14px; margin-bottom: 20px; }
    .status { display: inline-block; padding: 6px 12px; border-radius: 4px; color: white; font-weight: 600; background: ${statusColor}; }
    table { width: 100%; border-collapse: collapse; margin: 15px 0; }
    th, td { padding: 10px; text-align: left; border-bottom: 1px solid #e5e7eb; }
    th { background: #f9fafb; font-weight: 600; }
    .error { color: #ef4444; }
    .warning { color: #eab308; }
    .metric { font-size: 24px; font-weight: 700; color: #111827; }
    .metric-label { font-size: 12px; color: #6b7280; text-transform: uppercase; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; margin: 20px 0; }
    .card { background: #f9fafb; padding: 15px; border-radius: 6px; text-align: center; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Transformation Report</h1>
    <div class="meta">
      <strong>Session:</strong> ${data.sessionId} |
      <strong>Framework:</strong> ${data.framework} |
      <strong>Source:</strong> ${data.source}
    </div>
    <div class="status">${status.toUpperCase()}</div>

    <h2>Summary</h2>
    <div class="grid">
      <div class="card">
        <div class="metric">${data.nodesProcessed}</div>
        <div class="metric-label">Total Nodes</div>
      </div>
      <div class="card">
        <div class="metric">${data.nodesSuccessful}</div>
        <div class="metric-label">Successful</div>
      </div>
      <div class="card">
        <div class="metric">${data.nodesFailed}</div>
        <div class="metric-label">Failed</div>
      </div>
      <div class="card">
        <div class="metric">${data.metrics.coverage.toFixed(1)}%</div>
        <div class="metric-label">Coverage</div>
      </div>
    </div>

    ${data.errors.length > 0 ? `
    <h2>Errors (${data.errors.length})</h2>
    <ul>
      ${data.errors.slice(0, 10).map(e => `<li class="error">${e.message}</li>`).join('')}
      ${data.errors.length > 10 ? `<li>... and ${data.errors.length - 10} more</li>` : ''}
    </ul>
    ` : ''}

    ${data.warnings.length > 0 ? `
    <h2>Warnings (${data.warnings.length})</h2>
    <ul>
      ${data.warnings.slice(0, 10).map(w => `<li class="warning">${w.message}</li>`).join('')}
      ${data.warnings.length > 10 ? `<li>... and ${data.warnings.length - 10} more</li>` : ''}
    </ul>
    ` : ''}

    ${data.recommendations.length > 0 ? `
    <h2>Recommendations</h2>
    <ul>
      ${data.recommendations.map(r => `<li>${r.text}</li>`).join('')}
    </ul>
    ` : ''}

    <div class="meta" style="margin-top: 30px;">
      Generated: ${new Date().toISOString()} |
      Duration: ${data.duration ? data.duration + 'ms' : 'N/A'}
    </div>
  </div>
</body>
</html>`;
  }

  /**
   * Generate plain text report
   * @param {Object} data - Report data
   * @returns {string} Text string
   * @private
   */
  _generateText(data) {
    const lines = [];
    const status = this._determineStatus(data);

    lines.push('='.repeat(60));
    lines.push('TRANSFORMATION REPORT');
    lines.push('='.repeat(60));
    lines.push('');
    lines.push(`Session:   ${data.sessionId}`);
    lines.push(`Framework: ${data.framework}`);
    lines.push(`Source:    ${data.source}`);
    lines.push(`Status:    ${status.toUpperCase()}`);
    lines.push('');
    lines.push('-'.repeat(60));
    lines.push('SUMMARY');
    lines.push('-'.repeat(60));
    lines.push(`Total Nodes:      ${data.nodesProcessed}`);
    lines.push(`Successful:       ${data.nodesSuccessful}`);
    lines.push(`Failed:           ${data.nodesFailed}`);
    lines.push(`Skipped:          ${data.nodesSkipped}`);
    lines.push(`Degraded:         ${data.nodesDegraded}`);
    lines.push(`Coverage:         ${data.metrics.coverage.toFixed(1)}%`);
    lines.push(`Degradation Rate: ${data.metrics.degradationRate.toFixed(1)}%`);
    if (data.duration) {
      lines.push(`Duration:         ${data.duration}ms`);
    }
    lines.push('');

    if (data.errors.length > 0) {
      lines.push('-'.repeat(60));
      lines.push(`ERRORS (${data.errors.length})`);
      lines.push('-'.repeat(60));
      for (const error of data.errors.slice(0, 20)) {
        lines.push(`* ${error.message}`);
      }
      lines.push('');
    }

    if (data.warnings.length > 0) {
      lines.push('-'.repeat(60));
      lines.push(`WARNINGS (${data.warnings.length})`);
      lines.push('-'.repeat(60));
      for (const warning of data.warnings.slice(0, 20)) {
        lines.push(`* ${warning.message}`);
      }
      lines.push('');
    }

    lines.push('='.repeat(60));
    lines.push(`Generated: ${new Date().toISOString()}`);
    lines.push('='.repeat(60));

    return lines.join('\n');
  }

  /**
   * Determine overall status
   * @param {Object} data - Report data
   * @returns {string} Status
   * @private
   */
  _determineStatus(data) {
    if (data.nodesFailed === 0 && data.nodesDegraded === 0) {
      return STATUS.SUCCESS;
    }
    if (data.nodesSuccessful === 0) {
      return STATUS.FAILED;
    }
    if (data.nodesProcessed === data.nodesSkipped) {
      return STATUS.SKIPPED;
    }
    return STATUS.PARTIAL;
  }

  /**
   * Get status emoji
   * @param {string} status - Status value
   * @returns {string} Emoji
   * @private
   */
  _getStatusEmoji(status) {
    switch (status) {
      case STATUS.SUCCESS: return '✅';
      case STATUS.PARTIAL: return '⚠️';
      case STATUS.FAILED: return '❌';
      case STATUS.SKIPPED: return '⏭️';
      default: return '❓';
    }
  }
}

// =============================================================================
// REPORT WRITER
// =============================================================================

/**
 * Writes reports to disk
 */
class ReportWriter {
  /**
   * Create a report writer
   * @param {Object} options - Writer options
   */
  constructor(options = {}) {
    this.options = {
      outputDir: options.outputDir || '.design/reports',
      filePrefix: options.filePrefix || 'transform-report',
      ...options
    };

    this.generator = new ReportGenerator(options.generator);
  }

  /**
   * Write report to file
   * @param {Object} data - Report data
   * @param {Object} options - Write options
   * @returns {Object} Write result
   */
  write(data, options = {}) {
    const format = options.format || REPORT_FORMATS.MARKDOWN;
    const filename = options.filename ||
      `${this.options.filePrefix}-${data.sessionId}.${this._getExtension(format)}`;

    const outputPath = path.resolve(this.options.outputDir, filename);

    // Ensure directory exists
    const dir = path.dirname(outputPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Generate and write
    const content = this.generator.generate(data, format);
    fs.writeFileSync(outputPath, content);

    return {
      success: true,
      path: outputPath,
      format,
      size: content.length
    };
  }

  /**
   * Write multiple format reports
   * @param {Object} data - Report data
   * @param {string[]} formats - Formats to generate
   * @returns {Object[]} Write results
   */
  writeAll(data, formats = [REPORT_FORMATS.MARKDOWN, REPORT_FORMATS.JSON]) {
    return formats.map(format => this.write(data, { format }));
  }

  /**
   * Get file extension for format
   * @param {string} format - Report format
   * @returns {string} File extension
   * @private
   */
  _getExtension(format) {
    switch (format) {
      case REPORT_FORMATS.JSON: return 'json';
      case REPORT_FORMATS.MARKDOWN: return 'md';
      case REPORT_FORMATS.HTML: return 'html';
      case REPORT_FORMATS.TEXT: return 'txt';
      default: return 'txt';
    }
  }
}

// =============================================================================
// CONVENIENCE FUNCTIONS
// =============================================================================

/**
 * Create a complete report system
 * @param {Object} options - System options
 * @returns {Object} Report system
 */
function createReportSystem(options = {}) {
  const collector = new ReportCollector(options.collector);
  const generator = new ReportGenerator(options.generator);
  const writer = new ReportWriter(options.writer);

  return {
    collector,
    generator,
    writer,
    // Convenience methods
    startCollection: () => collector.reset(),
    recordNode: (node, result) => collector.recordNode(node, result),
    recordWarning: (msg, ctx) => collector.recordWarning(msg, ctx),
    recordError: (err, ctx) => collector.recordError(err, ctx),
    finalize: () => collector.finalize(),
    generate: (format) => generator.generate(collector.getData(), format),
    write: (options) => writer.write(collector.finalize(), options),
    writeAll: (formats) => writer.writeAll(collector.finalize(), formats)
  };
}

/**
 * Quick report generation from data
 * @param {Object} data - Report data
 * @param {string} format - Output format
 * @returns {string} Formatted report
 */
function generateReport(data, format = REPORT_FORMATS.MARKDOWN) {
  const generator = new ReportGenerator();
  return generator.generate(data, format);
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Classes
  ReportCollector,
  ReportGenerator,
  ReportWriter,
  // Constants
  REPORT_FORMATS,
  REPORT_SECTIONS,
  STATUS,
  // Factory functions
  createReportSystem,
  // Convenience functions
  generateReport
};
