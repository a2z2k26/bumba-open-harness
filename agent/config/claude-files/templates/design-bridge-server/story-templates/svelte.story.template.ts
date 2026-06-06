import type { Meta, StoryObj } from '@storybook/svelte';
import {{COMPONENT_NAME}} from './{{COMPONENT_NAME}}.svelte';

const meta: Meta<typeof {{COMPONENT_NAME}}> = {
  title: '{{STORY_TITLE}}',
  component: {{COMPONENT_NAME}},
  parameters: {
    layout: '{{LAYOUT}}',
    {{#if FIGMA_URL}}
    design: {
      type: 'figma',
      url: '{{FIGMA_URL}}'
    },
    {{/if}}
    // Accessibility configuration
    a11y: {
      // Element to check for accessibility
      element: '#storybook-root',
      // Accessibility rules configuration
      config: {
        rules: [
          // Ensure color contrast meets WCAG AA standards
          { id: 'color-contrast', enabled: true },
          // Ensure interactive elements are focusable
          { id: 'focus-order-semantics', enabled: true },
          // Ensure buttons have accessible names
          { id: 'button-name', enabled: true },
          // Ensure images have alt text
          { id: 'image-alt', enabled: true },
          // Ensure form inputs have labels
          { id: 'label', enabled: true },
        ],
      },
      // Run accessibility checks automatically
      manual: false,
    },
  },
  tags: ['autodocs'],
  argTypes: {
    {{ARG_TYPES}}
    // Accessibility-related argTypes
    'aria-label': {
      control: 'text',
      description: 'Accessible label for screen readers',
      table: {
        category: 'Accessibility',
      },
    },
    'aria-describedby': {
      control: 'text',
      description: 'ID of element describing this component',
      table: {
        category: 'Accessibility',
      },
    },
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    {{DEFAULT_ARGS}}
  }
};

// Accessibility test story - tests keyboard navigation
export const KeyboardNavigation: Story = {
  args: {
    {{DEFAULT_ARGS}}
  },
  parameters: {
    docs: {
      description: {
        story: 'Test keyboard navigation by tabbing through interactive elements.',
      },
    },
  },
  play: async ({ canvasElement }) => {
    // Focus the first interactive element
    const firstFocusable = canvasElement.querySelector('button, input, a, [tabindex="0"]');
    if (firstFocusable instanceof HTMLElement) {
      firstFocusable.focus();
    }
  },
};

// Screen reader test story
export const ScreenReaderAnnouncements: Story = {
  args: {
    {{DEFAULT_ARGS}}
    'aria-label': '{{COMPONENT_NAME}} component',
  },
  parameters: {
    docs: {
      description: {
        story: 'Verify screen reader announcements with appropriate ARIA attributes.',
      },
    },
  },
};
