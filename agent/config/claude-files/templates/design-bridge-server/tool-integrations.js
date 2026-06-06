#!/usr/bin/env node

/**
 * Design Bridge External Tool Integrations
 * Sprint 8.3: Third-Party Tool Connectors
 *
 * Features:
 * - Storybook integration with story generation
 * - Chromatic visual testing
 * - GitHub/GitLab CI integration
 * - Slack/Discord notifications
 * - Figma API connector
 * - NPM/Yarn package publishing
 * - Jira issue tracking
 * - Linear issue tracking
 */

const EventEmitter = require('events');
const https = require('https');
const http = require('http');
const fs = require('fs').promises;
const path = require('path');
const { spawn, exec } = require('child_process');
const crypto = require('crypto');

// ============================================================================
// Base Integration Class
// ============================================================================

class BaseIntegration extends EventEmitter {
  constructor(name, config = {}) {
    super();
    this.name = name;
    this.config = config;
    this.connected = false;
    this.lastActivity = null;
    this.requestCount = 0;
    this.errorCount = 0;
  }

  async connect() {
    throw new Error('connect must be implemented');
  }

  async disconnect() {
    this.connected = false;
    this.emit('disconnected', { integration: this.name });
  }

  async healthCheck() {
    return {
      healthy: this.connected,
      name: this.name,
      lastActivity: this.lastActivity,
      requestCount: this.requestCount,
      errorCount: this.errorCount
    };
  }

  makeRequest(url, options = {}) {
    return new Promise((resolve, reject) => {
      const protocol = url.startsWith('https') ? https : http;
      const parsedUrl = new URL(url);

      const requestOptions = {
        hostname: parsedUrl.hostname,
        port: parsedUrl.port || (url.startsWith('https') ? 443 : 80),
        path: parsedUrl.pathname + parsedUrl.search,
        method: options.method || 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          ...options.headers
        },
        timeout: options.timeout || 30000
      };

      const req = protocol.request(requestOptions, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          this.requestCount++;
          this.lastActivity = new Date().toISOString();

          try {
            const parsed = data ? JSON.parse(data) : null;
            resolve({ status: res.statusCode, data: parsed, headers: res.headers });
          } catch {
            resolve({ status: res.statusCode, data, headers: res.headers });
          }
        });
      });

      req.on('error', (error) => {
        this.errorCount++;
        reject(error);
      });

      req.on('timeout', () => {
        req.destroy();
        reject(new Error('Request timeout'));
      });

      if (options.body) {
        const body = typeof options.body === 'string'
          ? options.body
          : JSON.stringify(options.body);
        req.write(body);
      }

      req.end();
    });
  }

  async retryRequest(url, options = {}, maxRetries = 3) {
    let lastError;
    for (let i = 0; i < maxRetries; i++) {
      try {
        return await this.makeRequest(url, options);
      } catch (error) {
        lastError = error;
        await this.delay(Math.pow(2, i) * 1000); // Exponential backoff
      }
    }
    throw lastError;
  }

  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  formatComponentName(name) {
    return name
      .replace(/[^a-zA-Z0-9]/g, ' ')
      .split(' ')
      .filter(Boolean)
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join('');
  }

  formatKebabCase(name) {
    return name
      .replace(/[^a-zA-Z0-9]/g, '-')
      .toLowerCase()
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
  }
}

// ============================================================================
// Storybook Integration
// ============================================================================

class StorybookIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('storybook', config);
    this.config = {
      configDir: config.configDir || '.storybook',
      outputDir: config.outputDir || 'storybook-static',
      port: config.port || 6006,
      framework: config.framework || 'react',
      typescript: config.typescript !== false,
      // NOTE: Only @storybook/addon-docs is needed for Storybook 10.x
      // addon-essentials, addon-links, addon-interactions are DEPRECATED (merged into core)
      addons: config.addons || [
        '@storybook/addon-docs'
      ],
      ...config
    };
  }

  async connect() {
    this.connected = true;
    this.emit('connected', { integration: this.name });
    return true;
  }

  async generateStory(component) {
    const { name, props = [], variants = [], description = '' } = component;
    const componentName = this.formatComponentName(name);
    const ext = this.config.typescript ? 'tsx' : 'jsx';

    const propsArgs = this.generateArgTypes(props);
    const defaultArgs = this.generateDefaultArgs(props);
    const variantStories = this.generateVariantStories(componentName, variants);

    const story = `import type { Meta, StoryObj } from '@storybook/${this.config.framework}';
import { ${componentName} } from './${componentName}';

/**
 * ${description || `${componentName} component`}
 */
const meta: Meta<typeof ${componentName}> = {
  title: 'Components/${componentName}',
  component: ${componentName},
  parameters: {
    layout: 'centered',
    docs: {
      description: {
        component: '${description || `A reusable ${componentName} component.`}',
      },
    },
  },
  tags: ['autodocs'],
  argTypes: {
${propsArgs}
  },
  args: {
${defaultArgs}
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Default ${componentName} appearance.
 */
export const Default: Story = {
  args: {},
};

${variantStories}

/**
 * ${componentName} in disabled state.
 */
export const Disabled: Story = {
  args: {
    disabled: true,
  },
};

/**
 * ${componentName} with custom className.
 */
export const CustomStyled: Story = {
  args: {
    className: 'custom-${this.formatKebabCase(name)}',
  },
};
`;

    this.emit('story:generated', { component: componentName });
    return {
      filename: `${componentName}.stories.${ext}`,
      content: story,
      type: 'story'
    };
  }

  generateArgTypes(props) {
    return props.map(prop => {
      const propName = prop.name.replace(/[^a-zA-Z0-9]/g, '');
      const control = this.getControlConfig(prop);
      const description = prop.description || `The ${propName} prop`;

      return `    ${propName}: {
      control: ${JSON.stringify(control)},
      description: '${description}',
      table: {
        type: { summary: '${prop.type || 'string'}' },
        defaultValue: { summary: ${JSON.stringify(prop.default)} },
      },
    },`;
    }).join('\n');
  }

  getControlConfig(prop) {
    const type = prop.type || 'string';

    if (prop.options && prop.options.length > 0) {
      return { type: 'select', options: prop.options };
    }

    const controlMap = {
      'string': { type: 'text' },
      'number': { type: 'number', min: prop.min, max: prop.max, step: prop.step },
      'boolean': { type: 'boolean' },
      'array': { type: 'object' },
      'object': { type: 'object' },
      'color': { type: 'color' },
      'date': { type: 'date' },
      'range': { type: 'range', min: prop.min || 0, max: prop.max || 100, step: prop.step || 1 }
    };

    return controlMap[type] || { type: 'text' };
  }

  generateDefaultArgs(props) {
    return props
      .filter(prop => prop.default !== undefined)
      .map(prop => {
        const propName = prop.name.replace(/[^a-zA-Z0-9]/g, '');
        return `    ${propName}: ${JSON.stringify(prop.default)},`;
      }).join('\n');
  }

  generateVariantStories(componentName, variants) {
    if (!variants || variants.length === 0) return '';

    return variants.map(variant => {
      const variantName = this.formatComponentName(variant.name);
      const description = variant.description || `${componentName} in ${variant.name} variant`;

      return `/**
 * ${description}
 */
export const ${variantName}: Story = {
  args: {
    variant: '${variant.name}',
  },
  parameters: {
    docs: {
      description: {
        story: '${description}',
      },
    },
  },
};`;
    }).join('\n\n');
  }

  async generateStoriesForComponents(components) {
    const stories = [];
    for (const component of components) {
      const story = await this.generateStory(component);
      stories.push(story);
    }
    return stories;
  }

  async buildStorybook(options = {}) {
    return new Promise((resolve, reject) => {
      const args = ['storybook', 'build'];

      if (options.outputDir || this.config.outputDir) {
        args.push('-o', options.outputDir || this.config.outputDir);
      }
      if (options.configDir || this.config.configDir) {
        args.push('-c', options.configDir || this.config.configDir);
      }
      if (options.quiet) {
        args.push('--quiet');
      }

      const build = spawn('npx', args, {
        stdio: 'pipe',
        cwd: options.cwd || process.cwd()
      });

      let stdout = '';
      let stderr = '';

      build.stdout.on('data', (data) => {
        stdout += data;
        this.emit('build:output', { type: 'stdout', data: data.toString() });
      });

      build.stderr.on('data', (data) => {
        stderr += data;
        this.emit('build:output', { type: 'stderr', data: data.toString() });
      });

      build.on('close', (code) => {
        const result = {
          success: code === 0,
          code,
          stdout,
          stderr,
          outputDir: options.outputDir || this.config.outputDir
        };

        if (code === 0) {
          this.emit('build:complete', result);
          resolve(result);
        } else {
          this.emit('build:failed', result);
          reject(new Error(`Storybook build failed with code ${code}: ${stderr}`));
        }
      });
    });
  }

  async startDevServer(options = {}) {
    return new Promise((resolve, reject) => {
      const args = ['storybook', 'dev'];

      args.push('-p', String(options.port || this.config.port));

      if (options.configDir || this.config.configDir) {
        args.push('-c', options.configDir || this.config.configDir);
      }
      if (options.ci) {
        args.push('--ci');
      }

      const server = spawn('npx', args, {
        stdio: 'pipe',
        cwd: options.cwd || process.cwd(),
        detached: options.detached || false
      });

      let started = false;

      server.stdout.on('data', (data) => {
        const output = data.toString();
        if (output.includes('Local:') && !started) {
          started = true;
          this.emit('server:started', { port: options.port || this.config.port });
          resolve({ server, port: options.port || this.config.port });
        }
      });

      server.stderr.on('data', (data) => {
        if (!started) {
          this.emit('server:error', { error: data.toString() });
        }
      });

      server.on('error', reject);

      // Timeout after 60 seconds
      setTimeout(() => {
        if (!started) {
          server.kill();
          reject(new Error('Storybook dev server startup timeout'));
        }
      }, 60000);
    });
  }

  generateMainConfig() {
    const framework = this.config.framework;
    const addons = this.config.addons;

    return {
      filename: 'main.ts',
      content: `import type { StorybookConfig } from '@storybook/${framework}';

const config: StorybookConfig = {
  stories: [
    '../src/**/*.mdx',
    '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)'
  ],
  addons: ${JSON.stringify(addons, null, 4).replace(/"/g, "'")},
  framework: {
    name: '@storybook/${framework}',
    options: {},
  },
  docs: {
    autodocs: 'tag',
  },
  staticDirs: ['../public'],
  typescript: {
    check: true,
    reactDocgen: 'react-docgen-typescript',
  },
};

export default config;
`,
      type: 'config'
    };
  }

  generatePreviewConfig() {
    return {
      filename: 'preview.ts',
      content: `import type { Preview } from '@storybook/${this.config.framework}';
import '../src/styles/globals.css';

const preview: Preview = {
  parameters: {
    actions: { argTypesRegex: '^on[A-Z].*' },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    backgrounds: {
      default: 'light',
      values: [
        { name: 'light', value: '#ffffff' },
        { name: 'dark', value: '#1a1a1a' },
        { name: 'gray', value: '#f5f5f5' },
      ],
    },
    viewport: {
      viewports: {
        mobile: { name: 'Mobile', styles: { width: '375px', height: '667px' } },
        tablet: { name: 'Tablet', styles: { width: '768px', height: '1024px' } },
        desktop: { name: 'Desktop', styles: { width: '1440px', height: '900px' } },
      },
    },
  },
  globalTypes: {
    theme: {
      name: 'Theme',
      description: 'Global theme for components',
      defaultValue: 'light',
      toolbar: {
        icon: 'paintbrush',
        items: ['light', 'dark'],
        showName: true,
      },
    },
  },
};

export default preview;
`,
      type: 'config'
    };
  }

  generateManagerConfig() {
    return {
      filename: 'manager.ts',
      content: `import { addons } from 'storybook/manager-api';
import { create } from 'storybook/theming';

const theme = create({
  base: 'light',
  brandTitle: 'Design Bridge Components',
  brandUrl: 'https://design-bridge.dev',
  brandTarget: '_self',

  // UI
  appBg: '#f8f8f8',
  appContentBg: '#ffffff',
  appBorderColor: '#e0e0e0',
  appBorderRadius: 4,

  // Typography
  fontBase: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
  fontCode: '"Fira Code", monospace',

  // Text colors
  textColor: '#1a1a1a',
  textInverseColor: '#ffffff',

  // Toolbar colors
  barTextColor: '#666666',
  barSelectedColor: '#0066cc',
  barBg: '#ffffff',

  // Form colors
  inputBg: '#ffffff',
  inputBorder: '#e0e0e0',
  inputTextColor: '#1a1a1a',
  inputBorderRadius: 4,
});

addons.setConfig({
  theme,
  sidebar: {
    showRoots: true,
    collapsedRoots: ['other'],
  },
  toolbar: {
    title: { hidden: false },
    zoom: { hidden: false },
    eject: { hidden: false },
    copy: { hidden: false },
    fullscreen: { hidden: false },
  },
});
`,
      type: 'config'
    };
  }
}

// ============================================================================
// Chromatic Integration
// ============================================================================

class ChromaticIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('chromatic', config);
    this.config = {
      projectToken: config.projectToken || process.env.CHROMATIC_PROJECT_TOKEN,
      buildScriptName: config.buildScriptName || 'build-storybook',
      storybookBuildDir: config.storybookBuildDir || 'storybook-static',
      onlyChanged: config.onlyChanged !== false,
      externals: config.externals || ['**/*.md'],
      ...config
    };
  }

  async connect() {
    if (!this.config.projectToken) {
      throw new Error('Chromatic project token required. Set CHROMATIC_PROJECT_TOKEN environment variable.');
    }
    this.connected = true;
    this.emit('connected', { integration: this.name });
    return true;
  }

  async runVisualTests(options = {}) {
    return new Promise((resolve, reject) => {
      const args = ['chromatic'];

      // Authentication
      args.push('--project-token', this.config.projectToken);

      // Build options
      if (options.buildScriptName || this.config.buildScriptName) {
        args.push('--build-script-name', options.buildScriptName || this.config.buildScriptName);
      }
      if (options.storybookBuildDir || this.config.storybookBuildDir) {
        args.push('--storybook-build-dir', options.storybookBuildDir || this.config.storybookBuildDir);
      }

      // Behavior options
      if (options.exitZeroOnChanges) {
        args.push('--exit-zero-on-changes');
      }
      if (options.exitOnceUploaded) {
        args.push('--exit-once-uploaded');
      }
      if (options.autoAcceptChanges) {
        args.push('--auto-accept-changes');
      }
      if (options.onlyChanged !== false && this.config.onlyChanged) {
        args.push('--only-changed');
      }
      if (options.skip) {
        args.push('--skip');
      }

      // Branch options
      if (options.branchName) {
        args.push('--branch-name', options.branchName);
      }
      if (options.patchBuild) {
        args.push('--patch-build', options.patchBuild);
      }

      // Output options
      if (options.debug) {
        args.push('--debug');
      }

      const chromatic = spawn('npx', args, {
        stdio: 'pipe',
        cwd: options.cwd || process.cwd()
      });

      let stdout = '';
      let stderr = '';

      chromatic.stdout.on('data', (data) => {
        stdout += data;
        this.emit('test:output', { type: 'stdout', data: data.toString() });
      });

      chromatic.stderr.on('data', (data) => {
        stderr += data;
        this.emit('test:output', { type: 'stderr', data: data.toString() });
      });

      chromatic.on('close', (code) => {
        const result = this.parseOutput(stdout + stderr, code);
        result.stdout = stdout;
        result.stderr = stderr;
        result.exitCode = code;

        this.emit('test:complete', result);

        if (code === 0 || options.exitZeroOnChanges) {
          resolve(result);
        } else {
          reject(new Error(`Chromatic tests failed with code ${code}`));
        }
      });
    });
  }

  parseOutput(output, exitCode) {
    const result = {
      success: exitCode === 0,
      buildNumber: null,
      buildUrl: null,
      storybookUrl: null,
      changes: 0,
      snapshots: 0,
      components: 0,
      specs: 0,
      errors: []
    };

    // Parse build number
    const buildMatch = output.match(/Build (\d+)/i);
    if (buildMatch) {
      result.buildNumber = buildMatch[1];
    }

    // Parse build URL
    const urlMatch = output.match(/https:\/\/www\.chromatic\.com\/build\?[^\s]+/);
    if (urlMatch) {
      result.buildUrl = urlMatch[0];
    }

    // Parse storybook URL
    const storybookMatch = output.match(/https:\/\/[^\s]+\.chromatic\.com/);
    if (storybookMatch) {
      result.storybookUrl = storybookMatch[0];
    }

    // Parse changes
    const changesMatch = output.match(/(\d+)\s+changes?\s+detected/i);
    if (changesMatch) {
      result.changes = parseInt(changesMatch[1]);
    }

    // Parse snapshots
    const snapshotsMatch = output.match(/(\d+)\s+snapshots?/i);
    if (snapshotsMatch) {
      result.snapshots = parseInt(snapshotsMatch[1]);
    }

    // Parse components
    const componentsMatch = output.match(/(\d+)\s+components?/i);
    if (componentsMatch) {
      result.components = parseInt(componentsMatch[1]);
    }

    // Parse specs/stories
    const specsMatch = output.match(/(\d+)\s+(?:specs?|stories)/i);
    if (specsMatch) {
      result.specs = parseInt(specsMatch[1]);
    }

    // Parse errors
    const errorMatches = output.matchAll(/error[:\s]+([^\n]+)/gi);
    for (const match of errorMatches) {
      result.errors.push(match[1].trim());
    }

    return result;
  }

  async acceptChanges(buildNumber) {
    // This would typically use Chromatic's API
    this.emit('changes:accepted', { buildNumber });
    return { success: true, buildNumber };
  }

  generateCIConfig(ciType = 'github') {
    const configs = {
      github: this.generateGitHubAction(),
      gitlab: this.generateGitLabCI(),
      circleci: this.generateCircleCI()
    };

    return configs[ciType] || configs.github;
  }

  generateGitHubAction() {
    return {
      filename: 'chromatic.yml',
      content: `name: Chromatic

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  chromatic:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Run Chromatic
        uses: chromaui/action@latest
        with:
          projectToken: \${{ secrets.CHROMATIC_PROJECT_TOKEN }}
          buildScriptName: ${this.config.buildScriptName}
          onlyChanged: true
          exitZeroOnChanges: true
          autoAcceptChanges: "main"
`,
      type: 'ci-config'
    };
  }

  generateGitLabCI() {
    return {
      filename: '.gitlab-ci-chromatic.yml',
      content: `chromatic:
  image: node:20
  stage: test
  cache:
    paths:
      - node_modules/
  script:
    - npm ci
    - npx chromatic --project-token=\${CHROMATIC_PROJECT_TOKEN} --exit-zero-on-changes
  only:
    - main
    - merge_requests
`,
      type: 'ci-config'
    };
  }

  generateCircleCI() {
    return {
      filename: 'config.yml',
      content: `version: 2.1

orbs:
  node: circleci/node@5

jobs:
  chromatic:
    executor: node/default
    steps:
      - checkout
      - node/install-packages
      - run:
          name: Run Chromatic
          command: npx chromatic --project-token=\${CHROMATIC_PROJECT_TOKEN} --exit-zero-on-changes

workflows:
  visual-testing:
    jobs:
      - chromatic
`,
      type: 'ci-config'
    };
  }
}

// ============================================================================
// GitHub Integration
// ============================================================================

class GitHubIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('github', config);
    this.config = {
      token: config.token || process.env.GITHUB_TOKEN,
      owner: config.owner || process.env.GITHUB_OWNER,
      repo: config.repo || process.env.GITHUB_REPO,
      apiUrl: config.apiUrl || 'https://api.github.com',
      ...config
    };
    this.user = null;
  }

  async connect() {
    if (!this.config.token) {
      throw new Error('GitHub token required. Set GITHUB_TOKEN environment variable.');
    }

    const response = await this.makeRequest(`${this.config.apiUrl}/user`, {
      headers: {
        'Authorization': `token ${this.config.token}`,
        'User-Agent': 'DesignBridge/1.0'
      }
    });

    if (response.status === 200) {
      this.connected = true;
      this.user = response.data;
      this.emit('connected', { integration: this.name, user: this.user.login });
      return true;
    }

    throw new Error(`GitHub authentication failed: ${response.status}`);
  }

  getAuthHeaders() {
    return {
      'Authorization': `token ${this.config.token}`,
      'User-Agent': 'DesignBridge/1.0',
      'Accept': 'application/vnd.github.v3+json'
    };
  }

  async getRepository(owner, repo) {
    owner = owner || this.config.owner;
    repo = repo || this.config.repo;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}`,
      { headers: this.getAuthHeaders() }
    );

    return response.data;
  }

  async createPullRequest(options) {
    const { title, body, head, base = 'main', draft = false, maintainerCanModify = true } = options;
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/pulls`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: {
          title,
          body,
          head,
          base,
          draft,
          maintainer_can_modify: maintainerCanModify
        }
      }
    );

    if (response.status === 201) {
      this.emit('pr:created', {
        number: response.data.number,
        url: response.data.html_url,
        title
      });
      return response.data;
    }

    throw new Error(`Failed to create PR: ${JSON.stringify(response.data)}`);
  }

  async updatePullRequest(prNumber, options) {
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/pulls/${prNumber}`,
      {
        method: 'PATCH',
        headers: this.getAuthHeaders(),
        body: options
      }
    );

    this.emit('pr:updated', { number: prNumber });
    return response.data;
  }

  async mergePullRequest(prNumber, options = {}) {
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;
    const { commitTitle, commitMessage, mergeMethod = 'squash' } = options;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/pulls/${prNumber}/merge`,
      {
        method: 'PUT',
        headers: this.getAuthHeaders(),
        body: {
          commit_title: commitTitle,
          commit_message: commitMessage,
          merge_method: mergeMethod
        }
      }
    );

    if (response.status === 200) {
      this.emit('pr:merged', { number: prNumber });
      return response.data;
    }

    throw new Error(`Failed to merge PR: ${JSON.stringify(response.data)}`);
  }

  async createIssue(options) {
    const { title, body, labels = [], assignees = [], milestone } = options;
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/issues`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: { title, body, labels, assignees, milestone }
      }
    );

    if (response.status === 201) {
      this.emit('issue:created', {
        number: response.data.number,
        url: response.data.html_url
      });
      return response.data;
    }

    throw new Error(`Failed to create issue: ${JSON.stringify(response.data)}`);
  }

  async createComment(issueNumber, body, options = {}) {
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/issues/${issueNumber}/comments`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: { body }
      }
    );

    this.emit('comment:created', { issueNumber, commentId: response.data.id });
    return response.data;
  }

  async createRelease(options) {
    const { tagName, name, body, draft = false, prerelease = false, targetCommitish = 'main' } = options;
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/releases`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: {
          tag_name: tagName,
          name,
          body,
          draft,
          prerelease,
          target_commitish: targetCommitish
        }
      }
    );

    if (response.status === 201) {
      this.emit('release:created', {
        id: response.data.id,
        tagName,
        url: response.data.html_url
      });
      return response.data;
    }

    throw new Error(`Failed to create release: ${JSON.stringify(response.data)}`);
  }

  async triggerWorkflow(workflowId, options = {}) {
    const ref = options.ref || 'main';
    const inputs = options.inputs || {};
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/actions/workflows/${workflowId}/dispatches`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: { ref, inputs }
      }
    );

    if (response.status === 204) {
      this.emit('workflow:triggered', { workflowId, ref, inputs });
      return true;
    }

    throw new Error(`Failed to trigger workflow: ${response.status}`);
  }

  async getWorkflowRuns(workflowId, options = {}) {
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/actions/workflows/${workflowId}/runs`,
      { headers: this.getAuthHeaders() }
    );

    return response.data;
  }

  async createOrUpdateFile(options) {
    const { path, content, message, branch = 'main', sha } = options;
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;

    const body = {
      message,
      content: Buffer.from(content).toString('base64'),
      branch
    };

    if (sha) {
      body.sha = sha;
    }

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/contents/${path}`,
      {
        method: 'PUT',
        headers: this.getAuthHeaders(),
        body
      }
    );

    this.emit('file:updated', { path, branch });
    return response.data;
  }

  async getFile(path, options = {}) {
    const owner = options.owner || this.config.owner;
    const repo = options.repo || this.config.repo;
    const ref = options.ref || 'main';

    const response = await this.makeRequest(
      `${this.config.apiUrl}/repos/${owner}/${repo}/contents/${path}?ref=${ref}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.data.content) {
      response.data.decodedContent = Buffer.from(response.data.content, 'base64').toString('utf8');
    }

    return response.data;
  }

  generateWorkflow(options = {}) {
    const {
      name = 'Design Bridge Sync',
      triggers = ['push', 'workflow_dispatch'],
      nodeVersion = '20',
      steps = []
    } = options;

    const triggerConfig = triggers.map(t => {
      if (t === 'push') return '  push:\n    branches: [main]';
      if (t === 'pull_request') return '  pull_request:\n    branches: [main]';
      if (t === 'workflow_dispatch') return '  workflow_dispatch:';
      if (t === 'schedule') return '  schedule:\n    - cron: "0 0 * * *"';
      return `  ${t}:`;
    }).join('\n');

    const defaultSteps = `
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '${nodeVersion}'
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Sync Design Tokens
        run: npx design-bridge sync
        env:
          FIGMA_TOKEN: \${{ secrets.FIGMA_TOKEN }}
          FIGMA_FILE_ID: \${{ secrets.FIGMA_FILE_ID }}

      - name: Generate Components
        run: npx design-bridge generate

      - name: Build
        run: npm run build

      - name: Test
        run: npm test

      - name: Commit changes
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: 'chore: sync design tokens [skip ci]'
          file_pattern: 'src/tokens/* src/components/*'
`;

    const customSteps = steps.length > 0
      ? steps.map(s => `      - name: ${s.name}\n        run: ${s.run}`).join('\n\n')
      : defaultSteps;

    return {
      filename: 'design-bridge.yml',
      content: `name: ${name}

on:
${triggerConfig}

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
${customSteps}
`,
      type: 'workflow'
    };
  }
}

// ============================================================================
// Slack Integration
// ============================================================================

class SlackIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('slack', config);
    this.config = {
      webhookUrl: config.webhookUrl || process.env.SLACK_WEBHOOK_URL,
      botToken: config.botToken || process.env.SLACK_BOT_TOKEN,
      channel: config.channel || process.env.SLACK_CHANNEL,
      username: config.username || 'Design Bridge',
      iconEmoji: config.iconEmoji || ':art:',
      iconUrl: config.iconUrl,
      ...config
    };
  }

  async connect() {
    if (!this.config.webhookUrl && !this.config.botToken) {
      throw new Error('Slack webhook URL or bot token required.');
    }
    this.connected = true;
    this.emit('connected', { integration: this.name });
    return true;
  }

  async sendMessage(message) {
    const payload = {
      channel: message.channel || this.config.channel,
      username: this.config.username,
      icon_emoji: this.config.iconEmoji,
      icon_url: this.config.iconUrl,
      text: message.text,
      blocks: message.blocks,
      attachments: message.attachments,
      thread_ts: message.threadTs,
      unfurl_links: message.unfurlLinks !== false,
      unfurl_media: message.unfurlMedia !== false
    };

    // Remove undefined values
    Object.keys(payload).forEach(key => payload[key] === undefined && delete payload[key]);

    let response;
    if (this.config.botToken) {
      response = await this.makeRequest('https://slack.com/api/chat.postMessage', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.config.botToken}`
        },
        body: payload
      });
    } else {
      response = await this.makeRequest(this.config.webhookUrl, {
        method: 'POST',
        body: payload
      });
    }

    this.emit('message:sent', { channel: payload.channel });
    return response;
  }

  async sendSyncNotification(syncResult) {
    const { components = [], tokens = [], errors = [], duration, fileId } = syncResult;
    const hasErrors = errors.length > 0;

    const blocks = [
      {
        type: 'header',
        text: {
          type: 'plain_text',
          text: hasErrors ? ':warning: Design Sync Completed with Warnings' : ':white_check_mark: Design Sync Complete',
          emoji: true
        }
      },
      {
        type: 'section',
        fields: [
          {
            type: 'mrkdwn',
            text: `*Components*\n${components.length} synced`
          },
          {
            type: 'mrkdwn',
            text: `*Tokens*\n${tokens.length} updated`
          },
          {
            type: 'mrkdwn',
            text: `*Duration*\n${duration || 'N/A'}s`
          },
          {
            type: 'mrkdwn',
            text: `*Errors*\n${errors.length}`
          }
        ]
      }
    ];

    if (fileId) {
      blocks.push({
        type: 'context',
        elements: [
          {
            type: 'mrkdwn',
            text: `Figma File: \`${fileId}\``
          }
        ]
      });
    }

    if (errors.length > 0) {
      blocks.push({
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `*Errors:*\n${errors.slice(0, 5).map(e => `• ${e}`).join('\n')}${errors.length > 5 ? `\n_...and ${errors.length - 5} more_` : ''}`
        }
      });
    }

    if (components.length > 0) {
      const componentList = components.slice(0, 10).map(c => c.name || c).join(', ');
      blocks.push({
        type: 'context',
        elements: [
          {
            type: 'mrkdwn',
            text: `Components: ${componentList}${components.length > 10 ? ` +${components.length - 10} more` : ''}`
          }
        ]
      });
    }

    blocks.push({
      type: 'actions',
      elements: [
        {
          type: 'button',
          text: { type: 'plain_text', text: 'View Changes', emoji: true },
          url: syncResult.prUrl || syncResult.commitUrl || '#',
          action_id: 'view_changes'
        }
      ]
    });

    return this.sendMessage({ blocks });
  }

  async sendBuildNotification(buildResult) {
    const { success, duration, tests = {}, buildUrl, commitSha } = buildResult;
    const statusEmoji = success ? ':white_check_mark:' : ':x:';
    const statusText = success ? 'Build Passed' : 'Build Failed';

    const blocks = [
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `${statusEmoji} *${statusText}*`
        }
      },
      {
        type: 'section',
        fields: [
          { type: 'mrkdwn', text: `*Duration*\n${duration}s` },
          { type: 'mrkdwn', text: `*Tests*\n${tests.passed || 0}/${tests.total || 0} passed` }
        ]
      }
    ];

    if (commitSha) {
      blocks.push({
        type: 'context',
        elements: [
          { type: 'mrkdwn', text: `Commit: \`${commitSha.substring(0, 7)}\`` }
        ]
      });
    }

    if (buildUrl) {
      blocks.push({
        type: 'actions',
        elements: [
          {
            type: 'button',
            text: { type: 'plain_text', text: 'View Build', emoji: true },
            url: buildUrl,
            action_id: 'view_build'
          }
        ]
      });
    }

    return this.sendMessage({ blocks });
  }

  async sendComponentUpdateNotification(updateResult) {
    const { component, changes, author, prUrl } = updateResult;

    const blocks = [
      {
        type: 'header',
        text: {
          type: 'plain_text',
          text: ':pencil2: Component Updated',
          emoji: true
        }
      },
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `*${component}* has been updated`
        }
      }
    ];

    if (changes && changes.length > 0) {
      blocks.push({
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `*Changes:*\n${changes.map(c => `• ${c}`).join('\n')}`
        }
      });
    }

    if (author) {
      blocks.push({
        type: 'context',
        elements: [
          { type: 'mrkdwn', text: `Updated by: ${author}` }
        ]
      });
    }

    if (prUrl) {
      blocks.push({
        type: 'actions',
        elements: [
          {
            type: 'button',
            text: { type: 'plain_text', text: 'View PR', emoji: true },
            url: prUrl,
            action_id: 'view_pr'
          }
        ]
      });
    }

    return this.sendMessage({ blocks });
  }
}

// ============================================================================
// Discord Integration
// ============================================================================

class DiscordIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('discord', config);
    this.config = {
      webhookUrl: config.webhookUrl || process.env.DISCORD_WEBHOOK_URL,
      username: config.username || 'Design Bridge',
      avatarUrl: config.avatarUrl,
      ...config
    };
  }

  async connect() {
    if (!this.config.webhookUrl) {
      throw new Error('Discord webhook URL required. Set DISCORD_WEBHOOK_URL environment variable.');
    }
    this.connected = true;
    this.emit('connected', { integration: this.name });
    return true;
  }

  async sendMessage(content, options = {}) {
    const payload = {
      content: content || undefined,
      username: this.config.username,
      avatar_url: this.config.avatarUrl,
      embeds: options.embeds || [],
      tts: options.tts || false,
      allowed_mentions: options.allowedMentions
    };

    // Remove undefined values
    Object.keys(payload).forEach(key => payload[key] === undefined && delete payload[key]);

    const response = await this.makeRequest(this.config.webhookUrl, {
      method: 'POST',
      body: payload
    });

    this.emit('message:sent', {});
    return response;
  }

  async sendSyncNotification(syncResult) {
    const { components = [], tokens = [], errors = [], duration } = syncResult;
    const hasErrors = errors.length > 0;

    const embed = {
      title: hasErrors ? '⚠️ Design Sync Completed with Warnings' : '✅ Design Sync Complete',
      color: hasErrors ? 0xff9900 : 0x00ff00,
      fields: [
        { name: '📦 Components', value: `${components.length} synced`, inline: true },
        { name: '🎨 Tokens', value: `${tokens.length} updated`, inline: true },
        { name: '⏱️ Duration', value: `${duration || 'N/A'}s`, inline: true }
      ],
      timestamp: new Date().toISOString(),
      footer: {
        text: 'Design Bridge'
      }
    };

    if (errors.length > 0) {
      embed.fields.push({
        name: '❌ Errors',
        value: errors.slice(0, 5).map(e => `• ${e}`).join('\n') +
          (errors.length > 5 ? `\n...and ${errors.length - 5} more` : ''),
        inline: false
      });
    }

    return this.sendMessage('', { embeds: [embed] });
  }

  async sendBuildNotification(buildResult) {
    const { success, duration, tests = {}, buildUrl } = buildResult;

    const embed = {
      title: success ? '✅ Build Passed' : '❌ Build Failed',
      color: success ? 0x00ff00 : 0xff0000,
      fields: [
        { name: 'Duration', value: `${duration}s`, inline: true },
        { name: 'Tests', value: `${tests.passed || 0}/${tests.total || 0}`, inline: true }
      ],
      timestamp: new Date().toISOString()
    };

    if (buildUrl) {
      embed.url = buildUrl;
    }

    return this.sendMessage('', { embeds: [embed] });
  }

  async sendComponentUpdateNotification(updateResult) {
    const { component, changes = [], author } = updateResult;

    const embed = {
      title: '📝 Component Updated',
      description: `**${component}** has been updated`,
      color: 0x5865f2,
      fields: [],
      timestamp: new Date().toISOString()
    };

    if (changes.length > 0) {
      embed.fields.push({
        name: 'Changes',
        value: changes.map(c => `• ${c}`).join('\n')
      });
    }

    if (author) {
      embed.footer = { text: `Updated by ${author}` };
    }

    return this.sendMessage('', { embeds: [embed] });
  }
}

// ============================================================================
// Figma API Integration
// ============================================================================

class FigmaIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('figma', config);
    this.config = {
      accessToken: config.accessToken || process.env.FIGMA_TOKEN,
      apiUrl: config.apiUrl || 'https://api.figma.com/v1',
      cacheEnabled: config.cacheEnabled !== false,
      cacheTtl: config.cacheTtl || 300000, // 5 minutes
      ...config
    };
    this.cache = new Map();
    this.user = null;
  }

  async connect() {
    if (!this.config.accessToken) {
      throw new Error('Figma access token required. Set FIGMA_TOKEN environment variable.');
    }

    const response = await this.makeRequest(`${this.config.apiUrl}/me`, {
      headers: { 'X-Figma-Token': this.config.accessToken }
    });

    if (response.status === 200) {
      this.connected = true;
      this.user = response.data;
      this.emit('connected', { integration: this.name, user: this.user.handle });
      return true;
    }

    throw new Error(`Figma authentication failed: ${response.status}`);
  }

  getAuthHeaders() {
    return { 'X-Figma-Token': this.config.accessToken };
  }

  getCached(key) {
    if (!this.config.cacheEnabled) return null;

    const cached = this.cache.get(key);
    if (cached && Date.now() - cached.timestamp < this.config.cacheTtl) {
      return cached.data;
    }
    return null;
  }

  setCache(key, data) {
    if (this.config.cacheEnabled) {
      this.cache.set(key, { data, timestamp: Date.now() });
    }
  }

  clearCache() {
    this.cache.clear();
  }

  async getFile(fileKey, options = {}) {
    const cacheKey = `file:${fileKey}:${JSON.stringify(options)}`;
    const cached = this.getCached(cacheKey);
    if (cached) return cached;

    const params = new URLSearchParams();
    if (options.version) params.append('version', options.version);
    if (options.ids) params.append('ids', options.ids.join(','));
    if (options.depth) params.append('depth', options.depth);
    if (options.geometry) params.append('geometry', options.geometry);
    if (options.pluginData) params.append('plugin_data', options.pluginData);
    if (options.branchData) params.append('branch_data', 'true');

    const url = `${this.config.apiUrl}/files/${fileKey}${params.toString() ? '?' + params : ''}`;
    const response = await this.makeRequest(url, { headers: this.getAuthHeaders() });

    if (response.status === 200) {
      this.setCache(cacheKey, response.data);
      this.emit('file:fetched', { fileKey, name: response.data.name });
      return response.data;
    }

    throw new Error(`Failed to fetch file: ${response.status}`);
  }

  async getFileNodes(fileKey, nodeIds, options = {}) {
    const ids = Array.isArray(nodeIds) ? nodeIds.join(',') : nodeIds;
    const params = new URLSearchParams({ ids });
    if (options.version) params.append('version', options.version);
    if (options.depth) params.append('depth', options.depth);
    if (options.geometry) params.append('geometry', options.geometry);
    if (options.pluginData) params.append('plugin_data', options.pluginData);

    const response = await this.makeRequest(
      `${this.config.apiUrl}/files/${fileKey}/nodes?${params}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data;
    }

    throw new Error(`Failed to fetch nodes: ${response.status}`);
  }

  async getImages(fileKey, nodeIds, options = {}) {
    const ids = Array.isArray(nodeIds) ? nodeIds.join(',') : nodeIds;
    const params = new URLSearchParams({ ids });
    params.append('format', options.format || 'png');
    params.append('scale', options.scale || 2);

    if (options.svgIncludeId) params.append('svg_include_id', 'true');
    if (options.svgSimplifyStroke) params.append('svg_simplify_stroke', 'true');
    if (options.useAbsoluteBounds) params.append('use_absolute_bounds', 'true');
    if (options.version) params.append('version', options.version);

    const response = await this.makeRequest(
      `${this.config.apiUrl}/images/${fileKey}?${params}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      this.emit('images:fetched', { fileKey, count: Object.keys(response.data.images).length });
      return response.data.images;
    }

    throw new Error(`Failed to fetch images: ${response.status}`);
  }

  async getImageFills(fileKey) {
    const response = await this.makeRequest(
      `${this.config.apiUrl}/files/${fileKey}/images`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data.meta.images;
    }

    throw new Error(`Failed to fetch image fills: ${response.status}`);
  }

  async getComments(fileKey, options = {}) {
    const params = new URLSearchParams();
    if (options.asMarkdown) params.append('as_md', 'true');

    const response = await this.makeRequest(
      `${this.config.apiUrl}/files/${fileKey}/comments${params.toString() ? '?' + params : ''}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data.comments;
    }

    throw new Error(`Failed to fetch comments: ${response.status}`);
  }

  async postComment(fileKey, message, options = {}) {
    const body = {
      message,
      client_meta: options.clientMeta,
      comment_id: options.replyTo
    };

    const response = await this.makeRequest(
      `${this.config.apiUrl}/files/${fileKey}/comments`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body
      }
    );

    if (response.status === 200) {
      this.emit('comment:posted', { fileKey, commentId: response.data.id });
      return response.data;
    }

    throw new Error(`Failed to post comment: ${response.status}`);
  }

  async getStyles(fileKey) {
    const response = await this.makeRequest(
      `${this.config.apiUrl}/files/${fileKey}/styles`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data.meta.styles;
    }

    throw new Error(`Failed to fetch styles: ${response.status}`);
  }

  async getTeamComponents(teamId, options = {}) {
    const params = new URLSearchParams();
    if (options.pageSize) params.append('page_size', options.pageSize);
    if (options.after) params.append('after', options.after);

    const response = await this.makeRequest(
      `${this.config.apiUrl}/teams/${teamId}/components${params.toString() ? '?' + params : ''}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data;
    }

    throw new Error(`Failed to fetch team components: ${response.status}`);
  }

  async getTeamStyles(teamId, options = {}) {
    const params = new URLSearchParams();
    if (options.pageSize) params.append('page_size', options.pageSize);
    if (options.after) params.append('after', options.after);

    const response = await this.makeRequest(
      `${this.config.apiUrl}/teams/${teamId}/styles${params.toString() ? '?' + params : ''}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data;
    }

    throw new Error(`Failed to fetch team styles: ${response.status}`);
  }

  async getFileVersions(fileKey) {
    const response = await this.makeRequest(
      `${this.config.apiUrl}/files/${fileKey}/versions`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data.versions;
    }

    throw new Error(`Failed to fetch versions: ${response.status}`);
  }

  async getProjects(teamId) {
    const response = await this.makeRequest(
      `${this.config.apiUrl}/teams/${teamId}/projects`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data.projects;
    }

    throw new Error(`Failed to fetch projects: ${response.status}`);
  }

  async getProjectFiles(projectId, options = {}) {
    const params = new URLSearchParams();
    if (options.branchData) params.append('branch_data', 'true');

    const response = await this.makeRequest(
      `${this.config.apiUrl}/projects/${projectId}/files${params.toString() ? '?' + params : ''}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data.files;
    }

    throw new Error(`Failed to fetch project files: ${response.status}`);
  }

  extractColors(file) {
    const colors = [];

    const traverse = (node) => {
      if (node.fills) {
        node.fills.forEach(fill => {
          if (fill.type === 'SOLID' && fill.color) {
            colors.push({
              name: node.name,
              color: fill.color,
              opacity: fill.opacity
            });
          }
        });
      }
      if (node.children) {
        node.children.forEach(traverse);
      }
    };

    if (file.document) {
      traverse(file.document);
    }

    return colors;
  }

  extractTypography(file) {
    const typography = [];

    const traverse = (node) => {
      if (node.type === 'TEXT' && node.style) {
        typography.push({
          name: node.name,
          fontFamily: node.style.fontFamily,
          fontSize: node.style.fontSize,
          fontWeight: node.style.fontWeight,
          lineHeight: node.style.lineHeightPx || node.style.lineHeightPercent,
          letterSpacing: node.style.letterSpacing
        });
      }
      if (node.children) {
        node.children.forEach(traverse);
      }
    };

    if (file.document) {
      traverse(file.document);
    }

    return typography;
  }
}

// ============================================================================
// NPM Integration
// ============================================================================

class NPMIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('npm', config);
    this.config = {
      token: config.token || process.env.NPM_TOKEN,
      registry: config.registry || 'https://registry.npmjs.org',
      scope: config.scope,
      ...config
    };
  }

  async connect() {
    if (!this.config.token) {
      throw new Error('NPM token required. Set NPM_TOKEN environment variable.');
    }
    this.connected = true;
    this.emit('connected', { integration: this.name });
    return true;
  }

  async publish(packagePath, options = {}) {
    const { tag = 'latest', access = 'public', dryRun = false, otp } = options;

    return new Promise((resolve, reject) => {
      const args = ['publish'];

      args.push('--tag', tag);
      args.push('--access', access);

      if (dryRun) {
        args.push('--dry-run');
      }
      if (otp) {
        args.push('--otp', otp);
      }
      if (this.config.registry !== 'https://registry.npmjs.org') {
        args.push('--registry', this.config.registry);
      }

      const npm = spawn('npm', args, {
        cwd: packagePath,
        stdio: 'pipe',
        env: {
          ...process.env,
          NPM_TOKEN: this.config.token
        }
      });

      let stdout = '';
      let stderr = '';

      npm.stdout.on('data', (data) => {
        stdout += data;
        this.emit('publish:output', { type: 'stdout', data: data.toString() });
      });

      npm.stderr.on('data', (data) => {
        stderr += data;
        this.emit('publish:output', { type: 'stderr', data: data.toString() });
      });

      npm.on('close', (code) => {
        const result = {
          success: code === 0,
          code,
          stdout,
          stderr,
          path: packagePath,
          tag
        };

        if (code === 0) {
          this.emit('publish:complete', result);
          resolve(result);
        } else {
          this.emit('publish:failed', result);
          reject(new Error(`NPM publish failed: ${stderr}`));
        }
      });
    });
  }

  async getPackageInfo(packageName) {
    const encodedName = encodeURIComponent(packageName);
    const response = await this.makeRequest(`${this.config.registry}/${encodedName}`, {});

    if (response.status === 200) {
      return response.data;
    }

    if (response.status === 404) {
      return null;
    }

    throw new Error(`Failed to fetch package info: ${response.status}`);
  }

  async getPackageVersions(packageName) {
    const info = await this.getPackageInfo(packageName);
    return info ? Object.keys(info.versions) : [];
  }

  async getLatestVersion(packageName) {
    const info = await this.getPackageInfo(packageName);
    return info ? info['dist-tags'].latest : null;
  }

  async deprecate(packageName, version, message) {
    return new Promise((resolve, reject) => {
      const args = ['deprecate', `${packageName}@${version}`, message];

      if (this.config.registry !== 'https://registry.npmjs.org') {
        args.push('--registry', this.config.registry);
      }

      const npm = spawn('npm', args, {
        stdio: 'pipe',
        env: {
          ...process.env,
          NPM_TOKEN: this.config.token
        }
      });

      let output = '';
      npm.stdout.on('data', (data) => output += data);
      npm.stderr.on('data', (data) => output += data);

      npm.on('close', (code) => {
        if (code === 0) {
          this.emit('deprecate:complete', { packageName, version, message });
          resolve({ success: true });
        } else {
          reject(new Error(`Deprecation failed: ${output}`));
        }
      });
    });
  }

  async unpublish(packageName, version) {
    return new Promise((resolve, reject) => {
      const spec = version ? `${packageName}@${version}` : packageName;
      const args = ['unpublish', spec, '--force'];

      if (this.config.registry !== 'https://registry.npmjs.org') {
        args.push('--registry', this.config.registry);
      }

      const npm = spawn('npm', args, {
        stdio: 'pipe',
        env: {
          ...process.env,
          NPM_TOKEN: this.config.token
        }
      });

      let output = '';
      npm.stdout.on('data', (data) => output += data);
      npm.stderr.on('data', (data) => output += data);

      npm.on('close', (code) => {
        if (code === 0) {
          this.emit('unpublish:complete', { packageName, version });
          resolve({ success: true });
        } else {
          reject(new Error(`Unpublish failed: ${output}`));
        }
      });
    });
  }

  generateNpmrc(options = {}) {
    const lines = [];

    // Registry
    if (this.config.scope) {
      lines.push(`${this.config.scope}:registry=${this.config.registry}`);
    }
    if (this.config.registry !== 'https://registry.npmjs.org') {
      lines.push(`registry=${this.config.registry}`);
    }

    // Auth
    const registryHost = new URL(this.config.registry).host;
    lines.push(`//${registryHost}/:_authToken=\${NPM_TOKEN}`);
    lines.push('always-auth=true');

    // Options
    if (options.saveExact) {
      lines.push('save-exact=true');
    }
    if (options.engineStrict) {
      lines.push('engine-strict=true');
    }

    return {
      filename: '.npmrc',
      content: lines.join('\n') + '\n',
      type: 'config'
    };
  }

  generatePackageJson(options) {
    const {
      name,
      version = '1.0.0',
      description = '',
      main = 'dist/index.js',
      module = 'dist/index.esm.js',
      types = 'dist/index.d.ts',
      exports = {},
      files = ['dist'],
      keywords = [],
      author,
      license = 'MIT',
      repository,
      peerDependencies = {},
      dependencies = {},
      devDependencies = {}
    } = options;

    const pkg = {
      name,
      version,
      description,
      main,
      module,
      types,
      exports: {
        '.': {
          import: `./${module}`,
          require: `./${main}`,
          types: `./${types}`
        },
        ...exports
      },
      files,
      keywords,
      author,
      license,
      repository: repository ? { type: 'git', url: repository } : undefined,
      peerDependencies,
      dependencies,
      devDependencies,
      scripts: {
        build: 'tsup',
        dev: 'tsup --watch',
        lint: 'eslint src/',
        test: 'vitest',
        prepublishOnly: 'npm run build'
      }
    };

    // Remove undefined values
    Object.keys(pkg).forEach(key => pkg[key] === undefined && delete pkg[key]);

    return {
      filename: 'package.json',
      content: JSON.stringify(pkg, null, 2) + '\n',
      type: 'config'
    };
  }
}

// ============================================================================
// Jira Integration
// ============================================================================

class JiraIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('jira', config);
    this.config = {
      host: config.host || process.env.JIRA_HOST,
      email: config.email || process.env.JIRA_EMAIL,
      apiToken: config.apiToken || process.env.JIRA_API_TOKEN,
      projectKey: config.projectKey || process.env.JIRA_PROJECT_KEY,
      ...config
    };
  }

  async connect() {
    if (!this.config.host || !this.config.email || !this.config.apiToken) {
      throw new Error('Jira host, email, and API token required.');
    }

    const response = await this.makeRequest(`https://${this.config.host}/rest/api/3/myself`, {
      headers: this.getAuthHeaders()
    });

    if (response.status === 200) {
      this.connected = true;
      this.user = response.data;
      this.emit('connected', { integration: this.name, user: this.user.displayName });
      return true;
    }

    throw new Error(`Jira authentication failed: ${response.status}`);
  }

  getAuthHeaders() {
    const auth = Buffer.from(`${this.config.email}:${this.config.apiToken}`).toString('base64');
    return {
      'Authorization': `Basic ${auth}`,
      'Accept': 'application/json'
    };
  }

  async createIssue(options) {
    const {
      summary,
      description,
      issueType = 'Task',
      priority,
      labels = [],
      assignee,
      components = []
    } = options;
    const projectKey = options.projectKey || this.config.projectKey;

    const body = {
      fields: {
        project: { key: projectKey },
        summary,
        description: {
          type: 'doc',
          version: 1,
          content: [
            {
              type: 'paragraph',
              content: [{ type: 'text', text: description }]
            }
          ]
        },
        issuetype: { name: issueType },
        labels
      }
    };

    if (priority) {
      body.fields.priority = { name: priority };
    }
    if (assignee) {
      body.fields.assignee = { accountId: assignee };
    }
    if (components.length > 0) {
      body.fields.components = components.map(c => ({ name: c }));
    }

    const response = await this.makeRequest(
      `https://${this.config.host}/rest/api/3/issue`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body
      }
    );

    if (response.status === 201) {
      this.emit('issue:created', {
        key: response.data.key,
        id: response.data.id
      });
      return response.data;
    }

    throw new Error(`Failed to create issue: ${JSON.stringify(response.data)}`);
  }

  async getIssue(issueKey) {
    const response = await this.makeRequest(
      `https://${this.config.host}/rest/api/3/issue/${issueKey}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data;
    }

    throw new Error(`Failed to fetch issue: ${response.status}`);
  }

  async updateIssue(issueKey, fields) {
    const response = await this.makeRequest(
      `https://${this.config.host}/rest/api/3/issue/${issueKey}`,
      {
        method: 'PUT',
        headers: this.getAuthHeaders(),
        body: { fields }
      }
    );

    if (response.status === 204) {
      this.emit('issue:updated', { key: issueKey });
      return true;
    }

    throw new Error(`Failed to update issue: ${response.status}`);
  }

  async transitionIssue(issueKey, transitionId) {
    const response = await this.makeRequest(
      `https://${this.config.host}/rest/api/3/issue/${issueKey}/transitions`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: {
          transition: { id: transitionId }
        }
      }
    );

    if (response.status === 204) {
      this.emit('issue:transitioned', { key: issueKey, transitionId });
      return true;
    }

    throw new Error(`Failed to transition issue: ${response.status}`);
  }

  async addComment(issueKey, body) {
    const response = await this.makeRequest(
      `https://${this.config.host}/rest/api/3/issue/${issueKey}/comment`,
      {
        method: 'POST',
        headers: this.getAuthHeaders(),
        body: {
          body: {
            type: 'doc',
            version: 1,
            content: [
              {
                type: 'paragraph',
                content: [{ type: 'text', text: body }]
              }
            ]
          }
        }
      }
    );

    if (response.status === 201) {
      return response.data;
    }

    throw new Error(`Failed to add comment: ${response.status}`);
  }

  async searchIssues(jql, options = {}) {
    const params = new URLSearchParams({
      jql,
      maxResults: options.maxResults || 50,
      startAt: options.startAt || 0
    });

    if (options.fields) {
      params.append('fields', options.fields.join(','));
    }

    const response = await this.makeRequest(
      `https://${this.config.host}/rest/api/3/search?${params}`,
      { headers: this.getAuthHeaders() }
    );

    if (response.status === 200) {
      return response.data;
    }

    throw new Error(`Failed to search issues: ${response.status}`);
  }
}

// ============================================================================
// Linear Integration
// ============================================================================

class LinearIntegration extends BaseIntegration {
  constructor(config = {}) {
    super('linear', config);
    this.config = {
      apiKey: config.apiKey || process.env.LINEAR_API_KEY,
      apiUrl: config.apiUrl || 'https://api.linear.app/graphql',
      teamId: config.teamId || process.env.LINEAR_TEAM_ID,
      ...config
    };
  }

  async connect() {
    if (!this.config.apiKey) {
      throw new Error('Linear API key required. Set LINEAR_API_KEY environment variable.');
    }

    const query = `query { viewer { id name email } }`;
    const response = await this.graphql(query);

    if (response.data && response.data.viewer) {
      this.connected = true;
      this.user = response.data.viewer;
      this.emit('connected', { integration: this.name, user: this.user.name });
      return true;
    }

    throw new Error('Linear authentication failed');
  }

  async graphql(query, variables = {}) {
    const response = await this.makeRequest(this.config.apiUrl, {
      method: 'POST',
      headers: {
        'Authorization': this.config.apiKey,
        'Content-Type': 'application/json'
      },
      body: { query, variables }
    });

    if (response.data.errors) {
      throw new Error(`GraphQL Error: ${JSON.stringify(response.data.errors)}`);
    }

    return response.data;
  }

  async createIssue(options) {
    const { title, description, priority, labels = [], assigneeId, stateId, estimate } = options;
    const teamId = options.teamId || this.config.teamId;

    const mutation = `
      mutation CreateIssue($input: IssueCreateInput!) {
        issueCreate(input: $input) {
          success
          issue {
            id
            identifier
            title
            url
          }
        }
      }
    `;

    const input = {
      teamId,
      title,
      description,
      priority,
      labelIds: labels,
      assigneeId,
      stateId,
      estimate
    };

    // Remove undefined values
    Object.keys(input).forEach(key => input[key] === undefined && delete input[key]);

    const response = await this.graphql(mutation, { input });

    if (response.data.issueCreate.success) {
      const issue = response.data.issueCreate.issue;
      this.emit('issue:created', {
        id: issue.id,
        identifier: issue.identifier,
        url: issue.url
      });
      return issue;
    }

    throw new Error('Failed to create issue');
  }

  async getIssue(issueId) {
    const query = `
      query GetIssue($id: String!) {
        issue(id: $id) {
          id
          identifier
          title
          description
          priority
          state { id name }
          assignee { id name }
          labels { nodes { id name } }
          url
          createdAt
          updatedAt
        }
      }
    `;

    const response = await this.graphql(query, { id: issueId });
    return response.data.issue;
  }

  async updateIssue(issueId, input) {
    const mutation = `
      mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
        issueUpdate(id: $id, input: $input) {
          success
          issue {
            id
            identifier
            title
            url
          }
        }
      }
    `;

    const response = await this.graphql(mutation, { id: issueId, input });

    if (response.data.issueUpdate.success) {
      this.emit('issue:updated', { id: issueId });
      return response.data.issueUpdate.issue;
    }

    throw new Error('Failed to update issue');
  }

  async getTeams() {
    const query = `
      query {
        teams {
          nodes {
            id
            name
            key
          }
        }
      }
    `;

    const response = await this.graphql(query);
    return response.data.teams.nodes;
  }

  async getStates(teamId) {
    teamId = teamId || this.config.teamId;

    const query = `
      query GetStates($teamId: String!) {
        team(id: $teamId) {
          states {
            nodes {
              id
              name
              type
              position
            }
          }
        }
      }
    `;

    const response = await this.graphql(query, { teamId });
    return response.data.team.states.nodes;
  }

  async getLabels(teamId) {
    teamId = teamId || this.config.teamId;

    const query = `
      query GetLabels($teamId: String!) {
        team(id: $teamId) {
          labels {
            nodes {
              id
              name
              color
            }
          }
        }
      }
    `;

    const response = await this.graphql(query, { teamId });
    return response.data.team.labels.nodes;
  }

  async searchIssues(searchTerm, options = {}) {
    const teamId = options.teamId || this.config.teamId;

    const query = `
      query SearchIssues($teamId: String!, $filter: IssueFilter) {
        team(id: $teamId) {
          issues(filter: $filter, first: ${options.first || 50}) {
            nodes {
              id
              identifier
              title
              description
              priority
              state { name }
              url
            }
          }
        }
      }
    `;

    const filter = options.filter || {
      or: [
        { title: { contains: searchTerm } },
        { description: { contains: searchTerm } }
      ]
    };

    const response = await this.graphql(query, { teamId, filter });
    return response.data.team.issues.nodes;
  }
}

// ============================================================================
// Integration Manager
// ============================================================================

class IntegrationManager extends EventEmitter {
  constructor() {
    super();
    this.integrations = new Map();
    this.instances = new Map();
    this.registerBuiltInIntegrations();
  }

  registerBuiltInIntegrations() {
    this.registerIntegration('storybook', StorybookIntegration);
    this.registerIntegration('chromatic', ChromaticIntegration);
    this.registerIntegration('github', GitHubIntegration);
    this.registerIntegration('slack', SlackIntegration);
    this.registerIntegration('discord', DiscordIntegration);
    this.registerIntegration('figma', FigmaIntegration);
    this.registerIntegration('npm', NPMIntegration);
    this.registerIntegration('jira', JiraIntegration);
    this.registerIntegration('linear', LinearIntegration);
  }

  registerIntegration(name, IntegrationClass) {
    this.integrations.set(name, IntegrationClass);
    this.emit('integration:registered', { name });
  }

  unregisterIntegration(name) {
    this.integrations.delete(name);
    this.instances.delete(name);
    this.emit('integration:unregistered', { name });
  }

  createIntegration(name, config = {}) {
    const IntegrationClass = this.integrations.get(name);
    if (!IntegrationClass) {
      throw new Error(`Unknown integration: ${name}. Available: ${this.listIntegrations().join(', ')}`);
    }

    const instance = new IntegrationClass(config);
    this.instances.set(name, instance);

    // Forward events
    instance.on('connected', (data) => this.emit('connected', { ...data, integration: name }));
    instance.on('disconnected', (data) => this.emit('disconnected', { ...data, integration: name }));

    return instance;
  }

  getInstance(name) {
    return this.instances.get(name);
  }

  listIntegrations() {
    return Array.from(this.integrations.keys());
  }

  hasIntegration(name) {
    return this.integrations.has(name);
  }

  async connectAll(configs = {}) {
    const results = {};

    for (const [name, config] of Object.entries(configs)) {
      try {
        const integration = this.createIntegration(name, config);
        await integration.connect();
        results[name] = { success: true };
      } catch (error) {
        results[name] = { success: false, error: error.message };
      }
    }

    return results;
  }

  async disconnectAll() {
    for (const [name, instance] of this.instances) {
      try {
        await instance.disconnect();
      } catch (error) {
        console.error(`Failed to disconnect ${name}:`, error);
      }
    }
    this.instances.clear();
  }

  async healthCheckAll() {
    const results = {};

    for (const [name, instance] of this.instances) {
      try {
        results[name] = await instance.healthCheck();
      } catch (error) {
        results[name] = { healthy: false, error: error.message };
      }
    }

    return results;
  }
}

// Factory function
function createIntegration(name, config = {}) {
  const manager = new IntegrationManager();
  return manager.createIntegration(name, config);
}

module.exports = {
  // Base
  BaseIntegration,

  // Integrations
  StorybookIntegration,
  ChromaticIntegration,
  GitHubIntegration,
  SlackIntegration,
  DiscordIntegration,
  FigmaIntegration,
  NPMIntegration,
  JiraIntegration,
  LinearIntegration,

  // Manager
  IntegrationManager,
  createIntegration,

  // Constants
  SUPPORTED_INTEGRATIONS: [
    'storybook',
    'chromatic',
    'github',
    'slack',
    'discord',
    'figma',
    'npm',
    'jira',
    'linear'
  ]
};
