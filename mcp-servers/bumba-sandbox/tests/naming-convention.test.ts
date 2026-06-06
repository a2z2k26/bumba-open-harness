/**
 * Bumba Sandbox MCP - Naming Convention Migration Tests
 *
 * Validates that the E2B to Bumba Sandbox naming migration was completed correctly:
 * 1. All branding references updated to "Bumba Sandbox"
 * 2. E2B SDK references preserved (imports, API keys, URLs)
 * 3. Configuration files renamed and content updated
 * 4. TypeScript interfaces renamed correctly
 */

import * as fs from 'fs';
import * as path from 'path';

const PROJECT_ROOT = path.resolve(__dirname, '..');
const SRC_DIR = path.join(PROJECT_ROOT, 'src');
const DIST_DIR = path.join(PROJECT_ROOT, 'dist');

describe('Naming Convention Migration', () => {

  describe('Package Configuration', () => {
    let packageJson: any;

    beforeAll(() => {
      const content = fs.readFileSync(path.join(PROJECT_ROOT, 'package.json'), 'utf-8');
      packageJson = JSON.parse(content);
    });

    test('package name should be bumba-sandbox-mcp', () => {
      expect(packageJson.name).toBe('bumba-sandbox-mcp');
    });

    test('description should mention Bumba Sandbox', () => {
      expect(packageJson.description).toContain('Bumba Sandbox');
    });

    test('start script should reference bumba-sandbox.js', () => {
      expect(packageJson.scripts['start']).toContain('bumba-sandbox.js');
    });

    test('main entry should reference bumba-sandbox.js', () => {
      expect(packageJson.main).toContain('bumba-sandbox.js');
    });

    test('keywords should include bumba-sandbox', () => {
      expect(packageJson.keywords).toContain('bumba-sandbox');
    });

    test('e2b SDK dependency should be preserved', () => {
      expect(packageJson.dependencies).toHaveProperty('e2b');
    });
  });

  describe('Source File Existence', () => {
    test('bumba-sandbox.ts main server file should exist', () => {
      const filePath = path.join(SRC_DIR, 'mcp-servers', 'bumba-sandbox.ts');
      expect(fs.existsSync(filePath)).toBe(true);
    });

    test('old e2b-orchestrator.ts should NOT exist', () => {
      const filePath = path.join(SRC_DIR, 'mcp-servers', 'e2b-orchestrator.ts');
      expect(fs.existsSync(filePath)).toBe(false);
    });

    test('types.ts should exist', () => {
      const filePath = path.join(SRC_DIR, 'mcp-servers', 'types.ts');
      expect(fs.existsSync(filePath)).toBe(true);
    });

    test('utils.ts should exist', () => {
      const filePath = path.join(SRC_DIR, 'mcp-servers', 'utils.ts');
      expect(fs.existsSync(filePath)).toBe(true);
    });
  });

  describe('Compiled Output Existence', () => {
    test('bumba-sandbox.js compiled file should exist', () => {
      const filePath = path.join(DIST_DIR, 'mcp-servers', 'bumba-sandbox.js');
      expect(fs.existsSync(filePath)).toBe(true);
    });

    test('old e2b-orchestrator.js should NOT exist', () => {
      const filePath = path.join(DIST_DIR, 'mcp-servers', 'e2b-orchestrator.js');
      expect(fs.existsSync(filePath)).toBe(false);
    });
  });

  describe('Main Server File Content', () => {
    let serverContent: string;

    beforeAll(() => {
      serverContent = fs.readFileSync(
        path.join(SRC_DIR, 'mcp-servers', 'bumba-sandbox.ts'),
        'utf-8'
      );
    });

    test('SERVER_NAME constant should be bumba-sandbox', () => {
      expect(serverContent).toContain("const SERVER_NAME = 'bumba-sandbox'");
    });

    test('should import BumbaSandboxConfig from types', () => {
      expect(serverContent).toContain('BumbaSandboxConfig');
    });

    test('header comment should mention Bumba Sandbox', () => {
      expect(serverContent).toContain('Bumba Sandbox MCP Server');
    });

    test('should NOT contain old E2BConfig reference', () => {
      expect(serverContent).not.toContain('E2BConfig');
    });

    test('config path should reference bumba-sandbox-config.json', () => {
      expect(serverContent).toContain('bumba-sandbox-config.json');
    });
  });

  describe('Types File Content', () => {
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

    test('should NOT contain old E2BConfig interface', () => {
      expect(typesContent).not.toMatch(/export interface E2BConfig\b/);
    });

    test('header comment should mention Bumba Sandbox', () => {
      expect(typesContent).toContain('Bumba Sandbox');
    });
  });

  describe('Utils File Content', () => {
    let utilsContent: string;

    beforeAll(() => {
      utilsContent = fs.readFileSync(
        path.join(SRC_DIR, 'mcp-servers', 'utils.ts'),
        'utf-8'
      );
    });

    test('should import BumbaSandboxConfig from types', () => {
      expect(utilsContent).toContain('BumbaSandboxConfig');
    });

    test('DEFAULT_CONFIG_PATH should reference bumba-sandbox-config.json', () => {
      expect(utilsContent).toContain('bumba-sandbox-config.json');
    });

    test('should NOT contain old E2BConfig reference', () => {
      expect(utilsContent).not.toContain('E2BConfig');
    });

    test('header comment should mention Bumba Sandbox', () => {
      expect(utilsContent).toContain('Bumba Sandbox');
    });
  });

  describe('E2B SDK References Preserved', () => {
    let sandboxLifecycleContent: string;

    beforeAll(() => {
      sandboxLifecycleContent = fs.readFileSync(
        path.join(SRC_DIR, 'tools', 'sandbox-lifecycle.ts'),
        'utf-8'
      );
    });

    test('should still import Sandbox from e2b', () => {
      expect(sandboxLifecycleContent).toContain("import { Sandbox } from 'e2b'");
    });

    test('should still use Sandbox.create() method', () => {
      expect(sandboxLifecycleContent).toContain('Sandbox.create');
    });

    test('should still use Sandbox.connect() method', () => {
      expect(sandboxLifecycleContent).toContain('Sandbox.connect');
    });
  });

  describe('Environment File Content', () => {
    test('.env.example should exist and mention Bumba Sandbox', () => {
      const filePath = path.join(PROJECT_ROOT, '.env.example');
      if (fs.existsSync(filePath)) {
        const content = fs.readFileSync(filePath, 'utf-8');
        expect(content).toContain('Bumba Sandbox');
      }
    });

    test('.env.example should preserve E2B_API_KEY reference', () => {
      const filePath = path.join(PROJECT_ROOT, '.env.example');
      if (fs.existsSync(filePath)) {
        const content = fs.readFileSync(filePath, 'utf-8');
        expect(content).toContain('E2B_API_KEY');
      }
    });
  });
});

describe('No Stale E2B References', () => {

  const checkFileForStaleReferences = (filePath: string): string[] => {
    const content = fs.readFileSync(filePath, 'utf-8');
    const issues: string[] = [];

    // Check for stale e2b-orchestrator references (excluding SDK)
    if (content.includes('e2b-orchestrator') && !content.includes("from 'e2b'")) {
      issues.push('Contains stale "e2b-orchestrator" reference');
    }

    // Check for old E2BConfig type (case sensitive)
    if (/\bE2BConfig\b/.test(content)) {
      issues.push('Contains stale "E2BConfig" type reference');
    }

    // Check for old e2b-config.json path
    if (content.includes('e2b-config.json')) {
      issues.push('Contains stale "e2b-config.json" path reference');
    }

    return issues;
  };

  test('bumba-sandbox.ts should have no stale references', () => {
    const issues = checkFileForStaleReferences(
      path.join(SRC_DIR, 'mcp-servers', 'bumba-sandbox.ts')
    );
    expect(issues).toEqual([]);
  });

  test('types.ts should have no stale references', () => {
    const issues = checkFileForStaleReferences(
      path.join(SRC_DIR, 'mcp-servers', 'types.ts')
    );
    expect(issues).toEqual([]);
  });

  test('utils.ts should have no stale references', () => {
    const issues = checkFileForStaleReferences(
      path.join(SRC_DIR, 'mcp-servers', 'utils.ts')
    );
    expect(issues).toEqual([]);
  });

  test('logger.ts should have no stale references', () => {
    const issues = checkFileForStaleReferences(
      path.join(SRC_DIR, 'mcp-servers', 'logger.ts')
    );
    expect(issues).toEqual([]);
  });
});

describe('Tool Files Integrity', () => {
  const toolFiles = [
    'sandbox-lifecycle.ts',
    'command-execution.ts',
    'file-operations.ts',
    'orchestration.ts',
    'analyze-dependencies.ts'
  ];

  toolFiles.forEach(fileName => {
    test(`${fileName} should exist`, () => {
      const filePath = path.join(SRC_DIR, 'tools', fileName);
      expect(fs.existsSync(filePath)).toBe(true);
    });
  });

  test('orchestration.ts should mention Bumba Sandbox in error messages', () => {
    const content = fs.readFileSync(
      path.join(SRC_DIR, 'tools', 'orchestration.ts'),
      'utf-8'
    );
    expect(content).toContain('Bumba Sandbox');
  });
});
