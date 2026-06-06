import 'dotenv/config';

/**
 * Main entry point
 * Generated with Bumba Sandbox Orchestrator
 */

async function main(): Promise<void> {
  console.log('Hello from {{PROJECT_NAME}}!');
  console.log('Environment:', process.env.NODE_ENV || 'development');
}

main().catch(console.error);

export { main };
