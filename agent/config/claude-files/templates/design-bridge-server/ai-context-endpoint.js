/**
 * AI Context Endpoint for Design System
 * Provides comprehensive context API for AI partners to understand and use the design system
 */

const ComponentSchemaSystem = require('./component-schemas');
const TokenSemanticsLayer = require('./token-semantics');
const TokenNormalizer = require('./token-normalizer');
const fs = require('fs').promises;
const path = require('path');

class AIContextEndpoint {
  constructor() {
    this.componentSchemas = new ComponentSchemaSystem();
    this.tokenSemantics = new TokenSemanticsLayer();
    this.tokenNormalizer = new TokenNormalizer();
    this.contextCache = new Map();
  }

  /**
   * Get complete AI context for the design system
   */
  async getCompleteContext() {
    const cacheKey = 'complete-context';
    if (this.contextCache.has(cacheKey)) {
      return this.contextCache.get(cacheKey);
    }

    const context = {
      metadata: this.getSystemMetadata(),
      tokens: await this.getTokenContext(),
      components: this.getComponentContext(),
      patterns: this.getPatternContext(),
      guidelines: this.getDesignGuidelines(),
      codeGeneration: this.getCodeGenerationRules(),
      relationships: this.getSystemRelationships()
    };

    this.contextCache.set(cacheKey, context);
    return context;
  }

  /**
   * Get system metadata
   */
  getSystemMetadata() {
    return {
      name: 'BUMBA CLI 1.0 Design System',
      version: '1.0.0',
      framework: 'shadcn/ui',
      baseLibrary: 'Radix UI',
      styling: 'Tailwind CSS',
      brand: {
        gradient: ['#00AA00', '#FFDD00', '#DD0000'],
        identity: 'Dynamic, creative, bold',
        voice: 'Professional yet approachable'
      },
      aiPartnership: {
        level: 'Full integration',
        capabilities: ['Component generation', 'Token application', 'Pattern recognition', 'Accessibility validation'],
        optimization: 'Semantic preservation and context awareness'
      }
    };
  }

  /**
   * Get token context with semantics
   */
  async getTokenContext() {
    try {
      const tokensPath = path.join(process.cwd(), 'test-catalog', 'tokens.json');
      const tokensData = await fs.readFile(tokensPath, 'utf-8');
      const tokens = JSON.parse(tokensData);
      const normalized = this.tokenNormalizer.normalize(tokens);

      const tokenContext = {};
      for (const [category, categoryTokens] of Object.entries(normalized)) {
        tokenContext[category] = {
          values: categoryTokens,
          semantics: {},
          relationships: []
        };

        for (const tokenName of Object.keys(categoryTokens)) {
          const semantics = this.tokenSemantics.getTokenSemantics(category, tokenName);
          if (semantics) {
            tokenContext[category].semantics[tokenName] = semantics;
          }
        }

        tokenContext[category].relationships = this.tokenSemantics.getCategoryRelationships(category);
      }

      return tokenContext;
    } catch (error) {
      return {
        error: 'Unable to load tokens',
        fallback: this.getDefaultTokens()
      };
    }
  }

  /**
   * Get component context with schemas
   */
  getComponentContext() {
    const schemas = this.componentSchemas.getAllSchemas();
    const componentContext = {};

    for (const [componentName, schema] of Object.entries(schemas)) {
      componentContext[componentName] = {
        ...schema,
        aiContext: this.componentSchemas.generateAIContext(componentName),
        typescript: this.componentSchemas.generateTypeScriptInterface(componentName),
        usagePatterns: this.getComponentUsagePatterns(componentName),
        commonMistakes: this.getCommonMistakes(componentName)
      };
    }

    return componentContext;
  }

  /**
   * Get pattern context
   */
  getPatternContext() {
    return {
      forms: {
        description: 'Form construction patterns',
        components: ['Input', 'Select', 'Checkbox', 'Radio', 'Button'],
        structure: {
          container: 'Form or div',
          layout: 'Vertical stack with consistent spacing',
          validation: 'Inline error messages below fields',
          submission: 'Primary button at bottom right'
        },
        accessibility: {
          labels: 'Required for all inputs',
          errors: 'Associated with aria-describedby',
          requiredFields: 'Marked with aria-required'
        }
      },
      navigation: {
        description: 'Navigation patterns',
        components: ['NavigationMenu', 'Tabs', 'Breadcrumb', 'Sidebar'],
        structure: {
          hierarchy: 'Clear parent-child relationships',
          activeStates: 'Visual indication of current location',
          responsive: 'Mobile-first with hamburger menu'
        }
      },
      dataDisplay: {
        description: 'Data presentation patterns',
        components: ['Table', 'Card', 'List', 'DataTable'],
        structure: {
          headers: 'Clear column/section headers',
          sorting: 'Interactive column headers',
          pagination: 'Bottom-right placement',
          loading: 'Skeleton states during fetch'
        }
      },
      feedback: {
        description: 'User feedback patterns',
        components: ['Alert', 'Toast', 'Dialog', 'AlertDialog'],
        structure: {
          success: 'Green with checkmark icon',
          error: 'Red with X icon',
          warning: 'Yellow with warning icon',
          info: 'Blue with info icon'
        }
      }
    };
  }

  /**
   * Get design guidelines for AI
   */
  getDesignGuidelines() {
    return {
      spacing: {
        rule: 'Use consistent spacing scale',
        values: ['0', '1', '2', '4', '8'],
        application: {
          withinComponent: '1-2 units',
          betweenComponents: '4 units',
          sectionSeparation: '8 units'
        }
      },
      color: {
        rule: 'Maintain WCAG AA compliance',
        primary: 'Use for key actions and brand moments',
        semantic: {
          success: 'Positive feedback only',
          error: 'Validation and errors only',
          warning: 'Caution states only'
        },
        contrast: 'Minimum 4.5:1 for normal text'
      },
      typography: {
        rule: 'Maintain clear hierarchy',
        h1: 'One per page, page title',
        h2: 'Section headers',
        body: 'Default for content',
        lineLength: '45-75 characters ideal'
      },
      interaction: {
        touchTargets: 'Minimum 44x44px',
        hoverStates: 'All interactive elements',
        focusIndicators: 'Visible keyboard navigation',
        loading: 'Show feedback for actions >300ms'
      }
    };
  }

  /**
   * Get code generation rules
   */
  getCodeGenerationRules() {
    return {
      imports: {
        pattern: "import { Component } from '@/components/ui/component'",
        rule: 'Always use aliased imports from @/components/ui'
      },
      composition: {
        pattern: 'Use compound components when available',
        example: '<Card><CardHeader><CardTitle>Title</CardTitle></CardHeader></Card>'
      },
      props: {
        pattern: 'Use explicit props over classNames when available',
        example: 'variant="primary" not className="btn-primary"'
      },
      accessibility: {
        pattern: 'Always include ARIA attributes',
        labels: 'Required for icon-only buttons',
        descriptions: 'For complex interactions',
        live: 'For dynamic content updates'
      },
      styling: {
        pattern: 'Tailwind utilities for custom styling',
        avoid: 'Inline styles except for dynamic values',
        extend: 'Use cn() utility for conditional classes'
      }
    };
  }

  /**
   * Get system relationships
   */
  getSystemRelationships() {
    return {
      tokenToComponent: {
        'spacing-4': ['Button padding', 'Card padding', 'Input padding'],
        'primary-500': ['Button primary', 'Link color', 'Focus rings'],
        'heading-1': ['Page titles', 'Hero sections']
      },
      componentDependencies: {
        Dialog: ['Portal', 'Overlay', 'Button'],
        Select: ['Popover', 'Command', 'Button'],
        DataTable: ['Table', 'Button', 'Input', 'Select']
      },
      patternComposition: {
        'Login Form': ['Card', 'Input', 'Button', 'Label', 'Alert'],
        'Data Grid': ['DataTable', 'Input', 'Select', 'Button', 'Pagination'],
        'Settings Panel': ['Tabs', 'Card', 'Switch', 'Button', 'Input']
      }
    };
  }

  /**
   * Get component usage patterns
   */
  getComponentUsagePatterns(componentName) {
    const patterns = {
      Button: [
        'Primary CTA: variant="default" size="default"',
        'Secondary action: variant="outline"',
        'Danger action: variant="destructive"',
        'Icon only: size="icon" with aria-label'
      ],
      Input: [
        'With label: <Label htmlFor="id">Text</Label><Input id="id" />',
        'With error: <Input aria-invalid="true" aria-describedby="error-id" />',
        'Disabled state: <Input disabled />',
        'With placeholder: <Input placeholder="Enter text..." />'
      ],
      Select: [
        'Basic: <Select><SelectTrigger>...</SelectTrigger><SelectContent>...</SelectContent></Select>',
        'With placeholder: <SelectValue placeholder="Choose..." />',
        'Controlled: value={value} onValueChange={setValue}'
      ]
    };

    return patterns[componentName] || [];
  }

  /**
   * Get common mistakes to avoid
   */
  getCommonMistakes(componentName) {
    const mistakes = {
      Button: [
        'Missing aria-label on icon-only buttons',
        'Using div with onClick instead of Button',
        'Nesting interactive elements inside buttons'
      ],
      Input: [
        'Missing associated Label',
        'No error message association',
        'Using placeholder as label'
      ],
      Dialog: [
        'Missing DialogTitle for accessibility',
        'Not handling escape key',
        'Focus not trapped within modal'
      ]
    };

    return mistakes[componentName] || [];
  }

  /**
   * Get default tokens fallback
   */
  getDefaultTokens() {
    return {
      colors: {
        'primary-500': '#8B51E2',
        'primary-600': '#7536D4',
        'success': '#10B981',
        'warning': '#F59E0B',
        'error': '#EF4444'
      },
      spacing: {
        '0': '0px',
        '1': '4px',
        '2': '8px',
        '4': '16px',
        '8': '32px'
      },
      typography: {
        'heading-1': { fontSize: '48px', fontWeight: 700, lineHeight: 1.2 },
        'body-default': { fontSize: '16px', fontWeight: 400, lineHeight: 1.5 }
      }
    };
  }

  /**
   * Query specific context
   */
  async queryContext(query) {
    const { type, target, detail } = query;

    switch (type) {
      case 'component':
        return this.getComponentSpecificContext(target, detail);
      case 'token':
        return this.getTokenSpecificContext(target, detail);
      case 'pattern':
        return this.getPatternSpecificContext(target, detail);
      case 'relationship':
        return this.getRelationshipContext(target, detail);
      default:
        return { error: 'Unknown query type' };
    }
  }

  /**
   * Get component-specific context
   */
  getComponentSpecificContext(componentName, detail) {
    const schema = this.componentSchemas.getComponentSchema(componentName);
    if (!schema) return { error: 'Component not found' };

    if (detail === 'typescript') {
      return this.componentSchemas.generateTypeScriptInterface(componentName);
    }

    if (detail === 'ai') {
      return this.componentSchemas.generateAIContext(componentName);
    }

    return schema;
  }

  /**
   * Get token-specific context
   */
  async getTokenSpecificContext(category, tokenName) {
    const tokens = await this.getTokenContext();
    if (tokens[category] && tokens[category].values[tokenName]) {
      return {
        value: tokens[category].values[tokenName],
        semantics: tokens[category].semantics[tokenName] || {},
        category: category
      };
    }
    return { error: 'Token not found' };
  }

  /**
   * Get pattern-specific context
   */
  getPatternSpecificContext(patternName, detail) {
    const patterns = this.getPatternContext();
    if (patterns[patternName]) {
      if (detail && patterns[patternName][detail]) {
        return patterns[patternName][detail];
      }
      return patterns[patternName];
    }
    return { error: 'Pattern not found' };
  }

  /**
   * Get relationship context
   */
  getRelationshipContext(source, target) {
    const relationships = this.getSystemRelationships();

    if (source === 'token' && relationships.tokenToComponent[target]) {
      return { usage: relationships.tokenToComponent[target] };
    }

    if (source === 'component' && relationships.componentDependencies[target]) {
      return { dependencies: relationships.componentDependencies[target] };
    }

    return { error: 'Relationship not found' };
  }

  /**
   * Generate implementation suggestion
   */
  async generateImplementation(requirement) {
    const context = await this.getCompleteContext();

    return {
      requirement,
      suggestedComponents: this.suggestComponents(requirement, context),
      tokens: this.suggestTokens(requirement, context),
      pattern: this.suggestPattern(requirement, context),
      implementation: this.generateCode(requirement, context)
    };
  }

  /**
   * Suggest components based on requirement
   */
  suggestComponents(requirement, context) {
    const keywords = requirement.toLowerCase().split(' ');
    const suggestions = [];

    for (const [name, schema] of Object.entries(context.components)) {
      const description = schema.description.toLowerCase();
      if (keywords.some(keyword => description.includes(keyword))) {
        suggestions.push({
          name,
          confidence: 'high',
          reason: schema.description
        });
      }
    }

    return suggestions;
  }

  /**
   * Suggest tokens based on requirement
   */
  suggestTokens(requirement, context) {
    const suggestions = [];
    const keywords = requirement.toLowerCase();

    if (keywords.includes('space') || keywords.includes('padding') || keywords.includes('margin')) {
      suggestions.push({ category: 'spacing', tokens: Object.keys(context.tokens.spacing?.values || {}) });
    }

    if (keywords.includes('color') || keywords.includes('brand')) {
      suggestions.push({ category: 'colors', tokens: Object.keys(context.tokens.colors?.values || {}) });
    }

    return suggestions;
  }

  /**
   * Suggest pattern based on requirement
   */
  suggestPattern(requirement, context) {
    const keywords = requirement.toLowerCase();

    for (const [patternName, pattern] of Object.entries(context.patterns)) {
      if (keywords.includes(patternName.toLowerCase()) ||
          pattern.description.toLowerCase().includes(keywords)) {
        return { name: patternName, pattern };
      }
    }

    return null;
  }

  /**
   * Generate code based on requirement
   */
  generateCode(requirement, context) {
    const components = this.suggestComponents(requirement, context);
    if (components.length === 0) return null;

    const primaryComponent = components[0].name;
    const schema = context.components[primaryComponent];

    return {
      imports: schema.usage.import,
      example: schema.usage.example,
      props: schema.props,
      accessibility: schema.accessibility
    };
  }
}

module.exports = AIContextEndpoint;