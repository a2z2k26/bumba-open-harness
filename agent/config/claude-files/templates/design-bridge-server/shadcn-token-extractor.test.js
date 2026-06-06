/**
 * shadcn-token-extractor.test.js
 * Unit tests for Tailwind token extraction
 */

const {
  extractTokenDependencies,
  extractColorTokens,
  extractTypographyTokens,
  extractSpacingTokens,
  extractEffectTokens,
  extractBorderRadiusTokens,
  extractCssVariables,
  mapToDesignTokens,
  formatTokenSummary,
  createEmptyTokens
} = require('./shadcn-token-extractor');

let passed = 0;
let failed = 0;

function test(name, condition) {
  if (condition) {
    console.log(`  [PASS] ${name}`);
    passed++;
  } else {
    console.log(`  [FAIL] ${name}`);
    failed++;
  }
}

// Mock ShadCN button source with various Tailwind classes
const mockButtonSource = `
import { cva } from "class-variance-authority"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-xs hover:bg-primary/90",
        destructive: "bg-destructive text-white shadow-xs hover:bg-destructive/90",
        outline: "border border-input bg-background shadow-xs hover:bg-accent",
        secondary: "bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline"
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md gap-1.5 px-3",
        lg: "h-10 rounded-md px-6",
        icon: "size-9"
      }
    }
  }
)

export function Button({ className, ...props }) {
  return <button className={buttonVariants({ className })} {...props} />
}
`;

// Mock card source with CSS variables
const mockCardSource = `
function Card({ className, ...props }) {
  return (
    <div
      className="rounded-xl border bg-card text-card-foreground shadow"
      style={{ backgroundColor: 'var(--card)', borderColor: 'var(--border)' }}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }) {
  return <div className="flex flex-col space-y-1.5 p-6" {...props} />
}
`;

// Mock badge with limited classes
const mockBadgeSource = `
const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "border-transparent bg-destructive text-destructive-foreground",
        outline: "text-foreground"
      }
    }
  }
)
`;

function runTests() {
  console.log('\n=== ShadCN Token Extractor Tests ===\n');

  // Test: extractTokenDependencies - full extraction
  console.log('--- extractTokenDependencies ---');
  const buttonTokens = extractTokenDependencies(mockButtonSource);

  test('returns object with all token categories',
    buttonTokens.colors && buttonTokens.typography && buttonTokens.spacing
  );
  test('extracts color tokens', buttonTokens.colors.length > 0);
  test('extracts typography tokens', buttonTokens.typography.length > 0);
  test('extracts spacing tokens', buttonTokens.spacing.length > 0);
  test('extracts effect tokens', buttonTokens.effects.length > 0);
  test('extracts border radius tokens', buttonTokens.borderRadius.length > 0);

  // Test: extractColorTokens
  console.log('\n--- extractColorTokens ---');
  const colors = extractColorTokens(mockButtonSource);

  test('extracts bg-primary', colors.includes('bg-primary'));
  test('extracts bg-destructive', colors.includes('bg-destructive'));
  test('extracts bg-secondary', colors.includes('bg-secondary'));
  test('extracts text-primary-foreground', colors.includes('text-primary-foreground'));
  test('extracts text-white', colors.includes('text-white'));
  test('extracts border-input', colors.includes('border-input'));

  // Test: extractTypographyTokens
  console.log('\n--- extractTypographyTokens ---');
  const typography = extractTypographyTokens(mockButtonSource);

  test('extracts text-sm', typography.includes('text-sm'));
  test('extracts font-medium', typography.includes('font-medium'));

  const badgeTypography = extractTypographyTokens(mockBadgeSource);
  test('extracts text-xs from badge', badgeTypography.includes('text-xs'));
  test('extracts font-semibold from badge', badgeTypography.includes('font-semibold'));

  // Test: extractSpacingTokens
  console.log('\n--- extractSpacingTokens ---');
  const spacing = extractSpacingTokens(mockButtonSource);

  test('extracts h-9', spacing.includes('h-9'));
  test('extracts h-8', spacing.includes('h-8'));
  test('extracts h-10', spacing.includes('h-10'));
  test('extracts px-4', spacing.includes('px-4'));
  test('extracts py-2', spacing.includes('py-2'));
  test('extracts gap-2', spacing.includes('gap-2'));
  test('extracts size-9', spacing.includes('size-9'));

  const cardSpacing = extractSpacingTokens(mockCardSource);
  test('extracts p-6 from card', cardSpacing.includes('p-6'));
  test('extracts space-y-1.5 from card', cardSpacing.includes('space-y-1.5'));

  // Test: extractEffectTokens
  console.log('\n--- extractEffectTokens ---');
  const effects = extractEffectTokens(mockButtonSource);

  test('extracts shadow-xs', effects.includes('shadow-xs'));
  test('extracts transition-colors', effects.includes('transition-colors'));

  // Test: extractBorderRadiusTokens
  console.log('\n--- extractBorderRadiusTokens ---');
  const radii = extractBorderRadiusTokens(mockButtonSource);

  test('extracts rounded-md', radii.includes('rounded-md'));

  const cardRadii = extractBorderRadiusTokens(mockCardSource);
  test('extracts rounded-xl from card', cardRadii.includes('rounded-xl'));

  const badgeRadii = extractBorderRadiusTokens(mockBadgeSource);
  test('extracts rounded-md from badge', badgeRadii.includes('rounded-md'));

  // Test: extractCssVariables
  console.log('\n--- extractCssVariables ---');
  const cssVars = extractCssVariables(mockCardSource);

  test('extracts --card variable', cssVars.includes('--card'));
  test('extracts --border variable', cssVars.includes('--border'));

  const buttonVars = extractCssVariables(mockButtonSource);
  test('button has no CSS variables', buttonVars.length === 0);

  // Test: null/empty input
  console.log('\n--- Edge Cases ---');
  const nullTokens = extractTokenDependencies(null);
  const emptyTokens = extractTokenDependencies('');

  test('handles null input', nullTokens.colors.length === 0);
  test('handles empty string', emptyTokens.colors.length === 0);
  test('null returns empty structure', Array.isArray(nullTokens.typography));
  test('empty returns empty structure', Array.isArray(emptyTokens.spacing));

  // Test: createEmptyTokens
  console.log('\n--- createEmptyTokens ---');
  const empty = createEmptyTokens();

  test('creates colors array', Array.isArray(empty.colors) && empty.colors.length === 0);
  test('creates typography array', Array.isArray(empty.typography) && empty.typography.length === 0);
  test('creates spacing array', Array.isArray(empty.spacing) && empty.spacing.length === 0);
  test('creates effects array', Array.isArray(empty.effects) && empty.effects.length === 0);
  test('creates borderRadius array', Array.isArray(empty.borderRadius) && empty.borderRadius.length === 0);
  test('creates cssVariables array', Array.isArray(empty.cssVariables) && empty.cssVariables.length === 0);

  // Test: mapToDesignTokens
  console.log('\n--- mapToDesignTokens ---');
  const mapped = mapToDesignTokens(buttonTokens);

  test('maps colors to design tokens', Array.isArray(mapped.colors));
  test('maps typography to design tokens', Array.isArray(mapped.typography));
  test('mapped colors have tailwind property', mapped.colors.length > 0 && mapped.colors[0].tailwind);
  test('mapped colors have designToken property', mapped.colors.length > 0 && 'designToken' in mapped.colors[0]);

  // Check specific mappings
  const bgPrimaryMapping = mapped.colors.find(c => c.tailwind === 'bg-primary');
  test('bg-primary maps to colors/primary/500', bgPrimaryMapping && bgPrimaryMapping.designToken === 'colors/primary/500');

  // Test: formatTokenSummary
  console.log('\n--- formatTokenSummary ---');
  const summary = formatTokenSummary(buttonTokens);

  test('formats summary string', typeof summary === 'string');
  test('summary includes Token Dependencies header', summary.includes('Token Dependencies'));
  test('summary includes Colors section', summary.includes('Colors'));
  test('summary includes Typography section', summary.includes('Typography'));
  test('summary includes Spacing section', summary.includes('Spacing'));

  // Print results
  console.log('\n=== Test Results ===');
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  console.log(`Total: ${passed + failed}`);

  return { passed, failed };
}

// Run if executed directly
if (require.main === module) {
  runTests();
}

module.exports = { runTests };
