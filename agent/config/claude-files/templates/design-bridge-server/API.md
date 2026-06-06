# Design Bridge Server API Documentation

## Overview

The Design Bridge Server provides a comprehensive pipeline for transforming Figma designs into production-ready code across multiple frameworks.

## Table of Contents

1. [Core Modules](#core-modules)
2. [Code Generation](#code-generation)
3. [Story Generation](#story-generation)
4. [Registry Management](#registry-management)
5. [Error Handling](#error-handling)
6. [Logging](#logging)
7. [Schema Validation](#schema-validation)
8. [Caching](#caching)
9. [Async Pipeline](#async-pipeline)

---

## Core Modules

### SmartCodeGenerator

Generates framework-specific component code from Figma design data.

```javascript
const SmartCodeGenerator = require('./smart-code-generator');

const generator = new SmartCodeGenerator(options);
const result = await generator.generateCode(figmaData, framework, options);
```

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `outputDir` | string | `'./output'` | Output directory for generated files |
| `includeStyles` | boolean | `true` | Include CSS/styles in output |
| `includeAccessibility` | boolean | `true` | Add ARIA attributes |
| `tokens` | object | `{}` | Design tokens for style resolution |

#### Supported Frameworks

- `react` - React with TypeScript
- `vue` - Vue 3 Composition API
- `angular` - Angular standalone components
- `svelte` - Svelte components
- `react-native` - React Native
- `flutter` - Flutter/Dart widgets
- `swiftui` - SwiftUI views
- `jetpack-compose` - Android Jetpack Compose

---

### StoryGenerator

Generates Storybook stories for components.

```javascript
const { StoryGenerator } = require('./story-generator');

const generator = new StoryGenerator(options);
const story = await generator.generateStory(componentData, framework);
```

#### Output

Returns an object containing:
- `content` - Story file content
- `argTypes` - Storybook controls
- `args` - Default prop values
- `variants` - Available variants

---

## Registry Management

### RegistryManager

Manages component registry with O(1) lookups.

```javascript
const RegistryManager = require('./registry-manager');

const registry = new RegistryManager(registryPath);

// Add component
await registry.addComponent({
  id: 'btn-001',
  name: 'Button',
  source: 'figma',
  figmaNodeId: '1:234'
});

// Query components
const component = registry.getById('btn-001');
const byFigma = registry.getByFigmaNodeId('1:234');
const byName = registry.getByName('Button');
```

### Registry Entry Schema

```typescript
interface RegistryEntry {
  id: string;           // Unique identifier
  name: string;         // Component name
  source: 'figma' | 'shadcn' | 'nlp' | 'manual' | 'code';
  figmaNodeId?: string; // Figma node reference
  shadcnName?: string;  // Mapped shadcn/ui component
  category?: string;    // Component category
  transformedTo?: string[]; // Generated frameworks
  outputPaths?: Record<string, string>; // Output file paths
  metadata?: object;    // Additional metadata
  syncMetadata?: {
    lastSynced: string;
    version: string;
    contentHash: string;
  };
}
```

---

## Error Handling

### Error Types

All errors extend `DesignBridgeError` with structured context.

```javascript
const {
  DesignBridgeError,
  ValidationError,
  SchemaValidationError,
  ComponentNotFoundError,
  FigmaApiError,
  FigmaRateLimitError
} = require('./error-types');

// Throw specific error
throw new ComponentNotFoundError('btn-001');

// Wrap native errors
const wrapped = wrapError(nativeError);

// Check error type
if (isErrorType(error, FigmaRateLimitError)) {
  await sleep(error.retryAfter * 1000);
}

// Check recoverability
if (isRecoverable(error)) {
  // Retry operation
}
```

### Error Properties

| Property | Type | Description |
|----------|------|-------------|
| `code` | string | Error code (e.g., `VALIDATION_ERROR`) |
| `statusCode` | number | HTTP status code |
| `context` | object | Additional context data |
| `recoverable` | boolean | Whether error is recoverable |
| `timestamp` | string | ISO timestamp |
| `cause` | Error | Original error if wrapped |

### Available Error Types

- **Validation**: `ValidationError`, `SchemaValidationError`, `RequiredFieldError`
- **Component**: `ComponentNotFoundError`, `ComponentGenerationError`
- **Registry**: `RegistryReadError`, `RegistryWriteError`, `RegistryCorruptionError`
- **Token**: `TokenNotFoundError`, `TokenResolutionError`
- **Figma**: `FigmaApiError`, `FigmaNodeNotFoundError`, `FigmaRateLimitError`
- **Framework**: `UnsupportedFrameworkError`, `FrameworkConfigError`
- **FileSystem**: `FileNotFoundError`, `FileWriteError`, `PermissionError`
- **Sync**: `SyncConflictError`, `SyncTimeoutError`
- **Config**: `ConfigurationError`, `MissingConfigError`

---

## Logging

### Unified Logger

Structured logging with levels, context, and metrics.

```javascript
const { createLogger, LOG_LEVELS } = require('./unified-logger');

const logger = createLogger('my-module');

// Log at different levels
logger.trace('Detailed trace info');
logger.debug('Debug information');
logger.info('Operation completed', { count: 42 });
logger.warn('Something unusual', { detail: 'context' });
logger.error('Operation failed', { error: err.message });
logger.fatal('Critical failure');

// Timed operations
const timer = logger.time('operation');
// ... do work ...
timer.end('Operation complete');

// Async timed
const result = await logger.timed('fetch-data', async () => {
  return await fetchData();
});

// Child loggers
const childLogger = logger.child({ name: 'sub-module' });

// Get metrics
const metrics = logger.getMetrics();
// { logged: { INFO: 5, ERROR: 1, ... }, uptime: 12345 }
```

### Log Levels

| Level | Priority | Use Case |
|-------|----------|----------|
| TRACE | 0 | Very detailed debugging |
| DEBUG | 1 | Debugging information |
| INFO | 2 | Normal operations |
| WARN | 3 | Warning conditions |
| ERROR | 4 | Error conditions |
| FATAL | 5 | Critical failures |
| SILENT | 99 | Disable all logging |

---

## Schema Validation

### validate()

Validate data against JSON schemas.

```javascript
const {
  validate,
  validateFigmaComponent,
  validateRegistryEntry,
  validateGeneratedComponent
} = require('./schema-validator');

// Generic validation
const result = validate(data, schema);
if (!result.valid) {
  console.error(result.errors);
}

// Type-specific validators
const figmaResult = validateFigmaComponent(componentData);
const registryResult = validateRegistryEntry(entry);

// Assert valid (throws on failure)
assertValid(data, schema, 'Data must be valid');

// Validate with fallback
const { data, valid, errors } = validateWithFallback(
  inputData,
  schema,
  defaultValue
);
```

### Available Schemas

- `FIGMA_COMPONENT_SCHEMA` - Figma node structure
- `TOKEN_SCHEMA` - Design tokens
- `REGISTRY_ENTRY_SCHEMA` - Component registry entries
- `GENERATED_COMPONENT_SCHEMA` - Generated code output
- `STORY_SCHEMA` - Story file output

---

## Caching

### CacheManager

Multi-layer caching with LRU memory and file persistence.

```javascript
const {
  CacheManager,
  ComponentCache,
  TokenCache
} = require('./cache-manager');

// Create cache manager
const cache = new CacheManager({
  name: 'my-cache',
  memoryCacheSize: 100,
  defaultTTL: 300000, // 5 minutes
  cacheDir: './.cache'
});

// Basic operations
cache.set('key', value);
const value = cache.get('key');
cache.delete('key');

// Memoize expensive functions
const cachedFetch = cache.memoize(fetchData, {
  prefix: 'fetch',
  ttl: 60000
});

// Specialized caches
const componentCache = new ComponentCache();
componentCache.setComponent('btn-001', 'react', '<Button />');

const tokenCache = new TokenCache();
tokenCache.setToken('colors.primary', '#3b82f6');
```

### LRU Cache

```javascript
const { LRUCache } = require('./cache-manager');

const lru = new LRUCache(100); // Max 100 items
lru.set('key', 'value', 5000); // 5 second TTL
const value = lru.get('key');
const stats = lru.getStats();
// { size: 50, maxSize: 100, hits: 100, misses: 10, hitRate: '90.91%' }
```

---

## Async Pipeline

### Batch Processing

Process items in parallel with concurrency control.

```javascript
const { BatchProcessor } = require('./async-pipeline');

const processor = new BatchProcessor({
  concurrency: 5,
  stopOnError: false
});

processor.on('progress', ({ completed, total, percent }) => {
  console.log(`Progress: ${percent}%`);
});

const result = await processor.process(items, async (item, index) => {
  return await processItem(item);
});

console.log(result.summary);
// { total: 100, completed: 98, failed: 2, cancelled: false }
```

### Rate Limiting

```javascript
const { RateLimiter } = require('./async-pipeline');

const limiter = new RateLimiter({
  tokensPerInterval: 10,
  interval: 1000 // 10 requests per second
});

async function rateLimitedOperation() {
  await limiter.acquire();
  return await fetchFromApi();
}
```

### Retry with Backoff

```javascript
const { retry } = require('./async-pipeline');

const result = await retry(
  async (attempt) => {
    console.log(`Attempt ${attempt}`);
    return await riskyOperation();
  },
  {
    maxAttempts: 5,
    baseDelay: 1000,
    factor: 2, // Exponential backoff
    shouldRetry: (error) => error.statusCode !== 404
  }
);
```

### Pipeline Stages

```javascript
const { Pipeline } = require('./async-pipeline');

const pipeline = new Pipeline('transform')
  .addStage('fetch', async (input) => {
    return await fetchData(input);
  })
  .addStage('transform', async (data) => {
    return transformData(data);
  })
  .addStage('save', async (result) => {
    return await saveResult(result);
  }, { timeout: 5000 })
  .onError(async (error, stage, input) => {
    if (stage.name === 'fetch') {
      return fallbackData; // Recovery value
    }
  });

pipeline.on('stage:complete', ({ stage, result }) => {
  console.log(`${stage} completed`);
});

const result = await pipeline.execute(input);
```

### Async Helpers

```javascript
const {
  sleep,
  withTimeout,
  parallel,
  mapAsync,
  filterAsync,
  withFallback,
  debounceAsync,
  throttleAsync
} = require('./async-pipeline');

// Sleep
await sleep(1000);

// Timeout
const result = await withTimeout(asyncOp(), 5000, 'Timeout!');

// Parallel with concurrency
const results = await parallel(asyncFunctions, 5);

// Map with concurrency
const mapped = await mapAsync(items, async (x) => x * 2, 10);

// Filter async
const filtered = await filterAsync(items, async (x) => x > 0, 5);

// Fallback on error
const value = await withFallback(riskyOp, 'default', 3000);
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level |
| `CACHE_DIR` | `./.cache` | Cache directory |
| `OUTPUT_DIR` | `./output` | Generated file output |

---

## Testing

Run the test suites:

```bash
# All tests
node test/e2e/pipeline.test.js
node test/e2e/error-logging.test.js
node test/e2e/validation.test.js
node test/e2e/performance.test.js

# Integration tests
node test/integration/run-tests.js
```

---

## Version History

- **v4.0.0** - Unified registry with O(1) lookups
- **v3.0.0** - Phase 3 complete (testing, validation, performance)
- **v2.0.0** - Accessibility automation
- **v1.0.0** - Initial code generation pipeline
