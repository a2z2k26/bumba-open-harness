/**
 * Hook: on-design-init-complete
 * Deterministic execution for design-init command
 *
 * This hook handles ALL file system operations after the design-init command
 * collects user configuration. By separating interactive prompts (Claude) from
 * deterministic execution (this script), we ensure reliable, reproducible results.
 *
 * Triggers when: .design/config.json is created/updated by design-init command
 *
 * @version 1.0.0
 * @phase Phase 5 - Two-State Architecture
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// Canonical source paths
const CATALOG_SOURCE = '/home/operator/Bumba-Design/design-catalog-html';
const STORYBOOK_SOURCE = '/home/operator/Bumba-Design/Bumba - Design Components/.storybook';

module.exports = {
  name: 'on-design-init-complete',
  version: '1.0.0',
  description: 'Deterministic file system operations for design-init',
  watch: '.design/config.json',
  debounce: 500,
  enabled: true,
  priority: 10, // Run early

  /**
   * Execute deterministic initialization
   * @param {Object} event - File change event
   * @returns {Object} Execution result
   */
  async execute(event) {
    const { filePath, projectPath } = event;
    const startTime = Date.now();
    const results = {
      success: true,
      steps: [],
      errors: [],
      warnings: []
    };

    process.stderr.write(`[on-design-init-complete] Starting deterministic initialization\n`);
    process.stderr.write(`  Project: ${projectPath}\n`);

    try {
      // Step 1: Read configuration
      const configPath = path.join(projectPath, '.design/config.json');
      if (!fs.existsSync(configPath)) {
        throw new Error(`Config file not found: ${configPath}`);
      }

      const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
      process.stderr.write(`[on-design-init-complete] Loaded config for: ${config.project?.name || 'unknown'}\n`);
      results.steps.push({ name: 'load-config', success: true });

      // Step 2: Create directory structure
      const dirResult = await this.createDirectoryStructure(projectPath, config);
      results.steps.push({ name: 'create-directories', ...dirResult });
      if (!dirResult.success) results.errors.push(dirResult.error);

      // Step 3: Install BUMBA Design Catalog
      const catalogResult = await this.installCatalog(projectPath, config);
      results.steps.push({ name: 'install-catalog', ...catalogResult });
      if (!catalogResult.success) results.warnings.push(catalogResult.error);

      // Step 4: Install Storybook theme (if enabled)
      if (config.storybook?.enabled) {
        const storybookResult = await this.installStorybookTheme(projectPath, config);
        results.steps.push({ name: 'install-storybook', ...storybookResult });
        if (!storybookResult.success) results.warnings.push(storybookResult.error);
      }

      // Step 5: Generate registry files
      const registryResult = await this.generateRegistryFiles(projectPath, config);
      results.steps.push({ name: 'generate-registries', ...registryResult });
      if (!registryResult.success) results.errors.push(registryResult.error);

      // Step 6: Generate metadata.json
      const metadataResult = await this.generateMetadata(projectPath, config);
      results.steps.push({ name: 'generate-metadata', ...metadataResult });
      if (!metadataResult.success) results.errors.push(metadataResult.error);

      // Step 7: Generate README.md
      const readmeResult = await this.generateReadme(projectPath, config);
      results.steps.push({ name: 'generate-readme', ...readmeResult });
      if (!readmeResult.success) results.warnings.push(readmeResult.error);

      // Step 8: Generate .gitignore
      const gitignoreResult = await this.generateGitignore(projectPath, config);
      results.steps.push({ name: 'generate-gitignore', ...gitignoreResult });
      if (!gitignoreResult.success) results.warnings.push(gitignoreResult.error);

      // Step 9: Update package.json scripts and dependencies
      const scriptsResult = await this.updatePackageScripts(projectPath, config);
      results.steps.push({ name: 'update-scripts', ...scriptsResult });
      if (!scriptsResult.success) results.warnings.push(scriptsResult.error);

      // Step 9b: Install npm dependencies (if Storybook enabled and dependencies were added)
      if (config.storybook?.enabled && scriptsResult.success && scriptsResult.dependenciesAdded) {
        const installResult = await this.installDependencies(projectPath, config);
        results.steps.push({ name: 'install-dependencies', ...installResult });
        if (!installResult.success) results.warnings.push(installResult.error);
      }

      // Step 10: Setup Design Bridge Server
      const serverResult = await this.setupDesignBridgeServer(projectPath, config);
      results.steps.push({ name: 'setup-server', ...serverResult });
      if (!serverResult.success) results.warnings.push(serverResult.error);

      // Step 11: Verify structure
      const verifyResult = await this.verifyStructure(projectPath, config);
      results.steps.push({ name: 'verify-structure', ...verifyResult });
      if (!verifyResult.success) results.warnings.push(verifyResult.error);

      // Summary
      const duration = Date.now() - startTime;
      const successCount = results.steps.filter(s => s.success).length;
      const totalCount = results.steps.length;

      process.stderr.write(`[on-design-init-complete] Completed in ${duration}ms\n`);
      process.stderr.write(`  Steps: ${successCount}/${totalCount} successful\n`);
      process.stderr.write(`  Errors: ${results.errors.length}, Warnings: ${results.warnings.length}\n`);

      return {
        success: results.errors.length === 0,
        message: `Initialization complete: ${successCount}/${totalCount} steps successful`,
        duration,
        steps: results.steps,
        errors: results.errors,
        warnings: results.warnings
      };

    } catch (error) {
      process.stderr.write(`[on-design-init-complete] Fatal error: ${error.message}\n`);
      return {
        success: false,
        message: error.message,
        error,
        steps: results.steps
      };
    }
  },

  /**
   * Create complete directory structure
   */
  async createDirectoryStructure(projectPath, config) {
    try {
      const framework = config.project?.framework || 'react';
      const outputPath = config.output?.finalOutputPath || 'src/design-system';
      const layoutsEnabled = config.layouts?.enabled || false;
      const assetsDir = config.layouts?.assetsDir || 'public/design-assets';

      const directories = [
        // Base .design directories
        '.design',
        '.design/tokens',
        '.design/components',
        '.design/extracted-code',
        '.design/assets/fonts',
        '.design/assets/icons',
        '.design/assets/images',
        '.design/backups',
        '.design/logs',

        // Source-agnostic raw data
        '.design/source/tokens/colors',
        '.design/source/tokens/typography',
        '.design/source/tokens/spacing',
        '.design/source/tokens/effects',
        '.design/source/tokens/borderRadius',
        '.design/source/components',
        '.design/source/layouts',

        // Framework-specific extracted code
        `.design/extracted-code/${framework}`,
        `.design/extracted-code/${framework}/tokens`,
        `.design/extracted-code/${framework}/components`,
        '.design/extracted-code/templates',

        // Output directory
        `${outputPath}/tokens`,
        `${outputPath}/components`
      ];

      // Add layout directories if enabled
      if (layoutsEnabled) {
        directories.push(
          '.design/layouts',
          `.design/extracted-code/${framework}/layouts`,
          `${assetsDir}/layouts`,
          `${outputPath}/layouts`
        );
      }

      // Create directories
      let created = 0;
      for (const dir of directories) {
        const fullPath = path.join(projectPath, dir);
        if (!fs.existsSync(fullPath)) {
          fs.mkdirSync(fullPath, { recursive: true });
          created++;
        }
      }

      // Create .gitkeep files
      const gitkeepDirs = [
        '.design/tokens',
        '.design/components',
        '.design/source/tokens/colors',
        '.design/source/tokens/typography',
        '.design/source/tokens/spacing',
        '.design/source/tokens/effects',
        '.design/source/tokens/borderRadius',
        '.design/source/components',
        '.design/source/layouts',
        '.design/assets/fonts',
        '.design/assets/icons',
        '.design/assets/images',
        '.design/backups',
        '.design/logs',
        // Framework-specific extracted code directories
        `.design/extracted-code/${framework}`,
        `.design/extracted-code/${framework}/tokens`,
        `.design/extracted-code/${framework}/components`,
        '.design/extracted-code/templates'
      ];

      if (layoutsEnabled) {
        gitkeepDirs.push(
          '.design/layouts',
          `${assetsDir}/layouts`,
          `.design/extracted-code/${framework}/layouts`
        );
      }

      for (const dir of gitkeepDirs) {
        const gitkeepPath = path.join(projectPath, dir, '.gitkeep');
        if (!fs.existsSync(gitkeepPath)) {
          fs.writeFileSync(gitkeepPath, '');
        }
      }

      process.stderr.write(`[on-design-init-complete] Created ${created} directories\n`);
      return { success: true, created };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Install BUMBA Design Catalog
   */
  async installCatalog(projectPath, config) {
    try {
      const targetPath = path.join(projectPath, '.design/catalog');

      // Check if source exists
      if (!fs.existsSync(CATALOG_SOURCE)) {
        return { success: false, error: `Catalog source not found: ${CATALOG_SOURCE}` };
      }

      // Create target directory
      if (!fs.existsSync(targetPath)) {
        fs.mkdirSync(targetPath, { recursive: true });
      }

      // Use rsync if available, fall back to recursive copy
      try {
        execSync(`rsync -av --exclude='.git' "${CATALOG_SOURCE}/" "${targetPath}/"`, {
          stdio: 'pipe',
          cwd: projectPath
        });
      } catch (rsyncError) {
        // Fallback: recursive copy
        this.copyDirRecursive(CATALOG_SOURCE, targetPath, ['.git']);
      }

      // Count files copied
      const files = this.countFiles(targetPath);
      process.stderr.write(`[on-design-init-complete] Installed catalog: ${files} files\n`);

      return { success: true, files };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Install Storybook BUMBA theme
   */
  async installStorybookTheme(projectPath, config) {
    try {
      const targetPath = path.join(projectPath, '.storybook');

      // Create target directory
      if (!fs.existsSync(targetPath)) {
        fs.mkdirSync(targetPath, { recursive: true });
      }

      // Theme files to copy (all files from canonical theme)
      const themeFiles = [
        'theme.js',
        'manager.js',
        'preview.jsx',
        'main.js',
        'bumba-manager.css',
        'bumba-preview.css',
        'THEME-README.md',
        'dependencies.json',
        'manifest.json'
      ];

      let copied = 0;
      for (const file of themeFiles) {
        const sourcePath = path.join(STORYBOOK_SOURCE, file);
        const destPath = path.join(targetPath, file);

        if (fs.existsSync(sourcePath)) {
          fs.copyFileSync(sourcePath, destPath);
          copied++;
        }
      }

      process.stderr.write(`[on-design-init-complete] Installed Storybook theme: ${copied} files\n`);
      return { success: true, copied };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Generate registry files
   */
  async generateRegistryFiles(projectPath, config) {
    try {
      const timestamp = new Date().toISOString();
      const outputPath = config.output?.finalOutputPath || 'src/design-system';
      const layoutsEnabled = config.layouts?.enabled || false;

      // Token registry
      const tokenRegistry = {
        version: '1.0.0',
        sources: [],
        categories: {
          colors: { count: 0, tokens: [] },
          typography: { count: 0, tokens: [] },
          spacing: { count: 0, tokens: [] },
          effects: { count: 0, tokens: [] },
          borderRadius: { count: 0, tokens: [] }
        },
        lastUpdated: timestamp
      };
      fs.writeFileSync(
        path.join(projectPath, '.design/tokens/index.json'),
        JSON.stringify(tokenRegistry, null, 2)
      );

      // Internal component registry
      const internalRegistry = {
        version: '1.0.0',
        components: {},
        categories: {},
        stats: { total: 0, extracted: 0, transformed: 0 },
        lastUpdated: timestamp
      };
      fs.writeFileSync(
        path.join(projectPath, '.design/components/registry.json'),
        JSON.stringify(internalRegistry, null, 2)
      );

      // Output component registry
      const outputRegistry = {
        version: '1.0.0',
        generatedAt: timestamp,
        components: {}
      };
      fs.writeFileSync(
        path.join(projectPath, outputPath, 'componentRegistry.json'),
        JSON.stringify(outputRegistry, null, 2)
      );

      // Layout manifest (if layouts enabled)
      if (layoutsEnabled) {
        const layoutManifest = {
          version: '1.0.0',
          generatedAt: timestamp,
          layouts: []
        };
        fs.writeFileSync(
          path.join(projectPath, outputPath, 'layoutManifest.json'),
          JSON.stringify(layoutManifest, null, 2)
        );
      }

      process.stderr.write(`[on-design-init-complete] Generated registry files\n`);
      return { success: true, registries: layoutsEnabled ? 4 : 3 };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Generate metadata.json
   */
  async generateMetadata(projectPath, config) {
    try {
      const metadata = {
        version: '1.0.0',
        figmaFileKey: null,
        figmaFileName: null,
        figmaVersion: null,
        lastSync: null,
        createdAt: new Date().toISOString(),
        initializedBy: 'on-design-init-complete hook',
        tokens: {},
        components: {},
        syncHistory: [],
        transformHistory: []
      };

      fs.writeFileSync(
        path.join(projectPath, '.design/metadata.json'),
        JSON.stringify(metadata, null, 2)
      );

      process.stderr.write(`[on-design-init-complete] Generated metadata.json\n`);
      return { success: true };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Generate README.md
   */
  async generateReadme(projectPath, config) {
    try {
      const framework = config.project?.framework || 'react';
      const typescript = config.project?.typescript ? 'Enabled' : 'Disabled';
      const outputPath = config.output?.finalOutputPath || 'src/design-system';
      const autoSync = config.figma?.autoSync ? 'Enabled' : 'Disabled';
      const storybook = config.storybook?.enabled ? 'Enabled' : 'Disabled';
      const projectName = config.project?.name || path.basename(projectPath);
      const timestamp = new Date().toISOString();

      const readme = `# Design System - ${projectName}

> Auto-generated by Design Bridge on ${timestamp}

This directory contains design tokens and components extracted from Figma and transformed for use in your ${framework} project.

## Directory Structure

- **tokens/** - Raw design tokens extracted from Figma
- **components/** - Component metadata and specifications
- **catalog/** - BUMBA Design Catalog (zero-dependency HTML viewer)
- **extracted-code/** - Transformed code ready for use
- **source/** - Raw extracted data (source-agnostic)
- **assets/** - Design assets (fonts, icons, images)
- **backups/** - Versioned backups
- **logs/** - Sync and transformation logs

## Configuration

| Setting | Value |
|---------|-------|
| **Framework** | ${framework} |
| **TypeScript** | ${typescript} |
| **Output Path** | \`${outputPath}\` |
| **Auto-sync** | ${autoSync} |
| **Storybook** | ${storybook} |

Edit configuration: \`.design/config.json\`

## Quick Start

### View Design Catalog (No Dependencies)
\`\`\`bash
npm run catalog
# or open .design/catalog/index.html directly
\`\`\`

### View in Storybook
\`\`\`bash
npm run storybook
\`\`\`

### Transform Tokens
\`\`\`bash
/transform-${framework}
\`\`\`

## Documentation

For detailed instructions, see the full Design Bridge documentation.

---

**Last updated:** ${timestamp}
**Initialized by:** /design-init command + on-design-init-complete hook
`;

      fs.writeFileSync(
        path.join(projectPath, '.design/README.md'),
        readme
      );

      process.stderr.write(`[on-design-init-complete] Generated README.md\n`);
      return { success: true };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Generate .gitignore files
   */
  async generateGitignore(projectPath, config) {
    try {
      const gitignore = `# Design Bridge .gitignore
# Generated by on-design-init-complete hook

# Log files
logs/*.log
logs/*.txt

# Temporary files
*.tmp
*.temp
.DS_Store
Thumbs.db

# Node modules if any scripts are added
node_modules/

# Environment files
.env
.env.local

# Keep directory structure
!tokens/.gitkeep
!components/.gitkeep
!extracted-code/.gitkeep
!assets/**/.gitkeep
!backups/.gitkeep
!logs/.gitkeep
`;

      fs.writeFileSync(
        path.join(projectPath, '.design/.gitignore'),
        gitignore
      );

      // Append to root .gitignore if exists
      const rootGitignore = path.join(projectPath, '.gitignore');
      const appendContent = `
# Design Bridge logs and temp files
.design/logs/*.log
.design/*.tmp
`;

      if (fs.existsSync(rootGitignore)) {
        const content = fs.readFileSync(rootGitignore, 'utf-8');
        if (!content.includes('.design/logs')) {
          fs.appendFileSync(rootGitignore, appendContent);
        }
      }

      process.stderr.write(`[on-design-init-complete] Generated .gitignore\n`);
      return { success: true };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Update package.json scripts and dependencies
   */
  async updatePackageScripts(projectPath, config) {
    try {
      const packagePath = path.join(projectPath, 'package.json');

      if (!fs.existsSync(packagePath)) {
        return { success: false, error: 'No package.json found' };
      }

      const pkg = JSON.parse(fs.readFileSync(packagePath, 'utf-8'));
      pkg.scripts = pkg.scripts || {};

      // Add catalog scripts
      pkg.scripts['catalog'] = 'open .design/catalog/index.html';
      pkg.scripts['catalog:serve'] = 'node .design/catalog/server.js';

      let dependenciesAdded = false;

      // Add storybook scripts and dependencies if enabled
      if (config.storybook?.enabled) {
        pkg.scripts['storybook'] = pkg.scripts['storybook'] || 'storybook dev -p 6006';
        pkg.scripts['build-storybook'] = pkg.scripts['build-storybook'] || 'storybook build';

        // Read dependencies from dependencies.json
        const depsPath = path.join(projectPath, '.storybook/dependencies.json');
        if (fs.existsSync(depsPath)) {
          const deps = JSON.parse(fs.readFileSync(depsPath, 'utf-8'));

          // Merge devDependencies
          pkg.devDependencies = pkg.devDependencies || {};
          if (deps.devDependencies) {
            Object.assign(pkg.devDependencies, deps.devDependencies);
            dependenciesAdded = true;
          }

          process.stderr.write(`[on-design-init-complete] Added Storybook dependencies to package.json\n`);
        }
      }

      fs.writeFileSync(packagePath, JSON.stringify(pkg, null, 2));

      process.stderr.write(`[on-design-init-complete] Updated package.json scripts and dependencies\n`);
      return { success: true, dependenciesAdded };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Install npm dependencies
   */
  async installDependencies(projectPath, config) {
    try {
      process.stderr.write(`[on-design-init-complete] Installing npm dependencies...\n`);
      process.stderr.write(`[on-design-init-complete] This may take a minute...\n`);

      // Detect package manager
      const hasYarnLock = fs.existsSync(path.join(projectPath, 'yarn.lock'));
      const hasPnpmLock = fs.existsSync(path.join(projectPath, 'pnpm-lock.yaml'));

      let installCommand = 'npm install';
      if (hasPnpmLock) {
        installCommand = 'pnpm install';
      } else if (hasYarnLock) {
        installCommand = 'yarn install';
      }

      process.stderr.write(`[on-design-init-complete] Running: ${installCommand}\n`);

      // Run install command
      execSync(installCommand, {
        cwd: projectPath,
        stdio: 'inherit' // Show output to user
      });

      process.stderr.write(`[on-design-init-complete] Dependencies installed successfully\n`);
      return { success: true, command: installCommand };

    } catch (error) {
      process.stderr.write(`[on-design-init-complete] Failed to install dependencies: ${error.message}\n`);
      return {
        success: false,
        error: error.message,
        note: 'Please run npm install manually'
      };
    }
  },

  /**
   * Verify created structure
   */
  async verifyStructure(projectPath, config) {
    try {
      const requiredPaths = [
        '.design/config.json',
        '.design/metadata.json',
        '.design/README.md',
        '.design/tokens/index.json',
        '.design/components/registry.json',
        '.design/catalog/index.html'
      ];

      // Add Storybook theme files to verification if enabled
      if (config.storybook?.enabled) {
        requiredPaths.push(
          '.storybook/theme.js',
          '.storybook/manager.js',
          '.storybook/preview.jsx',
          '.storybook/main.js',
          '.storybook/bumba-manager.css',
          '.storybook/bumba-preview.css',
          '.storybook/THEME-README.md',
          '.storybook/dependencies.json',
          '.storybook/manifest.json'
        );
      }

      const missing = [];
      for (const p of requiredPaths) {
        if (!fs.existsSync(path.join(projectPath, p))) {
          missing.push(p);
        }
      }

      if (missing.length > 0) {
        return { success: false, error: `Missing: ${missing.join(', ')}`, missing };
      }

      process.stderr.write(`[on-design-init-complete] Verified structure: all ${requiredPaths.length} files present\n`);
      return { success: true, verified: requiredPaths.length };

    } catch (error) {
      return { success: false, error: error.message };
    }
  },

  /**
   * Helper: Recursive directory copy
   */
  copyDirRecursive(src, dest, excludes = []) {
    if (!fs.existsSync(dest)) {
      fs.mkdirSync(dest, { recursive: true });
    }

    const entries = fs.readdirSync(src, { withFileTypes: true });

    for (const entry of entries) {
      if (excludes.includes(entry.name)) continue;

      const srcPath = path.join(src, entry.name);
      const destPath = path.join(dest, entry.name);

      if (entry.isDirectory()) {
        this.copyDirRecursive(srcPath, destPath, excludes);
      } else {
        fs.copyFileSync(srcPath, destPath);
      }
    }
  },

  /**
   * Setup Design Bridge Server
   * Triggers the on-design-server-setup hook to copy server files
   */
  async setupDesignBridgeServer(projectPath, config) {
    try {
      process.stderr.write(`[on-design-init-complete] Setting up Design Bridge Server...\n`);

      const hookPath = path.join(process.env.HOME, '.claude', 'hooks', 'on-design-server-setup.js');

      if (!fs.existsSync(hookPath)) {
        process.stderr.write(`[on-design-init-complete] Server setup hook not found: ${hookPath}\n`);
        return {
          success: false,
          error: 'on-design-server-setup.js hook not found'
        };
      }

      // Execute the server setup hook
      execSync(`node "${hookPath}"`, {
        cwd: projectPath,
        stdio: 'inherit'
      });

      process.stderr.write(`[on-design-init-complete] Design Bridge Server setup complete\n`);

      return { success: true };

    } catch (error) {
      process.stderr.write(`[on-design-init-complete] Server setup error: ${error.message}\n`);
      return {
        success: false,
        error: error.message
      };
    }
  },

  /**
   * Helper: Count files in directory
   */
  countFiles(dir) {
    let count = 0;
    const entries = fs.readdirSync(dir, { withFileTypes: true });

    for (const entry of entries) {
      if (entry.isDirectory()) {
        count += this.countFiles(path.join(dir, entry.name));
      } else {
        count++;
      }
    }

    return count;
  }
};
