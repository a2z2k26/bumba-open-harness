/**
 * shadcn-variant-extractor.test.js
 * Unit tests for CVA variant extraction
 */

const {
  extractCvaVariants,
  findCvaBlocks,
  parseCvaContent,
  parseVariantDimensions,
  parseVariantOptions,
  parseDefaultVariants,
  extractTokensFromClasses,
  toDesignBridgeFormat,
  generatePropsInterface,
  extractInteractiveStates,
  formatVariantSummary
} = require('./shadcn-variant-extractor');

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

// Mock ShadCN button source code (simplified)
const mockButtonSource = `
import { cva, type VariantProps } from "class-variance-authority"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-xs hover:bg-primary/90",
        destructive: "bg-destructive text-white shadow-xs hover:bg-destructive/90",
        outline: "border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline"
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9"
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default"
    }
  }
)

function Button({ className, variant, size, ...props }) {
  return <button className={buttonVariants({ variant, size, className })} {...props} />
}

export { Button, buttonVariants }
`;

// Mock badge source
const mockBadgeSource = `
import { cva, type VariantProps } from "class-variance-authority"

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
    },
    defaultVariants: {
      variant: "default"
    }
  }
)

export function Badge({ className, variant, ...props }) {
  return <div className={badgeVariants({ variant, className })} {...props} />
}
`;

// Source without CVA
const mockCardSource = `
import * as React from "react"

function Card({ className, ...props }) {
  return <div className="rounded-xl border bg-card text-card-foreground shadow" {...props} />
}

function CardHeader({ className, ...props }) {
  return <div className="flex flex-col space-y-1.5 p-6" {...props} />
}

export { Card, CardHeader }
`;

function runTests() {
  console.log('\n=== ShadCN Variant Extractor Tests ===\n');

  // Test: extractCvaVariants - button
  console.log('--- extractCvaVariants ---');
  const buttonCva = extractCvaVariants(mockButtonSource);

  test('extracts variants from button', buttonCva.variants.length === 2);
  test('finds variant dimension', buttonCva.variants.some(v => v.name === 'variant'));
  test('finds size dimension', buttonCva.variants.some(v => v.name === 'size'));
  test('extracts default variants', Object.keys(buttonCva.defaultVariants).length === 2);
  test('default variant is "default"', buttonCva.defaultVariants.variant === 'default');
  test('default size is "default"', buttonCva.defaultVariants.size === 'default');
  test('extracts base classes', buttonCva.baseClasses.includes('inline-flex'));

  // Test: variant options
  console.log('\n--- Variant Options ---');
  const variantDim = buttonCva.variants.find(v => v.name === 'variant');
  const sizeDim = buttonCva.variants.find(v => v.name === 'size');

  test('variant has 6 options', variantDim && variantDim.options.length === 6);
  test('size has 4 options', sizeDim && sizeDim.options.length === 4);
  test('includes "destructive" variant', variantDim && variantDim.options.some(o => o.value === 'destructive'));
  test('includes "icon" size', sizeDim && sizeDim.options.some(o => o.value === 'icon'));

  // Test: extractCvaVariants - badge
  console.log('\n--- Badge CVA ---');
  const badgeCva = extractCvaVariants(mockBadgeSource);

  test('extracts badge variants', badgeCva.variants.length === 1);
  test('badge has only variant dimension', badgeCva.variants[0].name === 'variant');
  test('badge variant has 4 options', badgeCva.variants[0].options.length === 4);

  // Test: no CVA (card)
  console.log('\n--- No CVA Detection ---');
  const cardCva = extractCvaVariants(mockCardSource);

  test('returns empty for no CVA', cardCva.variants.length === 0);
  test('empty defaults for no CVA', Object.keys(cardCva.defaultVariants).length === 0);

  // Test: null/undefined input
  console.log('\n--- Edge Cases ---');
  const nullCva = extractCvaVariants(null);
  const emptyCva = extractCvaVariants('');

  test('handles null input', nullCva.variants.length === 0);
  test('handles empty string', emptyCva.variants.length === 0);

  // Test: extractTokensFromClasses
  console.log('\n--- Token Extraction from Classes ---');
  const tokens = extractTokensFromClasses('bg-primary text-white hover:bg-primary/90 px-4 py-2 shadow-xs');

  test('extracts color tokens', tokens.some(t => t.type === 'color'));
  test('extracts spacing tokens', tokens.some(t => t.type === 'spacing'));
  test('extracts effect tokens', tokens.some(t => t.type === 'effect'));

  // Test: toDesignBridgeFormat
  console.log('\n--- Design Bridge Format ---');
  const dbFormat = toDesignBridgeFormat(buttonCva.variants, buttonCva.defaultVariants);

  test('converts to DB format', dbFormat.length === 2);
  test('includes default value', dbFormat[0].default === 'default');
  test('includes options array', Array.isArray(dbFormat[0].options));
  test('sets type to variant', dbFormat[0].type === 'variant');

  // Test: generatePropsInterface
  console.log('\n--- TypeScript Props Generation ---');
  const propsInterface = generatePropsInterface(buttonCva.variants, 'Button');

  test('generates interface', propsInterface.includes('interface ButtonProps'));
  test('includes variant prop', propsInterface.includes('variant?:'));
  test('includes size prop', propsInterface.includes('size?:'));
  test('includes className prop', propsInterface.includes('className?: string'));

  // Test: extractInteractiveStates
  console.log('\n--- Interactive States ---');
  const states = extractInteractiveStates(buttonCva.variants);

  test('extracts hover states', Object.keys(states).length > 0 || states.hover !== undefined);

  // Test: formatVariantSummary
  console.log('\n--- Format Summary ---');
  const summary = formatVariantSummary(buttonCva);

  test('formats summary', summary.includes('Variant Dimensions'));
  test('shows base classes', summary.includes('Base Classes'));

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
