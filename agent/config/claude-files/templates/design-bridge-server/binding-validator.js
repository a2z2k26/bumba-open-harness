/**
 * Project Binding Validator
 * Sprint 8-10: Validates and manages project-to-Figma bindings
 */

const fs = require('fs').promises;
const path = require('path');

class BindingValidator {
  constructor() {
    this.supportedFrameworks = [
      'react',
      'vue',
      'angular',
      'svelte',
      'web-components'
    ];
  }

  /**
   * Validate a binding configuration
   */
  async validate(binding) {
    const errors = [];
    const warnings = [];

    // Validate required fields
    if (!binding.figmaFileKey) {
      errors.push('Missing required field: figmaFileKey');
    } else if (!this.isValidFigmaKey(binding.figmaFileKey)) {
      errors.push('Invalid Figma file key format');
    }

    if (!binding.projectPath) {
      errors.push('Missing required field: projectPath');
    } else {
      // Check if project path exists
      try {
        const stats = await fs.stat(binding.projectPath);
        if (!stats.isDirectory()) {
          errors.push('Project path is not a directory');
        }
      } catch (error) {
        errors.push(`Project path does not exist: ${binding.projectPath}`);
      }
    }

    // Validate framework
    if (!binding.framework) {
      warnings.push('No framework specified, will use default (react)');
    } else if (!this.supportedFrameworks.includes(binding.framework)) {
      errors.push(`Unsupported framework: ${binding.framework}. Supported: ${this.supportedFrameworks.join(', ')}`);
    }

    // Validate output path
    if (binding.outputPath) {
      const fullPath = path.join(binding.projectPath, binding.outputPath);
      try {
        await fs.mkdir(fullPath, { recursive: true });
      } catch (error) {
        warnings.push(`Could not create output path: ${binding.outputPath}`);
      }
    }

    // Check for duplicate bindings
    const existingBindings = await this.loadExistingBindings();
    const duplicate = existingBindings.bindings.find(b =>
      b.figmaFileKey === binding.figmaFileKey &&
      b.projectPath === binding.projectPath &&
      b.id !== binding.id
    );

    if (duplicate) {
      errors.push('A binding already exists for this Figma file and project');
    }

    return {
      valid: errors.length === 0,
      errors,
      warnings
    };
  }

  /**
   * Check if Figma file key is valid format
   */
  isValidFigmaKey(key) {
    // Figma keys are alphanumeric strings, typically 10+ characters
    return /^[a-zA-Z0-9]{10,}$/.test(key);
  }

  /**
   * Load existing bindings
   */
  async loadExistingBindings() {
    const bindingsPath = path.join(process.cwd(), '.bumba/figma-bindings.json');
    try {
      const content = await fs.readFile(bindingsPath, 'utf8');
      return JSON.parse(content);
    } catch (error) {
      // Return default structure if file doesn't exist
      return {
        version: '1.0.0',
        bindings: [],
        defaultSettings: {
          framework: 'react',
          autoSync: true,
          syncInterval: 5000
        }
      };
    }
  }

  /**
   * Save bindings to file
   */
  async saveBindings(bindings) {
    const bindingsPath = path.join(process.cwd(), '.bumba/figma-bindings.json');
    await fs.writeFile(bindingsPath, JSON.stringify(bindings, null, 2), 'utf8');
  }

  /**
   * Create a new binding
   */
  async createBinding(bindingData) {
    const binding = {
      id: `binding_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      figmaFileKey: bindingData.figmaFileKey,
      projectPath: bindingData.projectPath,
      framework: bindingData.framework || 'react',
      autoSync: bindingData.autoSync !== false,
      syncInterval: bindingData.syncInterval || 5000,
      outputPath: bindingData.outputPath || 'src/components/generated',
      generateTests: bindingData.generateTests !== false,
      generateStorybook: bindingData.generateStorybook !== false,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      lastSyncedAt: null,
      syncCount: 0,
      status: 'active'
    };

    // Validate before saving
    const validation = await this.validate(binding);
    if (!validation.valid) {
      throw new Error(`Invalid binding: ${validation.errors.join(', ')}`);
    }

    // Load existing bindings
    const allBindings = await this.loadExistingBindings();

    // Add new binding
    allBindings.bindings.push(binding);

    // Save back to file
    await this.saveBindings(allBindings);

    return binding;
  }

  /**
   * Remove a binding
   */
  async removeBinding(bindingId) {
    const allBindings = await this.loadExistingBindings();

    const index = allBindings.bindings.findIndex(b => b.id === bindingId);
    if (index === -1) {
      throw new Error(`Binding not found: ${bindingId}`);
    }

    const removed = allBindings.bindings.splice(index, 1)[0];
    await this.saveBindings(allBindings);

    return removed;
  }

  /**
   * Update a binding
   */
  async updateBinding(bindingId, updates) {
    const allBindings = await this.loadExistingBindings();

    const binding = allBindings.bindings.find(b => b.id === bindingId);
    if (!binding) {
      throw new Error(`Binding not found: ${bindingId}`);
    }

    // Apply updates
    Object.assign(binding, updates, {
      updatedAt: new Date().toISOString()
    });

    // Validate updated binding
    const validation = await this.validate(binding);
    if (!validation.valid) {
      throw new Error(`Invalid binding update: ${validation.errors.join(', ')}`);
    }

    await this.saveBindings(allBindings);
    return binding;
  }

  /**
   * Get binding by ID
   */
  async getBinding(bindingId) {
    const allBindings = await this.loadExistingBindings();
    return allBindings.bindings.find(b => b.id === bindingId);
  }

  /**
   * Get all bindings
   */
  async getAllBindings() {
    const allBindings = await this.loadExistingBindings();
    return allBindings.bindings;
  }

  /**
   * Get bindings for a specific Figma file
   */
  async getBindingsForFile(figmaFileKey) {
    const allBindings = await this.loadExistingBindings();
    return allBindings.bindings.filter(b => b.figmaFileKey === figmaFileKey);
  }

  /**
   * Get bindings for a specific project
   */
  async getBindingsForProject(projectPath) {
    const allBindings = await this.loadExistingBindings();
    return allBindings.bindings.filter(b => b.projectPath === projectPath);
  }

  /**
   * Update sync stats for a binding
   */
  async updateSyncStats(bindingId) {
    const allBindings = await this.loadExistingBindings();

    const binding = allBindings.bindings.find(b => b.id === bindingId);
    if (!binding) {
      throw new Error(`Binding not found: ${bindingId}`);
    }

    binding.lastSyncedAt = new Date().toISOString();
    binding.syncCount = (binding.syncCount || 0) + 1;

    await this.saveBindings(allBindings);
    return binding;
  }
}

module.exports = new BindingValidator();