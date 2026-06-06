/**
 * Hook System Core Infrastructure
 * Adapted from agent-sandboxes hooks.py - Provides security and observability for agents
 *
 * Implements 6 hook types:
 * - PreToolUse: Path validation before tool execution
 * - PostToolUse: Result logging after tool execution
 * - UserPromptSubmit: User prompt logging
 * - Stop: Cost/token tracking on agent completion
 * - SubagentStop: Task tool monitoring
 * - PreCompact: Context window management
 */

import * as path from 'path';
import { HookType, HookResult, PreToolUseData, PostToolUseData, StopData } from './types';
import { AgentLogger } from './logger';
import { isPathAllowed } from './utils';

// ============================================================================
// Hook Factory Function Pattern (from agent-sandboxes)
// ============================================================================

export interface HookContext {
  agentId: string;
  issueNumber: number;
  logger: AgentLogger;
  config: HookConfiguration;
}

export interface HookConfiguration {
  enabled: boolean;
  enabledHooks: HookType[];
  pathRestrictions: {
    enabled: boolean;
    allowedPaths: string[];
    blockedTools: string[];
  };
  logging: {
    logAllToolUse: boolean;
    logPrompts: boolean;
    logCosts: boolean;
  };
  baseDir: string; // Base directory for path validation
}

/**
 * Hook factory function type
 */
export type HookFactory = (context: HookContext) => HookFunction;

/**
 * Hook function type
 */
export type HookFunction = (data: any) => Promise<HookResult>;

// ============================================================================
// PreToolUse Hook - Path Validation (CRITICAL SECURITY)
// ============================================================================

/**
 * PreToolUse hook factory - Validates paths and blocks unauthorized operations
 * This is the PRIMARY security mechanism preventing agents from accessing files outside allowed paths
 */
export function createPreToolUseHook(context: HookContext): HookFunction {
  return async (data: PreToolUseData) => {
    const { tool, params } = data;

    // Skip if path restrictions are disabled
    if (!context.config.pathRestrictions.enabled) {
      return {
        hookType: 'PreToolUse',
        hookSpecificOutput: {
          permissionDecision: 'allow'
        }
      };
    }

    // Block explicitly denied tools
    if (context.config.pathRestrictions.blockedTools.includes(tool)) {
      const reason = `Tool ${tool} is blocked by configuration`;
      await context.logger.logHook('PreToolUse', tool, 'deny', { reason });

      return {
        hookType: 'PreToolUse',
        hookSpecificOutput: {
          permissionDecision: 'deny',
          reason
        }
      };
    }

    // Validate file paths for tools that operate on files
    const filePathParam = extractFilePath(tool, params);

    if (filePathParam) {
      const allowed = isPathAllowed(
        filePathParam,
        context.config.pathRestrictions.allowedPaths,
        context.config.baseDir
      );

      if (!allowed) {
        const reason = `Path '${filePathParam}' is outside allowed directories: ${context.config.pathRestrictions.allowedPaths.join(', ')}`;
        await context.logger.logHook('PreToolUse', tool, 'deny', {
          reason,
          path: filePathParam,
          allowedPaths: context.config.pathRestrictions.allowedPaths
        });

        return {
          hookType: 'PreToolUse',
          hookSpecificOutput: {
            permissionDecision: 'deny',
            reason
          }
        };
      }
    }

    // Log allowed tool use
    await context.logger.logHook('PreToolUse', tool, 'allow', { params });

    return {
      hookType: 'PreToolUse',
      hookSpecificOutput: {
        permissionDecision: 'allow'
      }
    };
  };
}

/**
 * Extract file path from tool parameters
 */
function extractFilePath(tool: string, params: Record<string, any>): string | null {
  // Map of tools to their file path parameter names
  const pathParams: Record<string, string[]> = {
    'Read': ['file_path', 'path'],
    'Write': ['file_path', 'path'],
    'Edit': ['file_path', 'path'],
    'Bash': [], // Bash commands handled separately
    'files_write': ['path'],
    'files_read': ['path'],
    'files_upload': ['path'],
    'files_download': ['path'],
    'file_remove': ['path'],
    'file_rename': ['old_path', 'new_path'],
    'make_directory': ['path']
  };

  const possibleParams = pathParams[tool];
  if (!possibleParams) {
    return null;
  }

  for (const paramName of possibleParams) {
    if (params[paramName]) {
      return params[paramName];
    }
  }

  return null;
}

// ============================================================================
// PostToolUse Hook - Result Logging
// ============================================================================

/**
 * PostToolUse hook factory - Logs all tool execution results
 */
export function createPostToolUseHook(context: HookContext): HookFunction {
  return async (data: PostToolUseData) => {
    if (!context.config.logging.logAllToolUse) {
      return { hookType: 'PostToolUse' };
    }

    const { tool, params, result, error } = data;

    // Log tool execution
    await context.logger.logToolUse(tool, params, result, error);

    // Log detailed info for file operations
    if (tool.startsWith('file_') || ['Read', 'Write', 'Edit'].includes(tool)) {
      const filePath = extractFilePath(tool, params);
      if (filePath) {
        await context.logger.debug(`File operation: ${tool} on ${filePath}`, {
          success: !error,
          error
        });
      }
    }

    return { hookType: 'PostToolUse' };
  };
}

// ============================================================================
// UserPromptSubmit Hook - Prompt Logging
// ============================================================================

/**
 * UserPromptSubmit hook factory - Logs user prompts (optional)
 */
export function createUserPromptSubmitHook(context: HookContext): HookFunction {
  return async (data: { prompt: string }) => {
    if (!context.config.logging.logPrompts) {
      return { hookType: 'UserPromptSubmit' };
    }

    await context.logger.info('User prompt submitted', {
      prompt: data.prompt.substring(0, 200) + (data.prompt.length > 200 ? '...' : '')
    });

    return { hookType: 'UserPromptSubmit' };
  };
}

// ============================================================================
// Stop Hook - Cost/Token Tracking (CRITICAL for budgeting)
// ============================================================================

/**
 * Stop hook factory - Tracks costs and token usage on agent completion
 */
export function createStopHook(context: HookContext): HookFunction {
  return async (data: StopData) => {
    if (!context.config.logging.logCosts) {
      return { hookType: 'Stop' };
    }

    const { reason, inputTokens, outputTokens, totalTokens, totalCost } = data;

    await context.logger.info('Agent stopped', {
      reason,
      inputTokens,
      outputTokens,
      totalTokens,
      totalCost: `$${totalCost.toFixed(4)}`
    });

    // Log detailed cost breakdown
    await context.logger.info('Cost breakdown', {
      inputCost: `$${(totalCost * (inputTokens / totalTokens)).toFixed(4)}`,
      outputCost: `$${(totalCost * (outputTokens / totalTokens)).toFixed(4)}`,
      totalCost: `$${totalCost.toFixed(4)}`
    });

    return {
      hookType: 'Stop',
      hookSpecificOutput: {
        totalCost,
        inputTokens,
        outputTokens
      }
    };
  };
}

// ============================================================================
// SubagentStop Hook - Task Tool Monitoring
// ============================================================================

/**
 * SubagentStop hook factory - Monitors Task tool (subagent) completions
 */
export function createSubagentStopHook(context: HookContext): HookFunction {
  return async (data: { subagentId: string; result: any; error?: string }) => {
    const { subagentId, result, error } = data;

    await context.logger.info('Subagent stopped', {
      subagentId,
      success: !error,
      error
    });

    return { hookType: 'SubagentStop' };
  };
}

// ============================================================================
// PreCompact Hook - Context Window Management
// ============================================================================

/**
 * PreCompact hook factory - Logs context window compaction events
 */
export function createPreCompactHook(context: HookContext): HookFunction {
  return async (data: { beforeSize: number; afterSize: number }) => {
    const { beforeSize, afterSize } = data;
    const reduction = ((beforeSize - afterSize) / beforeSize * 100).toFixed(1);

    await context.logger.info('Context compacted', {
      beforeSize,
      afterSize,
      reduction: `${reduction}%`
    });

    return { hookType: 'PreCompact' };
  };
}

// ============================================================================
// Hook Registration System
// ============================================================================

export interface HookMatcher {
  hooks: HookFunction[];
}

/**
 * Create hooks dictionary for Claude Agent SDK
 * This is the format expected by ClaudeAgentOptions
 */
export function createHooksDict(context: HookContext): Record<HookType, HookMatcher[]> {
  const hooks: Record<HookType, HookMatcher[]> = {
    PreToolUse: [],
    PostToolUse: [],
    UserPromptSubmit: [],
    Stop: [],
    SubagentStop: [],
    PreCompact: []
  };

  // Only register enabled hooks
  const { enabledHooks } = context.config;

  if (enabledHooks.includes('PreToolUse')) {
    hooks.PreToolUse.push({
      hooks: [createPreToolUseHook(context)]
    });
  }

  if (enabledHooks.includes('PostToolUse')) {
    hooks.PostToolUse.push({
      hooks: [createPostToolUseHook(context)]
    });
  }

  if (enabledHooks.includes('UserPromptSubmit')) {
    hooks.UserPromptSubmit.push({
      hooks: [createUserPromptSubmitHook(context)]
    });
  }

  if (enabledHooks.includes('Stop')) {
    hooks.Stop.push({
      hooks: [createStopHook(context)]
    });
  }

  if (enabledHooks.includes('SubagentStop')) {
    hooks.SubagentStop.push({
      hooks: [createSubagentStopHook(context)]
    });
  }

  if (enabledHooks.includes('PreCompact')) {
    hooks.PreCompact.push({
      hooks: [createPreCompactHook(context)]
    });
  }

  return hooks;
}

// ============================================================================
// Hook Testing & Validation
// ============================================================================

/**
 * Test PreToolUse hook with a file path
 */
export async function testPathValidation(
  context: HookContext,
  tool: string,
  filePath: string
): Promise<{ allowed: boolean; reason?: string }> {
  const hook = createPreToolUseHook(context);
  const result = await hook({
    tool,
    params: { file_path: filePath }
  });

  return {
    allowed: result.hookSpecificOutput?.permissionDecision === 'allow',
    reason: result.hookSpecificOutput?.reason
  };
}

/**
 * Validate hook configuration
 */
export function validateHookConfig(config: HookConfiguration): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  // Validate enabled hooks
  const validHooks: HookType[] = ['PreToolUse', 'PostToolUse', 'UserPromptSubmit', 'Stop', 'SubagentStop', 'PreCompact'];
  for (const hook of config.enabledHooks) {
    if (!validHooks.includes(hook)) {
      errors.push(`Invalid hook type: ${hook}`);
    }
  }

  // Validate allowed paths
  if (config.pathRestrictions.enabled) {
    if (config.pathRestrictions.allowedPaths.length === 0) {
      errors.push('Path restrictions enabled but no allowed paths specified');
    }
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

// ============================================================================
// Default Hook Configuration
// ============================================================================

export function getDefaultHookConfig(baseDir: string): HookConfiguration {
  return {
    enabled: true,
    enabledHooks: ['PreToolUse', 'PostToolUse', 'Stop'],
    pathRestrictions: {
      enabled: true,
      allowedPaths: ['temp/'],
      blockedTools: ['Glob', 'Grep', 'NotebookEdit', 'TodoWrite']
    },
    logging: {
      logAllToolUse: true,
      logPrompts: false,
      logCosts: true
    },
    baseDir
  };
}

// ============================================================================
// Hook Statistics
// ============================================================================

export interface HookStatistics {
  totalExecutions: number;
  byType: Record<HookType, { count: number; blocked: number; errors: number }>;
  recentBlocks: Array<{
    agentId: string;
    hookType: HookType;
    tool: string;
    reason: string;
    timestamp: string;
  }>;
}

/**
 * Initialize empty hook statistics
 */
export function initializeHookStats(): HookStatistics {
  return {
    totalExecutions: 0,
    byType: {
      PreToolUse: { count: 0, blocked: 0, errors: 0 },
      PostToolUse: { count: 0, blocked: 0, errors: 0 },
      UserPromptSubmit: { count: 0, blocked: 0, errors: 0 },
      Stop: { count: 0, blocked: 0, errors: 0 },
      SubagentStop: { count: 0, blocked: 0, errors: 0 },
      PreCompact: { count: 0, blocked: 0, errors: 0 }
    },
    recentBlocks: []
  };
}
