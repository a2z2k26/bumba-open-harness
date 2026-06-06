/**
 * Sandbox Command Execution Tool
 * Adapted from agent-sandboxes execute_command tool
 *
 * Provides full-featured command execution with:
 * - Custom shell
 * - Root privilege escalation
 * - Environment variables
 * - Working directory
 * - Timeout
 * - Background execution
 */

import { getSandbox } from './sandbox-lifecycle.js';

// ============================================================================
// execute_command - Full-featured command execution
// ============================================================================

export interface ExecuteCommandArgs {
  sandboxId: string;
  command: string;
  shell?: string;
  root?: boolean;
  env?: Record<string, string>;
  cwd?: string;
  timeout?: number;
  background?: boolean;
}

export interface ExecuteCommandResult {
  stdout: string;
  stderr: string;
  exitCode: number;
  success: boolean;
  duration?: number;
}

/**
 * Execute a command in the sandbox
 * Full parameter support from agent-sandboxes
 */
export async function executeCommand(args: ExecuteCommandArgs): Promise<ExecuteCommandResult> {
  const {
    sandboxId,
    command,
    shell = '/bin/bash',
    root = false,
    env = {},
    cwd,
    timeout = 60,
    background = false,
  } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  const startTime = Date.now();

  try {
    // Build full command with environment variables
    let fullCommand = command;

    // Add environment variables if provided
    if (Object.keys(env).length > 0) {
      const envVars = Object.entries(env)
        .map(([key, value]) => `export ${key}="${value}"`)
        .join('; ');
      fullCommand = `${envVars}; ${command}`;
    }

    // Add working directory change if provided
    if (cwd) {
      fullCommand = `cd "${cwd}" && ${fullCommand}`;
    }

    // Add root privilege if requested
    if (root) {
      fullCommand = `sudo ${fullCommand}`;
    }

    // Execute command
    if (background) {
      // Background execution - fire and forget
      sandbox.commands.run(fullCommand, {
        timeoutMs: timeout * 1000,
      });

      return {
        stdout: '',
        stderr: '',
        exitCode: 0,
        success: true,
        duration: 0,
      };
    } else {
      // Foreground execution - wait for completion
      const result = await sandbox.commands.run(fullCommand, {
        timeoutMs: timeout * 1000,
      });

      const duration = Date.now() - startTime;

      return {
        stdout: result.stdout,
        stderr: result.stderr,
        exitCode: result.exitCode,
        success: result.exitCode === 0,
        duration,
      };
    }
  } catch (error) {
    const duration = Date.now() - startTime;
    const errorMessage = error instanceof Error ? error.message : String(error);

    return {
      stdout: '',
      stderr: errorMessage,
      exitCode: 1,
      success: false,
      duration,
    };
  }
}
