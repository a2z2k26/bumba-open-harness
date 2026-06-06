import type { Meta, StoryObj } from '@storybook/react-native';
import { View } from 'react-native';
import { {{COMPONENT_NAME}} } from './{{COMPONENT_NAME}}';

const meta: Meta<typeof {{COMPONENT_NAME}}> = {
  title: '{{STORY_TITLE}}',
  component: {{COMPONENT_NAME}},
  decorators: [
    (Story) => (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 }}>
        <Story />
      </View>
    ),
  ],
  parameters: {
    layout: '{{LAYOUT}}',
    {{#if FIGMA_URL}}
    design: {
      type: 'figma',
      url: '{{FIGMA_URL}}'
    },
    {{/if}}
  },
  tags: ['autodocs'],
  argTypes: {
    {{ARG_TYPES}}
    // Accessibility-related argTypes (React Native uses accessibilityLabel instead of aria-label)
    accessibilityLabel: {
      control: 'text',
      description: 'Accessible label for screen readers (VoiceOver/TalkBack)',
      table: {
        category: 'Accessibility',
      },
    },
    accessibilityHint: {
      control: 'text',
      description: 'Additional context about what happens when interacting',
      table: {
        category: 'Accessibility',
      },
    },
    accessibilityRole: {
      control: 'select',
      options: ['button', 'link', 'text', 'image', 'header', 'search', 'switch', 'adjustable'],
      description: 'Accessibility role for screen readers',
      table: {
        category: 'Accessibility',
      },
    },
    accessible: {
      control: 'boolean',
      description: 'Whether the element is accessible',
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

// Accessibility test story - with screen reader labels
export const WithAccessibilityLabels: Story = {
  args: {
    {{DEFAULT_ARGS}}
    accessibilityLabel: '{{COMPONENT_NAME}} component',
    accessible: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Component with accessibility labels for VoiceOver (iOS) and TalkBack (Android).',
      },
    },
  },
};

// Accessibility test story - with accessibility hint
export const WithAccessibilityHint: Story = {
  args: {
    {{DEFAULT_ARGS}}
    accessibilityLabel: '{{COMPONENT_NAME}}',
    accessibilityHint: 'Double tap to interact with this component',
    accessible: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Component with accessibility hint providing additional context.',
      },
    },
  },
};
