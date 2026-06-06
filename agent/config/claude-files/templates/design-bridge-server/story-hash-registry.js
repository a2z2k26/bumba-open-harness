/**
 * Story Hash Registry - Tracks generated story checksums for conflict detection
 *
 * Manages a registry of SHA-256 hashes for auto-generated Storybook stories.
 * Used by the post-transform hook to detect user modifications and prevent
 * overwriting customized stories.
 *
 * @module story-hash-registry
 * @version 1.0.0
 * @phase Option C - Sprint 1.3/1.4
 */

const fs = require('fs').promises;
const path = require('path');
const { calculateHash, hashFile, hasFileChanged } = require('./content-hasher');

// ============================================================================
// Constants
// ============================================================================

const REGISTRY_FILENAME = 'storyHashRegistry.json';
const REGISTRY_VERSION = '2.0.0'; // Upgraded for code file tracking

// ============================================================================
// Registry Schema
// ============================================================================

/**
 * @typedef {Object} StoryEntry
 * @property {string} generatedHash - Hash of the auto-generated content
 * @property {string} generatedAt - ISO timestamp when story was generated
 * @property {string} lastChecked - ISO timestamp of last modification check
 * @property {string} [framework] - Framework the story was generated for
 * @property {string} [sourceType] - Source type (figma, shadcn, nlp)
 */

/**
 * @typedef {Object} CodeFileEntry
 * @property {string} generatedHash - Hash of the auto-generated code
 * @property {string} generatedAt - ISO timestamp when code was generated
 * @property {string} lastChecked - ISO timestamp of last modification check
 * @property {string} [framework] - Framework the code was generated for
 * @property {string} [componentId] - Component registry ID
 */

/**
 * @typedef {Object} StoryHashRegistry
 * @property {string} version - Registry schema version
 * @property {Object.<string, StoryEntry>} stories - Map of story paths to entries
 * @property {Object.<string, CodeFileEntry>} codeFiles - Map of code paths to entries (v2.0.0+)
 * @property {string} lastUpdated - ISO timestamp of last registry update
 */

// ============================================================================
// StoryHashRegistry Class
// ============================================================================

class StoryHashRegistry {
  /**
   * Create a new StoryHashRegistry instance
   * @param {string} projectPath - Path to the project root
   */
  constructor(projectPath) {
    this.projectPath = projectPath;
    this.registryPath = path.join(projectPath, '.design', REGISTRY_FILENAME);
    this.registry = null;
    this.dirty = false;
  }

  /**
   * Load the registry from disk
   * @returns {Promise<StoryHashRegistry>} The loaded registry
   */
  async load() {
    try {
      const content = await fs.readFile(this.registryPath, 'utf8');
      this.registry = JSON.parse(content);

      // Ensure version compatibility
      if (!this.registry.version) {
        this.registry.version = REGISTRY_VERSION;
      }

      // Ensure stories object exists
      if (!this.registry.stories) {
        this.registry.stories = {};
      }

      // v2.0.0: Ensure codeFiles object exists (backward compatibility)
      if (!this.registry.codeFiles) {
        this.registry.codeFiles = {};
      }

      return this.registry;

    } catch (error) {
      // File doesn't exist or is invalid - create new registry
      this.registry = {
        version: REGISTRY_VERSION,
        stories: {},
        codeFiles: {}, // v2.0.0: code file tracking
        lastUpdated: new Date().toISOString()
      };
      return this.registry;
    }
  }

  /**
   * Save the registry to disk
   * @returns {Promise<void>}
   */
  async save() {
    if (!this.registry) {
      throw new Error('Registry not loaded. Call load() first.');
    }

    // Update timestamp
    this.registry.lastUpdated = new Date().toISOString();

    // Ensure .design directory exists
    const designDir = path.dirname(this.registryPath);
    await fs.mkdir(designDir, { recursive: true });

    // Write atomically by writing to temp file first
    const tempPath = this.registryPath + '.tmp';
    await fs.writeFile(tempPath, JSON.stringify(this.registry, null, 2), 'utf8');
    await fs.rename(tempPath, this.registryPath);

    this.dirty = false;
  }

  /**
   * Register a newly generated story
   * @param {string} storyPath - Absolute or relative path to story file
   * @param {string} content - The generated story content
   * @param {Object} [metadata={}] - Additional metadata
   * @param {string} [metadata.framework] - Target framework
   * @param {string} [metadata.sourceType] - Source type (figma, shadcn, nlp)
   * @returns {Promise<string>} The generated hash
   */
  async registerStory(storyPath, content, metadata = {}) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(storyPath);
    const hash = calculateHash(content);

    this.registry.stories[relPath] = {
      generatedHash: hash,
      generatedAt: new Date().toISOString(),
      lastChecked: new Date().toISOString(),
      framework: metadata.framework || null,
      sourceType: metadata.sourceType || null
    };

    this.dirty = true;
    await this.save();

    return hash;
  }

  // ==========================================================================
  // Code File Tracking Methods (v2.0.0)
  // ==========================================================================

  /**
   * Register a newly generated code file
   * @param {string} codePath - Absolute or relative path to code file
   * @param {string} content - The generated code content
   * @param {Object} [metadata={}] - Additional metadata
   * @param {string} [metadata.framework] - Target framework
   * @param {string} [metadata.componentId] - Component registry ID
   * @returns {Promise<string>} The generated hash
   */
  async registerCodeFile(codePath, content, metadata = {}) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(codePath);
    const hash = calculateHash(content);

    this.registry.codeFiles[relPath] = {
      generatedHash: hash,
      generatedAt: new Date().toISOString(),
      lastChecked: new Date().toISOString(),
      framework: metadata.framework || null,
      componentId: metadata.componentId || null
    };

    this.dirty = true;
    await this.save();

    return hash;
  }

  /**
   * Check if a code file has been modified by the user
   * @param {string} codePath - Path to code file
   * @returns {Promise<Object>} Result with isModified flag and details
   */
  async checkCodeModified(codePath) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(codePath);
    const absPath = this.getAbsolutePath(codePath);
    const entry = this.registry.codeFiles[relPath];

    // No entry means code wasn't auto-generated (treat as modified/user-created)
    if (!entry) {
      return {
        isModified: true,
        reason: 'not-registered',
        message: 'Code file is not in the auto-generation registry'
      };
    }

    try {
      // Check if file exists
      await fs.access(absPath);

      // Calculate current hash
      const currentHash = await hashFile(absPath);

      // Update lastChecked timestamp
      entry.lastChecked = new Date().toISOString();
      this.dirty = true;

      if (entry.generatedHash === currentHash) {
        return {
          isModified: false,
          reason: 'unchanged',
          message: 'Code matches the auto-generated version'
        };
      } else {
        return {
          isModified: true,
          reason: 'content-changed',
          message: 'Code has been modified since auto-generation',
          originalHash: entry.generatedHash,
          currentHash
        };
      }

    } catch (error) {
      // File doesn't exist
      return {
        isModified: false,
        reason: 'file-missing',
        message: 'Code file does not exist'
      };
    }
  }

  /**
   * Update the stored hash for a code file (after regeneration)
   * @param {string} codePath - Path to code file
   * @param {string} newHash - New hash value
   * @returns {Promise<void>}
   */
  async updateCodeHash(codePath, newHash) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(codePath);
    const entry = this.registry.codeFiles[relPath];

    if (entry) {
      entry.generatedHash = newHash;
      entry.generatedAt = new Date().toISOString();
      entry.lastChecked = new Date().toISOString();
      this.dirty = true;
      await this.save();
    }
  }

  /**
   * Get code file entry
   * @param {string} codePath - Path to code file
   * @returns {Promise<CodeFileEntry|null>} Code entry or null
   */
  async getCodeEntry(codePath) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(codePath);
    return this.registry.codeFiles[relPath] || null;
  }

  /**
   * Check if a code file is registered
   * @param {string} codePath - Path to code file
   * @returns {Promise<boolean>} True if code is in registry
   */
  async hasCodeFile(codePath) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(codePath);
    return relPath in this.registry.codeFiles;
  }

  /**
   * Remove a code file from the registry
   * @param {string} codePath - Path to code file
   * @returns {Promise<boolean>} True if entry was removed
   */
  async clearCodeFile(codePath) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(codePath);

    if (this.registry.codeFiles[relPath]) {
      delete this.registry.codeFiles[relPath];
      this.dirty = true;
      await this.save();
      return true;
    }

    return false;
  }

  /**
   * List all registered code files
   * @returns {Promise<Array>} Array of code entries with paths
   */
  async listCodeFiles() {
    if (!this.registry) {
      await this.load();
    }

    return Object.entries(this.registry.codeFiles).map(([path, entry]) => ({
      path,
      ...entry
    }));
  }

  /**
   * Get code files by component ID
   * @param {string} componentId - Component ID to filter by
   * @returns {Promise<Array>} Filtered code entries
   */
  async getCodeFilesByComponent(componentId) {
    const codeFiles = await this.listCodeFiles();
    return codeFiles.filter(c => c.componentId === componentId);
  }

  // ==========================================================================
  // Story Methods (Original)
  // ==========================================================================

  /**
   * Check if a story has been modified by the user
   * @param {string} storyPath - Path to story file
   * @returns {Promise<Object>} Result with isModified flag and details
   */
  async checkStoryModified(storyPath) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(storyPath);
    const absPath = this.getAbsolutePath(storyPath);
    const entry = this.registry.stories[relPath];

    // No entry means story wasn't auto-generated (treat as modified/user-created)
    if (!entry) {
      return {
        isModified: true,
        reason: 'not-registered',
        message: 'Story is not in the auto-generation registry'
      };
    }

    try {
      // Check if file exists
      await fs.access(absPath);

      // Calculate current hash
      const currentHash = await hashFile(absPath);

      // Update lastChecked timestamp
      entry.lastChecked = new Date().toISOString();
      this.dirty = true;

      if (entry.generatedHash === currentHash) {
        return {
          isModified: false,
          reason: 'unchanged',
          message: 'Story matches the auto-generated version'
        };
      } else {
        return {
          isModified: true,
          reason: 'content-changed',
          message: 'Story has been modified since auto-generation',
          originalHash: entry.generatedHash,
          currentHash
        };
      }

    } catch (error) {
      // File doesn't exist
      return {
        isModified: false,
        reason: 'file-missing',
        message: 'Story file does not exist'
      };
    }
  }

  /**
   * Update the stored hash for a story (after regeneration)
   * @param {string} storyPath - Path to story file
   * @param {string} newHash - New hash value
   * @returns {Promise<void>}
   */
  async updateHash(storyPath, newHash) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(storyPath);
    const entry = this.registry.stories[relPath];

    if (entry) {
      entry.generatedHash = newHash;
      entry.generatedAt = new Date().toISOString();
      entry.lastChecked = new Date().toISOString();
      this.dirty = true;
      await this.save();
    }
  }

  /**
   * Remove a story from the registry
   * @param {string} storyPath - Path to story file
   * @returns {Promise<boolean>} True if entry was removed
   */
  async clearStory(storyPath) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(storyPath);

    if (this.registry.stories[relPath]) {
      delete this.registry.stories[relPath];
      this.dirty = true;
      await this.save();
      return true;
    }

    return false;
  }

  /**
   * Get entry for a story
   * @param {string} storyPath - Path to story file
   * @returns {StoryEntry|null} Story entry or null
   */
  async getEntry(storyPath) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(storyPath);
    return this.registry.stories[relPath] || null;
  }

  /**
   * Check if a story is registered
   * @param {string} storyPath - Path to story file
   * @returns {Promise<boolean>} True if story is in registry
   */
  async hasStory(storyPath) {
    if (!this.registry) {
      await this.load();
    }

    const relPath = this.getRelativePath(storyPath);
    return relPath in this.registry.stories;
  }

  /**
   * List all registered stories
   * @returns {Promise<Array>} Array of story entries with paths
   */
  async listStories() {
    if (!this.registry) {
      await this.load();
    }

    return Object.entries(this.registry.stories).map(([path, entry]) => ({
      path,
      ...entry
    }));
  }

  /**
   * Get stories by framework
   * @param {string} framework - Framework to filter by
   * @returns {Promise<Array>} Filtered story entries
   */
  async getStoriesByFramework(framework) {
    const stories = await this.listStories();
    return stories.filter(s => s.framework === framework);
  }

  /**
   * Clear all entries from the registry
   * @param {Object} [options={}] - Clear options
   * @param {boolean} [options.stories=true] - Clear stories
   * @param {boolean} [options.codeFiles=true] - Clear code files
   * @returns {Promise<void>}
   */
  async clearAll(options = {}) {
    const { stories = true, codeFiles = true } = options;

    if (!this.registry) {
      await this.load();
    }

    if (stories) {
      this.registry.stories = {};
    }
    if (codeFiles) {
      this.registry.codeFiles = {};
    }
    this.dirty = true;
    await this.save();
  }

  /**
   * Get registry statistics
   * @returns {Promise<Object>} Statistics about the registry
   */
  async getStats() {
    if (!this.registry) {
      await this.load();
    }

    const stories = Object.values(this.registry.stories);
    const codeFiles = Object.values(this.registry.codeFiles || {});

    const storiesByFramework = {};
    const codeByFramework = {};

    for (const story of stories) {
      const fw = story.framework || 'unknown';
      storiesByFramework[fw] = (storiesByFramework[fw] || 0) + 1;
    }

    for (const code of codeFiles) {
      const fw = code.framework || 'unknown';
      codeByFramework[fw] = (codeByFramework[fw] || 0) + 1;
    }

    return {
      totalStories: stories.length,
      storiesByFramework,
      totalCodeFiles: codeFiles.length,
      codeByFramework,
      version: this.registry.version,
      lastUpdated: this.registry.lastUpdated
    };
  }

  /**
   * Convert absolute path to relative path
   * @private
   */
  getRelativePath(filePath) {
    if (path.isAbsolute(filePath)) {
      return path.relative(this.projectPath, filePath);
    }
    return filePath;
  }

  /**
   * Convert relative path to absolute path
   * @private
   */
  getAbsolutePath(filePath) {
    if (path.isAbsolute(filePath)) {
      return filePath;
    }
    return path.join(this.projectPath, filePath);
  }
}

// ============================================================================
// Standalone Utility Functions
// ============================================================================

/**
 * Load registry from a project path
 * @param {string} projectPath - Path to project root
 * @returns {Promise<StoryHashRegistry>} The registry data
 */
async function loadRegistry(projectPath) {
  const registry = new StoryHashRegistry(projectPath);
  await registry.load();
  return registry;
}

/**
 * Quick check if a story has been modified
 * @param {string} projectPath - Path to project root
 * @param {string} storyPath - Path to story file
 * @returns {Promise<boolean>} True if story has been modified
 */
async function isStoryModified(projectPath, storyPath) {
  const registry = new StoryHashRegistry(projectPath);
  const result = await registry.checkStoryModified(storyPath);
  return result.isModified;
}

/**
 * Register a story with the hash registry
 * @param {string} projectPath - Path to project root
 * @param {string} storyPath - Path to story file
 * @param {string} content - Story content
 * @param {Object} [metadata] - Optional metadata
 * @returns {Promise<string>} The generated hash
 */
async function registerStory(projectPath, storyPath, content, metadata = {}) {
  const registry = new StoryHashRegistry(projectPath);
  return registry.registerStory(storyPath, content, metadata);
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  // Class
  StoryHashRegistry,

  // Utility functions
  loadRegistry,
  isStoryModified,
  registerStory,

  // Constants
  REGISTRY_FILENAME,
  REGISTRY_VERSION
};
