/**
 * Naming Normalizer
 *
 * Provides canonical naming system for design system components.
 * Ensures consistent, valid component names across all frameworks.
 *
 * Core Principles:
 * 1. Canonical Name = Single source of truth (PascalCase, no spaces)
 * 2. Framework-specific file names derived from canonical
 * 3. Validation before code generation
 * 4. No information loss from Figma names
 *
 * Examples:
 * - "AI Chat Box" → canonical: "AiChatBox"
 *   - React: "AiChatBox.tsx"
 *   - Angular: "ai-chat-box.component.ts"
 *   - Vue: "ai-chat-box.vue"
 *   - Flutter: "ai_chat_box.dart"
 */

class NamingNormalizer {
  constructor() {
    // Framework-specific reserved words to check
    this.reservedWords = {
      javascript: ['abstract', 'arguments', 'await', 'boolean', 'break', 'byte', 'case', 'catch', 'char', 'class', 'const', 'continue', 'debugger', 'default', 'delete', 'do', 'double', 'else', 'enum', 'eval', 'export', 'extends', 'false', 'final', 'finally', 'float', 'for', 'function', 'goto', 'if', 'implements', 'import', 'in', 'instanceof', 'int', 'interface', 'let', 'long', 'native', 'new', 'null', 'package', 'private', 'protected', 'public', 'return', 'short', 'static', 'super', 'switch', 'synchronized', 'this', 'throw', 'throws', 'transient', 'true', 'try', 'typeof', 'var', 'void', 'volatile', 'while', 'with', 'yield'],
      dart: ['abstract', 'as', 'assert', 'async', 'await', 'break', 'case', 'catch', 'class', 'const', 'continue', 'covariant', 'default', 'deferred', 'do', 'dynamic', 'else', 'enum', 'export', 'extends', 'extension', 'external', 'factory', 'false', 'final', 'finally', 'for', 'Function', 'get', 'hide', 'if', 'implements', 'import', 'in', 'interface', 'is', 'late', 'library', 'mixin', 'new', 'null', 'on', 'operator', 'part', 'required', 'rethrow', 'return', 'set', 'show', 'static', 'super', 'switch', 'sync', 'this', 'throw', 'true', 'try', 'typedef', 'var', 'void', 'while', 'with', 'yield'],
      swift: ['as', 'associatedtype', 'break', 'case', 'catch', 'class', 'continue', 'default', 'defer', 'deinit', 'do', 'else', 'enum', 'extension', 'fallthrough', 'false', 'fileprivate', 'for', 'func', 'guard', 'if', 'import', 'in', 'init', 'inout', 'internal', 'is', 'let', 'nil', 'open', 'operator', 'private', 'protocol', 'public', 'repeat', 'rethrows', 'return', 'self', 'Self', 'static', 'struct', 'subscript', 'super', 'switch', 'throw', 'throws', 'true', 'try', 'typealias', 'var', 'where', 'while'],
      kotlin: ['as', 'break', 'class', 'continue', 'do', 'else', 'false', 'for', 'fun', 'if', 'in', 'interface', 'is', 'null', 'object', 'package', 'return', 'super', 'this', 'throw', 'true', 'try', 'typealias', 'typeof', 'val', 'var', 'when', 'while']
    };

    // Framework file extension patterns
    this.fileExtensions = {
      react: '.tsx',
      vue: '.vue',
      angular: '.component.ts',
      flutter: '.dart',
      'react-native': '.tsx',
      svelte: '.svelte',
      swiftui: '.swift',
      'jetpack-compose': '.kt',
      'web-components': '.ts'
    };
  }

  /**
   * Convert Figma name to canonical PascalCase
   * Preserves word boundaries and handles special cases
   *
   * @param {string} figmaName - Component name from Figma (e.g., "AI Chat Box", "Button / Primary")
   * @returns {string} Canonical PascalCase name (e.g., "AiChatBox", "ButtonPrimary")
   */
  figmaToCanonical(figmaName) {
    if (!figmaName || typeof figmaName !== 'string') {
      throw new Error('Invalid figma name: must be a non-empty string');
    }

    // Step 0: Handle special characters and edge cases
    let normalized = figmaName
      .replace(/^\.+/, '')           // Remove leading dots (e.g., ".Slot" → "Slot")
      .replace(/->/g, ' ')           // Replace arrows with spaces (e.g., "AI Chat -> Response" → "AI Chat Response")
      .replace(/\//g, ' ')           // Replace slashes with spaces (handle Figma categories)
      .replace(/[<>|]/g, ' ')        // Remove other special characters
      .trim();

    if (!normalized) {
      throw new Error(`Cannot create valid canonical name from: "${figmaName}" (normalized to empty string)`);
    }

    // Step 2: Split into words (preserve acronyms)
    const words = [];

    // Split on spaces, underscores, hyphens, and camelCase/PascalCase boundaries
    const parts = normalized.split(/[\s_-]+/);

    for (const part of parts) {
      if (!part) continue;

      // Handle camelCase and PascalCase within parts
      const subWords = part.split(/(?=[A-Z][a-z])|(?<=[a-z])(?=[A-Z])/);

      for (const subWord of subWords) {
        if (!subWord) continue;

        // Check if word is an acronym (all uppercase, 2+ chars)
        if (subWord.length > 1 && subWord === subWord.toUpperCase()) {
          // Acronym: capitalize first letter, lowercase rest
          // "AI" → "Ai", "API" → "Api"
          words.push(subWord.charAt(0).toUpperCase() + subWord.slice(1).toLowerCase());
        } else {
          // Regular word: capitalize first letter, lowercase rest
          words.push(subWord.charAt(0).toUpperCase() + subWord.slice(1).toLowerCase());
        }
      }
    }

    // Step 3: Join words (PascalCase)
    const canonical = words.join('');

    // Step 4: Validate result
    if (!canonical || !this._isValidIdentifier(canonical)) {
      throw new Error(`Cannot create valid canonical name from: "${figmaName}" → "${canonical}"`);
    }

    return canonical;
  }

  /**
   * Get framework-specific file name from canonical name
   *
   * @param {string} canonicalName - PascalCase canonical name (e.g., "AiChatBox")
   * @param {string} framework - Framework identifier (e.g., "react", "vue", "flutter")
   * @returns {string} Framework-specific file name (e.g., "AiChatBox.tsx", "ai-chat-box.vue")
   */
  getFileName(canonicalName, framework) {
    if (!canonicalName || typeof canonicalName !== 'string') {
      throw new Error('Invalid canonical name: must be a non-empty string');
    }

    if (!framework || typeof framework !== 'string') {
      throw new Error('Invalid framework: must be a non-empty string');
    }

    const normalizedFramework = framework.toLowerCase();

    switch (normalizedFramework) {
      case 'react':
      case 'nextjs':  // Next.js uses same naming as React
      case 'react-native':
      case 'web-components':
        // PascalCase.tsx
        const ext = normalizedFramework === 'react' || normalizedFramework === 'nextjs'
          ? '.tsx'
          : this.fileExtensions[normalizedFramework] || this.fileExtensions['react'];
        return `${canonicalName}${ext}`;

      case 'vue':
      case 'svelte':
        // kebab-case.vue
        return `${this.toKebabCase(canonicalName)}${this.fileExtensions[normalizedFramework]}`;

      case 'angular':
        // kebab-case.component.ts
        return `${this.toKebabCase(canonicalName)}${this.fileExtensions[normalizedFramework]}`;

      case 'flutter':
        // snake_case.dart
        return `${this.toSnakeCase(canonicalName)}${this.fileExtensions[normalizedFramework]}`;

      case 'swiftui':
        // PascalCase.swift
        return `${canonicalName}${this.fileExtensions[normalizedFramework]}`;

      case 'jetpack-compose':
        // PascalCase.kt
        return `${canonicalName}${this.fileExtensions[normalizedFramework]}`;

      default:
        throw new Error(`Unsupported framework: ${framework}`);
    }
  }

  /**
   * Validate canonical name for framework compatibility
   *
   * @param {string} canonicalName - PascalCase canonical name
   * @param {string} framework - Framework identifier
   * @returns {Object} Validation result { valid: boolean, errors: string[] }
   */
  validateForFramework(canonicalName, framework) {
    const errors = [];

    // Check 1: Valid JavaScript/TypeScript identifier
    if (!this._isValidIdentifier(canonicalName)) {
      errors.push(`"${canonicalName}" is not a valid identifier`);
    }

    // Check 2: PascalCase format
    if (!/^[A-Z][a-zA-Z0-9]*$/.test(canonicalName)) {
      errors.push(`"${canonicalName}" is not in PascalCase format`);
    }

    // Check 3: Not a reserved word
    const normalizedFramework = framework.toLowerCase();
    const reservedWordSet = this._getReservedWords(normalizedFramework);

    if (reservedWordSet.has(canonicalName.toLowerCase())) {
      errors.push(`"${canonicalName}" is a reserved word in ${framework}`);
    }

    // Check 4: Framework-specific conventions
    switch (normalizedFramework) {
      case 'react':
      case 'nextjs':
      case 'react-native':
        // React components must start with uppercase
        if (!/^[A-Z]/.test(canonicalName)) {
          errors.push('React components must start with an uppercase letter');
        }
        break;

      case 'vue':
        // Vue components should be PascalCase or kebab-case (we use PascalCase canonical)
        // No specific restrictions beyond valid identifier
        break;

      case 'angular':
        // Angular components typically avoid certain suffixes that conflict with Angular internals
        if (canonicalName.endsWith('Directive') || canonicalName.endsWith('Pipe') || canonicalName.endsWith('Module')) {
          errors.push(`"${canonicalName}" uses a reserved Angular suffix`);
        }
        break;

      case 'flutter':
        // Dart/Flutter: Must be valid Dart class name
        // Already covered by valid identifier check
        break;

      case 'swiftui':
        // Swift: Must be valid Swift type name
        if (/^\d/.test(canonicalName)) {
          errors.push('Swift type names cannot start with a number');
        }
        break;

      case 'jetpack-compose':
        // Kotlin: Must be valid Kotlin class name
        // Already covered by valid identifier check
        break;
    }

    return {
      valid: errors.length === 0,
      errors
    };
  }

  /**
   * Convert PascalCase to kebab-case
   *
   * @param {string} str - PascalCase string (e.g., "AiChatBox")
   * @returns {string} kebab-case string (e.g., "ai-chat-box")
   */
  toKebabCase(str) {
    return str
      .replace(/([a-z])([A-Z])/g, '$1-$2')  // Insert hyphen between lowercase and uppercase
      .replace(/([A-Z])([A-Z][a-z])/g, '$1-$2')  // Handle acronyms (e.g., "HTTPSConnection" → "https-connection")
      .toLowerCase();
  }

  /**
   * Convert PascalCase to snake_case
   *
   * @param {string} str - PascalCase string (e.g., "AiChatBox")
   * @returns {string} snake_case string (e.g., "ai_chat_box")
   */
  toSnakeCase(str) {
    return str
      .replace(/([a-z])([A-Z])/g, '$1_$2')  // Insert underscore between lowercase and uppercase
      .replace(/([A-Z])([A-Z][a-z])/g, '$1_$2')  // Handle acronyms
      .toLowerCase();
  }

  /**
   * Convert string to PascalCase (authoritative implementation)
   *
   * @param {string} str - Any string (e.g., "ai-chat-box", "AI Chat Box")
   * @returns {string} PascalCase string (e.g., "AiChatBox")
   */
  toPascalCase(str) {
    // Use figmaToCanonical as the authoritative implementation
    return this.figmaToCanonical(str);
  }

  /**
   * Convert PascalCase to camelCase
   *
   * @param {string} str - PascalCase string (e.g., "AiChatBox")
   * @returns {string} camelCase string (e.g., "aiChatBox")
   */
  toCamelCase(str) {
    if (!str || typeof str !== 'string') return '';
    return str.charAt(0).toLowerCase() + str.slice(1);
  }

  /**
   * Check if string is a valid JavaScript/TypeScript identifier
   *
   * @private
   * @param {string} str - String to check
   * @returns {boolean} True if valid identifier
   */
  _isValidIdentifier(str) {
    // Must start with letter, underscore, or dollar sign
    // Can contain letters, digits, underscores, dollar signs
    // Cannot be empty
    return /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(str);
  }

  /**
   * Get reserved words set for framework
   *
   * @private
   * @param {string} framework - Framework identifier
   * @returns {Set<string>} Set of lowercase reserved words
   */
  _getReservedWords(framework) {
    switch (framework) {
      case 'react':
      case 'react-native':
      case 'vue':
      case 'svelte':
      case 'angular':
      case 'web-components':
        return new Set(this.reservedWords.javascript);

      case 'flutter':
        return new Set(this.reservedWords.dart);

      case 'swiftui':
        return new Set(this.reservedWords.swift);

      case 'jetpack-compose':
        return new Set(this.reservedWords.kotlin);

      default:
        return new Set(this.reservedWords.javascript);
    }
  }
}

module.exports = NamingNormalizer;
