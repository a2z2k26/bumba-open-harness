# Design Init Template Schema

All templates must follow this JSON structure for the `/design-init` command.

## Schema

```json
{
  "name": "string (template identifier)",
  "description": "string (human-readable description)",
  "version": "string (semver)",
  "framework": "string (react|vue|angular|svelte|react-native|flutter|swiftui|jetpack-compose)",
  "typescript": boolean,
  "outputPath": "string (relative path)",
  "autoSync": boolean,
  "storybook": boolean,
  "features": {
    "tests": boolean,
    "backups": boolean,
    "linting": boolean
  },
  "transformerOptions": {
    "useStyledComponents": boolean,
    "useTailwind": boolean,
    "useEmotions": boolean,
    "generateStories": boolean,
    "generateTests": boolean
  },
  "additionalDependencies": ["string"],
  "devDependencies": ["string"],
  "scripts": {
    "scriptName": "command"
  },
  "notes": ["string"]
}
```

## Required Fields

- **name**: Must match filename (without .json)
- **description**: Shown when listing templates (max 100 chars)
- **framework**: Must be valid framework identifier
- **typescript**: Boolean for TypeScript support
- **outputPath**: Where transformed code goes (relative path)

## Optional Fields

- **features**: Enable/disable optional features
  - `tests`: Generate test files
  - `backups`: Create backups on sync
  - `linting`: Include linting configuration

- **transformerOptions**: Framework-specific transformer settings
  - `useStyledComponents`: Enable styled-components (React)
  - `useTailwind`: Enable Tailwind CSS
  - `useEmotions`: Enable Emotion CSS-in-JS (React)
  - `generateStories`: Auto-generate Storybook stories
  - `generateTests`: Auto-generate test files

- **additionalDependencies**: npm packages to suggest installing
- **devDependencies**: Dev dependencies to suggest
- **scripts**: Suggested package.json scripts
- **notes**: Additional information for users

## Validation

Templates are validated on load. Invalid templates are skipped with error message.

### Validation Rules

1. `name` must be alphanumeric with hyphens
2. `framework` must be in allowed list
3. `outputPath` must be relative (not start with `/`)
4. `typescript` must be boolean
5. All `features` values must be boolean
6. All `transformerOptions` values must be boolean

## Example: React TypeScript Storybook

```json
{
  "name": "react-ts-storybook",
  "description": "React with TypeScript, Storybook, and Styled Components",
  "version": "1.0.0",
  "framework": "react",
  "typescript": true,
  "outputPath": "src/design-system",
  "autoSync": true,
  "storybook": true,
  "features": {
    "tests": true,
    "backups": true,
    "linting": true
  },
  "transformerOptions": {
    "useStyledComponents": true,
    "useTailwind": false,
    "useEmotions": false,
    "generateStories": true,
    "generateTests": true
  },
  "additionalDependencies": [
    "styled-components",
    "@types/styled-components"
  ],
  "scripts": {
    "storybook": "storybook dev -p 6006"
  },
  "notes": [
    "Requires Storybook to be installed",
    "Styled Components will be used for styling"
  ]
}
```

## Template Naming Convention

Format: `{framework}-{variant}[-{feature}]`

Examples:
- `react-ts-storybook` - React + TypeScript + Storybook
- `react-ts-tailwind` - React + TypeScript + Tailwind
- `react-ts-minimal` - React + TypeScript (minimal)
- `vue-composition` - Vue 3 Composition API
- `angular-ts` - Angular with TypeScript

## Creating New Templates

1. Copy existing template as starting point
2. Modify fields to match your configuration
3. Validate JSON syntax
4. Test with `/design-init --template=<name>`
5. Document in template notes
