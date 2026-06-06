# How to Use skill-template.md

## Creating a New Framework Skill

1. Copy template to framework directory:
   ```bash
   cp shared/skill-template.md transform-react/skill.md
   ```

2. Replace all template variables:
   - `{FRAMEWORK}` → react
   - `{FRAMEWORK_DISPLAY}` → React
   - `{EXT}` → tsx
   - `{FRAMEWORK_OPTIONS}` → framework-specific options
   - `{NEXT_STEPS}` → framework-specific next steps

3. Add framework-specific details:
   - Configuration options
   - Output structure
   - Best practices

4. Test the skill:
   - Create test project
   - Run /transform-{framework}
   - Verify output

## Template Sections

1. **Header** - Command name and purpose
2. **Purpose** - What the skill does
3. **Prerequisites** - Required setup
4. **Instructions** - Step-by-step execution
5. **Expected Output** - File structure examples
6. **Configuration** - Config.json options
7. **Troubleshooting** - Common issues
8. **Related Skills** - Cross-references

## Customization Points

- Framework-specific options
- Output file structure
- Next steps recommendations
- Troubleshooting scenarios

## Template Variables Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `{FRAMEWORK}` | Lowercase framework name | react, vue, angular |
| `{FRAMEWORK_DISPLAY}` | Display name | React, Vue, Angular |
| `{EXT}` | File extension | tsx, vue, ts |
| `{FRAMEWORK_OPTIONS}` | Framework-specific config | See examples below |
| `{NEXT_STEPS}` | Post-transformation steps | Import tokens, run dev server |

## Framework-Specific Examples

### React
- `{FRAMEWORK}` → react
- `{FRAMEWORK_DISPLAY}` → React
- `{EXT}` → tsx
- `{FRAMEWORK_OPTIONS}`:
  ```json
  "useStyledComponents": true,
  "generateStories": true
  ```
- `{NEXT_STEPS}`:
  - Import tokens in your components
  - Run Storybook: npm run storybook
  - Copy to src/: cp -r .design/extracted-code/react/* src/design-system/

### Vue
- `{FRAMEWORK}` → vue
- `{FRAMEWORK_DISPLAY}` → Vue
- `{EXT}` → vue
- `{FRAMEWORK_OPTIONS}`:
  ```json
  "compositionApi": true,
  "generateStories": true
  ```

### Angular
- `{FRAMEWORK}` → angular
- `{FRAMEWORK_DISPLAY}` → Angular
- `{EXT}` → ts
- `{FRAMEWORK_OPTIONS}`:
  ```json
  "standalone": true,
  "generateStories": true
  ```

### Svelte
- `{FRAMEWORK}` → svelte
- `{FRAMEWORK_DISPLAY}` → Svelte
- `{EXT}` → svelte
- `{FRAMEWORK_OPTIONS}`:
  ```json
  "typescript": true,
  "generateStories": true
  ```

### React Native
- `{FRAMEWORK}` → react-native
- `{FRAMEWORK_DISPLAY}` → React Native
- `{EXT}` → tsx
- `{FRAMEWORK_OPTIONS}`:
  ```json
  "useStyleSheet": true,
  "generateStories": false
  ```

### Flutter
- `{FRAMEWORK}` → flutter
- `{FRAMEWORK_DISPLAY}` → Flutter
- `{EXT}` → dart
- `{FRAMEWORK_OPTIONS}`:
  ```json
  "generateTheme": true,
  "generateWidgets": true
  ```

### SwiftUI
- `{FRAMEWORK}` → swiftui
- `{FRAMEWORK_DISPLAY}` → SwiftUI
- `{EXT}` → swift
- `{FRAMEWORK_OPTIONS}`:
  ```json
  "generateTheme": true,
  "generateViews": true
  ```

### Jetpack Compose
- `{FRAMEWORK}` → jetpack-compose
- `{FRAMEWORK_DISPLAY}` → Jetpack Compose
- `{EXT}` → kt
- `{FRAMEWORK_OPTIONS}`:
  ```json
  "generateTheme": true,
  "generateComponents": true
  ```
