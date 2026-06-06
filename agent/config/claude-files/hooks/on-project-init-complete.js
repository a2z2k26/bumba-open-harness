/**
 * on-project-init-complete.js
 *
 * Hook triggered when a project is initialized with /project-init
 * Creates the complete E2B Orchestrator directory structure
 *
 * Trigger: .claude/project-config.json is written
 *
 * @module on-project-init-complete
 */

const fs = require('fs');
const path = require('path');

// Source paths for templates
const TEMPLATES_SOURCE = '/home/operator/.claude/templates';
const SCHEMAS_SOURCE = '/home/operator/.claude/config';

module.exports = {
  name: 'on-project-init-complete',
  description: 'Creates E2B Orchestrator project structure when project-config.json is written',
  watch: '.claude/project-config.json',
  enabled: true,
  priority: 10,

  /**
   * Execute the project initialization
   * @param {Object} event - Event data from trigger
   * @param {string} event.filePath - Path to the written file
   * @param {string} event.projectPath - Path to the project root
   */
  async execute(event) {
    const { filePath, projectPath } = event;
    const startTime = Date.now();

    process.stderr.write('[on-project-init-complete] Starting project initialization\n');
    process.stderr.write(`  Project: ${projectPath}\n`);

    const results = {
      steps: [],
      errors: [],
      warnings: []
    };

    try {
      // Step 1: Load project config
      const config = await this.loadConfig(filePath);
      results.steps.push({ name: 'load-config', success: true });
      process.stderr.write(`[on-project-init-complete] Loaded config for: ${config.project?.name || 'unknown'}\n`);

      // Step 2: Create directory structure
      const dirsCreated = await this.createDirectories(projectPath, config);
      results.steps.push({ name: 'create-directories', success: true, created: dirsCreated });
      process.stderr.write(`[on-project-init-complete] Created ${dirsCreated} directories\n`);

      // Step 3: Copy config schemas
      const schemasCopied = await this.copyConfigSchemas(projectPath);
      results.steps.push({ name: 'copy-schemas', success: true, copied: schemasCopied });
      process.stderr.write(`[on-project-init-complete] Copied ${schemasCopied} config schemas\n`);

      // Step 4: Generate config files
      const configsGenerated = await this.generateConfigFiles(projectPath, config);
      results.steps.push({ name: 'generate-configs', success: true, generated: configsGenerated });
      process.stderr.write(`[on-project-init-complete] Generated ${configsGenerated} config files\n`);

      // Step 5: Apply language template
      if (config.project?.template && config.project.template !== 'none') {
        const templateFiles = await this.applyTemplate(projectPath, config);
        results.steps.push({ name: 'apply-template', success: true, files: templateFiles });
        process.stderr.write(`[on-project-init-complete] Applied template: ${config.project.template} (${templateFiles} files)\n`);
      } else {
        results.steps.push({ name: 'apply-template', success: true, skipped: true });
        process.stderr.write(`[on-project-init-complete] Skipped template (none specified)\n`);
      }

      // Step 6: Generate documentation
      const docsGenerated = await this.generateDocumentation(projectPath, config);
      results.steps.push({ name: 'generate-docs', success: true, generated: docsGenerated });
      process.stderr.write(`[on-project-init-complete] Generated ${docsGenerated} documentation files\n`);

      // Step 7: Create .gitignore
      await this.createGitignore(projectPath, config);
      results.steps.push({ name: 'create-gitignore', success: true });
      process.stderr.write(`[on-project-init-complete] Created .gitignore\n`);

      // Step 8: Create .env.template
      await this.createEnvTemplate(projectPath, config);
      results.steps.push({ name: 'create-env-template', success: true });
      process.stderr.write(`[on-project-init-complete] Created .env.template\n`);

      // Step 9: Generate README.md
      await this.generateReadme(projectPath, config);
      results.steps.push({ name: 'generate-readme', success: true });
      process.stderr.write(`[on-project-init-complete] Generated README.md\n`);

      // Step 10: Verify structure
      const verified = await this.verifyStructure(projectPath, config);
      results.steps.push({ name: 'verify-structure', success: verified.success, verified: verified.count });
      if (!verified.success) {
        results.warnings.push(...verified.missing.map(f => `Missing: ${f}`));
      }
      process.stderr.write(`[on-project-init-complete] Verified structure: ${verified.success ? 'all files present' : verified.missing.length + ' missing'}\n`);

      // Step 11: Create Notion dashboard (if enabled)
      let notionDashboardUrl = null;
      if (config.options?.notionDashboard) {
        try {
          notionDashboardUrl = await this.createNotionDashboard(projectPath, config);
          results.steps.push({ name: 'create-notion-dashboard', success: true, url: notionDashboardUrl });
          process.stderr.write(`[on-project-init-complete] Created Notion dashboard: ${notionDashboardUrl}\n`);

          // Step 11.1: Store project metadata in bumba-memory
          try {
            // Note: We need to pass projectEntry and epicEntry IDs, but they're in createNotionDashboard scope
            // We'll update this after refactoring
            await this.storeProjectInMemory(projectPath, config, notionDashboardUrl);
            results.steps.push({ name: 'store-project-memory', success: true });
            process.stderr.write(`[on-project-init-complete] Stored project metadata in bumba-memory\n`);
          } catch (memoryError) {
            results.warnings.push(`Failed to store in bumba-memory: ${memoryError.message}`);
            results.steps.push({ name: 'store-project-memory', success: false, error: memoryError.message });
            process.stderr.write(`[on-project-init-complete] Memory storage error: ${memoryError.message}\n`);
          }
        } catch (error) {
          results.errors.push(`Notion dashboard creation failed: ${error.message}`);
          results.steps.push({ name: 'create-notion-dashboard', success: false, error: error.message });
          process.stderr.write(`[on-project-init-complete] Notion dashboard error: ${error.message}\n`);
        }
      } else {
        results.steps.push({ name: 'create-notion-dashboard', success: true, skipped: true });
      }

      const duration = Date.now() - startTime;
      const successCount = results.steps.filter(s => s.success).length;

      process.stderr.write(`[on-project-init-complete] Completed in ${duration}ms\n`);
      process.stderr.write(`  Steps: ${successCount}/${results.steps.length} successful\n`);
      process.stderr.write(`  Errors: ${results.errors.length}, Warnings: ${results.warnings.length}\n`);

      return {
        hook: this.name,
        duration,
        success: results.errors.length === 0,
        message: `Project initialized: ${successCount}/${results.steps.length} steps successful`,
        steps: results.steps,
        errors: results.errors,
        warnings: results.warnings
      };

    } catch (error) {
      process.stderr.write(`[on-project-init-complete] Error: ${error.message}\n`);
      results.errors.push(error.message);

      return {
        hook: this.name,
        duration: Date.now() - startTime,
        success: false,
        message: `Initialization failed: ${error.message}`,
        steps: results.steps,
        errors: results.errors,
        warnings: results.warnings
      };
    }
  },

  /**
   * Load and parse project config
   */
  async loadConfig(configPath) {
    const content = fs.readFileSync(configPath, 'utf8');
    return JSON.parse(content);
  },

  /**
   * Create the directory structure
   */
  async createDirectories(projectPath, config) {
    const directories = [
      // .claude structure
      '.claude/commands',
      '.claude/mcp-servers',
      '.claude/config',
      '.claude/templates',
      '.claude/hooks',
      // Apps structure (agent-sandboxes pattern)
      'apps/sandbox_agent_working_dir',
      'apps/sandbox_agent_working_dir/temp',
      'apps/sandbox_agent_working_dir/logs',
      'apps/sandbox_agent_working_dir/code',
      // Documentation
      'docs/e2b',
      'docs/prd',
      'docs/specs',
      // Worktrees for parallel development
      'worktrees',
      // Source and tests (template may override)
      'src',
      'tests'
    ];

    let created = 0;
    for (const dir of directories) {
      const fullPath = path.join(projectPath, dir);
      if (!fs.existsSync(fullPath)) {
        fs.mkdirSync(fullPath, { recursive: true });
        created++;
      }
    }

    return created;
  },

  /**
   * Copy config schemas from source
   */
  async copyConfigSchemas(projectPath) {
    const schemas = [
      'bumba-sandbox-config.schema.json',
      'orchestrator-state.schema.json'
    ];

    const targetDir = path.join(projectPath, '.claude', 'config');
    let copied = 0;

    for (const schema of schemas) {
      const sourcePath = path.join(SCHEMAS_SOURCE, schema);
      const targetPath = path.join(targetDir, schema);

      if (fs.existsSync(sourcePath) && !fs.existsSync(targetPath)) {
        fs.copyFileSync(sourcePath, targetPath);
        copied++;
      }
    }

    return copied;
  },

  /**
   * Generate config files
   */
  async generateConfigFiles(projectPath, config) {
    const configDir = path.join(projectPath, '.claude', 'config');
    let generated = 0;

    // bumba-sandbox-config.json
    const sandboxConfig = {
      defaultMode: 'auto',
      maxConcurrent: 10,
      budgetLimit: 100.00,
      autoCleanup: true,
      hookConfig: {
        enabledHooks: {
          preToolUse: true,
          postToolUse: true,
          userPromptSubmit: true,
          stop: true,
          subagentStop: true,
          preCompact: true
        },
        pathRestrictions: [
          'apps/sandbox_agent_working_dir/temp',
          'apps/sandbox_agent_working_dir/code',
          'apps/sandbox_agent_working_dir/logs'
        ]
      },
      autoModeRules: {
        backend: 'sandbox',
        frontend: 'local',
        docs: 'local',
        security: 'sandbox',
        database: 'sandbox',
        default: 'auto'
      },
      sandboxDefaults: {
        template: config.project?.template || 'base',
        timeout: 3600,
        memory: 2048,
        cpu: 2
      },
      notifications: {
        onComplete: true,
        onFailure: true,
        onBudgetAlert: true
      },
      costManagement: {
        alertThresholds: [0.8, 0.9, 1.0],
        optimizationEnabled: true
      }
    };

    const sandboxConfigPath = path.join(configDir, 'bumba-sandbox-config.json');
    if (!fs.existsSync(sandboxConfigPath)) {
      fs.writeFileSync(sandboxConfigPath, JSON.stringify(sandboxConfig, null, 2));
      generated++;
    }

    // orchestrator-state.json
    const stateConfig = {
      version: '1.0.0',
      projectName: config.project?.name || path.basename(projectPath),
      createdAt: new Date().toISOString(),
      activeSandboxes: [],
      completedFeatures: [],
      pendingFeatures: [],
      budgetUsed: 0,
      totalTokens: { input: 0, output: 0 },
      agentHistory: []
    };

    const statePath = path.join(configDir, 'orchestrator-state.json');
    if (!fs.existsSync(statePath)) {
      fs.writeFileSync(statePath, JSON.stringify(stateConfig, null, 2));
      generated++;
    }

    return generated;
  },

  /**
   * Apply language template with variable substitution
   */
  async applyTemplate(projectPath, config) {
    const template = config.project?.template || 'node';
    const templateDir = path.join(TEMPLATES_SOURCE, template);
    const projectName = config.project?.name || path.basename(projectPath);

    if (!fs.existsSync(templateDir)) {
      process.stderr.write(`[on-project-init-complete] Template not found: ${templateDir}\n`);
      return 0;
    }

    // Template variables to substitute
    const variables = {
      '{{PROJECT_NAME}}': projectName,
      '{{project_name}}': projectName.toLowerCase().replace(/-/g, '_'),
      '{{ProjectName}}': projectName.split('-').map(s => s.charAt(0).toUpperCase() + s.slice(1)).join('')
    };

    // Copy template files recursively with substitution
    return this.copyDirRecursive(templateDir, projectPath, variables);
  },

  /**
   * Recursively copy directory with template variable substitution
   */
  copyDirRecursive(src, dest, variables = {}) {
    if (!fs.existsSync(src)) return 0;

    let count = 0;
    const entries = fs.readdirSync(src, { withFileTypes: true });

    // File extensions that should have variable substitution
    const textExtensions = ['.json', '.ts', '.js', '.md', '.toml', '.yaml', '.yml', '.go', '.rs', '.py', '.txt', ''];

    for (const entry of entries) {
      const srcPath = path.join(src, entry.name);
      const destPath = path.join(dest, entry.name);

      if (entry.isDirectory()) {
        if (!fs.existsSync(destPath)) {
          fs.mkdirSync(destPath, { recursive: true });
        }
        count += this.copyDirRecursive(srcPath, destPath, variables);
      } else {
        if (!fs.existsSync(destPath)) {
          const ext = path.extname(entry.name).toLowerCase();

          if (textExtensions.includes(ext) && Object.keys(variables).length > 0) {
            // Read, substitute, write
            let content = fs.readFileSync(srcPath, 'utf8');
            for (const [placeholder, value] of Object.entries(variables)) {
              content = content.split(placeholder).join(value);
            }
            fs.writeFileSync(destPath, content);
          } else {
            // Binary file - just copy
            fs.copyFileSync(srcPath, destPath);
          }
          count++;
        }
      }
    }

    return count;
  },

  /**
   * Generate documentation files
   */
  async generateDocumentation(projectPath, config) {
    const docsDir = path.join(projectPath, 'docs', 'e2b');
    let generated = 0;

    // SETUP.md
    const setupContent = `# E2B Orchestrator Setup

## Prerequisites

- Node.js 18+
- E2B API Key
- Claude API Key (Anthropic)

## Installation

1. Copy environment template:
   \`\`\`bash
   cp .env.template .env
   \`\`\`

2. Add your API keys to \`.env\`:
   \`\`\`
   E2B_API_KEY=your_e2b_key
   ANTHROPIC_API_KEY=your_anthropic_key
   \`\`\`

3. Install dependencies:
   \`\`\`bash
   npm install
   \`\`\`

## Configuration

Edit \`.claude/config/bumba-sandbox-config.json\` to customize:
- Execution modes (local/sandbox/auto)
- Budget limits
- Sandbox defaults
- Hook behavior

## Quick Start

1. Create a PRD: \`/idea-requirements\`
2. Plan sprints: \`/spec-sprints\`
3. Implement: \`/code-parallel #1 #2\`
`;

    const setupPath = path.join(docsDir, 'SETUP.md');
    if (!fs.existsSync(setupPath)) {
      fs.writeFileSync(setupPath, setupContent);
      generated++;
    }

    // COMMANDS.md
    const commandsContent = `# E2B Orchestrator Commands

## Project Management

| Command | Description |
|---------|-------------|
| \`/initialize-project\` | Initialize new project with E2B structure |
| \`/idea-requirements\` | Create PRD document |
| \`/spec-sprints\` | Plan feature sprints |
| \`/spec-issues\` | Generate GitHub issues from specs |

## Feature Implementation

| Command | Description |
|---------|-------------|
| \`/code-parallel\` | Implement multiple features in parallel |
| \`/implement-feature\` | Implement single feature |
| \`/review-implementation\` | Review completed implementation |

## Sandbox Management

| Command | Description |
|---------|-------------|
| \`/list-sandboxes\` | List active sandboxes |
| \`/sandbox-status\` | Check sandbox status |
| \`/cleanup-sandboxes\` | Clean up idle sandboxes |

## Worktree Management

| Command | Description |
|---------|-------------|
| \`/create-worktree\` | Create feature worktree |
| \`/merge-worktree\` | Merge worktree to main |
| \`/list-worktrees\` | List active worktrees |
`;

    const commandsPath = path.join(docsDir, 'COMMANDS.md');
    if (!fs.existsSync(commandsPath)) {
      fs.writeFileSync(commandsPath, commandsContent);
      generated++;
    }

    // MCP_TOOLS_REFERENCE.md
    const mcpContent = `# MCP Tools Reference

## Bumba Sandbox MCP Server

### Tools

#### \`create_sandbox\`
Create a new E2B sandbox for isolated execution.

**Parameters:**
- \`template\` (string): Sandbox template name
- \`timeout\` (number): Timeout in seconds
- \`env\` (object): Environment variables

#### \`execute_in_sandbox\`
Execute code in an existing sandbox.

**Parameters:**
- \`sandbox_id\` (string): Sandbox identifier
- \`code\` (string): Code to execute
- \`language\` (string): Programming language

#### \`destroy_sandbox\`
Terminate and clean up a sandbox.

**Parameters:**
- \`sandbox_id\` (string): Sandbox identifier

### Configuration

Add to \`.mcp.json\`:
\`\`\`json
{
  "mcpServers": {
    "bumba-sandbox": {
      "command": "node",
      "args": [".claude/mcp-servers/bumba-sandbox.js"],
      "env": {
        "E2B_API_KEY": "\${E2B_API_KEY}"
      }
    }
  }
}
\`\`\`
`;

    const mcpPath = path.join(docsDir, 'MCP_TOOLS_REFERENCE.md');
    if (!fs.existsSync(mcpPath)) {
      fs.writeFileSync(mcpPath, mcpContent);
      generated++;
    }

    return generated;
  },

  /**
   * Create .gitignore
   */
  async createGitignore(projectPath, config) {
    const template = config.project?.template || 'node';

    const baseIgnore = `# Dependencies
node_modules/
.pnp
.pnp.js

# Environment
.env
.env.local
.env.*.local

# Build outputs
dist/
build/
out/
.next/

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Logs
*.log
logs/
*.log.*

# E2B Orchestrator
.claude/config/orchestrator-state.json
apps/sandbox_agent_working_dir/temp/*
apps/sandbox_agent_working_dir/logs/*
apps/sandbox_agent_working_dir/code/*
worktrees/*

# Keep directories
!apps/sandbox_agent_working_dir/temp/.gitkeep
!apps/sandbox_agent_working_dir/logs/.gitkeep
!worktrees/.gitkeep
`;

    const templateIgnores = {
      python: `
# Python
__pycache__/
*.py[cod]
*$py.class
.Python
*.so
.venv/
venv/
ENV/
.pytest_cache/
.coverage
htmlcov/
`,
      go: `
# Go
*.exe
*.exe~
*.dll
*.so
*.dylib
*.test
*.out
go.work
`,
      rust: `
# Rust
target/
Cargo.lock
**/*.rs.bk
`
    };

    const content = baseIgnore + (templateIgnores[template] || '');
    const gitignorePath = path.join(projectPath, '.gitignore');

    if (!fs.existsSync(gitignorePath)) {
      fs.writeFileSync(gitignorePath, content);
    }

    // Create .gitkeep files
    const gitkeepDirs = [
      'apps/sandbox_agent_working_dir/temp',
      'apps/sandbox_agent_working_dir/logs',
      'worktrees'
    ];

    for (const dir of gitkeepDirs) {
      const keepPath = path.join(projectPath, dir, '.gitkeep');
      if (!fs.existsSync(keepPath)) {
        fs.writeFileSync(keepPath, '');
      }
    }
  },

  /**
   * Create .env.template
   */
  async createEnvTemplate(projectPath, config) {
    const content = `# E2B Orchestrator Environment Variables
# Copy this file to .env and fill in your values

# Required: E2B API Key
E2B_API_KEY=

# Required: Anthropic API Key (for Claude)
ANTHROPIC_API_KEY=

# Optional: GitHub Token (for PR automation)
GITHUB_TOKEN=

# Optional: Budget limit override (USD)
BUDGET_LIMIT=100

# Optional: Log level (error, warn, info, debug)
LOG_LEVEL=info
`;

    const envPath = path.join(projectPath, '.env.template');
    if (!fs.existsSync(envPath)) {
      fs.writeFileSync(envPath, content);
    }
  },

  /**
   * Generate README.md
   */
  async generateReadme(projectPath, config) {
    const projectName = config.project?.name || path.basename(projectPath);
    const template = config.project?.template || 'node';

    const content = `# ${projectName}

> Generated with Bumba Sandbox Orchestrator

## Quick Start

1. **Setup environment:**
   \`\`\`bash
   cp .env.template .env
   # Edit .env with your API keys
   \`\`\`

2. **Install dependencies:**
   \`\`\`bash
   npm install
   \`\`\`

3. **Start developing:**
   \`\`\`bash
   # Create product requirements
   /idea-requirements

   # Plan development sprints
   /spec-sprints

   # Implement features in parallel
   /code-parallel #1 #2 #3
   \`\`\`

## Project Structure

\`\`\`
${projectName}/
├── .claude/
│   ├── commands/           # Custom slash commands
│   ├── mcp-servers/        # MCP server code
│   ├── config/             # Configuration files
│   └── templates/          # Custom templates
├── apps/
│   └── sandbox_agent_working_dir/
│       ├── temp/           # Temporary files
│       ├── logs/           # Execution logs
│       └── code/           # Agent workspace
├── docs/
│   ├── e2b/               # E2B documentation
│   ├── prd/               # Product requirements
│   └── specs/             # Technical specifications
├── worktrees/             # Git worktrees
├── src/                   # Source code
└── tests/                 # Tests
\`\`\`

## Configuration

- **Sandbox config:** \`.claude/config/bumba-sandbox-config.json\`
- **State tracking:** \`.claude/config/orchestrator-state.json\`
- **Environment:** \`.env\`

## Documentation

- [Setup Guide](docs/e2b/SETUP.md)
- [Commands Reference](docs/e2b/COMMANDS.md)
- [MCP Tools Reference](docs/e2b/MCP_TOOLS_REFERENCE.md)

## License

MIT
`;

    const readmePath = path.join(projectPath, 'README.md');
    if (!fs.existsSync(readmePath)) {
      fs.writeFileSync(readmePath, content);
    }
  },

  /**
   * Verify the structure was created correctly
   */
  async verifyStructure(projectPath, config) {
    const requiredFiles = [
      '.claude/config/bumba-sandbox-config.json',
      '.gitignore',
      '.env.template',
      'README.md',
      'docs/e2b/SETUP.md',
      'docs/e2b/COMMANDS.md'
    ];

    const missing = [];
    for (const file of requiredFiles) {
      const fullPath = path.join(projectPath, file);
      if (!fs.existsSync(fullPath)) {
        missing.push(file);
      }
    }

    return {
      success: missing.length === 0,
      count: requiredFiles.length - missing.length,
      missing
    };
  },

  /**
   * Create Notion project dashboard
   *
   * This method integrates with the bumba-notion plugin to create a project dashboard
   *
   * @param {string} projectPath - Path to the project root
   * @param {Object} config - Project configuration
   * @returns {Promise<string>} URL of the created Notion dashboard
   */
  async createNotionDashboard(projectPath, config) {
    process.stderr.write('[on-project-init-complete] Creating Notion dashboard...\n');

    // Load workspace mapping from bumba-notion plugin
    const workspaceMappingPath = path.join(
      process.env.HOME || process.env.USERPROFILE,
      '.claude',
      'plugins',
      'bumba-notion',
      'config',
      'workspace-mapping.json'
    );

    if (!fs.existsSync(workspaceMappingPath)) {
      throw new Error('Notion workspace mapping not found. Run bumba-notion plugin setup first.');
    }

    const workspaceMapping = JSON.parse(fs.readFileSync(workspaceMappingPath, 'utf8'));
    const { notionToken, masterDatabases, templatePageId } = workspaceMapping;

    if (!notionToken || !masterDatabases || !templatePageId) {
      throw new Error('Invalid workspace mapping configuration');
    }

    if (!config.options?.githubRepo) {
      throw new Error('GitHub repository URL is required for Notion dashboard creation');
    }

    const projectName = config.project?.name || path.basename(projectPath);
    const githubRepo = config.options.githubRepo;

    process.stderr.write(`[on-project-init-complete] Project: ${projectName}, Repo: ${githubRepo}\n`);

    // Step 1: Create entry in Projects Master database
    process.stderr.write('[on-project-init-complete] Creating Projects database entry...\n');
    const projectEntry = await this.notionCreateProjectEntry(
      notionToken,
      masterDatabases.projects,
      projectName,
      githubRepo
    );

    process.stderr.write(`[on-project-init-complete] Projects Master entry created: ${projectEntry.id}\n`);

    // Step 2: Create Epic entry (1:1 with Project)
    process.stderr.write('[on-project-init-complete] Creating Epic entry...\n');
    const epicEntry = await this.notionCreateEpicEntry(
      notionToken,
      masterDatabases.epics,
      projectName,
      projectEntry.id,
      githubRepo
    );

    process.stderr.write(`[on-project-init-complete] Epic entry created: ${epicEntry.id}\n`);

    // Step 3: Link Epic to Project
    process.stderr.write('[on-project-init-complete] Linking Epic to Project...\n');
    await this.notionLinkEpicToProject(
      notionToken,
      projectEntry.id,
      epicEntry.id
    );

    process.stderr.write('[on-project-init-complete] Epic linked to Project\n');

    // Step 4: Wait for Notion Agent to provision dashboard
    process.stderr.write('[on-project-init-complete] Waiting for BUMBA Project Provisioner agent...\n');
    process.stderr.write('[on-project-init-complete] The agent will duplicate the template and set Dashboard Page URL\n');

    const dashboardUrl = await this.pollForDashboardUrl(
      notionToken,
      projectEntry.id,
      60000  // Wait up to 60 seconds
    );

    if (!dashboardUrl) {
      process.stderr.write('[on-project-init-complete] Warning: Dashboard URL not set by Agent within timeout\n');
      process.stderr.write('[on-project-init-complete] The agent may still be running. Check Notion for the dashboard.\n');
      process.stderr.write('[on-project-init-complete] You can find it in Projects Master database\n');
      return null;
    }

    process.stderr.write(`[on-project-init-complete] Dashboard provisioned: ${dashboardUrl}\n`);

    // Step 5: Store project metadata in bumba-memory
    process.stderr.write('[on-project-init-complete] Storing project metadata in bumba-memory...\n');
    await this.storeProjectInMemory(projectPath, config, {
      dashboardUrl,
      projectEntryId: projectEntry.id,
      epicEntryId: epicEntry.id
    });
    process.stderr.write('[on-project-init-complete] Project metadata stored\n');

    return dashboardUrl;
  },

  /**
   * Poll for Dashboard Page URL to be set by the Notion Agent
   *
   * The BUMBA Project Provisioner agent duplicates the template and sets
   * the "Dashboard Page" property on the project entry.
   *
   * @param {string} token - Notion API token
   * @param {string} projectEntryId - ID of the project entry in Projects Master
   * @param {number} timeoutMs - Maximum time to wait in milliseconds
   * @returns {Promise<string|null>} Dashboard URL or null if timeout
   */
  async pollForDashboardUrl(token, projectEntryId, timeoutMs = 60000) {
    const startTime = Date.now();
    const pollInterval = 2000;  // Check every 2 seconds
    let attempts = 0;

    while (Date.now() - startTime < timeoutMs) {
      attempts++;

      try {
        // Get the project entry page
        const projectEntry = await this.notionApiRequest(
          token,
          'GET',
          `/v1/pages/${projectEntryId}`
        );

        // Check if Dashboard Page property is set
        const dashboardPageProp = projectEntry.properties['Dashboard Page'];

        if (dashboardPageProp && dashboardPageProp.url) {
          process.stderr.write(`[on-project-init-complete] Dashboard URL found after ${attempts} attempts (${Math.round((Date.now() - startTime) / 1000)}s)\n`);
          return dashboardPageProp.url;
        }

        // Wait before next poll
        if (attempts % 5 === 0) {
          process.stderr.write(`[on-project-init-complete] Still waiting... (${Math.round((Date.now() - startTime) / 1000)}s elapsed)\n`);
        }
        await new Promise(resolve => setTimeout(resolve, pollInterval));
      } catch (error) {
        process.stderr.write(`[on-project-init-complete] Error polling for dashboard URL: ${error.message}\n`);
        // Continue polling despite errors
        await new Promise(resolve => setTimeout(resolve, pollInterval));
      }
    }

    process.stderr.write(`[on-project-init-complete] Timeout after ${Math.round(timeoutMs / 1000)}s\n`);
    return null;  // Timeout
  },

  /**
   * Duplicate template page as a child of a parent page (Projects Master entry)
   *
   * @deprecated This method is no longer used. The Notion Agent handles template duplication.
   */
  async notionDuplicateTemplateAsChild(token, templatePageId, parentPageId, newTitle) {
    // Get template page blocks
    const templateBlocks = await this.notionApiRequest(token, 'GET', `/v1/blocks/${templatePageId}/children`);

    // Create new page as child of the parent (Projects Master entry)
    const newPage = await this.notionApiRequest(token, 'POST', '/v1/pages', {
      parent: {
        type: 'page_id',
        page_id: parentPageId
      },
      properties: {
        title: {
          title: [
            {
              text: {
                content: newTitle
              }
            }
          ]
        }
      }
    });

    // Copy blocks from template to new page
    if (templateBlocks.results && templateBlocks.results.length > 0) {
      // Filter and clean blocks for copying
      const blocksToAdd = templateBlocks.results.map(block => {
        // Remove metadata fields that shouldn't be copied
        const { id, created_time, last_edited_time, created_by, last_edited_by, has_children, archived, ...cleanBlock } = block;
        return cleanBlock;
      });

      // Add blocks in batches (Notion API limit is 100 blocks per request)
      const batchSize = 100;
      for (let i = 0; i < blocksToAdd.length; i += batchSize) {
        const batch = blocksToAdd.slice(i, i + batchSize);
        await this.notionApiRequest(token, 'PATCH', `/v1/blocks/${newPage.id}/children`, {
          children: batch
        });
      }
    }

    return newPage;
  },

  /**
   * Duplicate a Notion page using the Notion API
   */
  async notionDuplicatePage(token, pageId, newTitle) {
    const https = require('https');

    // First, get the template page content
    const pageContent = await this.notionApiRequest(token, 'GET', `/v1/pages/${pageId}`);

    // Create a new page with the same parent
    const newPage = await this.notionApiRequest(token, 'POST', '/v1/pages', {
      parent: pageContent.parent,
      properties: {
        title: {
          title: [
            {
              text: {
                content: newTitle
              }
            }
          ]
        }
      }
    });

    // Copy blocks from template to new page
    const templateBlocks = await this.notionApiRequest(token, 'GET', `/v1/blocks/${pageId}/children`);

    if (templateBlocks.results && templateBlocks.results.length > 0) {
      await this.notionApiRequest(token, 'PATCH', `/v1/blocks/${newPage.id}/children`, {
        children: templateBlocks.results.map(block => {
          // Remove id and other metadata that shouldn't be copied
          const { id, created_time, last_edited_time, has_children, archived, ...cleanBlock } = block;
          return cleanBlock;
        })
      });
    }

    return newPage;
  },

  /**
   * Create an entry in the Projects Master database
   */
  async notionCreateProjectEntry(token, databaseId, projectName, githubRepo) {
    return await this.notionApiRequest(token, 'POST', '/v1/pages', {
      parent: {
        database_id: databaseId
      },
      properties: {
        'Project / Dashboard Name': {
          title: [
            {
              text: {
                content: projectName
              }
            }
          ]
        },
        'Start Date': {
          date: {
            start: new Date().toISOString().split('T')[0]
          }
        },
        'Status': {
          status: {
            name: 'Active'
          }
        }
      }
    });
  },

  /**
   * Create an entry in the Epics Master database
   * Epic is 1:1 with Project for data integrity
   */
  async notionCreateEpicEntry(token, databaseId, epicName, projectId, githubRepo) {
    return await this.notionApiRequest(token, 'POST', '/v1/pages', {
      parent: {
        database_id: databaseId
      },
      properties: {
        'Epic Name': {
          title: [
            {
              text: {
                content: epicName
              }
            }
          ]
        },
        'Project': {
          relation: [
            {
              id: projectId
            }
          ]
        },
        'Status': {
          select: {
            name: 'active'
          }
        },
        'GitHub Repo': {
          url: githubRepo
        }
      }
    });
  },

  /**
   * Link Epic to Project by updating Project's Epic relation
   */
  async notionLinkEpicToProject(token, projectId, epicId) {
    return await this.notionApiRequest(token, 'PATCH', `/v1/pages/${projectId}`, {
      properties: {
        'Epic': {
          relation: [
            {
              id: epicId
            }
          ]
        }
      }
    });
  },

  /**
   * Helper method to make Notion API requests
   */
  async notionApiRequest(token, method, endpoint, body = null) {
    const https = require('https');

    return new Promise((resolve, reject) => {
      const options = {
        hostname: 'api.notion.com',
        port: 443,
        path: endpoint,
        method: method,
        headers: {
          'Authorization': `Bearer ${token}`,
          'Notion-Version': '2022-06-28',
          'Content-Type': 'application/json'
        }
      };

      const req = https.request(options, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            const parsed = JSON.parse(data);
            if (res.statusCode >= 200 && res.statusCode < 300) {
              resolve(parsed);
            } else {
              reject(new Error(`Notion API error (${res.statusCode}): ${parsed.message || data}`));
            }
          } catch (error) {
            reject(new Error(`Failed to parse Notion API response: ${error.message}`));
          }
        });
      });

      req.on('error', (error) => {
        reject(new Error(`Notion API request failed: ${error.message}`));
      });

      if (body) {
        req.write(JSON.stringify(body));
      }

      req.end();
    });
  },

  /**
   * Store project metadata in bumba-memory MCP
   *
   * Stores project information for global access by commands like /sync-github
   *
   * @param {string} projectPath - Path to the project root
   * @param {Object} config - Project configuration
   * @param {Object} notionData - Notion dashboard data (dashboardUrl, projectEntryId, epicEntryId)
   */
  async storeProjectInMemory(projectPath, config, notionData) {
    process.stderr.write('[on-project-init-complete] Storing project metadata in bumba-memory...\n');

    const projectName = config.project?.name || path.basename(projectPath);
    const projectSlug = projectName.toLowerCase().replace(/\s+/g, '-');
    const githubRepo = config.options?.githubRepo || '';

    // Handle both old (string) and new (object) format
    const dashboardUrl = typeof notionData === 'string' ? notionData : notionData.dashboardUrl;
    const projectEntryId = typeof notionData === 'object' ? notionData.projectEntryId : null;
    const epicEntryId = typeof notionData === 'object' ? notionData.epicEntryId : null;

    // Extract dashboard page ID from URL
    // Format: https://notion.so/abc123... or https://notion.so/Title-abc123...
    const dashboardPageId = dashboardUrl ? dashboardUrl.split('/').pop().replace(/-/g, '') : null;

    // Load workspace mapping for database IDs
    const workspaceMappingPath = path.join(
      process.env.HOME || process.env.USERPROFILE,
      '.claude',
      'plugins',
      'bumba-notion',
      'config',
      'workspace-mapping.json'
    );

    const workspaceMapping = JSON.parse(fs.readFileSync(workspaceMappingPath, 'utf8'));

    // Prepare project metadata
    const projectMetadata = {
      projectName: projectName,
      projectSlug: projectSlug,
      githubRepoUrl: githubRepo,
      dashboardPageId: dashboardPageId,
      dashboardUrl: dashboardUrl,
      projectMasterEntryId: projectEntryId,
      epicMasterEntryId: epicEntryId,
      localPath: projectPath,
      createdAt: new Date().toISOString(),
      notionDatabases: {
        tasks: workspaceMapping.masterDatabases.tasks,
        epics: workspaceMapping.masterDatabases.epics,
        sprints: workspaceMapping.masterDatabases.sprints,
        projects: workspaceMapping.masterDatabases.projects
      },
      template: config.project?.template || 'none',
      features: {
        gitInit: config.options?.gitInit || false,
        autoSandbox: config.options?.autoSandbox || false,
        githubIntegration: config.options?.githubIntegration || false,
        notionDashboard: config.options?.notionDashboard || false
      }
    };

    // Store project metadata using bumba-memory MCP
    // Key format: bumba-notion:project:{slug}
    const contextKey = `bumba-notion:project:${projectSlug}`;

    process.stderr.write(`[on-project-init-complete] Storing with key: ${contextKey}\n`);

    // Note: This will be executed by Claude Code which has access to MCP tools
    // We document the expected MCP call here
    const mcpStoreCommand = {
      tool: 'mcp__bumba-memory__store_context',
      parameters: {
        key: contextKey,
        value: projectMetadata,
        ttl: 0 // Never expire
      }
    };

    // Since we're in a hook, we need to execute this via child process or document it
    // For now, we'll create a marker file that indicates MCP storage is needed
    const stateDir = path.join(
      process.env.HOME || process.env.USERPROFILE,
      '.claude',
      'plugins',
      'bumba-notion',
      'state'
    );

    if (!fs.existsSync(stateDir)) {
      fs.mkdirSync(stateDir, { recursive: true });
    }

    // Store locally as backup and for reference
    const localStatePath = path.join(stateDir, `project-${projectSlug}.json`);
    fs.writeFileSync(localStatePath, JSON.stringify({
      ...projectMetadata,
      mcpKey: contextKey,
      storedAt: new Date().toISOString()
    }, null, 2));

    process.stderr.write(`[on-project-init-complete] Project metadata saved to: ${localStatePath}\n`);
    process.stderr.write(`[on-project-init-complete] MCP key: ${contextKey}\n`);

    // Also update global project index
    await this.updateProjectIndex(projectSlug, githubRepo);

    return {
      contextKey,
      projectSlug,
      localStatePath
    };
  },

  /**
   * Update the global project index in bumba-memory
   *
   * Maintains a list of all projects for easy discovery
   *
   * @param {string} projectSlug - Project slug to add
   * @param {string} githubRepo - GitHub repository URL
   */
  async updateProjectIndex(projectSlug, githubRepo) {
    const stateDir = path.join(
      process.env.HOME || process.env.USERPROFILE,
      '.claude',
      'plugins',
      'bumba-notion',
      'state'
    );

    const indexPath = path.join(stateDir, 'projects-index.json');

    let index = {
      projects: [],
      byRepo: {},
      lastUpdated: null
    };

    // Load existing index if present
    if (fs.existsSync(indexPath)) {
      try {
        index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));
      } catch (error) {
        process.stderr.write('[on-project-init-complete] Failed to load project index: ' + error.message + '\n');
      }
    }

    // Add project if not already in index
    if (!index.projects.includes(projectSlug)) {
      index.projects.push(projectSlug);
    }

    // Map GitHub repo to project slug
    if (githubRepo) {
      index.byRepo[githubRepo] = projectSlug;
    }

    index.lastUpdated = new Date().toISOString();

    // Save updated index
    fs.writeFileSync(indexPath, JSON.stringify(index, null, 2));

    process.stderr.write(`[on-project-init-complete] Updated project index: ${index.projects.length} projects\n`);

    // MCP storage for global index
    const mcpIndexKey = 'bumba-notion:projects:index';
    process.stderr.write(`[on-project-init-complete] MCP index key: ${mcpIndexKey}\n`);

    return index;
  }
};
