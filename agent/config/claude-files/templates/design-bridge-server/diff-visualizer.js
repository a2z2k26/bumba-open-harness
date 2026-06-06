/**
 * Diff Visualizer
 * Sprint 42: Visualize changes between catalog versions
 *
 * Creates human-readable diffs showing what changed during syncs:
 * - Colors added, modified, removed
 * - Typography changes
 * - Spacing changes
 * - Component changes
 * - Multiple output formats (console, JSON, HTML)
 */

const chalk = require('chalk');
const { logger } = require('../logging');

/**
 * Change Types
 */
const ChangeType = {
  ADDED: 'added',
  MODIFIED: 'modified',
  REMOVED: 'removed',
  UNCHANGED: 'unchanged'
};

/**
 * Field Types
 */
const FieldType = {
  COLORS: 'colors',
  TYPOGRAPHY: 'typography',
  SPACING: 'spacing',
  COMPONENTS: 'components',
  METADATA: 'metadata'
};

/**
 * Change Record
 * Represents a single change
 */
class ChangeRecord {
  constructor(data = {}) {
    this.type = data.type; // added, modified, removed
    this.field = data.field; // colors, typography, etc.
    this.path = data.path; // e.g., "colors[0]"
    this.itemId = data.itemId; // unique identifier
    this.itemName = data.itemName; // human-readable name
    this.before = data.before || null;
    this.after = data.after || null;
    this.details = data.details || {};
  }

  toJSON() {
    return {
      type: this.type,
      field: this.field,
      path: this.path,
      itemId: this.itemId,
      itemName: this.itemName,
      before: this.before,
      after: this.after,
      details: this.details
    };
  }
}

/**
 * Diff Result
 * Contains all changes for a sync
 */
class DiffResult {
  constructor(before, after) {
    this.before = before;
    this.after = after;
    this.changes = [];
    this.summary = {
      added: 0,
      modified: 0,
      removed: 0,
      unchanged: 0
    };
    this.byField = {};
  }

  addChange(change) {
    this.changes.push(change);
    this.summary[change.type]++;

    if (!this.byField[change.field]) {
      this.byField[change.field] = {
        added: 0,
        modified: 0,
        removed: 0
      };
    }
    this.byField[change.field][change.type]++;
  }

  toJSON() {
    return {
      summary: this.summary,
      byField: this.byField,
      changes: this.changes.map(c => c.toJSON())
    };
  }
}

/**
 * Diff Visualizer
 * Compares catalog data and generates visualizations
 */
class DiffVisualizer {
  constructor(options = {}) {
    this.colorMode = options.colorMode !== false; // Default true
    this.verbose = options.verbose || false;
    this.maxDiffItems = options.maxDiffItems || 50;
  }

  /**
   * Compare two catalog data sets
   */
  compare(before, after) {
    const diff = new DiffResult(before, after);

    // Compare each field type
    this.compareField(diff, before, after, FieldType.COLORS);
    this.compareField(diff, before, after, FieldType.TYPOGRAPHY);
    this.compareField(diff, before, after, FieldType.SPACING);
    this.compareField(diff, before, after, FieldType.COMPONENTS);

    return diff;
  }

  /**
   * Compare a specific field (array of items)
   */
  compareField(diff, before, after, fieldName) {
    const beforeItems = before[fieldName] || [];
    const afterItems = after[fieldName] || [];

    // Create lookup maps
    const beforeMap = new Map();
    const afterMap = new Map();

    for (const item of beforeItems) {
      const key = this.getItemKey(item);
      beforeMap.set(key, item);
    }

    for (const item of afterItems) {
      const key = this.getItemKey(item);
      afterMap.set(key, item);
    }

    // Find added items
    for (const [key, item] of afterMap) {
      if (!beforeMap.has(key)) {
        diff.addChange(new ChangeRecord({
          type: ChangeType.ADDED,
          field: fieldName,
          path: `${fieldName}[${key}]`,
          itemId: key,
          itemName: this.getItemName(item),
          after: item
        }));
      }
    }

    // Find modified and unchanged items
    for (const [key, beforeItem] of beforeMap) {
      if (afterMap.has(key)) {
        const afterItem = afterMap.get(key);
        const changes = this.findItemChanges(beforeItem, afterItem);

        if (changes.length > 0) {
          diff.addChange(new ChangeRecord({
            type: ChangeType.MODIFIED,
            field: fieldName,
            path: `${fieldName}[${key}]`,
            itemId: key,
            itemName: this.getItemName(beforeItem),
            before: beforeItem,
            after: afterItem,
            details: { propertyChanges: changes }
          }));
        }
      }
    }

    // Find removed items
    for (const [key, item] of beforeMap) {
      if (!afterMap.has(key)) {
        diff.addChange(new ChangeRecord({
          type: ChangeType.REMOVED,
          field: fieldName,
          path: `${fieldName}[${key}]`,
          itemId: key,
          itemName: this.getItemName(item),
          before: item
        }));
      }
    }
  }

  /**
   * Get unique key for an item
   */
  getItemKey(item) {
    return item.id || item.name || JSON.stringify(item);
  }

  /**
   * Get human-readable name for an item
   */
  getItemName(item) {
    return item.name || item.id || 'Unknown';
  }

  /**
   * Find property-level changes in an item
   */
  findItemChanges(before, after) {
    const changes = [];
    const allKeys = new Set([
      ...Object.keys(before),
      ...Object.keys(after)
    ]);

    for (const key of allKeys) {
      const beforeVal = before[key];
      const afterVal = after[key];

      if (JSON.stringify(beforeVal) !== JSON.stringify(afterVal)) {
        changes.push({
          property: key,
          before: beforeVal,
          after: afterVal
        });
      }
    }

    return changes;
  }

  /**
   * Render diff to console with colors
   */
  renderToConsole(diff) {
    const lines = [];

    // Header
    lines.push(chalk.white.bold('\n━━━ Catalog Changes ━━━\n'));

    // Summary
    lines.push(chalk.white('Summary:'));
    lines.push(chalk.green(`  + ${diff.summary.added} added`));
    lines.push(chalk.blue(`  ~ ${diff.summary.modified} modified`));
    lines.push(chalk.red(`  - ${diff.summary.removed} removed`));
    lines.push('');

    // By field
    lines.push(chalk.white('By Field:'));
    for (const [field, counts] of Object.entries(diff.byField)) {
      const total = counts.added + counts.modified + counts.removed;
      if (total > 0) {
        lines.push(chalk.gray(`  ${field}:`));
        if (counts.added > 0) lines.push(chalk.green(`    + ${counts.added} added`));
        if (counts.modified > 0) lines.push(chalk.blue(`    ~ ${counts.modified} modified`));
        if (counts.removed > 0) lines.push(chalk.red(`    - ${counts.removed} removed`));
      }
    }
    lines.push('');

    // Detailed changes (limited)
    const displayChanges = diff.changes.slice(0, this.maxDiffItems);
    const remaining = diff.changes.length - displayChanges.length;

    if (displayChanges.length > 0) {
      lines.push(chalk.white('Changes:'));

      for (const change of displayChanges) {
        lines.push(this.renderChange(change));
      }

      if (remaining > 0) {
        lines.push(chalk.gray(`\n  ... and ${remaining} more change(s)`));
      }
    }

    return lines.join('\n');
  }

  /**
   * Render a single change
   */
  renderChange(change) {
    const lines = [];

    switch (change.type) {
      case ChangeType.ADDED:
        lines.push(chalk.green(`\n  + Added ${change.field}: ${chalk.bold(change.itemName)}`));
        if (this.verbose && change.after) {
          lines.push(chalk.gray(`    ${JSON.stringify(change.after, null, 2).split('\n').join('\n    ')}`));
        }
        break;

      case ChangeType.REMOVED:
        lines.push(chalk.red(`\n  - Removed ${change.field}: ${chalk.bold(change.itemName)}`));
        if (this.verbose && change.before) {
          lines.push(chalk.gray(`    ${JSON.stringify(change.before, null, 2).split('\n').join('\n    ')}`));
        }
        break;

      case ChangeType.MODIFIED:
        lines.push(chalk.blue(`\n  ~ Modified ${change.field}: ${chalk.bold(change.itemName)}`));
        if (change.details && change.details.propertyChanges) {
          for (const propChange of change.details.propertyChanges) {
            lines.push(chalk.gray(`    ${propChange.property}:`));
            lines.push(chalk.red(`      - ${JSON.stringify(propChange.before)}`));
            lines.push(chalk.green(`      + ${JSON.stringify(propChange.after)}`));
          }
        }
        break;
    }

    return lines.join('\n');
  }

  /**
   * Render diff to JSON
   */
  renderToJSON(diff) {
    return JSON.stringify(diff.toJSON(), null, 2);
  }

  /**
   * Render diff to HTML
   */
  renderToHTML(diff) {
    const html = [];

    html.push('<!DOCTYPE html>');
    html.push('<html lang="en">');
    html.push('<head>');
    html.push('  <meta charset="UTF-8">');
    html.push('  <meta name="viewport" content="width=device-width, initial-scale=1.0">');
    html.push('  <title>Catalog Changes</title>');
    html.push('  <style>');
    html.push('    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 40px; background: #f5f5f5; }');
    html.push('    .container { max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }');
    html.push('    h1 { margin-top: 0; color: #333; }');
    html.push('    .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 30px 0; }');
    html.push('    .summary-card { padding: 20px; border-radius: 4px; text-align: center; }');
    html.push('    .summary-card.added { background: #e8f5e9; color: #2e7d32; }');
    html.push('    .summary-card.modified { background: #e3f2fd; color: #1565c0; }');
    html.push('    .summary-card.removed { background: #ffebee; color: #c62828; }');
    html.push('    .summary-card .number { font-size: 36px; font-weight: bold; }');
    html.push('    .summary-card .label { font-size: 14px; text-transform: uppercase; margin-top: 8px; }');
    html.push('    .field-section { margin: 30px 0; }');
    html.push('    .field-title { font-size: 18px; font-weight: 600; margin-bottom: 15px; color: #555; }');
    html.push('    .change { margin: 15px 0; padding: 15px; border-left: 4px solid; border-radius: 4px; }');
    html.push('    .change.added { border-color: #4caf50; background: #f1f8f4; }');
    html.push('    .change.modified { border-color: #2196f3; background: #f0f7ff; }');
    html.push('    .change.removed { border-color: #f44336; background: #fff5f5; }');
    html.push('    .change-header { font-weight: 600; margin-bottom: 8px; }');
    html.push('    .change-detail { margin: 8px 0; padding-left: 20px; font-size: 14px; }');
    html.push('    .change-detail .property { color: #666; }');
    html.push('    .change-detail .value { font-family: monospace; }');
    html.push('    .change-detail .old-value { color: #c62828; }');
    html.push('    .change-detail .new-value { color: #2e7d32; }');
    html.push('  </style>');
    html.push('</head>');
    html.push('<body>');
    html.push('  <div class="container">');
    html.push('    <h1>Catalog Changes</h1>');

    // Summary cards
    html.push('    <div class="summary">');
    html.push(`      <div class="summary-card added">`);
    html.push(`        <div class="number">${diff.summary.added}</div>`);
    html.push(`        <div class="label">Added</div>`);
    html.push(`      </div>`);
    html.push(`      <div class="summary-card modified">`);
    html.push(`        <div class="number">${diff.summary.modified}</div>`);
    html.push(`        <div class="label">Modified</div>`);
    html.push(`      </div>`);
    html.push(`      <div class="summary-card removed">`);
    html.push(`        <div class="number">${diff.summary.removed}</div>`);
    html.push(`        <div class="label">Removed</div>`);
    html.push(`      </div>`);
    html.push('    </div>');

    // Group changes by field
    const changesByField = {};
    for (const change of diff.changes) {
      if (!changesByField[change.field]) {
        changesByField[change.field] = [];
      }
      changesByField[change.field].push(change);
    }

    // Render each field section
    for (const [field, changes] of Object.entries(changesByField)) {
      html.push(`    <div class="field-section">`);
      html.push(`      <div class="field-title">${field.charAt(0).toUpperCase() + field.slice(1)}</div>`);

      for (const change of changes) {
        html.push(`      <div class="change ${change.type}">`);
        html.push(`        <div class="change-header">${this.escapeHtml(change.itemName)}</div>`);

        if (change.type === ChangeType.MODIFIED && change.details && change.details.propertyChanges) {
          for (const propChange of change.details.propertyChanges) {
            html.push(`        <div class="change-detail">`);
            html.push(`          <span class="property">${this.escapeHtml(propChange.property)}:</span>`);
            html.push(`          <div class="value old-value">- ${this.escapeHtml(JSON.stringify(propChange.before))}</div>`);
            html.push(`          <div class="value new-value">+ ${this.escapeHtml(JSON.stringify(propChange.after))}</div>`);
            html.push(`        </div>`);
          }
        }

        html.push(`      </div>`);
      }

      html.push(`    </div>`);
    }

    html.push('  </div>');
    html.push('</body>');
    html.push('</html>');

    return html.join('\n');
  }

  /**
   * Escape HTML entities
   */
  escapeHtml(text) {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
  }

  /**
   * Get simple summary of changes
   */
  getSummary(diff) {
    return {
      total: diff.changes.length,
      added: diff.summary.added,
      modified: diff.summary.modified,
      removed: diff.summary.removed,
      byField: diff.byField
    };
  }

  /**
   * Check if there are any changes
   */
  hasChanges(diff) {
    return diff.changes.length > 0;
  }
}

module.exports = DiffVisualizer;
module.exports.ChangeType = ChangeType;
module.exports.FieldType = FieldType;
module.exports.ChangeRecord = ChangeRecord;
module.exports.DiffResult = DiffResult;
