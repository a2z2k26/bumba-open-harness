/**
 * Minimal ESLint config for bumba-sandbox.
 *
 * Goal: make `npm run lint` execute against the TypeScript source (and tests)
 * without crashing. Rules are intentionally close to the recommended baseline
 * — this config establishes the seam, not the policy.
 */
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
  },
  plugins: ['@typescript-eslint'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
  ],
  env: {
    node: true,
    es2022: true,
    jest: true,
  },
  ignorePatterns: [
    'dist/',
    'node_modules/',
    'coverage/',
    '*.cjs',
    '*.js',
  ],
  rules: {
    // Keep the surface narrow on first activation; tighten later.
    '@typescript-eslint/no-explicit-any': 'off',
    '@typescript-eslint/no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    // Demoted to warnings on first activation — pre-existing violations in
    // src/ should be addressed in a follow-up rather than block the seam.
    'prefer-const': 'warn',
    'no-control-regex': 'warn',
    'no-useless-escape': 'warn',
    '@typescript-eslint/no-var-requires': 'warn',
  },
};
