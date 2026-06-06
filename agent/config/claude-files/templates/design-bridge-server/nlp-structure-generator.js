/**
 * nlp-structure-generator.js
 * NLP Structure Generator
 * Generates component structure from natural language description
 */

/**
 * Element type patterns
 */
const elementPatterns = {
  text: {
    heading: /\b(title|heading|header|h1|h2|h3|name)\b/i,
    body: /\b(description|body|text|content|paragraph|message)\b/i,
    label: /\b(label|caption|subtitle|subheading)\b/i,
    link: /\b(link|url|href)\b/i
  },
  media: {
    image: /\b(image|img|picture|photo|thumbnail|avatar|icon)\b/i,
    video: /\b(video|player)\b/i,
    icon: /\b(icon|symbol|glyph)\b/i
  },
  interactive: {
    button: /\b(button|btn|action|submit|cta|click)\b/i,
    input: /\b(input|field|text\s*field|entry)\b/i,
    checkbox: /\b(checkbox|check\s*box|toggle)\b/i,
    select: /\b(select|dropdown|combo\s*box|picker)\b/i
  },
  container: {
    list: /\b(list|items|collection|array)\b/i,
    grid: /\b(grid|gallery|tiles)\b/i,
    card: /\b(card|tile|panel|box)\b/i,
    section: /\b(section|area|region|zone)\b/i
  }
};

/**
 * Generate structure from description
 * @param {string} description - Natural language description
 * @param {string} componentName - Component name for root element
 * @returns {Object} Generated structure
 */
function generateStructure(description, componentName) {
  // Analyze description for elements
  const elements = analyzeDescription(description);

  // Determine layout strategy
  const layout = inferLayout(elements);

  // Build structure
  const structure = buildStructure(elements, componentName, layout);

  return structure;
}

/**
 * Analyze description for UI elements
 * @param {string} description - Natural language description
 * @returns {Array} Array of found elements
 */
function analyzeDescription(description) {
  const elements = [];
  const sentences = description.split(/[.,;]/);

  // Track what we've found
  const found = new Set();

  sentences.forEach((sentence, index) => {
    const lowercaseSentence = sentence.toLowerCase();

    // Check each element type
    for (const [category, patterns] of Object.entries(elementPatterns)) {
      for (const [elementType, pattern] of Object.entries(patterns)) {
        if (pattern.test(lowercaseSentence) && !found.has(`${category}-${elementType}`)) {
          found.add(`${category}-${elementType}`);

          // Extract element name from context
          const name = extractElementName(sentence, elementType);

          elements.push({
            category,
            type: elementType,
            name,
            order: index,
            rawText: sentence.trim()
          });
        }
      }
    }
  });

  // Sort by order of appearance
  elements.sort((a, b) => a.order - b.order);

  return elements;
}

/**
 * Extract element name from sentence context
 * @param {string} sentence - Source sentence
 * @param {string} elementType - Type of element
 * @returns {string} Extracted name in PascalCase
 */
function extractElementName(sentence, elementType) {
  // Try to find descriptive adjectives before the element type
  const pattern = new RegExp(`(\\w+(?:\\s+\\w+)?)\\s*${elementType}`, 'i');
  const match = sentence.match(pattern);

  if (match && match[1]) {
    // Clean up and capitalize
    return toPascalCase(match[1] + ' ' + elementType);
  }

  return toPascalCase(elementType);
}

/**
 * Infer layout from elements
 * @param {Array} elements - Array of found elements
 * @returns {Object} Layout configuration
 */
function inferLayout(elements) {
  // Check for explicit layout hints
  const hasGrid = elements.some(e => e.type === 'grid');
  const hasList = elements.some(e => e.type === 'list');

  // Count element types
  const hasMultipleButtons = elements.filter(e => e.type === 'button').length > 1;
  const hasImageAndText = elements.some(e => e.category === 'media') &&
                          elements.some(e => e.category === 'text');

  // Determine layout
  if (hasGrid) {
    return { type: 'grid', columns: 3 };
  }

  if (hasList) {
    return { type: 'flex-col', gap: 8 };
  }

  if (hasMultipleButtons) {
    return { type: 'flex-row', gap: 4, actionLayout: true };
  }

  if (hasImageAndText) {
    return { type: 'flex-col', gap: 16 };
  }

  // Default
  return { type: 'flex-col', gap: 8 };
}

/**
 * Build structure tree from elements
 * @param {Array} elements - Array of found elements
 * @param {string} componentName - Component name for root
 * @param {Object} layout - Layout configuration
 * @returns {Object} Structure tree
 */
function buildStructure(elements, componentName, layout) {
  const structure = {
    type: 'FRAME',
    name: componentName,
    layout: layout.type,
    gap: layout.gap,
    children: []
  };

  // Group elements by semantic meaning
  const groups = groupElements(elements);

  // Build children based on groups
  for (const group of groups) {
    const child = buildGroupStructure(group);
    if (child) {
      structure.children.push(child);
    }
  }

  return structure;
}

/**
 * Group elements into semantic units
 * @param {Array} elements - Array of found elements
 * @returns {Array} Array of element groups
 */
function groupElements(elements) {
  const groups = [];
  let currentGroup = { type: 'content', elements: [] };

  elements.forEach(element => {
    // Start new group for containers
    if (element.category === 'container') {
      if (currentGroup.elements.length > 0) {
        groups.push(currentGroup);
      }
      groups.push({ type: element.type, elements: [element] });
      currentGroup = { type: 'content', elements: [] };
      return;
    }

    // Group actions together
    if (element.category === 'interactive' && element.type === 'button') {
      // Check if we're already collecting actions
      if (currentGroup.type !== 'actions' && currentGroup.elements.length > 0) {
        groups.push(currentGroup);
        currentGroup = { type: 'actions', elements: [] };
      } else if (currentGroup.type !== 'actions') {
        currentGroup.type = 'actions';
      }
    }

    // Group media at top
    if (element.category === 'media' && groups.length === 0 && currentGroup.elements.length === 0) {
      groups.push({ type: 'media', elements: [element] });
      return;
    }

    currentGroup.elements.push(element);
  });

  // Add remaining group
  if (currentGroup.elements.length > 0) {
    groups.push(currentGroup);
  }

  return groups;
}

/**
 * Build structure for a group
 * @param {Object} group - Group object with type and elements
 * @returns {Object|null} Structure node or null
 */
function buildGroupStructure(group) {
  if (group.elements.length === 0) return null;

  // Single element group
  if (group.elements.length === 1 && group.type !== 'actions') {
    return elementToStructure(group.elements[0]);
  }

  // Actions group
  if (group.type === 'actions') {
    return {
      type: 'FRAME',
      name: 'Actions',
      layout: 'flex-row',
      gap: 4,
      children: group.elements.map(elementToStructure)
    };
  }

  // Content group
  if (group.type === 'content') {
    return {
      type: 'FRAME',
      name: 'Content',
      layout: 'flex-col',
      gap: 8,
      padding: 16,
      children: group.elements.map(elementToStructure)
    };
  }

  // Container group
  return {
    type: 'FRAME',
    name: toPascalCase(group.type),
    layout: group.type === 'list' ? 'flex-col' : 'grid',
    gap: 8,
    children: group.elements.map(elementToStructure)
  };
}

/**
 * Convert element to structure node
 * @param {Object} element - Element object
 * @returns {Object} Structure node
 */
function elementToStructure(element) {
  switch (element.category) {
    case 'text':
      return {
        type: 'TEXT',
        name: element.name,
        style: element.type // heading, body, label, link
      };

    case 'media':
      if (element.type === 'image') {
        return {
          type: 'IMAGE',
          name: element.name,
          constraints: { width: 'fill' }
        };
      }
      if (element.type === 'icon') {
        return {
          type: 'ICON',
          name: element.name,
          size: 24
        };
      }
      return { type: element.type.toUpperCase(), name: element.name };

    case 'interactive':
      if (element.type === 'button') {
        return {
          type: 'COMPONENT',
          name: element.name,
          componentRef: 'Button'
        };
      }
      if (element.type === 'input') {
        return {
          type: 'COMPONENT',
          name: element.name,
          componentRef: 'Input'
        };
      }
      return {
        type: 'COMPONENT',
        name: element.name,
        componentRef: toPascalCase(element.type)
      };

    default:
      return {
        type: 'FRAME',
        name: element.name
      };
  }
}

/**
 * Convert string to PascalCase
 * @param {string} str - Input string
 * @returns {string} PascalCase string
 */
function toPascalCase(str) {
  return str
    .split(/[\s_-]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

module.exports = {
  generateStructure,
  analyzeDescription,
  inferLayout,
  buildStructure,
  groupElements,
  buildGroupStructure,
  elementToStructure,
  toPascalCase,
  elementPatterns
};
