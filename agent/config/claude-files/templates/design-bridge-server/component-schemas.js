/**
 * Component Schema System for AI-Human Partnership
 * Provides machine-readable specifications for all UI components
 */

class ComponentSchemaSystem {
  constructor() {
    this.schemas = this.initializeSchemas();
  }

  /**
   * Initialize component schemas with full specifications
   */
  initializeSchemas() {
    return {
      // Core interaction components
      Button: {
        name: 'Button',
        category: 'actions',
        description: 'Primary interaction element for user actions',
        props: {
          variant: {
            type: 'enum',
            values: ['default', 'destructive', 'outline', 'secondary', 'ghost', 'link'],
            default: 'default',
            semantic: {
              default: 'Primary action, highest emphasis',
              destructive: 'Dangerous or irreversible actions',
              outline: 'Secondary action with border',
              secondary: 'Supporting actions',
              ghost: 'Tertiary or inline actions',
              link: 'Navigation or text-like button'
            }
          },
          size: {
            type: 'enum',
            values: ['default', 'sm', 'lg', 'icon'],
            default: 'default',
            semantic: {
              default: 'Standard touch target (40px)',
              sm: 'Compact layouts (32px)',
              lg: 'Emphasized actions (48px)',
              icon: 'Icon-only square button'
            }
          },
          disabled: {
            type: 'boolean',
            default: false,
            semantic: 'Prevents interaction, 50% opacity'
          },
          asChild: {
            type: 'boolean',
            default: false,
            semantic: 'Renders as child component slot'
          }
        },
        states: ['default', 'hover', 'active', 'disabled', 'loading'],
        accessibility: {
          role: 'button',
          ariaLabel: 'required when icon-only',
          keyboard: 'Space/Enter to activate',
          focus: 'Visible focus ring required'
        },
        dependencies: [],
        usage: {
          import: "import { Button } from '@/components/ui/button'",
          example: '<Button variant="default" size="default">Click me</Button>'
        }
      },

      Card: {
        name: 'Card',
        category: 'containers',
        description: 'Container for grouped content with consistent styling',
        props: {
          className: {
            type: 'string',
            default: '',
            semantic: 'Additional CSS classes'
          }
        },
        subComponents: ['CardHeader', 'CardTitle', 'CardDescription', 'CardContent', 'CardFooter'],
        states: ['default'],
        accessibility: {
          role: 'region',
          ariaLabel: 'optional for landmark',
          keyboard: 'Content dependent'
        },
        dependencies: [],
        usage: {
          import: "import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'",
          example: `<Card>
  <CardHeader>
    <CardTitle>Title</CardTitle>
  </CardHeader>
  <CardContent>Content</CardContent>
</Card>`
        }
      },

      Input: {
        name: 'Input',
        category: 'forms',
        description: 'Text input field for user data entry',
        props: {
          type: {
            type: 'enum',
            values: ['text', 'password', 'email', 'number', 'tel', 'url', 'search'],
            default: 'text',
            semantic: 'HTML input type for validation and keyboard'
          },
          placeholder: {
            type: 'string',
            default: '',
            semantic: 'Hint text when empty'
          },
          disabled: {
            type: 'boolean',
            default: false,
            semantic: 'Prevents editing'
          },
          required: {
            type: 'boolean',
            default: false,
            semantic: 'Field must be filled'
          }
        },
        states: ['default', 'hover', 'focus', 'disabled', 'error', 'success'],
        accessibility: {
          role: 'textbox',
          ariaLabel: 'required',
          ariaDescribedby: 'for errors/hints',
          keyboard: 'Tab to focus, type to input'
        },
        dependencies: ['Label'],
        usage: {
          import: "import { Input } from '@/components/ui/input'",
          example: '<Input type="email" placeholder="Email" />'
        }
      },

      Dialog: {
        name: 'Dialog',
        category: 'overlays',
        description: 'Modal overlay for focused interactions',
        props: {
          open: {
            type: 'boolean',
            default: false,
            semantic: 'Controls visibility'
          },
          onOpenChange: {
            type: 'function',
            semantic: 'Callback when open state changes'
          },
          modal: {
            type: 'boolean',
            default: true,
            semantic: 'Traps focus and blocks background'
          }
        },
        subComponents: ['DialogTrigger', 'DialogContent', 'DialogHeader', 'DialogTitle', 'DialogDescription', 'DialogFooter'],
        states: ['closed', 'opening', 'open', 'closing'],
        accessibility: {
          role: 'dialog',
          ariaModal: 'true',
          ariaLabelledby: 'dialog-title',
          keyboard: 'Escape to close',
          focus: 'Trap focus within dialog'
        },
        dependencies: ['Portal', 'Overlay'],
        usage: {
          import: "import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'",
          example: `<Dialog>
  <DialogTrigger>Open</DialogTrigger>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Title</DialogTitle>
    </DialogHeader>
  </DialogContent>
</Dialog>`
        }
      },

      Select: {
        name: 'Select',
        category: 'forms',
        description: 'Dropdown selection from predefined options',
        props: {
          value: {
            type: 'string',
            semantic: 'Currently selected value'
          },
          onValueChange: {
            type: 'function',
            semantic: 'Callback when selection changes'
          },
          placeholder: {
            type: 'string',
            default: 'Select an option',
            semantic: 'Display when no selection'
          },
          disabled: {
            type: 'boolean',
            default: false,
            semantic: 'Prevents selection'
          }
        },
        subComponents: ['SelectTrigger', 'SelectContent', 'SelectItem', 'SelectValue'],
        states: ['closed', 'open', 'disabled'],
        accessibility: {
          role: 'combobox',
          ariaExpanded: 'true/false',
          ariaControls: 'listbox',
          keyboard: 'Arrow keys to navigate, Enter to select'
        },
        dependencies: ['Popover', 'Command'],
        usage: {
          import: "import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'",
          example: `<Select>
  <SelectTrigger>
    <SelectValue placeholder="Select" />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="1">Option 1</SelectItem>
  </SelectContent>
</Select>`
        }
      }
    };
  }

  /**
   * Get schema for a specific component
   */
  getComponentSchema(componentName) {
    return this.schemas[componentName] || null;
  }

  /**
   * Get all component schemas
   */
  getAllSchemas() {
    return this.schemas;
  }

  /**
   * Get schemas by category
   */
  getSchemasByCategory(category) {
    return Object.values(this.schemas).filter(schema => schema.category === category);
  }

  /**
   * Generate TypeScript interface from schema
   */
  generateTypeScriptInterface(componentName) {
    const schema = this.schemas[componentName];
    if (!schema) return null;

    let interfaceStr = `interface ${componentName}Props {\n`;
    for (const [propName, propDef] of Object.entries(schema.props)) {
      const required = propDef.default === undefined ? '' : '?';
      let type = propDef.type;

      if (type === 'enum') {
        type = propDef.values.map(v => `'${v}'`).join(' | ');
      }

      interfaceStr += `  ${propName}${required}: ${type};\n`;
    }
    interfaceStr += '}';

    return interfaceStr;
  }

  /**
   * Generate AI context for component
   */
  generateAIContext(componentName) {
    const schema = this.schemas[componentName];
    if (!schema) return null;

    return {
      intent: schema.description,
      props: Object.entries(schema.props).map(([name, def]) => ({
        name,
        type: def.type,
        purpose: def.semantic,
        required: def.default === undefined
      })),
      states: schema.states,
      accessibility: schema.accessibility,
      relationships: {
        dependencies: schema.dependencies || [],
        subComponents: schema.subComponents || []
      },
      implementation: schema.usage
    };
  }

  /**
   * Validate component props against schema
   */
  validateProps(componentName, props) {
    const schema = this.schemas[componentName];
    if (!schema) return { valid: false, errors: ['Unknown component'] };

    const errors = [];

    // Check required props
    for (const [propName, propDef] of Object.entries(schema.props)) {
      if (propDef.default === undefined && !(propName in props)) {
        errors.push(`Missing required prop: ${propName}`);
      }

      // Validate enum values
      if (props[propName] && propDef.type === 'enum') {
        if (!propDef.values.includes(props[propName])) {
          errors.push(`Invalid value for ${propName}: ${props[propName]}`);
        }
      }
    }

    return {
      valid: errors.length === 0,
      errors
    };
  }
}

module.exports = ComponentSchemaSystem;