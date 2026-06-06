/**
 * BUMBA Design Catalog Orchestrator
 *
 * Coordinates catalog operations via event-driven architecture.
 * Listens to design bridge events and updates the catalog automatically.
 *
 * @class CatalogOrchestrator
 * @version 1.0.0
 */

const EventEmitter = require('events');
const fs = require('fs').promises;
const path = require('path');

class CatalogOrchestrator extends EventEmitter {
  /**
   * Create a CatalogOrchestrator instance
   * @constructor
   * @param {Object} options - Configuration options
   * @param {string} options.projectRoot - Project root directory
   */
  constructor(options = {}) {
    super();

    this.projectRoot = options.projectRoot || process.cwd();
    this.catalogPath = path.join(this.projectRoot, '.design', 'design-catalog.html');
    this.dataPath = path.join(this.projectRoot, '.design', 'catalog-data.json');
    this.designDir = path.join(this.projectRoot, '.design');

    console.log('✓ CatalogOrchestrator initialized');
    console.log(`  Catalog path: ${this.catalogPath}`);
    console.log(`  Data path: ${this.dataPath}`);
  }

  /**
   * Setup event listeners for design bridge events
   * Call this after instantiation to start listening
   *
   * @param {EventEmitter} designBridge - Design Bridge instance
   * @param {EventEmitter} designEngineer - Design Engineer Manager instance
   * @param {EventEmitter} figmaSync - Figma Library Sync instance (optional)
   * @returns {void}
   */
  setupListeners(designBridge, designEngineer, figmaSync = null) {
    try {
      // Design Bridge events
      if (designBridge) {
        designBridge.on('tokens:extracted', async (tokens) => {
          await this.updateTokens(tokens);
          console.log('✓ Catalog updated with design tokens');
        });

        console.log('✓ Listening to Design Bridge events');
      }

      // Design Engineer events
      if (designEngineer) {
        designEngineer.on('component:created', async (component) => {
          await this.addComponent(component);
          console.log(`✓ Added ${component.name} to catalog`);
        });

        console.log('✓ Listening to Design Engineer Manager events');
      }

      // Figma sync events (optional)
      if (figmaSync) {
        figmaSync.on('library:changed', async (changes) => {
          await this.syncChanges(changes);
          console.log('✓ Catalog synced with Figma changes');
        });

        figmaSync.on('figma:synced', async (data) => {
          await this.syncChanges(data);
          console.log('✓ Catalog synced with Figma');
        });

        console.log('✓ Listening to Figma Library Sync events');
      }

      console.log('✓ All event listeners registered');
    } catch (error) {
      console.error('✗ Error setting up listeners:', error);
      throw error;
    }
  }

  /**
   * Load catalog data from file
   * @returns {Promise<Object>} Catalog data object
   */
  async loadCatalogData() {
    try {
      // Check if .design directory exists
      try {
        await fs.access(this.designDir);
      } catch {
        console.warn('⚠ .design directory does not exist, creating it...');
        await fs.mkdir(this.designDir, { recursive: true });
      }

      // Check if catalog data file exists
      try {
        await fs.access(this.dataPath);
      } catch {
        console.warn('⚠ catalog-data.json does not exist, returning empty structure');
        return this.getEmptyStructure();
      }

      // Read the file
      const fileContent = await fs.readFile(this.dataPath, 'utf8');

      // Parse JSON
      const data = JSON.parse(fileContent);

      console.log('✓ Loaded catalog data from file');
      return data;
    } catch (error) {
      if (error instanceof SyntaxError) {
        console.error('✗ Invalid JSON in catalog-data.json, returning empty structure');
        return this.getEmptyStructure();
      }

      console.error('✗ Error loading catalog data:', error);
      return this.getEmptyStructure();
    }
  }

  /**
   * Save catalog data to file
   * @param {Object} data - Catalog data to save
   * @returns {Promise<void>}
   */
  async saveCatalogData(data) {
    try {
      // Ensure .design directory exists
      try {
        await fs.access(this.designDir);
      } catch {
        console.log('Creating .design directory...');
        await fs.mkdir(this.designDir, { recursive: true });
      }

      // Validate data structure
      if (!data.version) {
        data.version = '1.0.0';
      }

      if (!data.generatedAt) {
        data.generatedAt = new Date().toISOString();
      }

      // Ensure all required arrays exist
      if (!data.colors) data.colors = [];
      if (!data.typography) data.typography = [];
      if (!data.spacing) data.spacing = [];
      if (!data.components) data.components = [];
      if (!data.metadata) data.metadata = {};
      if (!data.history) data.history = [];

      // Convert to formatted JSON
      const jsonContent = JSON.stringify(data, null, 2);

      // Write to file
      await fs.writeFile(this.dataPath, jsonContent, 'utf8');

      console.log('✓ Saved catalog data to file');
    } catch (error) {
      console.error('✗ Error saving catalog data:', error);
      throw error;
    }
  }

  /**
   * Get empty catalog data structure
   * @private
   * @returns {Object} Empty catalog data structure
   */
  getEmptyStructure() {
    return {
      version: '1.0.0',
      generatedAt: new Date().toISOString(),
      projectName: '',
      colors: [],
      typography: [],
      spacing: [],
      components: [],
      metadata: {
        figmaFileId: null,
        figmaFileName: null,
        lastSync: null,
        framework: null,
        designSystem: null
      },
      history: []
    };
  }

  /**
   * Update tokens in catalog
   * Event handler for 'tokens:extracted'
   *
   * @param {Object} tokens - Extracted design tokens
   * @param {Array} tokens.colors - Color tokens
   * @param {Array} tokens.typography - Typography tokens
   * @param {Array} tokens.spacing - Spacing tokens
   * @returns {Promise<void>}
   */
  async updateTokens(tokens) {
    try {
      console.log('Updating catalog with tokens...');

      const data = await this.loadCatalogData();

      // Update token sections
      if (tokens.colors) {
        data.colors = tokens.colors;
      }

      if (tokens.typography) {
        data.typography = tokens.typography;
      }

      if (tokens.spacing) {
        data.spacing = tokens.spacing;
      }

      // Update timestamp
      data.generatedAt = new Date().toISOString();

      // Add to history
      if (!data.history) {
        data.history = [];
      }

      data.history.unshift({
        timestamp: new Date().toISOString(),
        changeType: 'tokens:extracted',
        description: 'Design tokens extracted from Figma',
        changes: {
          added: (tokens.colors?.length || 0) + (tokens.typography?.length || 0) + (tokens.spacing?.length || 0),
          modified: 0,
          removed: 0
        }
      });

      // Keep only last 10 history entries
      if (data.history.length > 10) {
        data.history = data.history.slice(0, 10);
      }

      await this.saveCatalogData(data);

      // Emit success event
      this.emit('catalog:updated', { type: 'tokens', data });

      console.log('✓ Tokens updated in catalog');
    } catch (error) {
      console.error('✗ Error updating tokens:', error);
      this.emit('catalog:error', { operation: 'updateTokens', error });
      throw error;
    }
  }

  /**
   * Add component to catalog
   * Event handler for 'component:created'
   *
   * @param {Object} component - Component metadata and code
   * @param {string} component.id - Component ID
   * @param {string} component.name - Component name
   * @param {string} component.category - Component category
   * @param {string} component.framework - Framework (react, vue, etc.)
   * @param {string} component.designSystem - Design system (shadcn, material-ui, etc.)
   * @param {string} component.preview - Preview HTML
   * @param {string} component.code - Component source code
   * @returns {Promise<void>}
   */
  async addComponent(component) {
    try {
      console.log(`Adding component "${component.name}" to catalog...`);

      const data = await this.loadCatalogData();

      // Initialize components array if needed
      if (!data.components) {
        data.components = [];
      }

      // Check if component already exists (by id)
      const existingIndex = data.components.findIndex(c => c.id === component.id);

      if (existingIndex !== -1) {
        // Update existing component
        data.components[existingIndex] = {
          ...data.components[existingIndex],
          ...component,
          updatedAt: new Date().toISOString()
        };
        console.log(`✓ Updated existing component "${component.name}"`);
      } else {
        // Add new component
        data.components.unshift({
          ...component,
          createdAt: new Date().toISOString()
        });
        console.log(`✓ Added new component "${component.name}"`);
      }

      // Update timestamp
      data.generatedAt = new Date().toISOString();

      // Add to history
      if (!data.history) {
        data.history = [];
      }

      data.history.unshift({
        timestamp: new Date().toISOString(),
        changeType: 'component:created',
        description: `Component "${component.name}" ${existingIndex !== -1 ? 'updated' : 'added'}`,
        changes: {
          added: existingIndex === -1 ? 1 : 0,
          modified: existingIndex !== -1 ? 1 : 0,
          removed: 0
        }
      });

      // Keep only last 10 history entries
      if (data.history.length > 10) {
        data.history = data.history.slice(0, 10);
      }

      await this.saveCatalogData(data);

      // Emit success event
      this.emit('catalog:updated', { type: 'component', component, data });

      console.log(`✓ Component "${component.name}" added to catalog`);
    } catch (error) {
      console.error('✗ Error adding component:', error);
      this.emit('catalog:error', { operation: 'addComponent', error });
      throw error;
    }
  }

  /**
   * Sync changes from Figma
   * Event handler for 'library:changed' or 'figma:synced'
   *
   * @param {Object} changes - Figma changes data
   * @returns {Promise<void>}
   */
  async syncChanges(changes) {
    try {
      console.log('Syncing Figma changes to catalog...');

      const data = await this.loadCatalogData();

      // Update metadata
      if (!data.metadata) {
        data.metadata = {};
      }

      data.metadata.lastSync = new Date().toISOString();

      if (changes.fileId) {
        data.metadata.figmaFileId = changes.fileId;
      }

      if (changes.fileName) {
        data.metadata.figmaFileName = changes.fileName;
      }

      // If changes include tokens, update them
      if (changes.colors || changes.typography || changes.spacing) {
        await this.updateTokens(changes);
      }

      // Update timestamp
      data.generatedAt = new Date().toISOString();

      // Add to history
      if (!data.history) {
        data.history = [];
      }

      data.history.unshift({
        timestamp: new Date().toISOString(),
        changeType: 'figma:synced',
        description: 'Synced with Figma library',
        changes: {
          added: 0,
          modified: 0,
          removed: 0
        }
      });

      // Keep only last 10 history entries
      if (data.history.length > 10) {
        data.history = data.history.slice(0, 10);
      }

      await this.saveCatalogData(data);

      // Emit success event
      this.emit('catalog:updated', { type: 'sync', changes, data });

      console.log('✓ Figma changes synced to catalog');
    } catch (error) {
      console.error('✗ Error syncing changes:', error);
      this.emit('catalog:error', { operation: 'syncChanges', error });
      throw error;
    }
  }

  /**
   * Get catalog statistics
   * @returns {Promise<Object>} Statistics object
   */
  async getStats() {
    try {
      const data = await this.loadCatalogData();

      return {
        colors: data.colors?.length || 0,
        typography: data.typography?.length || 0,
        spacing: data.spacing?.length || 0,
        components: data.components?.length || 0,
        lastUpdated: data.generatedAt || null,
        lastSync: data.metadata?.lastSync || null
      };
    } catch (error) {
      console.error('✗ Error getting stats:', error);
      return {
        colors: 0,
        typography: 0,
        spacing: 0,
        components: 0,
        lastUpdated: null,
        lastSync: null
      };
    }
  }

  /**
   * Check if catalog exists
   * @returns {Promise<boolean>} True if catalog exists
   */
  async catalogExists() {
    try {
      await fs.access(this.dataPath);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Check if catalog has content
   * @returns {Promise<boolean>} True if catalog has any content
   */
  async hasContent() {
    try {
      const data = await this.loadCatalogData();
      return (
        (data.colors && data.colors.length > 0) ||
        (data.typography && data.typography.length > 0) ||
        (data.spacing && data.spacing.length > 0) ||
        (data.components && data.components.length > 0)
      );
    } catch {
      return false;
    }
  }
}

module.exports = CatalogOrchestrator;
