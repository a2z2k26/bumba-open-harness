/**
 * Token System Integrator
 * Sprint 30: Complete token pipeline integration
 *
 * Orchestrates the full token lifecycle:
 * Figma → Extract → Normalize → Validate → Use in Generators
 */

const EventEmitter = require('events');
const { TokenExtractor } = require('./token-extractor');
const TokenNormalizer = require('./token-normalizer');
const TokenValidator = require('./token-validator');
const { getOptimizerRegistry } = require('./optimizer-registry');

class TokenSystemIntegrator extends EventEmitter {
  constructor(options = {}) {
    super();

    // Initialize token pipeline components
    this.extractor = new TokenExtractor({
      precision: options.precision || 2,
      units: options.units || 'px',
      colorFormat: options.colorFormat || 'hex'
    });

    this.normalizer = new TokenNormalizer();

    this.validator = new TokenValidator(
      options.schemaPath,
      options.validationPreset || 'standard'
    );

    // Get optimizer registry for feeding tokens to generators
    this.optimizerRegistry = getOptimizerRegistry();

    // Token cache
    this.tokenCache = new Map();
    this.lastSync = null;

    // Configuration
    this.config = {
      autoSync: options.autoSync !== false,
      validateOnExtract: options.validateOnExtract !== false,
      cacheTokens: options.cacheTokens !== false,
      ...options
    };

    // Statistics
    this.stats = {
      totalExtractions: 0,
      totalValidations: 0,
      successfulExtractions: 0,
      failedValidations: 0,
      lastExtractionTime: null
    };
  }

  /**
   * Process Figma data through complete token pipeline
   */
  async processTokens(figmaData, options = {}) {
    const startTime = Date.now();
    const pipelineId = `token_pipeline_${Date.now()}`;

    this.emit('pipeline:started', {
      id: pipelineId,
      source: 'figma',
      timestamp: new Date().toISOString()
    });

    try {
      // Step 1: Extract tokens from Figma data
      this.emit('pipeline:extracting', { id: pipelineId });
      const extractedTokens = await this.extractTokens(figmaData);

      this.stats.totalExtractions++;
      this.stats.successfulExtractions++;

      // Step 2: Normalize extracted tokens
      this.emit('pipeline:normalizing', { id: pipelineId });
      const normalizedTokens = this.normalizeTokens(extractedTokens);

      // Step 3: Validate normalized tokens (if enabled)
      let validationResult = { valid: true, errors: [], warnings: [] };
      if (this.config.validateOnExtract) {
        this.emit('pipeline:validating', { id: pipelineId });
        validationResult = await this.validateTokens(normalizedTokens);
        this.stats.totalValidations++;

        if (!validationResult.valid) {
          this.stats.failedValidations++;
        }
      }

      // Step 4: Cache tokens
      if (this.config.cacheTokens) {
        this.cacheTokens(normalizedTokens, figmaData.fileKey || pipelineId);
      }

      // Step 5: Make tokens available to generators
      this.feedToGenerators(normalizedTokens);

      const duration = Date.now() - startTime;
      this.stats.lastExtractionTime = duration;

      const result = {
        id: pipelineId,
        tokens: normalizedTokens,
        validation: validationResult,
        stats: {
          extracted: this.countTokens(extractedTokens),
          normalized: this.countTokens(normalizedTokens),
          duration,
          valid: validationResult.valid
        },
        timestamp: new Date().toISOString()
      };

      this.emit('pipeline:completed', result);

      return result;

    } catch (error) {
      this.emit('pipeline:failed', {
        id: pipelineId,
        error: error.message,
        timestamp: new Date().toISOString()
      });

      throw error;
    }
  }

  /**
   * Extract tokens from Figma data
   */
  async extractTokens(figmaData) {
    try {
      const tokens = this.extractor.extract(figmaData);

      this.emit('tokens:extracted', {
        count: this.countTokens(tokens),
        categories: Object.keys(tokens),
        timestamp: new Date().toISOString()
      });

      return tokens;
    } catch (error) {
      this.emit('extraction:error', { error: error.message });
      throw error;
    }
  }

  /**
   * Normalize extracted tokens
   */
  normalizeTokens(tokens) {
    try {
      const normalized = this.normalizer.normalize(tokens);

      this.emit('tokens:normalized', {
        count: this.countTokens(normalized),
        categories: Object.keys(normalized),
        timestamp: new Date().toISOString()
      });

      return normalized;
    } catch (error) {
      this.emit('normalization:error', { error: error.message });
      throw error;
    }
  }

  /**
   * Validate normalized tokens
   */
  async validateTokens(tokens) {
    try {
      this.validator.setPreset(this.config.validationPreset || 'standard');
      const result = this.validator.validate(tokens);

      this.emit('tokens:validated', {
        valid: result.valid,
        errorCount: result.errors?.length || 0,
        warningCount: result.warnings?.length || 0,
        timestamp: new Date().toISOString()
      });

      return result;
    } catch (error) {
      this.emit('validation:error', { error: error.message });
      throw error;
    }
  }

  /**
   * Cache tokens for quick access
   */
  cacheTokens(tokens, cacheKey) {
    this.tokenCache.set(cacheKey, {
      tokens,
      timestamp: new Date().toISOString()
    });

    this.emit('tokens:cached', {
      key: cacheKey,
      count: this.countTokens(tokens),
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Get cached tokens
   */
  getCachedTokens(cacheKey) {
    const cached = this.tokenCache.get(cacheKey);
    if (cached) {
      this.emit('cache:hit', { key: cacheKey });
      return cached.tokens;
    }

    this.emit('cache:miss', { key: cacheKey });
    return null;
  }

  /**
   * Feed tokens to code generators
   */
  feedToGenerators(tokens) {
    const frameworks = this.optimizerRegistry.getSupportedFrameworks();

    frameworks.forEach(framework => {
      const optimizer = this.optimizerRegistry.getOptimizer(framework);

      // Inject tokens into optimizer config if supported
      if (optimizer && optimizer.config) {
        optimizer.config.designTokens = tokens;
      }
    });

    this.emit('tokens:fed_to_generators', {
      frameworks: frameworks.length,
      tokenCount: this.countTokens(tokens),
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Sync token changes
   */
  async syncTokenChanges(oldTokens, newTokens) {
    const changes = this.detectTokenChanges(oldTokens, newTokens);

    if (changes.hasChanges) {
      this.emit('tokens:changed', {
        added: changes.added.length,
        modified: changes.modified.length,
        removed: changes.removed.length,
        timestamp: new Date().toISOString()
      });

      // Re-feed to generators if auto-sync enabled
      if (this.config.autoSync) {
        this.feedToGenerators(newTokens);
      }
    }

    return changes;
  }

  /**
   * Detect changes between token sets
   */
  detectTokenChanges(oldTokens, newTokens) {
    const changes = {
      hasChanges: false,
      added: [],
      modified: [],
      removed: []
    };

    if (!oldTokens) {
      return { hasChanges: true, added: Object.keys(newTokens), modified: [], removed: [] };
    }

    // Check each category
    const allCategories = new Set([
      ...Object.keys(oldTokens),
      ...Object.keys(newTokens)
    ]);

    allCategories.forEach(category => {
      const oldCategoryTokens = oldTokens[category] || {};
      const newCategoryTokens = newTokens[category] || {};

      // Check for added/modified tokens
      Object.keys(newCategoryTokens).forEach(tokenName => {
        const fullName = `${category}.${tokenName}`;

        if (!oldCategoryTokens[tokenName]) {
          changes.added.push(fullName);
          changes.hasChanges = true;
        } else if (JSON.stringify(oldCategoryTokens[tokenName]) !== JSON.stringify(newCategoryTokens[tokenName])) {
          changes.modified.push(fullName);
          changes.hasChanges = true;
        }
      });

      // Check for removed tokens
      Object.keys(oldCategoryTokens).forEach(tokenName => {
        if (!newCategoryTokens[tokenName]) {
          const fullName = `${category}.${tokenName}`;
          changes.removed.push(fullName);
          changes.hasChanges = true;
        }
      });
    });

    return changes;
  }

  /**
   * Get token references for a component
   */
  getTokenReferences(component, tokens) {
    const references = {
      colors: [],
      typography: [],
      spacing: [],
      shadows: [],
      other: []
    };

    // Analyze component to find token references
    if (component.styles) {
      // Check color references
      if (component.styles.colors && tokens.colors) {
        Object.keys(component.styles.colors).forEach(colorKey => {
          if (tokens.colors[colorKey]) {
            references.colors.push(colorKey);
          }
        });
      }

      // Check typography references
      if (component.styles.typography && tokens.typography) {
        Object.keys(component.styles.typography).forEach(typoKey => {
          if (tokens.typography[typoKey]) {
            references.typography.push(typoKey);
          }
        });
      }

      // Check spacing references
      if (component.styles.spacing && tokens.spacing) {
        Object.keys(component.styles.spacing).forEach(spaceKey => {
          if (tokens.spacing[spaceKey]) {
            references.spacing.push(spaceKey);
          }
        });
      }
    }

    this.emit('references:resolved', {
      component: component.name,
      totalReferences: this.countReferences(references),
      timestamp: new Date().toISOString()
    });

    return references;
  }

  /**
   * Update token references in component
   */
  updateTokenReferences(component, tokenChanges) {
    let updated = false;

    // Update modified token references
    tokenChanges.modified.forEach(tokenPath => {
      const [category, tokenName] = tokenPath.split('.');

      if (component.styles && component.styles[category] && component.styles[category][tokenName]) {
        // Token reference exists in component - mark for update
        updated = true;
      }
    });

    // Handle removed token references
    tokenChanges.removed.forEach(tokenPath => {
      const [category, tokenName] = tokenPath.split('.');

      if (component.styles && component.styles[category] && component.styles[category][tokenName]) {
        // Token was removed - need to handle this
        this.emit('reference:broken', {
          component: component.name,
          token: tokenPath,
          timestamp: new Date().toISOString()
        });
      }
    });

    if (updated) {
      this.emit('references:updated', {
        component: component.name,
        changes: tokenChanges.modified.length + tokenChanges.removed.length,
        timestamp: new Date().toISOString()
      });
    }

    return updated;
  }

  /**
   * Get all tokens
   */
  getAllTokens() {
    return Array.from(this.tokenCache.values())
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0]?.tokens || {};
  }

  /**
   * Get pipeline statistics
   */
  getStats() {
    return {
      ...this.stats,
      cachedTokenSets: this.tokenCache.size,
      lastSync: this.lastSync
    };
  }

  /**
   * Clear token cache
   */
  clearCache() {
    const size = this.tokenCache.size;
    this.tokenCache.clear();

    this.emit('cache:cleared', {
      count: size,
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Helper: Count tokens
   */
  countTokens(tokens) {
    // Handle null/undefined tokens
    if (!tokens || typeof tokens !== 'object') {
      return 0;
    }

    let count = 0;
    Object.values(tokens).forEach(category => {
      if (category && typeof category === 'object') {
        count += Object.keys(category).length;
      }
    });
    return count;
  }

  /**
   * Helper: Count references
   */
  countReferences(references) {
    // Handle null/undefined references
    if (!references || typeof references !== 'object') {
      return 0;
    }

    return Object.values(references).reduce((sum, arr) => {
      // Handle undefined or non-array values
      return sum + (Array.isArray(arr) ? arr.length : 0);
    }, 0);
  }

  /**
   * Test token flow
   */
  async testTokenFlow(sampleFigmaData) {
    console.log('🧪 Testing token flow...\n');

    try {
      // Step 1: Extract
      console.log('1️⃣ Extracting tokens...');
      const extracted = await this.extractTokens(sampleFigmaData);
      console.log(`   ✓ Extracted ${this.countTokens(extracted)} tokens\n`);

      // Step 2: Normalize
      console.log('2️⃣ Normalizing tokens...');
      const normalized = this.normalizeTokens(extracted);
      console.log(`   ✓ Normalized ${this.countTokens(normalized)} tokens\n`);

      // Step 3: Validate
      console.log('3️⃣ Validating tokens...');
      const validation = await this.validateTokens(normalized);
      console.log(`   ✓ Validation: ${validation.valid ? 'PASSED' : 'FAILED'}`);
      console.log(`   - Errors: ${validation.errors?.length || 0}`);
      console.log(`   - Warnings: ${validation.warnings?.length || 0}\n`);

      // Step 4: Feed to generators
      console.log('4️⃣ Feeding to generators...');
      this.feedToGenerators(normalized);
      console.log(`   ✓ Fed to ${this.optimizerRegistry.getSupportedFrameworks().length} framework optimizers\n`);

      console.log('✅ Token flow test complete!\n');

      return {
        success: true,
        extracted: this.countTokens(extracted),
        normalized: this.countTokens(normalized),
        valid: validation.valid
      };

    } catch (error) {
      console.error('❌ Token flow test failed:', error.message);
      throw error;
    }
  }
}

module.exports = TokenSystemIntegrator;
