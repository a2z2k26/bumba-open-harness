# Defensive Enhancement System

**Key Principle:** Make failures observable and recoverable, not silent and destructive.

## Overview

The Defensive Enhancement System provides robust error handling, logging, verification, and reporting capabilities for the Design Bridge transformation pipeline. It ensures that failures are detected early, logged comprehensively, and provide actionable feedback.

## Modules

### 1. Pattern Compatibility (`pattern-compatibility.js`)

Validates Figma patterns against framework capabilities before transformation.

```javascript
const { checkCompatibility, getFrameworkSupport, FRAMEWORK_LIST } = require('./pattern-compatibility.js');

// Check if a pattern works with a framework
const result = checkCompatibility('auto-layout', 'flutter');
// { compatible: true, warnings: [], alternatives: [] }

// Get full support matrix for a framework
const support = getFrameworkSupport('react');
// { 'auto-layout': 'full', 'variants': 'full', ... }
```

**Use Cases:**
- Pre-flight validation before transformation
- Framework selection guidance
- Migration planning between frameworks

---

### 2. Figma Complexity Analyzer (`figma-complexity-analyzer.js`)

Analyzes Figma nodes for transformation complexity and potential issues.

```javascript
const { analyzeNode, analyzeBatch, THRESHOLDS } = require('./figma-complexity-analyzer.js');

// Analyze a single node
const result = analyzeNode(figmaNode);
// { complexity: 'medium', score: 45, concerns: ['deep-nesting'], metrics: {...} }

// Analyze multiple nodes
const batchResults = analyzeBatch([node1, node2, node3]);
```

**Complexity Levels:**
- `low` (0-25): Simple components, fast transformation
- `medium` (26-50): Standard components, normal processing
- `high` (51-75): Complex components, may need optimization
- `extreme` (76+): Very complex, consider simplification

---

### 3. Sync Logger (`sync-logger.js`)

Structured logging for sync operations with timing, categories, and summaries.

```javascript
const { createLogger, LOG_LEVELS, CATEGORIES } = require('./sync-logger.js');

const logger = createLogger({ name: 'my-operation', output: 'memory' });

// Standard logging
logger.info('Processing started', { nodeId: '1:1' });
logger.warn('Fallback used', { reason: 'pattern-unsupported' });
logger.error('Transform failed', { error: err.message });

// Timed operations
const spanId = logger.startSpan('transform');
// ... do work ...
const duration = logger.endSpan(spanId); // returns ms

// Get summary
const summary = logger.getSummary();
// { counters: { info: 5, warn: 1 }, errors: [], warnings: [...] }
```

**Log Levels:** `error`, `warn`, `info`, `debug`, `trace`

**Categories:** `sync`, `transform`, `extract`, `validate`, `file`, `network`, `cache`, `render`, `error`, `perf`

---

### 4. Render Stability (`render-stability.js`)

Ensures stable rendering before capturing or transforming.

```javascript
const { waitForStableRender, createStableTransformer } = require('./render-stability.js');

// Wait for render stability
const isStable = await waitForStableRender(getValue, {
  checkInterval: 50,
  stabilityThreshold: 100,
  maxWait: 5000
});

// Create a transformer that waits for stability
const stableTransform = createStableTransformer(myTransformFn, {
  preStabilityWait: 50,
  postStabilityWait: 100
});
```

**Use Cases:**
- Screenshot capture timing
- DOM mutation detection
- Async rendering completion

---

### 5. Graceful Degradation (`graceful-degradation.js`)

Provides fallback options when transformations fail.

```javascript
const { GracefulDegradationManager, FALLBACK_LEVELS } = require('./graceful-degradation.js');

const manager = new GracefulDegradationManager();

// Get fallback for failed transformation
const fallback = manager.degrade('auto-layout', 'react', 'high');
// Returns: { level: 'simplified', code: '...', message: '...' }

// Wrap a transformer with automatic degradation
const { wrapWithDegradation } = require('./graceful-degradation.js');
const safeTransform = wrapWithDegradation(myTransformer, {
  framework: 'react',
  maxLevel: FALLBACK_LEVELS.BASIC
});
```

**Fallback Levels:**
1. `full` - Complete transformation
2. `simplified` - Reduced features
3. `basic` - Minimal structure
4. `minimal` - Placeholder only
5. `placeholder` - Empty component
6. `none` - No fallback available

---

### 6. Canonical ID System (`canonical-id.js`)

Generates stable, content-based IDs for tracking components across syncs.

```javascript
const { createIdSystem, generateCanonicalId } = require('./canonical-id.js');

// Generate a canonical ID
const id = generateCanonicalId(node, { strategy: 'content-hash' });
// 'ch_a1b2c3d4'

// Create a full ID system with mapping
const idSystem = createIdSystem({ persistPath: './.id-mapping.json' });
idSystem.register(figmaId, canonicalId);
const resolved = idSystem.resolve(figmaId); // returns canonicalId
```

**ID Strategies:**
- `content-hash` - Based on node content
- `path-based` - Based on node path
- `semantic` - Based on name/type
- `composite` - Combination of above

---

### 7. Sync Verifier (`sync-verifier.js`)

Verifies sync status and detects drift between design and code.

```javascript
const { SyncVerifier, DriftDetector, quickVerify } = require('./sync-verifier.js');

// Quick verification
const result = quickVerify(baselineData, currentData);
// { passed: true, syncRate: 98.5, drifted: [...] }

// Full verification
const verifier = new SyncVerifier();
verifier.setBaseline('component', componentData);
const nodeResult = verifier.verifyNode('component', currentData);
// { status: 'synced', differences: [] }

// Drift detection over time
const detector = new DriftDetector();
detector.recordState(currentState);
const drift = detector.detectDrift();
// { hasDrift: false, changes: [] }
```

**Verification Status:**
- `synced` - Matches baseline
- `drifted` - Has changes
- `missing` - Not in current
- `added` - New since baseline

---

### 8. Transformation Report (`transformation-report.js`)

Collects and generates transformation reports.

```javascript
const { ReportCollector, generateReport, REPORT_FORMATS } = require('./transformation-report.js');

// Collect metrics during transformation
const collector = new ReportCollector({ framework: 'react', source: 'figma' });
collector.recordNode(node, { status: 'success' });
collector.recordWarning('Using fallback', { pattern: 'auto-layout' });
collector.recordTiming('transform', 150, { nodeCount: 10 });

// Finalize and generate report
const data = collector.finalize();
const markdown = generateReport(data, REPORT_FORMATS.MARKDOWN);
```

**Report Formats:** `json`, `markdown`, `html`, `text`

---

## CLI Integration

### sync-verify Command

```bash
# Check sync status
design-bridge sync-verify status

# Create baseline snapshot
design-bridge sync-verify baseline

# Check for drift
design-bridge sync-verify check --verbose

# Generate verification report
design-bridge sync-verify report --format markdown -o report.md
```

**Options:**
- `-p, --path <dir>` - Design directory (default: .design)
- `-f, --framework <type>` - Target framework
- `--format <type>` - Report format (json, markdown, text)
- `-o, --output <file>` - Output file
- `--verbose` - Detailed output
- `--fix` - Show fix suggestions

---

## Integration with Existing Modules

### Layout Validator

```javascript
const { LayoutValidator } = require('./layout-validator.js');

const validator = new LayoutValidator(projectPath, {
  enableLogging: true,      // Enable sync logging
  enableVerification: true, // Enable sync verification
  enableReporting: true     // Enable transformation reports
});

// Defensive status check
const status = validator.getDefensiveStatus();
// { logging: { enabled: true, active: true }, ... }
```

### Figma Transformer

```javascript
const { transformFigmaNode, createTransformer } = require('./figma-transformer.js');

// Transform with defensive enhancements
const result = transformFigmaNode(node, styles, {
  enableComplexityAnalysis: true,
  enablePatternCheck: true,
  targetFramework: 'react'
});

// result.defensiveMetadata contains analysis results

// Create isolated transformer session
const transformer = createTransformer({ sessionName: 'my-session' });
const transformed = transformer.transformNode(node);
const report = transformer.getReport();
const logs = transformer.getLogSummary();
```

---

## Testing

Run the comprehensive test suite:

```bash
cd packages/@design-bridge/server
node test-defensive-enhancements.js
```

Expected output: 98 tests passing across all 8 modules.

---

## Best Practices

1. **Always enable logging** in production for debugging
2. **Create baselines** before major design changes
3. **Check for drift** regularly in CI/CD pipelines
4. **Use complexity analysis** to identify problematic components
5. **Enable graceful degradation** for resilient transformations
6. **Generate reports** for audit trails and debugging

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CLI (cli.js)                         │
│                  sync-verify command                    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              Integration Layer                          │
│  ┌─────────────────┐  ┌─────────────────┐              │
│  │ layout-validator │  │ figma-transformer│             │
│  │ (enhanced)      │  │ (enhanced)       │             │
│  └─────────────────┘  └─────────────────┘              │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  Core Modules                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   sync-      │  │   sync-      │  │transformation│  │
│  │   logger     │  │   verifier   │  │   report     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   render-    │  │   graceful-  │  │  canonical-  │  │
│  │   stability  │  │   degradation│  │     id       │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │   pattern-   │  │    figma-    │                    │
│  │ compatibility│  │  complexity  │                    │
│  └──────────────┘  └──────────────┘                    │
└─────────────────────────────────────────────────────────┘
```

---

## Version History

- **v1.0.0** - Initial defensive enhancement system
  - 8 core modules
  - CLI sync-verify command
  - Layout validator integration
  - Figma transformer integration
