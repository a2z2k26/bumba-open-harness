/**
 * Hook: on-component-transform
 * Triggers after a component is transformed to a target framework
 * Auto-generates Storybook stories with checksum guard for conflict detection
 *
 * @version 2.0.0
 * @phase Phase 5 - Two-State Architecture Integration
 *
 * Updates:
 * - Uses TransformStateUpdater from Phase 3 for state management
 * - Uses StoryHashRegistry from Phase 3 for modification detection
 * - Integrates with componentRegistry for component lookup
 * - Checks for cascade sync to avoid duplicate processing
 */
const fs = require('fs').promises;
const path = require('path');

// Frameworks that support Storybook story generation
const STORYBOOK_FRAMEWORKS = ['react', 'vue', 'svelte', 'angular', 'web-components'];

// Frameworks that only have preview (no story generation)
const PREVIEW_ONLY_FRAMEWORKS = ['flutter', 'swiftui', 'jetpack-compose', 'react-native'];

// Import Phase 3 modules for two-state architecture
let TransformStateUpdater, StoryHashRegistry, readComponentRegistry;
try {
  const serverPath = '/home/operator/Bumba-Design/Bumba - Design Components/server';
  const stateUpdaterModule = require(path.join(serverPath, 'transform-state-updater'));
  TransformStateUpdater = stateUpdaterModule.TransformStateUpdater;

  const hashRegistryModule = require(path.join(serverPath, 'story-hash-registry'));
  StoryHashRegistry = hashRegistryModule.StoryHashRegistry;

  const registryReader = require(path.join(serverPath, 'registry-reader'));
  readComponentRegistry = registryReader.readComponentRegistry;
} catch (e) {
  process.stderr.write(`[on-component-transform] Phase 3 modules not available: ${e.message}\n`);
  TransformStateUpdater = null;
  StoryHashRegistry = null;
  readComponentRegistry = null;
}

module.exports = {
  name: 'on-component-transform',
  version: '2.0.0',
  description: 'Auto-generates Storybook stories after component transformation (Phase 5)',
  watch: '.design/extracted-code/**/*',
  debounce: 500,
  enabled: true,
  priority: 100,

  /**
   * Execute the hook after a component is transformed
   * @param {Object} event - Transform event data
   * @param {string} event.componentName - Name of the transformed component
   * @param {string} event.framework - Target framework (react, vue, etc.)
   * @param {string} event.outputPath - Path where component was written
   * @param {string} event.sourceType - Source type (figma, shadcn, nlp)
   * @param {string} event.projectPath - Project root path
   * @returns {Object} Hook result with success status and details
   */
  async execute(event) {
    const { componentName, framework, outputPath, sourceType, projectPath } = event;

    // Validate required parameters
    const validation = this.validateParams(event);
    if (!validation.valid) {
      return {
        success: false,
        message: `Invalid parameters: ${validation.errors.join(', ')}`,
        action: 'skipped'
      };
    }

    process.stderr.write(`[on-component-transform] Component: ${componentName}, Framework: ${framework}\n`);

    // Check if cascade sync is handling this (avoid duplicate processing)
    if (this.isCascadeSyncActive()) {
      process.stderr.write('[on-component-transform] Cascade sync active - skipping duplicate story generation\n');
      return {
        success: true,
        message: 'Skipped - cascade sync handling story generation',
        action: 'skipped-cascade',
        framework
      };
    }

    // Check if framework supports Storybook
    if (!STORYBOOK_FRAMEWORKS.includes(framework)) {
      process.stderr.write(`[on-component-transform] Story generation N/A for ${framework}\n`);
      return {
        success: true,
        message: `Story generation not available for ${framework}`,
        action: 'skipped-unsupported',
        framework
      };
    }

    try {
      // Get component from registry (two-state architecture)
      let component = null;
      let componentId = null;
      if (readComponentRegistry) {
        const registry = await readComponentRegistry(projectPath);
        const result = this.findComponentByName(registry, componentName);
        if (result) {
          component = result.component;
          componentId = result.id;
          process.stderr.write(`[on-component-transform] Found component in registry: ${componentId}\n`);
        }
      }

      if (!component && readComponentRegistry) {
        process.stderr.write(`[on-component-transform] Component "${componentName}" not in registry - proceeding without state tracking\n`);
      }

      // Determine story output path
      const storyPath = this.getStoryPath(outputPath, framework, componentName);

      // Check if story exists
      const storyExists = await this.fileExists(storyPath);

      let storyResult;
      if (storyExists) {
        // Check if story was modified by user (use StoryHashRegistry from Phase 3 if available)
        const modCheck = await this.checkStoryModified(storyPath, projectPath);

        if (modCheck.isModified) {
          // User modified the story - preserve it
          process.stderr.write(`[on-component-transform] Story has user modifications, preserving: ${storyPath}\n`);
          return {
            success: true,
            message: `Story preserved (user modified): ${componentName}`,
            action: 'preserved',
            storyPath,
            reason: modCheck.reason,
            warning: `Story for ${componentName} has been modified. To regenerate, delete the story file or use 'design regenerate-story ${componentName}'.`
          };
        } else {
          // Story is unmodified - regenerate silently
          process.stderr.write(`[on-component-transform] Story unmodified, regenerating: ${storyPath}\n`);
          storyResult = await this.generateStory({
            componentName,
            framework,
            outputPath,
            storyPath,
            sourceType,
            projectPath,
            action: 'regenerated'
          });
        }
      } else {
        // No existing story - generate new
        process.stderr.write(`[on-component-transform] Generating new story: ${storyPath}\n`);
        storyResult = await this.generateStory({
          componentName,
          framework,
          outputPath,
          storyPath,
          sourceType,
          projectPath,
          action: 'generated'
        });
      }

      // Update component state using TransformStateUpdater (Phase 3)
      if (storyResult.success && componentId && TransformStateUpdater) {
        try {
          const stateUpdater = new TransformStateUpdater({ projectPath });
          await stateUpdater.markTransformed(componentId, {
            framework,
            codePath: outputPath,
            storyPath: storyResult.storyPath
          });
          process.stderr.write(`[on-component-transform] Updated transform state for: ${componentId}\n`);
        } catch (stateError) {
          process.stderr.write(`[on-component-transform] State update failed: ${stateError.message}\n`);
          // Don't fail the hook - story was generated successfully
        }
      }

      return storyResult;

    } catch (error) {
      process.stderr.write(`[on-component-transform] Error: ${error.message}\n`);
      return {
        success: false,
        message: error.message,
        action: 'error',
        error
      };
    }
  },

  /**
   * Check if cascade sync is currently active
   * Prevents duplicate processing when SyncCascade handles story generation
   * @returns {boolean} True if cascade sync is active
   */
  isCascadeSyncActive() {
    return process.env.DESIGN_BRIDGE_CASCADE_ACTIVE === 'true';
  },

  /**
   * Find component by name in registry
   * @param {Object} registry - Component registry
   * @param {string} name - Component name to find
   * @returns {Object|null} Component and ID if found
   */
  findComponentByName(registry, name) {
    if (!registry || !registry.components) return null;

    for (const [id, component] of Object.entries(registry.components)) {
      if (component.name === name) {
        return { id, component };
      }
    }
    return null;
  },

  /**
   * Validate required event parameters
   * @param {Object} event - Event data
   * @returns {Object} Validation result
   */
  validateParams(event) {
    const errors = [];

    if (!event.componentName) {
      errors.push('missing componentName');
    }

    if (!event.framework) {
      errors.push('missing framework');
    }

    if (!event.outputPath) {
      errors.push('missing outputPath');
    }

    return {
      valid: errors.length === 0,
      errors
    };
  },

  /**
   * Determine the story file path based on component output path
   * @param {string} componentPath - Path to transformed component
   * @param {string} framework - Target framework
   * @param {string} componentName - Component name
   * @returns {string} Story file path
   */
  getStoryPath(componentPath, framework, componentName) {
    const dir = path.dirname(componentPath);
    const ext = this.getStoryExtension(framework);
    return path.join(dir, `${componentName}.stories${ext}`);
  },

  /**
   * Get the appropriate story file extension for framework
   * @param {string} framework - Target framework
   * @returns {string} File extension
   */
  getStoryExtension(framework) {
    switch (framework) {
      case 'react':
        return '.tsx';
      case 'vue':
        return '.ts';
      case 'svelte':
        return '.ts';
      case 'angular':
        return '.ts';
      case 'web-components':
        return '.ts';
      default:
        return '.ts';
    }
  },

  /**
   * Check if a file exists
   * @param {string} filePath - Path to check
   * @returns {Promise<boolean>} True if file exists
   */
  async fileExists(filePath) {
    try {
      await fs.access(filePath);
      return true;
    } catch {
      return false;
    }
  },

  /**
   * Check if story has been modified by user (using StoryHashRegistry from Phase 3)
   * @param {string} storyPath - Path to story file
   * @param {string} projectPath - Project root path
   * @returns {Promise<Object>} Object with isModified flag and reason
   */
  async checkStoryModified(storyPath, projectPath) {
    try {
      // Use StoryHashRegistry from Phase 3 if available
      if (StoryHashRegistry) {
        const hashRegistry = new StoryHashRegistry({
          outputDir: path.join(projectPath, '.design')
        });

        // StoryHashRegistry.checkStoryModified returns { isModified, reason, message, ... }
        const result = await hashRegistry.checkStoryModified(storyPath);
        return {
          isModified: result.isModified,
          reason: result.reason || result.message || 'unknown'
        };
      }

      // Fallback: Manual check if Phase 3 module not available
      const registryPath = path.join(projectPath, '.design', 'storyHashRegistry.json');

      let registry;
      try {
        const content = await fs.readFile(registryPath, 'utf8');
        registry = JSON.parse(content);
      } catch {
        // No registry yet - treat as unmodified (first generation)
        return { isModified: false, reason: 'no_registry' };
      }

      // Get stored hash for this story
      const storyKey = path.relative(projectPath, storyPath);
      const entry = registry.stories?.[storyKey];

      if (!entry?.generatedHash) {
        // No hash stored - treat as modified (safe default)
        return { isModified: true, reason: 'no_stored_hash' };
      }

      // Calculate current file hash
      const currentContent = await fs.readFile(storyPath, 'utf8');
      const currentHash = this.calculateHash(currentContent);

      // Compare hashes
      const isModified = entry.generatedHash !== currentHash;
      return {
        isModified,
        reason: isModified ? 'hash_mismatch' : 'hash_match'
      };

    } catch (error) {
      process.stderr.write(`[on-component-transform] Hash check failed: ${error.message}\n`);
      // On error, preserve story (safe default)
      return { isModified: true, reason: `error: ${error.message}` };
    }
  },

  /**
   * Calculate SHA-256 hash of content
   * @param {string} content - Content to hash
   * @returns {string} Hex-encoded hash
   */
  calculateHash(content) {
    const crypto = require('crypto');
    return crypto.createHash('sha256').update(content, 'utf8').digest('hex');
  },

  /**
   * Generate a Storybook story for the component
   * @param {Object} options - Generation options
   * @returns {Promise<Object>} Generation result
   */
  async generateStory(options) {
    const { componentName, framework, storyPath, sourceType, projectPath, action } = options;

    try {
      // Load story generator (destructure named export)
      const storyServerPath = '/home/operator/Bumba-Design/Bumba - Design Components/server';
      const { StoryGenerator } = require(path.join(storyServerPath, 'story-generator.js'));

      // Initialize generator with options object
      const generator = new StoryGenerator({ projectPath });

      // Load component registry to get full component data
      generator.loadComponentRegistry(projectPath);

      // Look up the component in registry, or create minimal component object
      let component = generator.lookupComponent(componentName);
      if (!component) {
        // Create minimal component object if not in registry
        component = {
          name: componentName,
          props: {},
          figmaUrl: '',
          layout: 'centered'
        };
      }

      // Generate story (generateStoryFile expects component object, not name string)
      const storyContent = generator.generateStoryFile(component, framework);

      if (!storyContent) {
        return {
          success: false,
          message: 'Story generation returned null',
          action: 'error'
        };
      }

      // Write the story file
      await fs.mkdir(path.dirname(storyPath), { recursive: true });
      await fs.writeFile(storyPath, storyContent, 'utf8');

      // Register story hash for future comparisons
      await this.registerStoryHash(storyPath, storyContent, projectPath);

      process.stderr.write(`[on-component-transform] Story ${action}: ${storyPath}\n`);

      return {
        success: true,
        message: `Story ${action}: ${componentName}`,
        action,
        storyPath,
        framework,
        content: storyContent
      };

    } catch (error) {
      process.stderr.write(`[on-component-transform] Story generation error: ${error.message}\n`);
      return {
        success: false,
        message: `Story generation failed: ${error.message}`,
        action: 'error',
        error
      };
    }
  },

  /**
   * Register story hash in registry for future comparison (uses StoryHashRegistry from Phase 3)
   * @param {string} storyPath - Path to story file
   * @param {string} content - Story content
   * @param {string} projectPath - Project root path
   */
  async registerStoryHash(storyPath, content, projectPath) {
    try {
      // Use StoryHashRegistry from Phase 3 if available
      if (StoryHashRegistry) {
        const hashRegistry = new StoryHashRegistry({
          outputDir: path.join(projectPath, '.design')
        });

        await hashRegistry.registerStory(storyPath, content, {
          source: 'on-component-transform-hook',
          generatedAt: new Date().toISOString()
        });

        process.stderr.write(`[on-component-transform] Registered story hash via StoryHashRegistry\n`);
        return;
      }

      // Fallback: Manual registration if Phase 3 module not available
      const registryPath = path.join(projectPath, '.design', 'storyHashRegistry.json');
      const storyKey = path.relative(projectPath, storyPath);

      // Load or create registry
      let registry = { version: '1.0.0', stories: {} };
      try {
        const existing = await fs.readFile(registryPath, 'utf8');
        registry = JSON.parse(existing);
      } catch {
        // Create new registry
      }

      // Calculate and store hash
      const hash = this.calculateHash(content);
      registry.stories[storyKey] = {
        generatedHash: hash,
        generatedAt: new Date().toISOString(),
        lastChecked: new Date().toISOString()
      };

      // Ensure .design directory exists
      await fs.mkdir(path.dirname(registryPath), { recursive: true });

      // Save registry
      await fs.writeFile(registryPath, JSON.stringify(registry, null, 2), 'utf8');

      process.stderr.write(`[on-component-transform] Registered story hash: ${storyKey}\n`);

    } catch (error) {
      // Don't fail transform if hash registration fails
      process.stderr.write(`[on-component-transform] Hash registration failed: ${error.message}\n`);
    }
  }
};
