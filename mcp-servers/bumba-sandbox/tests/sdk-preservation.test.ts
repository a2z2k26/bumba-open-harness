/**
 * Bumba Sandbox MCP - E2B SDK Preservation Tests
 *
 * Critical tests to ensure the E2B SDK layer remains intact:
 * - SDK imports are unchanged
 * - Environment variable names are preserved
 * - API methods are called correctly
 */

import * as fs from 'fs';
import * as path from 'path';

const PROJECT_ROOT = path.resolve(__dirname, '..');
const SRC_DIR = path.join(PROJECT_ROOT, 'src');

describe('E2B SDK Import Preservation', () => {

  test('sandbox-lifecycle.ts should import from e2b package', () => {
    const content = fs.readFileSync(
      path.join(SRC_DIR, 'tools', 'sandbox-lifecycle.ts'),
      'utf-8'
    );
    expect(content).toContain("import { Sandbox } from 'e2b'");
  });

  test('e2b import should NOT be changed to bumba-sandbox', () => {
    const content = fs.readFileSync(
      path.join(SRC_DIR, 'tools', 'sandbox-lifecycle.ts'),
      'utf-8'
    );
    expect(content).not.toContain("from 'bumba-sandbox'");
    expect(content).not.toContain("from 'bumba'");
  });
});

describe('E2B SDK Method Usage', () => {
  let sandboxLifecycleContent: string;

  beforeAll(() => {
    sandboxLifecycleContent = fs.readFileSync(
      path.join(SRC_DIR, 'tools', 'sandbox-lifecycle.ts'),
      'utf-8'
    );
  });

  test('should use Sandbox.create() for creating sandboxes', () => {
    expect(sandboxLifecycleContent).toContain('Sandbox.create');
  });

  test('should use Sandbox.connect() for connecting to sandboxes', () => {
    expect(sandboxLifecycleContent).toContain('Sandbox.connect');
  });

  test('should use sandbox.kill() for terminating sandboxes', () => {
    expect(sandboxLifecycleContent).toContain('sandbox.kill()');
  });

  test('should use sandbox.sandboxId property', () => {
    expect(sandboxLifecycleContent).toContain('sandbox.sandboxId');
  });
});

describe('E2B SDK File Operations', () => {
  let fileOpsContent: string;

  beforeAll(() => {
    fileOpsContent = fs.readFileSync(
      path.join(SRC_DIR, 'tools', 'file-operations.ts'),
      'utf-8'
    );
  });

  test('should use sandbox.files.read() for reading files', () => {
    expect(fileOpsContent).toContain('sandbox.files.read');
  });

  test('should use sandbox.files.write() for writing files', () => {
    expect(fileOpsContent).toContain('sandbox.files.write');
  });

  test('should use sandbox.files.list() for listing files', () => {
    expect(fileOpsContent).toContain('sandbox.files.list');
  });
});

describe('E2B SDK Command Execution', () => {
  let commandExecContent: string;

  beforeAll(() => {
    commandExecContent = fs.readFileSync(
      path.join(SRC_DIR, 'tools', 'command-execution.ts'),
      'utf-8'
    );
  });

  test('should use sandbox.commands.run() for running commands', () => {
    // Check for process or command execution
    expect(
      commandExecContent.includes('sandbox.commands') ||
      commandExecContent.includes('sandbox.process')
    ).toBe(true);
  });
});

describe('Environment Variable Preservation', () => {

  test('.env.example should reference E2B_API_KEY (not BUMBA_API_KEY)', () => {
    const filePath = path.join(PROJECT_ROOT, '.env.example');
    const content = fs.readFileSync(filePath, 'utf-8');
    expect(content).toContain('E2B_API_KEY');
    expect(content).not.toContain('BUMBA_API_KEY');
    expect(content).not.toContain('BUMBA_SANDBOX_API_KEY');
  });

  test('.env.example should reference E2B_API_KEY', () => {
    const filePath = path.join(PROJECT_ROOT, '.env.example');
    if (fs.existsSync(filePath)) {
      const content = fs.readFileSync(filePath, 'utf-8');
      expect(content).toContain('E2B_API_KEY');
    }
  });
});

describe('E2B Package Dependency', () => {
  let packageJson: any;

  beforeAll(() => {
    const content = fs.readFileSync(
      path.join(PROJECT_ROOT, 'package.json'),
      'utf-8'
    );
    packageJson = JSON.parse(content);
  });

  test('should have e2b as a dependency', () => {
    expect(packageJson.dependencies).toHaveProperty('e2b');
  });

  test('e2b dependency should be a valid semver version', () => {
    const e2bVersion = packageJson.dependencies.e2b;
    expect(e2bVersion).toMatch(/^\^?\d+\.\d+\.\d+/);
  });

  test('should NOT have bumba-sandbox as a dependency', () => {
    expect(packageJson.dependencies).not.toHaveProperty('bumba-sandbox');
    expect(packageJson.dependencies).not.toHaveProperty('@bumba/sandbox');
  });
});

describe('SDK Comments Preservation', () => {

  test('sandbox-lifecycle.ts should have comment about E2B SDK usage', () => {
    const content = fs.readFileSync(
      path.join(SRC_DIR, 'tools', 'sandbox-lifecycle.ts'),
      'utf-8'
    );
    // Should mention E2B SDK or Bumba Sandbox (E2B SDK) in comments
    expect(
      content.includes('E2B SDK') ||
      content.includes('Bumba Sandbox') ||
      content.includes('e2b')
    ).toBe(true);
  });
});
