/**
 * Bumba Sandbox MCP - MCP Tools Registration Tests
 *
 * Tests that all MCP tools are properly exported and can be registered.
 */

import * as fs from 'fs';
import * as path from 'path';

const PROJECT_ROOT = path.resolve(__dirname, '..');
const SRC_DIR = path.join(PROJECT_ROOT, 'src');

describe('MCP Tool Exports', () => {

  describe('Sandbox Lifecycle Tools', () => {
    let content: string;

    beforeAll(() => {
      content = fs.readFileSync(
        path.join(SRC_DIR, 'tools', 'sandbox-lifecycle.ts'),
        'utf-8'
      );
    });

    test('should export sandboxInit function', () => {
      expect(content).toContain('export async function sandboxInit');
    });

    test('should export sandboxCreate function', () => {
      expect(content).toContain('export async function sandboxCreate');
    });

    test('should export sandboxConnect function', () => {
      expect(content).toContain('export async function sandboxConnect');
    });

    test('should export sandboxKill function', () => {
      expect(content).toContain('export async function sandboxKill');
    });

    test('should export sandboxStatus function', () => {
      expect(content).toContain('export async function sandboxStatus');
    });

    test('should export registerSandbox helper', () => {
      expect(content).toContain('export function registerSandbox');
    });

    test('should export getSandbox helper', () => {
      expect(content).toContain('export function getSandbox');
    });

    test('should export unregisterSandbox helper', () => {
      expect(content).toContain('export function unregisterSandbox');
    });
  });

  describe('File Operations Tools', () => {
    let content: string;

    beforeAll(() => {
      content = fs.readFileSync(
        path.join(SRC_DIR, 'tools', 'file-operations.ts'),
        'utf-8'
      );
    });

    test('should export filesRead function', () => {
      expect(content).toContain('export async function filesRead');
    });

    test('should export filesWrite function', () => {
      expect(content).toContain('export async function filesWrite');
    });

    test('should export filesList function', () => {
      expect(content).toContain('export async function filesList');
    });

    test('should export fileExists function', () => {
      expect(content).toContain('export async function fileExists');
    });

    test('should export fileRemove function', () => {
      expect(content).toContain('export async function fileRemove');
    });
  });

  describe('Command Execution Tools', () => {
    let content: string;

    beforeAll(() => {
      content = fs.readFileSync(
        path.join(SRC_DIR, 'tools', 'command-execution.ts'),
        'utf-8'
      );
    });

    test('should export executeCommand function', () => {
      expect(content).toContain('export async function executeCommand');
    });
  });

  describe('Orchestration Tools', () => {
    let content: string;

    beforeAll(() => {
      content = fs.readFileSync(
        path.join(SRC_DIR, 'tools', 'orchestration.ts'),
        'utf-8'
      );
    });

    test('should export planSandboxAllocation function', () => {
      expect(content).toContain('export async function planSandboxAllocation');
    });

    test('should export spawnSandboxAgent function', () => {
      expect(content).toContain('export async function spawnSandboxAgent');
    });

    test('should export monitorAgents function', () => {
      expect(content).toContain('export async function monitorAgents');
    });

    test('should export handleAgentEvent function', () => {
      expect(content).toContain('export async function handleAgentEvent');
    });

    test('should export optimizeResources function', () => {
      expect(content).toContain('export async function optimizeResources');
    });

    test('should export getCostTracking function', () => {
      expect(content).toContain('export async function getCostTracking');
    });
  });

  describe('Dependency Analysis Tools', () => {
    let content: string;

    beforeAll(() => {
      content = fs.readFileSync(
        path.join(SRC_DIR, 'tools', 'analyze-dependencies.ts'),
        'utf-8'
      );
    });

    test('should export analyzeDependencies function', () => {
      expect(content).toContain('export async function analyzeDependencies');
    });
  });
});

describe('Main Server Tool Registration', () => {
  let serverContent: string;

  beforeAll(() => {
    serverContent = fs.readFileSync(
      path.join(SRC_DIR, 'mcp-servers', 'bumba-sandbox.ts'),
      'utf-8'
    );
  });

  test('should import sandbox lifecycle tools', () => {
    expect(serverContent).toContain("import * as sandboxLifecycle from '../tools/sandbox-lifecycle.js'");
  });

  test('should import file operations tools', () => {
    expect(serverContent).toContain("import * as fileOps from '../tools/file-operations.js'");
  });

  test('should import command execution tools', () => {
    expect(serverContent).toContain("import * as commandExec from '../tools/command-execution.js'");
  });

  test('should import orchestration tools', () => {
    expect(serverContent).toContain("import * as orchestration from '../tools/orchestration.js'");
  });

  test('should import dependency analysis tools', () => {
    expect(serverContent).toContain("import * as depAnalysis from '../tools/analyze-dependencies.js'");
  });

  test('should import MCP SDK Server', () => {
    expect(serverContent).toContain("import { Server } from '@modelcontextprotocol/sdk/server/index.js'");
  });

  test('should import StdioServerTransport', () => {
    expect(serverContent).toContain("import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'");
  });
});

describe('Type Definitions', () => {
  let typesContent: string;

  beforeAll(() => {
    typesContent = fs.readFileSync(
      path.join(SRC_DIR, 'mcp-servers', 'types.ts'),
      'utf-8'
    );
  });

  test('should export BumbaSandboxConfig interface', () => {
    expect(typesContent).toContain('export interface BumbaSandboxConfig');
  });

  test('should export OrchestratorState interface', () => {
    expect(typesContent).toContain('export interface OrchestratorState');
  });

  test('should export SandboxState interface', () => {
    expect(typesContent).toContain('export interface SandboxState');
  });

  test('should export AgentState interface', () => {
    expect(typesContent).toContain('export interface AgentState');
  });

  test('should export IssueState interface', () => {
    expect(typesContent).toContain('export interface IssueState');
  });

  test('should export HookType type', () => {
    expect(typesContent).toContain('export type HookType');
  });

  test('should export OrchestrationStrategy type', () => {
    expect(typesContent).toContain('export type OrchestrationStrategy');
  });

  test('should export ExecutionMode type', () => {
    expect(typesContent).toContain('export type ExecutionMode');
  });
});
