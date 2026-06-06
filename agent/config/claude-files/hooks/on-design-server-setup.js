#!/usr/bin/env node
/**
 * Design Server Setup Hook
 *
 * Triggered after design-init completes to copy the canonical Design Bridge
 * server into the project's server/ directory.
 *
 * This ensures every project has a working, self-contained Design Bridge server
 * that can communicate with the Figma plugin.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

/**
 * Main function - sets up the Design Bridge server
 */
async function setupServer() {
  const TEMPLATE_DIR = path.join(process.env.HOME, '.claude', 'templates', 'design-bridge-server');
  const PROJECT_SERVER_DIR = path.join(process.cwd(), 'server');

  process.stderr.write('\n');
  process.stderr.write('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
  process.stderr.write('  Design Bridge Server Setup\n');
  process.stderr.write('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
  process.stderr.write('\n');

  // Check if template exists
  if (!fs.existsSync(TEMPLATE_DIR)) {
    process.stderr.write('✗ Template directory not found: ' + TEMPLATE_DIR + '\n');
    process.stderr.write('\n');
    process.stderr.write('The Design Bridge server template is missing.\n');
    process.stderr.write('Please ensure ~/.claude/templates/design-bridge-server/ exists.\n');
    process.exit(1);
  }

  // Create server directory if it doesn't exist
  if (!fs.existsSync(PROJECT_SERVER_DIR)) {
    process.stderr.write('Creating server/ directory...\n');
    fs.mkdirSync(PROJECT_SERVER_DIR, { recursive: true });
  }

  // Check if server files already exist
  const existingFiles = fs.readdirSync(PROJECT_SERVER_DIR);
  const hasServer = existingFiles.some(f =>
    f === 'plugin-bridge.js' || f === 'start-test-server.js'
  );

  if (hasServer) {
    process.stderr.write('✓ Design Bridge server already exists in server/\n');
    process.stderr.write('  Skipping copy (to update, manually delete server/ and re-run design-init)\n');
    process.stderr.write('\n');
    process.exit(0);
  }

  process.stderr.write('Copying Design Bridge server from template...\n');
  process.stderr.write('  Source: ' + TEMPLATE_DIR + '\n');
  process.stderr.write('  Destination: ' + PROJECT_SERVER_DIR + '\n');
  process.stderr.write('\n');

  try {
    // Use rsync to copy files (excluding node_modules and .DS_Store)
    execSync(
      `rsync -a --exclude='node_modules' --exclude='.DS_Store' "${TEMPLATE_DIR}/" "${PROJECT_SERVER_DIR}/"`,
      { stdio: 'inherit' }
    );

    process.stderr.write('✓ Server files copied successfully\n');
    process.stderr.write('\n');

    // Install dependencies
    process.stderr.write('Installing server dependencies...\n');
    process.stderr.write('  Running: npm install in server/\n');
    process.stderr.write('\n');

    execSync('npm install', {
      cwd: PROJECT_SERVER_DIR,
      stdio: 'inherit'
    });

    process.stderr.write('\n');
    process.stderr.write('✓ Dependencies installed successfully\n');
    process.stderr.write('\n');

    // Create npm scripts in root package.json if it exists
    const rootPackageJsonPath = path.join(process.cwd(), 'package.json');
    if (fs.existsSync(rootPackageJsonPath)) {
      process.stderr.write('Adding Design Bridge commands to package.json...\n');
      const packageJson = JSON.parse(fs.readFileSync(rootPackageJsonPath, 'utf8'));

      if (!packageJson.scripts) {
        packageJson.scripts = {};
      }

      // Add scripts if they don't exist
      const scriptsToAdd = {
        'bridge:start': 'cd server && node start-test-server.js',
        'bridge:stop': 'pkill -f "node.*start-test-server" || echo "Server not running"',
        'bridge:status': 'curl -s http://localhost:9001/health || echo "Server is NOT running"',
        'bridge:restart': 'npm run bridge:stop && sleep 1 && npm run bridge:start'
      };

      let added = false;
      for (const [name, command] of Object.entries(scriptsToAdd)) {
        if (!packageJson.scripts[name]) {
          packageJson.scripts[name] = command;
          added = true;
        }
      }

      if (added) {
        fs.writeFileSync(rootPackageJsonPath, JSON.stringify(packageJson, null, 2) + '\n');
        process.stderr.write('✓ Added bridge:* commands to package.json\n');
      } else {
        process.stderr.write('✓ Bridge commands already exist in package.json\n');
      }
    }

    process.stderr.write('\n');
    process.stderr.write('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
    process.stderr.write('  Design Bridge Server Ready!\n');
    process.stderr.write('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
    process.stderr.write('\n');
    process.stderr.write('Start the server:\n');
    process.stderr.write('  npm run bridge:start\n');
    process.stderr.write('\n');
    process.stderr.write('Or manually:\n');
    process.stderr.write('  cd server && node start-test-server.js\n');
    process.stderr.write('\n');
    process.stderr.write('Server will run on:\n');
    process.stderr.write('  HTTP:      http://localhost:9001\n');
    process.stderr.write('  WebSocket: ws://localhost:9002\n');
    process.stderr.write('\n');

  } catch (error) {
    process.stderr.write('✗ Error setting up Design Bridge server: ' + error.message + '\n');
    process.stderr.write('\n');
    process.stderr.write('You may need to manually copy the server:\n');
    process.stderr.write(`  cp -R ${TEMPLATE_DIR}/* ${PROJECT_SERVER_DIR}/\n`);
    process.stderr.write(`  cd ${PROJECT_SERVER_DIR} && npm install\n`);
    process.stderr.write('\n');
    process.exit(1);
  }
}

// Only run if executed directly (not when required as a module)
if (require.main === module) {
  setupServer().catch(error => {
    process.stderr.write('Fatal error: ' + error + '\n');
    process.exit(1);
  });
}
