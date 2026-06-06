/**
 * Spacing System Analyzer
 * Analyzes and extracts spacing systems from design files
 * Sprint 6: Spacing System Analyzer
 */

const EventEmitter = require('events');

class SpacingAnalyzer extends EventEmitter {
  constructor() {
    super();
    this.name = 'SpacingAnalyzer';
    this.version = '1.0.0';

    // Spacing analysis configuration
    this.config = {
      gridDetectionThreshold: 0.95,
      spacingPrecision: 2,
      minSpacingValue: 2,
      maxSpacingValue: 200,
      baselineMultiples: [4, 8, 10, 12, 16]
    };

    // Common spacing systems
    this.spacingSystems = {
      material: [0, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 56, 64],
      bootstrap: [0, 4, 8, 12, 16, 20, 24, 32, 40, 48],
      tailwind: [0, 1, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64, 72, 80, 96],
      carbon: [0, 2, 4, 8, 12, 16, 24, 32, 40, 48]
    };

    // Spacing registry
    this.registry = {
      values: new Set(),
      grids: [],
      scales: [],
      tokens: new Map()
    };
  }

  /**
   * Analyze spacing in design file
   */
  async analyzeSpacing(designFile, options = {}) {
    const config = { ...this.config, ...options };

    try {
      const analysis = {
        id: this.generateAnalysisId(),
        timestamp: new Date().toISOString(),
        file: designFile.name || 'untitled',
        spacing: {
          values: await this.extractSpacingValues(designFile, config),
          grid: await this.detectGridSystem(designFile, config),
          scale: await this.detectSpacingScale(designFile, config),
          responsive: await this.analyzeResponsiveSpacing(designFile, config),
          consistency: await this.validateConsistency(designFile, config),
          tokens: await this.generateSpacingTokens(designFile, config)
        },
        recommendations: [],
        score: 0
      };

      // Generate recommendations
      analysis.recommendations = this.generateRecommendations(analysis.spacing);

      // Calculate spacing system score
      analysis.score = this.calculateSpacingScore(analysis.spacing);

      // Store analysis
      this.storeAnalysis(analysis);

      // Emit analysis complete
      this.emit('spacing:analyzed', analysis);

      return analysis;
    } catch (error) {
      this.emit('spacing:error', { designFile, error });
      throw error;
    }
  }

  /**
   * Extract all spacing values
   */
  async extractSpacingValues(designFile, config) {
    const values = {
      padding: new Set(),
      margin: new Set(),
      gap: new Set(),
      width: new Set(),
      height: new Set(),
      all: new Set()
    };

    // Extract from components
    if (designFile.components) {
      for (const component of designFile.components) {
        this.extractComponentSpacing(component, values, config);
      }
    }

    // Extract from frames
    if (designFile.frames) {
      for (const frame of designFile.frames) {
        this.extractFrameSpacing(frame, values, config);
      }
    }

    // Convert sets to arrays and sort
    const result = {};
    for (const [key, set] of Object.entries(values)) {
      result[key] = Array.from(set).sort((a, b) => a - b);
    }

    // Analyze value distribution
    result.distribution = this.analyzeValueDistribution(result.all);

    // Find common multiples
    result.baseUnit = this.findBaseUnit(result.all);

    return result;
  }

  /**
   * Extract component spacing
   */
  extractComponentSpacing(component, values, config) {
    // Extract padding
    if (component.paddingLeft !== undefined) {
      const padding = this.normalizeValue(component.paddingLeft, config);
      if (padding >= config.minSpacingValue) {
        values.padding.add(padding);
        values.all.add(padding);
      }
    }
    if (component.paddingRight !== undefined) {
      const padding = this.normalizeValue(component.paddingRight, config);
      if (padding >= config.minSpacingValue) {
        values.padding.add(padding);
        values.all.add(padding);
      }
    }
    if (component.paddingTop !== undefined) {
      const padding = this.normalizeValue(component.paddingTop, config);
      if (padding >= config.minSpacingValue) {
        values.padding.add(padding);
        values.all.add(padding);
      }
    }
    if (component.paddingBottom !== undefined) {
      const padding = this.normalizeValue(component.paddingBottom, config);
      if (padding >= config.minSpacingValue) {
        values.padding.add(padding);
        values.all.add(padding);
      }
    }

    // Extract gap/spacing
    if (component.itemSpacing !== undefined) {
      const spacing = this.normalizeValue(component.itemSpacing, config);
      if (spacing >= config.minSpacingValue) {
        values.gap.add(spacing);
        values.all.add(spacing);
      }
    }

    // Extract dimensions
    if (component.width !== undefined && component.width <= config.maxSpacingValue) {
      const width = this.normalizeValue(component.width, config);
      if (width >= config.minSpacingValue) {
        values.width.add(width);
      }
    }
    if (component.height !== undefined && component.height <= config.maxSpacingValue) {
      const height = this.normalizeValue(component.height, config);
      if (height >= config.minSpacingValue) {
        values.height.add(height);
      }
    }

    // Recursively extract from children
    if (component.children) {
      for (const child of component.children) {
        this.extractComponentSpacing(child, values, config);
      }
    }
  }

  /**
   * Extract frame spacing
   */
  extractFrameSpacing(frame, values, config) {
    // Extract frame padding
    if (frame.padding) {
      Object.values(frame.padding).forEach(value => {
        const normalized = this.normalizeValue(value, config);
        if (normalized >= config.minSpacingValue) {
          values.padding.add(normalized);
          values.all.add(normalized);
        }
      });
    }

    // Extract auto-layout spacing
    if (frame.primaryAxisSpacing !== undefined) {
      const spacing = this.normalizeValue(frame.primaryAxisSpacing, config);
      if (spacing >= config.minSpacingValue) {
        values.gap.add(spacing);
        values.all.add(spacing);
      }
    }

    if (frame.counterAxisSpacing !== undefined) {
      const spacing = this.normalizeValue(frame.counterAxisSpacing, config);
      if (spacing >= config.minSpacingValue) {
        values.gap.add(spacing);
        values.all.add(spacing);
      }
    }
  }

  /**
   * Normalize spacing value
   */
  normalizeValue(value, config) {
    return Math.round(value * Math.pow(10, config.spacingPrecision)) / Math.pow(10, config.spacingPrecision);
  }

  /**
   * Analyze value distribution
   */
  analyzeValueDistribution(values) {
    if (values.length === 0) return null;

    const sorted = [...values].sort((a, b) => a - b);

    return {
      min: sorted[0],
      max: sorted[sorted.length - 1],
      median: sorted[Math.floor(sorted.length / 2)],
      mean: sorted.reduce((a, b) => a + b, 0) / sorted.length,
      count: sorted.length,
      gaps: this.findGaps(sorted),
      clusters: this.findClusters(sorted)
    };
  }

  /**
   * Find gaps in spacing values
   */
  findGaps(values) {
    const gaps = [];

    for (let i = 1; i < values.length; i++) {
      const gap = values[i] - values[i - 1];
      if (gap > 0) {
        gaps.push({
          from: values[i - 1],
          to: values[i],
          size: gap
        });
      }
    }

    return gaps.sort((a, b) => b.size - a.size);
  }

  /**
   * Find value clusters
   */
  findClusters(values) {
    const clusters = [];
    let currentCluster = [values[0]];

    for (let i = 1; i < values.length; i++) {
      const gap = values[i] - values[i - 1];

      if (gap <= 8) {
        currentCluster.push(values[i]);
      } else {
        if (currentCluster.length > 1) {
          clusters.push({
            values: currentCluster,
            range: [currentCluster[0], currentCluster[currentCluster.length - 1]]
          });
        }
        currentCluster = [values[i]];
      }
    }

    if (currentCluster.length > 1) {
      clusters.push({
        values: currentCluster,
        range: [currentCluster[0], currentCluster[currentCluster.length - 1]]
      });
    }

    return clusters;
  }

  /**
   * Find base unit
   */
  findBaseUnit(values) {
    if (values.length < 2) return null;

    // Find GCD of all values
    const gcd = (a, b) => b === 0 ? a : gcd(b, a % b);
    const findGCD = (arr) => arr.reduce((a, b) => gcd(a, b));

    const intValues = values.map(Math.round).filter(v => v > 0);
    if (intValues.length < 2) return null;

    const baseUnit = findGCD(intValues);

    // Check against common baselines
    for (const baseline of this.config.baselineMultiples) {
      if (intValues.every(v => v % baseline === 0)) {
        return baseline;
      }
    }

    return baseUnit > 1 ? baseUnit : null;
  }

  /**
   * Detect grid system
   */
  async detectGridSystem(designFile, config) {
    const grids = {
      detected: [],
      columns: null,
      rows: null,
      gutters: [],
      margins: [],
      baseline: null
    };

    // Analyze frames for grid patterns
    if (designFile.frames) {
      for (const frame of designFile.frames) {
        const grid = this.analyzeFrameGrid(frame, config);
        if (grid) {
          grids.detected.push(grid);
        }
      }
    }

    // Determine common grid properties
    if (grids.detected.length > 0) {
      grids.columns = this.findMostCommon(grids.detected.map(g => g.columns));
      grids.gutters = this.consolidateValues(grids.detected.flatMap(g => g.gutters));
      grids.margins = this.consolidateValues(grids.detected.flatMap(g => g.margins));
      grids.baseline = this.detectBaselineGrid(grids.detected);
    }

    return grids;
  }

  /**
   * Analyze frame for grid
   */
  analyzeFrameGrid(frame, config) {
    if (!frame.children || frame.children.length < 2) return null;

    const columns = this.detectColumns(frame.children);
    const rows = this.detectRows(frame.children);

    if (!columns && !rows) return null;

    return {
      id: frame.id,
      name: frame.name,
      columns: columns?.count || 0,
      rows: rows?.count || 0,
      gutters: columns?.gaps || [],
      margins: this.detectMargins(frame),
      type: this.determineGridType(columns, rows)
    };
  }

  /**
   * Detect columns in children
   */
  detectColumns(children) {
    const xPositions = children.map(c => c.x || 0).sort((a, b) => a - b);
    const uniqueX = [...new Set(xPositions)];

    if (uniqueX.length < 2) return null;

    const gaps = [];
    for (let i = 1; i < uniqueX.length; i++) {
      gaps.push(uniqueX[i] - uniqueX[i - 1]);
    }

    const isRegular = this.isRegularSpacing(gaps);

    return {
      count: uniqueX.length,
      positions: uniqueX,
      gaps: gaps,
      regular: isRegular
    };
  }

  /**
   * Detect rows in children
   */
  detectRows(children) {
    const yPositions = children.map(c => c.y || 0).sort((a, b) => a - b);
    const uniqueY = [...new Set(yPositions)];

    if (uniqueY.length < 2) return null;

    const gaps = [];
    for (let i = 1; i < uniqueY.length; i++) {
      gaps.push(uniqueY[i] - uniqueY[i - 1]);
    }

    const isRegular = this.isRegularSpacing(gaps);

    return {
      count: uniqueY.length,
      positions: uniqueY,
      gaps: gaps,
      regular: isRegular
    };
  }

  /**
   * Check if spacing is regular
   */
  isRegularSpacing(gaps) {
    if (gaps.length < 2) return true;

    const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
    const tolerance = avgGap * 0.1;

    return gaps.every(gap => Math.abs(gap - avgGap) <= tolerance);
  }

  /**
   * Detect margins
   */
  detectMargins(frame) {
    const margins = [];

    if (frame.children && frame.children.length > 0) {
      const leftMost = Math.min(...frame.children.map(c => c.x || 0));
      const rightMost = Math.max(...frame.children.map(c => (c.x || 0) + (c.width || 0)));
      const topMost = Math.min(...frame.children.map(c => c.y || 0));
      const bottomMost = Math.max(...frame.children.map(c => (c.y || 0) + (c.height || 0)));

      if (leftMost > 0) margins.push(leftMost);
      if (frame.width && frame.width - rightMost > 0) {
        margins.push(frame.width - rightMost);
      }
      if (topMost > 0) margins.push(topMost);
      if (frame.height && frame.height - bottomMost > 0) {
        margins.push(frame.height - bottomMost);
      }
    }

    return margins;
  }

  /**
   * Determine grid type
   */
  determineGridType(columns, rows) {
    if (columns && rows) return 'modular';
    if (columns) return 'column';
    if (rows) return 'row';
    return 'custom';
  }

  /**
   * Detect baseline grid
   */
  detectBaselineGrid(grids) {
    const allGaps = grids.flatMap(g => g.gutters);
    if (allGaps.length === 0) return null;

    const baseUnit = this.findBaseUnit(allGaps);
    if (!baseUnit) return null;

    return {
      unit: baseUnit,
      multiples: allGaps.map(gap => Math.round(gap / baseUnit))
    };
  }

  /**
   * Detect spacing scale
   */
  async detectSpacingScale(designFile, config) {
    const allValues = await this.extractAllSpacingValues(designFile, config);

    if (allValues.length < 3) return null;

    const scale = {
      type: null,
      base: null,
      multiplier: null,
      values: allValues,
      formula: null,
      consistency: 0
    };

    // Check for linear scale
    const linearScale = this.checkLinearScale(allValues);
    if (linearScale.isLinear) {
      scale.type = 'linear';
      scale.base = linearScale.base;
      scale.formula = `base * n`;
      scale.consistency = linearScale.consistency;
      return scale;
    }

    // Check for exponential scale
    const exponentialScale = this.checkExponentialScale(allValues);
    if (exponentialScale.isExponential) {
      scale.type = 'exponential';
      scale.base = exponentialScale.base;
      scale.multiplier = exponentialScale.multiplier;
      scale.formula = `base * (multiplier ^ n)`;
      scale.consistency = exponentialScale.consistency;
      return scale;
    }

    // Check for fibonacci scale
    const fibonacciScale = this.checkFibonacciScale(allValues);
    if (fibonacciScale.isFibonacci) {
      scale.type = 'fibonacci';
      scale.consistency = fibonacciScale.consistency;
      scale.formula = 'F(n) = F(n-1) + F(n-2)';
      return scale;
    }

    // Check for modular scale
    const modularScale = this.checkModularScale(allValues);
    if (modularScale.isModular) {
      scale.type = 'modular';
      scale.base = modularScale.base;
      scale.multiplier = modularScale.ratio;
      scale.formula = `base * (ratio ^ n)`;
      scale.consistency = modularScale.consistency;
      return scale;
    }

    // Custom scale
    scale.type = 'custom';
    scale.consistency = 0;
    scale.pattern = this.findCustomPattern(allValues);

    return scale;
  }

  /**
   * Extract all spacing values
   */
  async extractAllSpacingValues(designFile, config) {
    const values = new Set();

    // Recursively extract from all nodes
    const extractFromNode = (node) => {
      if (node.paddingLeft !== undefined) values.add(this.normalizeValue(node.paddingLeft, config));
      if (node.paddingRight !== undefined) values.add(this.normalizeValue(node.paddingRight, config));
      if (node.paddingTop !== undefined) values.add(this.normalizeValue(node.paddingTop, config));
      if (node.paddingBottom !== undefined) values.add(this.normalizeValue(node.paddingBottom, config));
      if (node.itemSpacing !== undefined) values.add(this.normalizeValue(node.itemSpacing, config));

      if (node.children) {
        for (const child of node.children) {
          extractFromNode(child);
        }
      }
    };

    if (designFile.document) {
      extractFromNode(designFile.document);
    }

    if (designFile.components) {
      for (const component of designFile.components) {
        extractFromNode(component);
      }
    }

    return Array.from(values).filter(v => v >= config.minSpacingValue && v <= config.maxSpacingValue).sort((a, b) => a - b);
  }

  /**
   * Check for linear scale
   */
  checkLinearScale(values) {
    if (values.length < 3) return { isLinear: false };

    const differences = [];
    for (let i = 1; i < values.length; i++) {
      differences.push(values[i] - values[i - 1]);
    }

    const avgDiff = differences.reduce((a, b) => a + b, 0) / differences.length;
    const variance = differences.reduce((sum, diff) => sum + Math.pow(diff - avgDiff, 2), 0) / differences.length;
    const consistency = 1 - (Math.sqrt(variance) / avgDiff);

    return {
      isLinear: consistency > 0.9,
      base: avgDiff,
      consistency
    };
  }

  /**
   * Check for exponential scale
   */
  checkExponentialScale(values) {
    if (values.length < 3 || values[0] === 0) return { isExponential: false };

    const ratios = [];
    for (let i = 1; i < values.length; i++) {
      if (values[i - 1] !== 0) {
        ratios.push(values[i] / values[i - 1]);
      }
    }

    if (ratios.length === 0) return { isExponential: false };

    const avgRatio = ratios.reduce((a, b) => a + b, 0) / ratios.length;
    const variance = ratios.reduce((sum, ratio) => sum + Math.pow(ratio - avgRatio, 2), 0) / ratios.length;
    const consistency = 1 - (Math.sqrt(variance) / avgRatio);

    return {
      isExponential: consistency > 0.9,
      base: values[0],
      multiplier: avgRatio,
      consistency
    };
  }

  /**
   * Check for fibonacci scale
   */
  checkFibonacciScale(values) {
    if (values.length < 5) return { isFibonacci: false };

    let matches = 0;
    for (let i = 2; i < values.length; i++) {
      const expected = values[i - 1] + values[i - 2];
      const actual = values[i];
      const tolerance = expected * 0.1;

      if (Math.abs(actual - expected) <= tolerance) {
        matches++;
      }
    }

    const consistency = matches / (values.length - 2);

    return {
      isFibonacci: consistency > 0.8,
      consistency
    };
  }

  /**
   * Check for modular scale
   */
  checkModularScale(values) {
    const commonRatios = [1.067, 1.125, 1.2, 1.25, 1.333, 1.414, 1.5, 1.618];

    for (const ratio of commonRatios) {
      let matches = 0;
      const base = values[0];

      for (let i = 0; i < values.length; i++) {
        const expected = base * Math.pow(ratio, i);
        const actual = values[i];
        const tolerance = expected * 0.1;

        if (Math.abs(actual - expected) <= tolerance) {
          matches++;
        }
      }

      const consistency = matches / values.length;

      if (consistency > 0.8) {
        return {
          isModular: true,
          base,
          ratio,
          consistency
        };
      }
    }

    return { isModular: false };
  }

  /**
   * Find custom pattern
   */
  findCustomPattern(values) {
    // Analyze differences between consecutive values
    const differences = [];
    for (let i = 1; i < values.length; i++) {
      differences.push(values[i] - values[i - 1]);
    }

    // Look for repeating patterns in differences
    const patterns = [];
    for (let len = 1; len <= differences.length / 2; len++) {
      const pattern = differences.slice(0, len);
      let isPattern = true;

      for (let i = len; i < differences.length; i++) {
        if (differences[i] !== pattern[i % len]) {
          isPattern = false;
          break;
        }
      }

      if (isPattern) {
        patterns.push({
          pattern,
          length: len,
          repeats: Math.floor(differences.length / len)
        });
      }
    }

    return patterns.length > 0 ? patterns[0] : null;
  }

  /**
   * Analyze responsive spacing
   */
  async analyzeResponsiveSpacing(designFile, config) {
    const responsive = {
      breakpoints: [],
      scalingFactors: {},
      fluidSpacing: [],
      adaptiveLayouts: []
    };

    // Detect breakpoints from frame widths
    if (designFile.frames) {
      const frameWidths = designFile.frames.map(f => f.width).filter(Boolean);
      responsive.breakpoints = this.detectBreakpoints(frameWidths);
    }

    // Analyze scaling between breakpoints
    if (responsive.breakpoints.length > 1) {
      responsive.scalingFactors = this.calculateScalingFactors(responsive.breakpoints);
    }

    // Detect fluid spacing
    responsive.fluidSpacing = this.detectFluidSpacing(designFile);

    // Detect adaptive layouts
    responsive.adaptiveLayouts = this.detectAdaptiveLayouts(designFile);

    return responsive;
  }

  /**
   * Detect breakpoints
   */
  detectBreakpoints(widths) {
    const commonBreakpoints = [320, 375, 414, 768, 1024, 1280, 1440, 1920];
    const detected = [];

    for (const width of widths) {
      for (const breakpoint of commonBreakpoints) {
        if (Math.abs(width - breakpoint) < 20) {
          detected.push({
            width: breakpoint,
            actual: width,
            type: this.getBreakpointType(breakpoint)
          });
        }
      }
    }

    return [...new Set(detected.map(d => d.width))].sort((a, b) => a - b);
  }

  /**
   * Get breakpoint type
   */
  getBreakpointType(width) {
    if (width <= 414) return 'mobile';
    if (width <= 768) return 'tablet';
    if (width <= 1280) return 'desktop';
    return 'widescreen';
  }

  /**
   * Calculate scaling factors
   */
  calculateScalingFactors(breakpoints) {
    const factors = {};

    for (let i = 1; i < breakpoints.length; i++) {
      const ratio = breakpoints[i] / breakpoints[i - 1];
      factors[`${breakpoints[i - 1]}-${breakpoints[i]}`] = ratio;
    }

    return factors;
  }

  /**
   * Detect fluid spacing
   */
  detectFluidSpacing(designFile) {
    const fluid = [];

    // Look for percentage-based spacing
    if (designFile.components) {
      for (const component of designFile.components) {
        if (component.constraints) {
          const hasFluid =
            component.constraints.horizontal === 'SCALE' ||
            component.constraints.vertical === 'SCALE';

          if (hasFluid) {
            fluid.push({
              id: component.id,
              name: component.name,
              type: 'scale',
              constraints: component.constraints
            });
          }
        }
      }
    }

    return fluid;
  }

  /**
   * Detect adaptive layouts
   */
  detectAdaptiveLayouts(designFile) {
    const adaptive = [];

    // Look for layout variations at different sizes
    if (designFile.components) {
      const componentGroups = {};

      for (const component of designFile.components) {
        const baseName = this.extractBaseName(component.name);
        if (!componentGroups[baseName]) {
          componentGroups[baseName] = [];
        }
        componentGroups[baseName].push(component);
      }

      for (const [name, components] of Object.entries(componentGroups)) {
        if (components.length > 1) {
          const widths = components.map(c => c.width).filter(Boolean);
          if (new Set(widths).size > 1) {
            adaptive.push({
              name,
              variations: components.length,
              widths: widths.sort((a, b) => a - b)
            });
          }
        }
      }
    }

    return adaptive;
  }

  /**
   * Extract base name
   */
  extractBaseName(name) {
    return name.replace(/[-_\s](mobile|tablet|desktop|small|medium|large|xs|sm|md|lg|xl)/gi, '').trim();
  }

  /**
   * Validate consistency
   */
  async validateConsistency(designFile, config) {
    const validation = {
      score: 100,
      issues: [],
      warnings: [],
      suggestions: []
    };

    const allValues = await this.extractAllSpacingValues(designFile, config);

    // Check for too many unique values
    if (allValues.length > 20) {
      validation.issues.push({
        type: 'complexity',
        message: `Too many unique spacing values (${allValues.length}). Consider consolidating.`,
        severity: 'warning'
      });
      validation.score -= 15;
    }

    // Check for inconsistent base unit
    const baseUnit = this.findBaseUnit(allValues);
    if (!baseUnit) {
      validation.warnings.push({
        type: 'consistency',
        message: 'No consistent base unit found in spacing values',
        severity: 'info'
      });
      validation.score -= 10;
    }

    // Check for outliers
    const outliers = this.findOutliers(allValues);
    if (outliers.length > 0) {
      validation.warnings.push({
        type: 'outlier',
        message: `Found ${outliers.length} outlier values: ${outliers.join(', ')}`,
        severity: 'info'
      });
      validation.score -= 5;
    }

    // Generate suggestions
    if (validation.score < 90) {
      validation.suggestions = this.generateConsistencySuggestions(allValues, baseUnit);
    }

    return validation;
  }

  /**
   * Find outliers
   */
  findOutliers(values) {
    if (values.length < 4) return [];

    const sorted = [...values].sort((a, b) => a - b);
    const q1 = sorted[Math.floor(sorted.length * 0.25)];
    const q3 = sorted[Math.floor(sorted.length * 0.75)];
    const iqr = q3 - q1;
    const lowerBound = q1 - 1.5 * iqr;
    const upperBound = q3 + 1.5 * iqr;

    return sorted.filter(v => v < lowerBound || v > upperBound);
  }

  /**
   * Generate consistency suggestions
   */
  generateConsistencySuggestions(values, baseUnit) {
    const suggestions = [];

    if (!baseUnit) {
      suggestions.push({
        type: 'base-unit',
        message: 'Consider establishing a base unit (e.g., 4px or 8px) for spacing',
        recommendation: 8
      });
    }

    if (values.length > 20) {
      suggestions.push({
        type: 'consolidation',
        message: 'Consider consolidating spacing values to a smaller set',
        recommendation: this.suggestConsolidatedScale(values)
      });
    }

    return suggestions;
  }

  /**
   * Suggest consolidated scale
   */
  suggestConsolidatedScale(values) {
    const base = 8;
    const scale = [];

    for (let i = 0; i <= 10; i++) {
      scale.push(base * Math.pow(1.5, i));
    }

    return scale.map(Math.round);
  }

  /**
   * Generate spacing tokens
   */
  async generateSpacingTokens(designFile, config) {
    const values = await this.extractAllSpacingValues(designFile, config);
    const tokens = new Map();

    // Generate token names
    for (let i = 0; i < values.length; i++) {
      const value = values[i];
      const name = this.generateTokenName(value, i);

      tokens.set(name, {
        value,
        pixel: `${value}px`,
        rem: `${value / 16}rem`,
        usage: []
      });
    }

    return {
      tokens: Array.from(tokens.entries()).map(([name, data]) => ({ name, ...data })),
      format: this.generateTokenFormats(tokens)
    };
  }

  /**
   * Generate token name
   */
  generateTokenName(value, index) {
    // Try to match common naming patterns
    const commonNames = {
      0: 'none',
      2: '2xs',
      4: 'xs',
      8: 'sm',
      12: 'md',
      16: 'lg',
      20: 'xl',
      24: '2xl',
      32: '3xl',
      40: '4xl',
      48: '5xl',
      56: '6xl',
      64: '7xl'
    };

    if (commonNames[value]) {
      return `spacing-${commonNames[value]}`;
    }

    return `spacing-${index}`;
  }

  /**
   * Generate token formats
   */
  generateTokenFormats(tokens) {
    const formats = {};

    // CSS Custom Properties
    formats.css = Array.from(tokens.entries())
      .map(([name, data]) => `--${name}: ${data.pixel};`)
      .join('\n');

    // SCSS Variables
    formats.scss = Array.from(tokens.entries())
      .map(([name, data]) => `$${name}: ${data.pixel};`)
      .join('\n');

    // JavaScript Object
    formats.js = `export const spacing = {\n${
      Array.from(tokens.entries())
        .map(([name, data]) => `  '${name}': '${data.pixel}'`)
        .join(',\n')
    }\n};`;

    // JSON
    formats.json = JSON.stringify(
      Object.fromEntries(
        Array.from(tokens.entries()).map(([name, data]) => [name, data.value])
      ),
      null,
      2
    );

    return formats;
  }

  /**
   * Generate recommendations
   */
  generateRecommendations(spacing) {
    const recommendations = [];

    // Check spacing scale
    if (!spacing.scale || spacing.scale.type === 'custom') {
      recommendations.push({
        type: 'scale',
        priority: 'high',
        message: 'Consider adopting a consistent spacing scale',
        suggestion: 'Use a linear (8px base) or modular (1.5 ratio) scale'
      });
    }

    // Check grid system
    if (!spacing.grid.detected || spacing.grid.detected.length === 0) {
      recommendations.push({
        type: 'grid',
        priority: 'medium',
        message: 'No grid system detected',
        suggestion: 'Implement a column grid for consistent layouts'
      });
    }

    // Check responsive spacing
    if (spacing.responsive.breakpoints.length < 3) {
      recommendations.push({
        type: 'responsive',
        priority: 'medium',
        message: 'Limited responsive breakpoints detected',
        suggestion: 'Define mobile, tablet, and desktop breakpoints'
      });
    }

    // Check consistency
    if (spacing.consistency.score < 80) {
      recommendations.push({
        type: 'consistency',
        priority: 'high',
        message: `Spacing consistency score is low (${spacing.consistency.score})`,
        suggestion: 'Review and consolidate spacing values'
      });
    }

    return recommendations;
  }

  /**
   * Calculate spacing score
   */
  calculateSpacingScore(spacing) {
    let score = 100;

    // Deduct for inconsistent scale
    if (!spacing.scale || spacing.scale.type === 'custom') {
      score -= 20;
    } else if (spacing.scale.consistency < 0.9) {
      score -= 10;
    }

    // Deduct for no grid
    if (!spacing.grid.detected || spacing.grid.detected.length === 0) {
      score -= 15;
    }

    // Deduct for poor consistency
    if (spacing.consistency.score < 80) {
      score -= (100 - spacing.consistency.score) / 2;
    }

    // Add for responsive features
    if (spacing.responsive.breakpoints.length >= 3) {
      score += 5;
    }

    // Add for proper tokens
    if (spacing.tokens && spacing.tokens.tokens.length > 0) {
      score += 5;
    }

    return Math.max(0, Math.min(100, score));
  }

  /**
   * Helper: Find most common value
   */
  findMostCommon(arr) {
    if (!arr || arr.length === 0) return null;

    const counts = {};
    for (const item of arr) {
      counts[item] = (counts[item] || 0) + 1;
    }

    let maxCount = 0;
    let mostCommon = null;

    for (const [item, count] of Object.entries(counts)) {
      if (count > maxCount) {
        maxCount = count;
        mostCommon = item;
      }
    }

    return mostCommon;
  }

  /**
   * Helper: Consolidate values
   */
  consolidateValues(values) {
    return [...new Set(values)].sort((a, b) => a - b);
  }

  /**
   * Store analysis
   */
  storeAnalysis(analysis) {
    this.registry.values = new Set([...this.registry.values, ...analysis.spacing.values.all]);

    if (analysis.spacing.grid.detected) {
      this.registry.grids.push(...analysis.spacing.grid.detected);
    }

    if (analysis.spacing.scale) {
      this.registry.scales.push(analysis.spacing.scale);
    }

    if (analysis.spacing.tokens) {
      for (const token of analysis.spacing.tokens.tokens) {
        this.registry.tokens.set(token.name, token);
      }
    }
  }

  /**
   * Generate analysis ID
   */
  generateAnalysisId() {
    return `spacing-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * Export spacing system
   */
  exportSpacingSystem(format = 'json') {
    const system = {
      values: Array.from(this.registry.values),
      grids: this.registry.grids,
      scales: this.registry.scales,
      tokens: Array.from(this.registry.tokens.values())
    };

    switch (format) {
      case 'json':
        return JSON.stringify(system, null, 2);
      case 'css':
        return this.exportAsCSS(system);
      case 'scss':
        return this.exportAsSCSS(system);
      case 'js':
        return this.exportAsJS(system);
      default:
        return system;
    }
  }

  /**
   * Export as CSS
   */
  exportAsCSS(system) {
    let css = ':root {\n';

    for (const token of system.tokens) {
      css += `  --${token.name}: ${token.pixel};\n`;
    }

    css += '}\n';
    return css;
  }

  /**
   * Export as SCSS
   */
  exportAsSCSS(system) {
    let scss = '// Spacing System\n\n';

    for (const token of system.tokens) {
      scss += `$${token.name}: ${token.pixel};\n`;
    }

    return scss;
  }

  /**
   * Export as JS
   */
  exportAsJS(system) {
    return `export const spacingSystem = ${JSON.stringify(system, null, 2)};`;
  }
}

module.exports = SpacingAnalyzer;