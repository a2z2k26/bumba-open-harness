/**
 * Thread-safe logging infrastructure for Bumba Sandbox Orchestrator
 * Adapted from agent-sandboxes logs.py - ForkLogger + LogManager pattern
 */

import * as fs from 'fs';
import * as path from 'path';
import * as winston from 'winston';
import { LoggingConfig } from './types';

// ============================================================================
// Mutex Lock for Thread Safety
// ============================================================================

class AsyncLock {
  private locked: boolean = false;
  private queue: Array<() => void> = [];

  async acquire(): Promise<() => void> {
    return new Promise((resolve) => {
      if (!this.locked) {
        this.locked = true;
        resolve(() => this.release());
      } else {
        this.queue.push(() => {
          this.locked = true;
          resolve(() => this.release());
        });
      }
    });
  }

  private release(): void {
    this.locked = false;
    const next = this.queue.shift();
    if (next) {
      next();
    }
  }
}

// ============================================================================
// AgentLogger - Thread-safe per-agent logging
// ============================================================================

export class AgentLogger {
  private lock: AsyncLock;
  private winstonLogger: winston.Logger;
  private logFilePath: string;
  private agentId: string;
  private issueNumber: number;

  constructor(agentId: string, issueNumber: number, logsDir: string) {
    this.agentId = agentId;
    this.issueNumber = issueNumber;
    this.lock = new AsyncLock();

    // Generate log file name: agent-{issueNum}-{timestamp}.log
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').split('T')[0];
    const filename = `agent-${issueNumber}-${timestamp}.log`;
    this.logFilePath = path.join(logsDir, filename);

    // Ensure logs directory exists
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }

    // Create Winston logger with file and console transports
    this.winstonLogger = winston.createLogger({
      level: 'debug',
      format: winston.format.combine(
        winston.format.timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
        winston.format.errors({ stack: true }),
        winston.format.printf(({ timestamp, level, message, ...meta }) => {
          const metaStr = Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : '';
          return `[${timestamp}] [${level.toUpperCase()}] ${message}${metaStr}`;
        })
      ),
      transports: [
        new winston.transports.File({
          filename: this.logFilePath,
          options: { flags: 'a' } // Append mode
        })
      ]
    });
  }

  /**
   * Thread-safe log method - acquires lock before writing
   */
  async log(level: 'info' | 'warn' | 'error' | 'debug', message: string, meta?: any): Promise<void> {
    const release = await this.lock.acquire();
    try {
      this.winstonLogger.log(level, message, meta);
      // Small delay to ensure async file write completes
      await new Promise(resolve => setTimeout(resolve, 50));
    } finally {
      release();
    }
  }

  async info(message: string, meta?: any): Promise<void> {
    return this.log('info', message, meta);
  }

  async warn(message: string, meta?: any): Promise<void> {
    return this.log('warn', message, meta);
  }

  async error(message: string, meta?: any): Promise<void> {
    return this.log('error', message, meta);
  }

  async debug(message: string, meta?: any): Promise<void> {
    return this.log('debug', message, meta);
  }

  /**
   * Log hook execution
   */
  async logHook(hookType: string, tool: string, result: string, meta?: any): Promise<void> {
    return this.log('info', `Hook: ${hookType} | Tool: ${tool} | Result: ${result}`, meta);
  }

  /**
   * Log tool usage
   */
  async logToolUse(tool: string, params: any, result?: any, error?: string): Promise<void> {
    const meta = {
      tool,
      params,
      result: result ? 'success' : 'error',
      error
    };
    return this.log('info', `Tool: ${tool}`, meta);
  }

  /**
   * Log agent progress
   */
  async logProgress(percentage: number, currentTask: string): Promise<void> {
    return this.log('info', `Progress: ${percentage}% - ${currentTask}`);
  }

  /**
   * Get log file path
   */
  getLogFilePath(): string {
    return this.logFilePath;
  }

  /**
   * Get agent ID
   */
  getAgentId(): string {
    return this.agentId;
  }

  /**
   * Get issue number
   */
  getIssueNumber(): number {
    return this.issueNumber;
  }

  /**
   * Read log file contents
   */
  async readLogs(lines?: number): Promise<string> {
    try {
      const content = await fs.promises.readFile(this.logFilePath, 'utf-8');
      if (!lines) {
        return content;
      }

      // Return last N lines
      const allLines = content.split('\n');
      return allLines.slice(-lines).join('\n');
    } catch (error) {
      return `Error reading log file: ${error}`;
    }
  }

  /**
   * Close logger and release resources
   */
  async close(): Promise<void> {
    const release = await this.lock.acquire();
    try {
      this.winstonLogger.close();
    } finally {
      release();
    }
  }
}

// ============================================================================
// LogManager - Manage multiple agent loggers
// ============================================================================

export class LogManager {
  private loggers: Map<string, AgentLogger>;
  private logsDir: string;

  constructor(logsDir: string) {
    this.loggers = new Map();
    this.logsDir = logsDir;

    // Ensure logs directory exists
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true });
    }
  }

  /**
   * Create a new agent logger
   */
  createLogger(agentId: string, issueNumber: number): AgentLogger {
    if (this.loggers.has(agentId)) {
      throw new Error(`Logger for agent ${agentId} already exists`);
    }

    const logger = new AgentLogger(agentId, issueNumber, this.logsDir);
    this.loggers.set(agentId, logger);
    return logger;
  }

  /**
   * Get an existing logger
   */
  getLogger(agentId: string): AgentLogger | undefined {
    return this.loggers.get(agentId);
  }

  /**
   * Get all loggers
   */
  getAllLoggers(): AgentLogger[] {
    return Array.from(this.loggers.values());
  }

  /**
   * Remove a logger
   */
  async removeLogger(agentId: string): Promise<void> {
    const logger = this.loggers.get(agentId);
    if (logger) {
      await logger.close();
      this.loggers.delete(agentId);
    }
  }

  /**
   * Close all loggers
   */
  async closeAll(): Promise<void> {
    const closePromises = Array.from(this.loggers.values()).map(logger => logger.close());
    await Promise.all(closePromises);
    this.loggers.clear();
  }

  /**
   * Get log directory
   */
  getLogsDir(): string {
    return this.logsDir;
  }

  /**
   * List all log files
   */
  async listLogFiles(): Promise<string[]> {
    try {
      const files = await fs.promises.readdir(this.logsDir);
      return files.filter(file => file.endsWith('.log'));
    } catch (error) {
      return [];
    }
  }

  /**
   * Query logs across all agents
   */
  async queryLogs(pattern: string): Promise<{ agentId: string; matches: string[] }[]> {
    const results: { agentId: string; matches: string[] }[] = [];

    for (const [agentId, logger] of this.loggers.entries()) {
      const content = await logger.readLogs();
      const matches = content
        .split('\n')
        .filter(line => line.includes(pattern));

      if (matches.length > 0) {
        results.push({ agentId, matches });
      }
    }

    return results;
  }
}

// ============================================================================
// Singleton Log Manager Instance
// ============================================================================

let globalLogManager: LogManager | null = null;

export function initializeLogManager(logsDir: string): LogManager {
  if (!globalLogManager) {
    globalLogManager = new LogManager(logsDir);
  }
  return globalLogManager;
}

export function getLogManager(): LogManager {
  if (!globalLogManager) {
    throw new Error('LogManager not initialized. Call initializeLogManager() first.');
  }
  return globalLogManager;
}

// ============================================================================
// Log Query Helpers
// ============================================================================

export interface LogQueryOptions {
  agentId?: string;
  issueNumber?: number;
  level?: 'info' | 'warn' | 'error' | 'debug';
  pattern?: string;
  since?: Date;
  limit?: number;
}

export async function queryLogs(options: LogQueryOptions): Promise<string[]> {
  const manager = getLogManager();
  const results: string[] = [];

  const loggers = options.agentId
    ? [manager.getLogger(options.agentId)].filter(Boolean) as AgentLogger[]
    : manager.getAllLoggers();

  for (const logger of loggers) {
    if (options.issueNumber && logger.getIssueNumber() !== options.issueNumber) {
      continue;
    }

    const content = await logger.readLogs();
    let lines = content.split('\n');

    // Apply filters
    if (options.level) {
      const level = options.level;
      lines = lines.filter(line => line.includes(`[${level.toUpperCase()}]`));
    }

    if (options.pattern) {
      const pattern = options.pattern;
      lines = lines.filter(line => line.includes(pattern));
    }

    if (options.since) {
      lines = lines.filter(line => {
        const match = line.match(/\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]/);
        if (match) {
          const logDate = new Date(match[1]);
          return logDate >= options.since!;
        }
        return false;
      });
    }

    results.push(...lines);
  }

  // Apply limit
  if (options.limit) {
    return results.slice(-options.limit);
  }

  return results;
}

/**
 * Get recent hook blocks for debugging
 */
export async function getRecentHookBlocks(limit: number = 10): Promise<any[]> {
  const logs = await queryLogs({
    pattern: 'Hook:',
    limit: limit * 2 // Get more to filter
  });

  const blocks = logs
    .filter(line => line.includes('Result: deny') || line.includes('Result: block'))
    .slice(-limit);

  return blocks.map(line => {
    // Parse log line to extract details
    const hookMatch = line.match(/Hook: (\w+)/);
    const toolMatch = line.match(/Tool: (\w+)/);
    const timestampMatch = line.match(/\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]/);

    return {
      hookType: hookMatch ? hookMatch[1] : 'unknown',
      tool: toolMatch ? toolMatch[1] : 'unknown',
      timestamp: timestampMatch ? timestampMatch[1] : 'unknown',
      rawLine: line
    };
  });
}

/**
 * Calculate hook statistics
 */
export async function getHookStats(): Promise<any> {
  const logs = await queryLogs({ pattern: 'Hook:' });

  const stats = {
    totalExecutions: logs.length,
    byType: {} as Record<string, { count: number; blocked: number; errors: number }>,
    recentBlocks: await getRecentHookBlocks(5)
  };

  for (const line of logs) {
    const hookMatch = line.match(/Hook: (\w+)/);
    if (hookMatch) {
      const hookType = hookMatch[1];
      if (!stats.byType[hookType]) {
        stats.byType[hookType] = { count: 0, blocked: 0, errors: 0 };
      }
      stats.byType[hookType].count++;

      if (line.includes('Result: deny') || line.includes('Result: block')) {
        stats.byType[hookType].blocked++;
      }
      if (line.includes('[ERROR]')) {
        stats.byType[hookType].errors++;
      }
    }
  }

  return stats;
}
