/**
 * Quality Metrics Extended - Additional quality assessment methods
 * Extends QualityMetrics with specialized analysis algorithms
 */

const QualityMetrics = require('./quality-metrics');

class QualityMetricsExtended extends QualityMetrics {

  // Color analysis methods
  groupColorsByShades(colors) {
    const groups = {};

    Object.entries(colors).forEach(([name, color]) => {
      const baseName = name.replace(/[-_]?\d+$/, '').replace(/[-_]?(light|dark|pale|deep)$/i, '');
      if (!groups[baseName]) groups[baseName] = [];
      groups[baseName].push({ name, color });
    });

    return groups;
  }

  calculateShadeConsistency(shadeGroups) {
    let totalConsistency = 0;
    let groupCount = 0;

    Object.values(shadeGroups).forEach(group => {
      if (group.length > 1) {
        groupCount++;
        const shadeNumbers = group
          .map(item => this.extractShadeNumber(item.name))
          .filter(num => num !== null)
          .sort((a, b) => a - b);

        if (shadeNumbers.length > 1) {
          // Check if shades follow expected pattern (50, 100, 200, etc.)
          const expectedShades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];
          const matchingShades = shadeNumbers.filter(shade => expectedShades.includes(shade));
          totalConsistency += matchingShades.length / shadeNumbers.length;
        }
      }
    });

    return groupCount > 0 ? totalConsistency / groupCount : 1;
  }

  extractShadeNumber(colorName) {
    const match = colorName.match(/(\d+)$/);
    return match ? parseInt(match[1]) : null;
  }

  areColorsRelated(name1, name2, color1, color2) {
    // Check if color names suggest they should be related
    const baseName1 = name1.replace(/[-_]?\d+$/, '').toLowerCase();
    const baseName2 = name2.replace(/[-_]?\d+$/, '').toLowerCase();

    if (baseName1 !== baseName2) return true; // Different color families are okay

    // If same base name, check if their values are consistently related
    const hue1 = this.extractHue(color1);
    const hue2 = this.extractHue(color2);

    return Math.abs(hue1 - hue2) < 30 || Math.abs(hue1 - hue2) > 330; // Similar hues
  }

  extractHue(color) {
    if (color.hsl) return color.hsl.h;
    if (color.rgb) {
      const { r, g, b } = color.rgb;
      return this.rgbToHsl(r, g, b).h;
    }
    return 0;
  }

  rgbToHsl(r, g, b) {
    r /= 255;
    g /= 255;
    b /= 255;

    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h, s, l;

    l = (max + min) / 2;

    if (max === min) {
      h = s = 0; // achromatic
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);

      switch (max) {
        case r: h = (g - b) / d + (g < b ? 6 : 0); break;
        case g: h = (b - r) / d + 2; break;
        case b: h = (r - g) / d + 4; break;
      }
      h /= 6;
    }

    return { h: h * 360, s: s * 100, l: l * 100 };
  }

  // Spacing analysis methods
  detectProgression(values) {
    if (values.length < 3) return { type: 'insufficient_data', pattern: null };

    // Check for arithmetic progression
    const differences = [];
    for (let i = 1; i < values.length; i++) {
      differences.push(values[i] - values[i - 1]);
    }

    const avgDifference = differences.reduce((sum, diff) => sum + diff, 0) / differences.length;
    const isArithmetic = differences.every(diff => Math.abs(diff - avgDifference) < avgDifference * 0.2);

    if (isArithmetic) {
      return { type: 'arithmetic', pattern: avgDifference };
    }

    // Check for geometric progression
    const ratios = [];
    for (let i = 1; i < values.length; i++) {
      if (values[i - 1] !== 0) {
        ratios.push(values[i] / values[i - 1]);
      }
    }

    if (ratios.length > 0) {
      const avgRatio = ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
      const isGeometric = ratios.every(ratio => Math.abs(ratio - avgRatio) < avgRatio * 0.2);

      if (isGeometric) {
        return { type: 'geometric', pattern: avgRatio };
      }
    }

    // Check for modular scale
    const modularScales = [1.125, 1.2, 1.25, 1.333, 1.414, 1.5, 1.618, 1.667, 1.778, 1.875, 2];
    for (const scale of modularScales) {
      if (this.fitsModularScale(values, scale)) {
        return { type: 'modular', pattern: scale };
      }
    }

    return { type: 'irregular', pattern: null };
  }

  fitsModularScale(values, scale) {
    if (values.length < 3) return false;

    const baseValue = values[0];
    let fits = 0;

    for (let i = 1; i < values.length; i++) {
      const expectedValue = baseValue * Math.pow(scale, i);
      if (Math.abs(values[i] - expectedValue) < expectedValue * 0.15) {
        fits++;
      }
    }

    return fits / (values.length - 1) > 0.7;
  }

  calculateProgressionConsistency(values, progression) {
    if (progression.type === 'insufficient_data' || progression.type === 'irregular') {
      return 0.3; // Low score for irregular patterns
    }

    if (progression.type === 'arithmetic') {
      const differences = [];
      for (let i = 1; i < values.length; i++) {
        differences.push(values[i] - values[i - 1]);
      }

      const avgDiff = progression.pattern;
      const consistentDiffs = differences.filter(diff =>
        Math.abs(diff - avgDiff) < avgDiff * 0.1
      ).length;

      return consistentDiffs / differences.length;
    }

    if (progression.type === 'geometric' || progression.type === 'modular') {
      // Similar logic for geometric/modular scales
      return 0.8; // Simplified for now
    }

    return 0.5;
  }

  checkScaleAdherence(values) {
    const commonScales = {
      '4pt': [4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48],
      '8pt': [8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96],
      'tailwind': [4, 8, 12, 16, 20, 24, 32, 40, 48, 56, 64, 80, 96],
      'bootstrap': [4, 8, 16, 24, 48] // rem * 16
    };

    let bestScale = null;
    let bestScore = 0;

    Object.entries(commonScales).forEach(([scaleName, scaleValues]) => {
      const matches = values.filter(value =>
        scaleValues.some(scaleValue => Math.abs(value - scaleValue) < 2)
      ).length;

      const score = matches / values.length;
      if (score > bestScore) {
        bestScore = score;
        bestScale = scaleName;
      }
    });

    return {
      score: bestScore,
      recommendedScale: bestScale,
      adherence: bestScore
    };
  }

  findSpacingOutliers(values, progression) {
    if (progression.type === 'irregular') return [];

    const outliers = [];

    if (progression.type === 'arithmetic') {
      const expectedDiff = progression.pattern;
      for (let i = 1; i < values.length; i++) {
        const actualDiff = values[i] - values[i - 1];
        if (Math.abs(actualDiff - expectedDiff) > expectedDiff * 0.2) {
          outliers.push({
            value: values[i],
            expected: values[i - 1] + expectedDiff,
            difference: Math.abs(actualDiff - expectedDiff)
          });
        }
      }
    }

    return outliers;
  }

  // Typography analysis methods
  analyzeTypographicScale(fontSizes) {
    if (!fontSizes || fontSizes.length === 0) {
      return { score: 1, scale: null, consistency: 'no_data' };
    }

    const validSizes = fontSizes.filter(size => size !== null).sort((a, b) => a - b);

    if (validSizes.length < 3) {
      return { score: 0.7, scale: 'insufficient_data', consistency: 'limited' };
    }

    // Common typographic scales
    const typographicScales = {
      'minor-second': 1.067,
      'major-second': 1.125,
      'minor-third': 1.2,
      'major-third': 1.25,
      'perfect-fourth': 1.333,
      'augmented-fourth': 1.414,
      'perfect-fifth': 1.5,
      'golden-ratio': 1.618
    };

    let bestMatch = null;
    let bestScore = 0;

    Object.entries(typographicScales).forEach(([scaleName, ratio]) => {
      const consistency = this.calculateTypeScaleConsistency(validSizes, ratio);
      if (consistency > bestScore) {
        bestScore = consistency;
        bestMatch = scaleName;
      }
    });

    return {
      score: bestScore,
      scale: bestMatch,
      consistency: bestScore > 0.8 ? 'excellent' : bestScore > 0.6 ? 'good' : 'poor',
      sizes: validSizes.length,
      recommendations: this.generateTypeScaleRecommendations(validSizes, bestMatch, bestScore)
    };
  }

  calculateTypeScaleConsistency(sizes, ratio) {
    if (sizes.length < 2) return 0;

    let consistentSteps = 0;
    const baseSize = sizes[0];

    for (let i = 1; i < sizes.length; i++) {
      const expectedSize = baseSize * Math.pow(ratio, i);
      const actualSize = sizes[i];

      if (Math.abs(actualSize - expectedSize) < expectedSize * 0.15) {
        consistentSteps++;
      }
    }

    return consistentSteps / (sizes.length - 1);
  }

  analyzeLineHeightConsistency(lineHeights, fontSizes) {
    if (!lineHeights || lineHeights.length === 0) {
      return { score: 1, pattern: 'no_data' };
    }

    const validLineHeights = lineHeights.filter(lh => lh !== null);

    if (validLineHeights.length === 0) {
      return { score: 1, pattern: 'no_data' };
    }

    // Check for consistent ratios
    const ratios = [];
    if (fontSizes && fontSizes.length === lineHeights.length) {
      for (let i = 0; i < fontSizes.length; i++) {
        if (fontSizes[i] && lineHeights[i]) {
          ratios.push(lineHeights[i] / fontSizes[i]);
        }
      }
    }

    if (ratios.length > 0) {
      const avgRatio = ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
      const consistentRatios = ratios.filter(ratio =>
        Math.abs(ratio - avgRatio) < 0.2
      ).length;

      return {
        score: consistentRatios / ratios.length,
        pattern: 'ratio-based',
        avgRatio: Math.round(avgRatio * 100) / 100,
        consistency: consistentRatios / ratios.length
      };
    }

    // Check for consistent absolute values
    const avgLineHeight = validLineHeights.reduce((sum, lh) => sum + lh, 0) / validLineHeights.length;
    const consistentValues = validLineHeights.filter(lh =>
      Math.abs(lh - avgLineHeight) < avgLineHeight * 0.1
    ).length;

    return {
      score: consistentValues / validLineHeights.length,
      pattern: 'absolute',
      avgValue: Math.round(avgLineHeight * 100) / 100,
      consistency: consistentValues / validLineHeights.length
    };
  }

  analyzeFontWeightConsistency(fontWeights) {
    if (!fontWeights || fontWeights.length === 0) {
      return { score: 1, weights: [] };
    }

    const validWeights = fontWeights.filter(fw => fw !== null);

    if (validWeights.length === 0) {
      return { score: 1, weights: [] };
    }

    // Standard font weights
    const standardWeights = [100, 200, 300, 400, 500, 600, 700, 800, 900];

    const standardCompliant = validWeights.filter(weight =>
      standardWeights.includes(weight)
    ).length;

    const score = standardCompliant / validWeights.length;

    return {
      score,
      weights: [...new Set(validWeights)].sort((a, b) => a - b),
      standardCompliant,
      total: validWeights.length,
      nonStandard: validWeights.filter(weight => !standardWeights.includes(weight))
    };
  }

  // Accessibility analysis methods
  generateContrastPairs(colors) {
    const pairs = [];
    const colorEntries = Object.entries(colors);

    // Generate likely foreground/background combinations
    const foregroundColors = colorEntries.filter(([name]) =>
      /text|foreground|fg|color(?!-bg)/.test(name.toLowerCase())
    );

    const backgroundColors = colorEntries.filter(([name]) =>
      /bg|background|surface|fill/.test(name.toLowerCase())
    );

    // If no specific fg/bg colors found, use all combinations
    const fgColors = foregroundColors.length > 0 ? foregroundColors : colorEntries;
    const bgColors = backgroundColors.length > 0 ? backgroundColors : colorEntries;

    fgColors.forEach(([fgName, fgColor]) => {
      bgColors.forEach(([bgName, bgColor]) => {
        if (fgName !== bgName) {
          const ratio = this.calculateContrastRatio(fgColor, bgColor);
          pairs.push({
            foreground: fgName,
            background: bgName,
            ratio,
            isLargeText: this.isLargeTextPair(fgName, bgName),
            wcagAA: ratio >= 4.5,
            wcagAAA: ratio >= 7.0
          });
        }
      });
    });

    return pairs;
  }

  calculateContrastRatio(color1, color2) {
    const l1 = this.getLuminance(color1);
    const l2 = this.getLuminance(color2);

    const lighter = Math.max(l1, l2);
    const darker = Math.min(l1, l2);

    return (lighter + 0.05) / (darker + 0.05);
  }

  getLuminance(color) {
    if (color.luminance) return color.luminance;

    let r, g, b;

    if (color.rgb) {
      ({ r, g, b } = color.rgb);
    } else if (color.hex) {
      const rgb = this.hexToRgb(color.hex);
      ({ r, g, b } = rgb);
    } else {
      return 0.5; // Default luminance
    }

    // Normalize RGB values
    r = r / 255;
    g = g / 255;
    b = b / 255;

    // Apply gamma correction
    r = r <= 0.03928 ? r / 12.92 : Math.pow((r + 0.055) / 1.055, 2.4);
    g = g <= 0.03928 ? g / 12.92 : Math.pow((g + 0.055) / 1.055, 2.4);
    b = b <= 0.03928 ? b / 12.92 : Math.pow((b + 0.055) / 1.055, 2.4);

    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? {
      r: parseInt(result[1], 16),
      g: parseInt(result[2], 16),
      b: parseInt(result[3], 16)
    } : { r: 0, g: 0, b: 0 };
  }

  isLargeTextPair(fgName, bgName) {
    const largeTextPatterns = [
      /large|big|xl|heading|title|h[1-6]|display/i
    ];

    return largeTextPatterns.some(pattern =>
      pattern.test(fgName) || pattern.test(bgName)
    );
  }

  simulateColorBlindness(colors, type) {
    // Simplified color blindness simulation
    const transformations = {
      protanopia: { r: [0.567, 0.433, 0], g: [0.558, 0.442, 0], b: [0, 0.242, 0.758] },
      deuteranopia: { r: [0.625, 0.375, 0], g: [0.7, 0.3, 0], b: [0, 0.3, 0.7] },
      tritanopia: { r: [0.95, 0.05, 0], g: [0, 0.433, 0.567], b: [0, 0.475, 0.525] }
    };

    const transform = transformations[type];
    if (!transform) return colors;

    const simulatedColors = {};

    Object.entries(colors).forEach(([name, color]) => {
      if (color.rgb) {
        const { r, g, b } = color.rgb;
        simulatedColors[name] = {
          ...color,
          rgb: {
            r: Math.round(r * transform.r[0] + g * transform.r[1] + b * transform.r[2]),
            g: Math.round(r * transform.g[0] + g * transform.g[1] + b * transform.g[2]),
            b: Math.round(r * transform.b[0] + g * transform.b[1] + b * transform.b[2])
          }
        };
      } else {
        simulatedColors[name] = color;
      }
    });

    return simulatedColors;
  }

  calculateColorDistinguishability(originalColors, simulatedColors) {
    const results = {
      overall: 0,
      byType: {},
      criticalIssues: []
    };

    Object.keys(simulatedColors).forEach(type => {
      const simulated = simulatedColors[type];
      let distinguishablePairs = 0;
      let totalPairs = 0;

      const colorNames = Object.keys(originalColors);

      for (let i = 0; i < colorNames.length; i++) {
        for (let j = i + 1; j < colorNames.length; j++) {
          totalPairs++;

          const color1 = simulated[colorNames[i]];
          const color2 = simulated[colorNames[j]];

          const distance = this.calculateColorDistance(color1, color2);

          if (distance > 20) { // Threshold for distinguishability
            distinguishablePairs++;
          } else {
            results.criticalIssues.push({
              type,
              colors: [colorNames[i], colorNames[j]],
              distance,
              severity: distance < 10 ? 'high' : 'medium'
            });
          }
        }
      }

      results.byType[type] = totalPairs > 0 ? distinguishablePairs / totalPairs : 1;
    });

    results.overall = Object.values(results.byType).reduce((sum, score) => sum + score, 0) / Object.keys(results.byType).length;

    return results;
  }

  calculateColorDistance(color1, color2) {
    if (!color1?.rgb || !color2?.rgb) return 100; // Assume distinguishable if no RGB data

    const { r: r1, g: g1, b: b1 } = color1.rgb;
    const { r: r2, g: g2, b: b2 } = color2.rgb;

    return Math.sqrt(
      Math.pow(r2 - r1, 2) +
      Math.pow(g2 - g1, 2) +
      Math.pow(b2 - b1, 2)
    );
  }

  // Additional utility methods
  generateContrastRecommendations(contrastPairs) {
    const violations = contrastPairs.filter(pair => !pair.wcagAA);

    return violations.map(violation => ({
      type: 'contrast',
      severity: violation.ratio < 3 ? 'high' : 'medium',
      foreground: violation.foreground,
      background: violation.background,
      currentRatio: Math.round(violation.ratio * 100) / 100,
      targetRatio: violation.isLargeText ? 3.0 : 4.5,
      recommendation: this.generateContrastFix(violation)
    }));
  }

  generateContrastFix(violation) {
    const targetRatio = violation.isLargeText ? 3.0 : 4.5;
    const improvementNeeded = targetRatio / violation.ratio;

    if (improvementNeeded > 2) {
      return 'Consider using a completely different color combination';
    } else if (improvementNeeded > 1.5) {
      return 'Significantly darken the foreground or lighten the background';
    } else {
      return 'Slightly adjust color values to improve contrast';
    }
  }

  generateTypeScaleRecommendations(sizes, bestMatch, score) {
    const recommendations = [];

    if (score < 0.6) {
      recommendations.push('Consider adopting a consistent typographic scale');
      if (bestMatch) {
        recommendations.push(`The ${bestMatch} scale (ratio: ${this.getScaleRatio(bestMatch)}) shows the best fit`);
      }
    }

    if (sizes.length < 5) {
      recommendations.push('Consider adding more font sizes for better hierarchical options');
    }

    if (sizes.length > 10) {
      recommendations.push('Consider reducing the number of font sizes to improve consistency');
    }

    return recommendations;
  }

  getScaleRatio(scaleName) {
    const ratios = {
      'minor-second': 1.067,
      'major-second': 1.125,
      'minor-third': 1.2,
      'major-third': 1.25,
      'perfect-fourth': 1.333,
      'augmented-fourth': 1.414,
      'perfect-fifth': 1.5,
      'golden-ratio': 1.618
    };

    return ratios[scaleName] || 1.25;
  }
}

module.exports = QualityMetricsExtended;