/**
 * Conflict User Handler
 * Sprint 6.6: PROMPT_USER strategy handler for conflict resolution
 */

const EventEmitter = require('events');
const readline = require('readline');

/**
 * User response options for conflict resolution
 */
const UserChoice = {
  KEEP_LOCAL: 'keep_local',
  USE_GENERATED: 'use_generated',
  MERGE: 'merge',
  SKIP: 'skip',
  SKIP_ALL: 'skip_all',
  OVERWRITE_ALL: 'overwrite_all',
  ABORT: 'abort'
};

/**
 * Handler for PROMPT_USER conflict resolution strategy
 */
class ConflictUserHandler extends EventEmitter {
  constructor(options = {}) {
    super();
    this.defaultChoice = options.defaultChoice || UserChoice.KEEP_LOCAL;
    this.autoResolve = options.autoResolve || false;
    this.timeout = options.timeout || 0; // 0 = no timeout
    this.skipAll = false;
    this.overwriteAll = false;
    this.rl = null;
    this.interactive = options.interactive !== false;
  }

  /**
   * Prompt user for conflict resolution
   */
  async promptForResolution(conflict) {
    // Check for batch decisions
    if (this.skipAll) {
      return { choice: UserChoice.SKIP, conflict };
    }

    if (this.overwriteAll) {
      return { choice: UserChoice.USE_GENERATED, conflict };
    }

    // Auto-resolve if enabled
    if (this.autoResolve) {
      this.emit('auto-resolved', { conflict, choice: this.defaultChoice });
      return { choice: this.defaultChoice, conflict };
    }

    // Non-interactive mode
    if (!this.interactive) {
      return { choice: this.defaultChoice, conflict };
    }

    // Interactive prompt
    return this.interactivePrompt(conflict);
  }

  /**
   * Interactive console prompt
   */
  async interactivePrompt(conflict) {
    return new Promise((resolve, reject) => {
      this.rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout
      });

      const prompt = this.formatConflictPrompt(conflict);
      console.log(prompt);

      const timeoutId = this.timeout > 0
        ? setTimeout(() => {
            this.rl.close();
            this.emit('timeout', { conflict });
            resolve({ choice: this.defaultChoice, conflict, timedOut: true });
          }, this.timeout)
        : null;

      this.rl.question('Your choice: ', (answer) => {
        if (timeoutId) clearTimeout(timeoutId);
        this.rl.close();

        const choice = this.parseUserInput(answer);

        // Handle batch choices
        if (choice === UserChoice.SKIP_ALL) {
          this.skipAll = true;
          resolve({ choice: UserChoice.SKIP, conflict, batchApplied: 'skip_all' });
        } else if (choice === UserChoice.OVERWRITE_ALL) {
          this.overwriteAll = true;
          resolve({ choice: UserChoice.USE_GENERATED, conflict, batchApplied: 'overwrite_all' });
        } else {
          resolve({ choice, conflict });
        }
      });

      this.rl.on('close', () => {
        if (timeoutId) clearTimeout(timeoutId);
      });

      this.rl.on('error', (err) => {
        if (timeoutId) clearTimeout(timeoutId);
        reject(err);
      });
    });
  }

  /**
   * Format conflict prompt for display
   */
  formatConflictPrompt(conflict) {
    const lines = [
      '\n╔══════════════════════════════════════════════════════════════╗',
      '║                    FILE CONFLICT DETECTED                     ║',
      '╠══════════════════════════════════════════════════════════════╣',
      `║ File: ${conflict.filePath.padEnd(54)}║`,
      `║ Type: ${conflict.conflictType.padEnd(54)}║`,
      '╠══════════════════════════════════════════════════════════════╣',
      `║ ${(conflict.message || 'Conflict detected').padEnd(60)}║`,
      '╠══════════════════════════════════════════════════════════════╣',
      '║ Options:                                                      ║',
      '║   [k] Keep local version                                      ║',
      '║   [g] Use generated version                                   ║',
      '║   [m] Merge (create .merge file)                              ║',
      '║   [s] Skip this file                                          ║',
      '║   [S] Skip ALL remaining conflicts                            ║',
      '║   [O] Overwrite ALL remaining files                           ║',
      '║   [a] Abort entire operation                                  ║',
      '╚══════════════════════════════════════════════════════════════╝'
    ];

    return lines.join('\n');
  }

  /**
   * Parse user input to choice
   */
  parseUserInput(input) {
    const normalized = input.trim().toLowerCase();

    switch (normalized) {
      case 'k':
      case 'keep':
      case 'keep_local':
      case 'local':
        return UserChoice.KEEP_LOCAL;

      case 'g':
      case 'generated':
      case 'use_generated':
      case 'overwrite':
        return UserChoice.USE_GENERATED;

      case 'm':
      case 'merge':
        return UserChoice.MERGE;

      case 's':
      case 'skip':
        return UserChoice.SKIP;

      case 'S': // Capital S for skip all
        return UserChoice.SKIP_ALL;

      case 'O': // Capital O for overwrite all
        return UserChoice.OVERWRITE_ALL;

      case 'a':
      case 'abort':
      case 'cancel':
        return UserChoice.ABORT;

      default:
        return this.defaultChoice;
    }
  }

  /**
   * Handle multiple conflicts
   */
  async handleConflicts(conflicts) {
    const results = [];
    let aborted = false;

    for (const conflict of conflicts) {
      if (aborted) {
        results.push({ choice: UserChoice.SKIP, conflict, aborted: true });
        continue;
      }

      const result = await this.promptForResolution(conflict);
      results.push(result);

      if (result.choice === UserChoice.ABORT) {
        aborted = true;
        this.emit('aborted', { processedCount: results.length - 1 });
      }
    }

    this.emit('all-resolved', {
      total: conflicts.length,
      results
    });

    return {
      aborted,
      results,
      summary: this.summarizeResults(results)
    };
  }

  /**
   * Summarize resolution results
   */
  summarizeResults(results) {
    const summary = {
      total: results.length,
      keptLocal: 0,
      usedGenerated: 0,
      merged: 0,
      skipped: 0,
      aborted: false
    };

    for (const result of results) {
      switch (result.choice) {
        case UserChoice.KEEP_LOCAL:
          summary.keptLocal++;
          break;
        case UserChoice.USE_GENERATED:
          summary.usedGenerated++;
          break;
        case UserChoice.MERGE:
          summary.merged++;
          break;
        case UserChoice.SKIP:
          summary.skipped++;
          break;
        case UserChoice.ABORT:
          summary.aborted = true;
          break;
      }
    }

    return summary;
  }

  /**
   * Reset batch decisions (for new operation)
   */
  reset() {
    this.skipAll = false;
    this.overwriteAll = false;
  }

  /**
   * Set auto-resolve mode
   */
  setAutoResolve(enabled, defaultChoice = null) {
    this.autoResolve = enabled;
    if (defaultChoice) {
      this.defaultChoice = defaultChoice;
    }
  }

  /**
   * Programmatic conflict resolution (for API usage)
   */
  async resolveConflict(conflict, choice) {
    // Validate choice
    if (!Object.values(UserChoice).includes(choice)) {
      throw new Error(`Invalid choice: ${choice}`);
    }

    this.emit('resolved', { conflict, choice });

    return {
      choice,
      conflict,
      programmatic: true
    };
  }

  /**
   * Create merge file content
   */
  createMergeContent(localContent, generatedContent, conflict) {
    const divider = '='.repeat(60);
    const lines = [
      `<<<<<<< LOCAL (${conflict.filePath})`,
      localContent,
      divider,
      generatedContent,
      `>>>>>>> GENERATED (from Figma)`
    ];

    return lines.join('\n');
  }

  /**
   * Close any open resources
   */
  close() {
    if (this.rl) {
      this.rl.close();
      this.rl = null;
    }
  }
}

/**
 * Factory function
 */
function createConflictUserHandler(options = {}) {
  return new ConflictUserHandler(options);
}

module.exports = ConflictUserHandler;
module.exports.ConflictUserHandler = ConflictUserHandler;
module.exports.createConflictUserHandler = createConflictUserHandler;
module.exports.UserChoice = UserChoice;
