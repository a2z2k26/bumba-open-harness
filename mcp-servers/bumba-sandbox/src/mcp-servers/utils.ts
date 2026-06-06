/**
 * Utility functions for Bumba Sandbox Orchestrator
 * Includes git utilities adapted from agent-sandboxes git_utils.py
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { BumbaSandboxConfig, OrchestratorState, ConfigurationError } from './types';

// ============================================================================
// Configuration Management
// ============================================================================

const HOME_DIR = process.env.HOME || os.homedir();
const DEFAULT_CONFIG_PATH = path.join(HOME_DIR, '.claude/config/bumba-sandbox-config.json');
const DEFAULT_STATE_PATH = path.join(HOME_DIR, '.claude/config/orchestrator-state.json');

/**
 * Load Bumba Sandbox configuration from file
 */
export async function loadConfig(configPath: string = DEFAULT_CONFIG_PATH): Promise<BumbaSandboxConfig> {
  try {
    const content = await fs.promises.readFile(configPath, 'utf-8');
    const config = JSON.parse(content) as BumbaSandboxConfig;
    return config;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      throw new ConfigurationError(
        `Configuration file not found: ${configPath}`,
        { path: configPath }
      );
    }
    throw new ConfigurationError(
      `Failed to load configuration: ${error}`,
      { path: configPath, error }
    );
  }
}

/**
 * Save Bumba Sandbox configuration to file
 */
export async function saveConfig(
  config: BumbaSandboxConfig,
  configPath: string = DEFAULT_CONFIG_PATH
): Promise<void> {
  try {
    // Validate against schema (basic validation)
    validateConfig(config);

    // Ensure directory exists
    const dir = path.dirname(configPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Write with pretty formatting
    const content = JSON.stringify(config, null, 2);
    await fs.promises.writeFile(configPath, content, 'utf-8');
  } catch (error) {
    throw new ConfigurationError(
      `Failed to save configuration: ${error}`,
      { path: configPath, error }
    );
  }
}

/**
 * Basic configuration validation
 */
function validateConfig(config: BumbaSandboxConfig): void {
  if (!['local', 'sandbox', 'auto'].includes(config.defaultMode)) {
    throw new ConfigurationError(
      `Invalid defaultMode: ${config.defaultMode}. Must be 'local', 'sandbox', or 'auto'.`
    );
  }

  if (config.sandboxDefaults.maxConcurrent < 1 || config.sandboxDefaults.maxConcurrent > 100) {
    throw new ConfigurationError(
      `Invalid maxConcurrent: ${config.sandboxDefaults.maxConcurrent}. Must be between 1 and 100.`
    );
  }

  if (config.costManagement.budgetLimit < 0) {
    throw new ConfigurationError(
      `Invalid budgetLimit: ${config.costManagement.budgetLimit}. Must be >= 0.`
    );
  }
}

/**
 * Load orchestrator state from file
 */
export async function loadState(statePath: string = DEFAULT_STATE_PATH): Promise<OrchestratorState | null> {
  try {
    const content = await fs.promises.readFile(statePath, 'utf-8');
    const state = JSON.parse(content) as OrchestratorState;
    return state;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      // State file doesn't exist yet - return null
      return null;
    }
    throw new ConfigurationError(
      `Failed to load orchestrator state: ${error}`,
      { path: statePath, error }
    );
  }
}

/**
 * Save orchestrator state to file (atomic write)
 */
export async function saveState(
  state: OrchestratorState,
  statePath: string = DEFAULT_STATE_PATH
): Promise<void> {
  try {
    // Ensure directory exists
    const dir = path.dirname(statePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Write to temporary file first (atomic write pattern)
    const tempPath = `${statePath}.tmp`;
    const content = JSON.stringify(state, null, 2);
    await fs.promises.writeFile(tempPath, content, 'utf-8');

    // Rename to actual file (atomic operation)
    await fs.promises.rename(tempPath, statePath);
  } catch (error) {
    throw new ConfigurationError(
      `Failed to save orchestrator state: ${error}`,
      { path: statePath, error }
    );
  }
}

// ============================================================================
// ID Generation
// ============================================================================

/**
 * Generate unique ID
 */
export function generateId(prefix: string = ''): string {
  const timestamp = Date.now();
  const random = Math.random().toString(36).substring(2, 15);
  return prefix ? `${prefix}-${timestamp}-${random}` : `${timestamp}-${random}`;
}

/**
 * Generate agent ID
 */
export function generateAgentId(issueNumber: number): string {
  return generateId(`agent-${issueNumber}`);
}

/**
 * Generate session ID
 */
export function generateSessionId(): string {
  return generateId('session');
}

/**
 * Generate event ID
 */
export function generateEventId(): string {
  return generateId('event');
}

// ============================================================================
// Cost Formatting
// ============================================================================

/**
 * Format cost in USD
 */
export function formatCost(cost: number): string {
  return `$${cost.toFixed(2)}`;
}

/**
 * Format cost with details
 */
export function formatCostDetailed(inputTokens: number, outputTokens: number, costPerInput: number, costPerOutput: number): string {
  const inputCost = (inputTokens / 1000) * costPerInput;
  const outputCost = (outputTokens / 1000) * costPerOutput;
  const totalCost = inputCost + outputCost;

  return `${formatCost(totalCost)} (${inputTokens} in + ${outputTokens} out tokens)`;
}

// ============================================================================
// Git Utilities (adapted from agent-sandboxes git_utils.py)
// ============================================================================

/**
 * Validate Git repository URL
 * Supports: https://github.com/owner/repo, git@github.com:owner/repo.git, etc.
 */
export function validateGitUrl(url: string): boolean {
  // HTTPS pattern
  const httpsPattern = /^https?:\/\/[a-zA-Z0-9.-]+\/[a-zA-Z0-9._-]+\/[a-zA-Z0-9._-]+(\.git)?$/;

  // SSH pattern
  const sshPattern = /^git@[a-zA-Z0-9.-]+:[a-zA-Z0-9._-]+\/[a-zA-Z0-9._-]+(\.git)?$/;

  return httpsPattern.test(url) || sshPattern.test(url);
}

/**
 * Extract repository name from Git URL
 * Examples:
 *   https://github.com/owner/repo.git -> repo
 *   git@github.com:owner/repo.git -> repo
 *   https://github.com/owner/repo -> repo
 */
export function extractRepoName(url: string): string {
  // Remove .git suffix if present
  let cleaned = url.replace(/\.git$/, '');

  // Extract last part after / or :
  const parts = cleaned.split(/[/:]/);
  const repoName = parts[parts.length - 1];

  if (!repoName) {
    throw new Error(`Could not extract repository name from URL: ${url}`);
  }

  return repoName;
}

/**
 * Extract repository owner from Git URL
 */
export function extractRepoOwner(url: string): string {
  // Remove .git suffix if present
  let cleaned = url.replace(/\.git$/, '');

  // Extract parts
  const parts = cleaned.split(/[/:]/);

  // Owner is second to last
  const owner = parts[parts.length - 2];

  if (!owner) {
    throw new Error(`Could not extract repository owner from URL: ${url}`);
  }

  return owner;
}

/**
 * Generate branch name from issue number
 */
export function generateBranchName(issueNumber: number, prefix: string = 'feature'): string {
  const timestamp = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  return `${prefix}/issue-${issueNumber}-${timestamp}`;
}

/**
 * Validate branch name format
 */
export function validateBranchName(branchName: string): boolean {
  // Git branch name rules:
  // - Cannot start with '/'
  // - Cannot contain '..' or '@{'
  // - Cannot end with '/'
  // - Cannot contain spaces
  const invalidPatterns = [
    /^\//,           // starts with /
    /\/$/,           // ends with /
    /\.\./,          // contains ..
    /@\{/,           // contains @{
    /\s/,            // contains whitespace
    /[\x00-\x1f\x7f]/, // contains control characters
    /[~^:?*\[\\]/    // contains invalid characters
  ];

  return !invalidPatterns.some(pattern => pattern.test(branchName));
}

/**
 * Generate worktree path from issue number
 */
export function generateWorktreePath(baseDir: string, issueNumber: number): string {
  const branchName = generateBranchName(issueNumber).replace(/\//g, '-');
  return path.join(baseDir, `feature-${issueNumber}`);
}

// ============================================================================
// Path Utilities
// ============================================================================

/**
 * Check if path is within allowed directory (for hook validation)
 */
export function isPathAllowed(filePath: string, allowedPaths: string[], baseDir: string): boolean {
  try {
    const absolutePath = path.resolve(baseDir, filePath);

    for (const allowedPath of allowedPaths) {
      const absoluteAllowed = path.resolve(baseDir, allowedPath);
      const relative = path.relative(absoluteAllowed, absolutePath);

      // If relative path doesn't start with '..' then it's inside allowed path
      if (!relative.startsWith('..') && !path.isAbsolute(relative)) {
        return true;
      }
    }

    return false;
  } catch (error) {
    return false;
  }
}

/**
 * Normalize path (resolve relative paths, remove . and ..)
 */
export function normalizePath(filePath: string, baseDir: string = process.cwd()): string {
  return path.resolve(baseDir, filePath);
}

// ============================================================================
// Time Utilities
// ============================================================================

/**
 * Get current ISO 8601 timestamp
 */
export function getCurrentTimestamp(): string {
  return new Date().toISOString();
}

/**
 * Calculate duration in seconds between two ISO timestamps
 */
export function calculateDuration(startTime: string, endTime: string): number {
  const start = new Date(startTime).getTime();
  const end = new Date(endTime).getTime();
  return Math.floor((end - start) / 1000);
}

/**
 * Format duration in human-readable format
 */
export function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}s`;
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;

  if (minutes < 60) {
    return `${minutes}m ${remainingSeconds}s`;
  }

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;

  return `${hours}h ${remainingMinutes}m ${remainingSeconds}s`;
}

// ============================================================================
// Error Handling
// ============================================================================

/**
 * Safe JSON parse with fallback
 */
export function safeJsonParse<T>(json: string, fallback: T): T {
  try {
    return JSON.parse(json) as T;
  } catch (error) {
    return fallback;
  }
}

/**
 * Extract error message from unknown error type
 */
export function extractErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'string') {
    return error;
  }
  return 'Unknown error occurred';
}

// ============================================================================
// Environment Variables
// ============================================================================

/**
 * Get required environment variable
 */
export function getRequiredEnv(key: string): string {
  const value = process.env[key];
  if (!value) {
    throw new ConfigurationError(
      `Required environment variable not set: ${key}`,
      { key }
    );
  }
  return value;
}

/**
 * Get optional environment variable with default
 */
export function getOptionalEnv(key: string, defaultValue: string): string {
  return process.env[key] || defaultValue;
}

/**
 * Validate all required environment variables
 */
export function validateEnvironment(): { valid: boolean; missing: string[] } {
  const required = ['E2B_API_KEY', 'GITHUB_TOKEN', 'GITHUB_REPO_OWNER', 'GITHUB_REPO_NAME'];
  const missing: string[] = [];

  for (const key of required) {
    if (!process.env[key]) {
      missing.push(key);
    }
  }

  return {
    valid: missing.length === 0,
    missing
  };
}
