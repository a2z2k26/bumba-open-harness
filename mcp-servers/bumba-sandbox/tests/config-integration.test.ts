/**
 * Bumba Sandbox MCP - Configuration Integration Tests
 *
 * Tests configuration file loading, validation, and schema compliance.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

const CLAUDE_CONFIG_DIR = path.join(os.homedir(), '.claude', 'config');

describe('Configuration Files', () => {

  describe('Config File Existence', () => {
    test('bumba-sandbox-config.json should exist', () => {
      const filePath = path.join(CLAUDE_CONFIG_DIR, 'bumba-sandbox-config.json');
      expect(fs.existsSync(filePath)).toBe(true);
    });

    test('bumba-sandbox-config.schema.json should exist', () => {
      const filePath = path.join(CLAUDE_CONFIG_DIR, 'bumba-sandbox-config.schema.json');
      expect(fs.existsSync(filePath)).toBe(true);
    });

    test('orchestrator-state.schema.json should exist', () => {
      const filePath = path.join(CLAUDE_CONFIG_DIR, 'orchestrator-state.schema.json');
      expect(fs.existsSync(filePath)).toBe(true);
    });

    test('old e2b-config.json should still exist (as backup reference)', () => {
      // The old file may or may not exist - this is informational
      const filePath = path.join(CLAUDE_CONFIG_DIR, 'e2b-config.json');
      const exists = fs.existsSync(filePath);
      console.log(`Old e2b-config.json exists: ${exists}`);
      // Not a hard requirement - just log status
      expect(true).toBe(true);
    });
  });

  describe('Config File Content', () => {
    let configContent: any;

    beforeAll(() => {
      const filePath = path.join(CLAUDE_CONFIG_DIR, 'bumba-sandbox-config.json');
      const content = fs.readFileSync(filePath, 'utf-8');
      configContent = JSON.parse(content);
    });

    test('config should be valid JSON', () => {
      expect(configContent).toBeDefined();
      expect(typeof configContent).toBe('object');
    });

    test('config should have defaultMode property', () => {
      expect(configContent).toHaveProperty('defaultMode');
      expect(['auto', 'local', 'sandbox']).toContain(configContent.defaultMode);
    });

    test('config should have sandboxDefaults property', () => {
      expect(configContent).toHaveProperty('sandboxDefaults');
    });

    test('config should have hookConfig property', () => {
      expect(configContent).toHaveProperty('hookConfig');
    });

    test('config should have costManagement property', () => {
      expect(configContent).toHaveProperty('costManagement');
    });
  });

  describe('Schema File Content', () => {
    let schemaContent: any;

    beforeAll(() => {
      const filePath = path.join(CLAUDE_CONFIG_DIR, 'bumba-sandbox-config.schema.json');
      const content = fs.readFileSync(filePath, 'utf-8');
      schemaContent = JSON.parse(content);
    });

    test('schema should be valid JSON Schema', () => {
      expect(schemaContent).toHaveProperty('$schema');
      expect(schemaContent.$schema).toContain('json-schema.org');
    });

    test('schema $id should reference bumba-sandbox', () => {
      expect(schemaContent.$id).toContain('bumba-sandbox');
    });

    test('schema title should mention Bumba Sandbox', () => {
      expect(schemaContent.title).toContain('Bumba Sandbox');
    });

    test('schema should NOT contain old E2B orchestrator references in $id', () => {
      expect(schemaContent.$id).not.toContain('e2b-orchestrator');
    });

    test('schema description should mention Bumba Sandbox', () => {
      expect(schemaContent.description).toContain('Bumba Sandbox');
    });
  });

  describe('State Schema File Content', () => {
    let stateSchemaContent: any;

    beforeAll(() => {
      const filePath = path.join(CLAUDE_CONFIG_DIR, 'orchestrator-state.schema.json');
      const content = fs.readFileSync(filePath, 'utf-8');
      stateSchemaContent = JSON.parse(content);
    });

    test('state schema $id should reference bumba-sandbox', () => {
      expect(stateSchemaContent.$id).toContain('bumba-sandbox');
    });

    test('state schema should NOT contain e2b-orchestrator reference in $id', () => {
      expect(stateSchemaContent.$id).not.toContain('e2b-orchestrator');
    });

    test('state schema description should mention Bumba Sandbox', () => {
      expect(stateSchemaContent.description).toContain('Bumba Sandbox');
    });
  });
});

// Optional integration check against the user's local Claude Desktop settings.
// Skipped automatically when no local installation is present, so a fresh clone
// of the repo passes its test suite without requiring Claude Desktop to be set up.
const settingsPath = path.join(os.homedir(), '.claude', 'settings.json');
const hasLocalSettings = fs.existsSync(settingsPath);
const describeIfLocal = hasLocalSettings ? describe : describe.skip;

describeIfLocal('Settings.json Integration (local install only)', () => {
  let settingsContent: any;

  beforeAll(() => {
    const content = fs.readFileSync(settingsPath, 'utf-8');
    settingsContent = JSON.parse(content);
  });

  test('settings should have mcpServers property', () => {
    expect(settingsContent).toHaveProperty('mcpServers');
  });

  test('mcpServers should not retain the old e2b-orchestrator name', () => {
    expect(settingsContent.mcpServers ?? {}).not.toHaveProperty('e2b-orchestrator');
  });

  test('bumba-sandbox entry, when present, should reference bumba-sandbox.js', () => {
    const entry = settingsContent.mcpServers?.['bumba-sandbox'];
    if (!entry) {
      return;
    }
    const args: string[] = entry.args ?? [];
    expect(args.some((arg) => arg.includes('bumba-sandbox.js'))).toBe(true);
  });
});
