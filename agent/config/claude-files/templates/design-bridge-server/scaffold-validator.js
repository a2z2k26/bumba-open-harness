/**
 * ScaffoldValidator - Validates and repairs project infrastructure
 *
 * Ensures target projects have all required files before transformation
 */

const fs = require('fs');
const path = require('path');

class ScaffoldValidator {
  constructor(projectPath) {
    this.projectPath = projectPath;
    this.templatesPath = path.join(__dirname, 'templates');
  }

  /**
   * Validate project has all required files
   * @returns {{ valid: boolean, missing: string[], warnings: string[] }}
   */
  validate() {
    const missing = [];
    const warnings = [];

    // Required files
    const requiredFiles = [
      'package.json',
      'tsconfig.json'
    ];

    // Required directories
    const requiredDirs = [
      '.storybook'
    ];

    // Check required files
    for (const file of requiredFiles) {
      const filePath = path.join(this.projectPath, file);
      if (!fs.existsSync(filePath)) {
        missing.push(file);
      }
    }

    // Check required directories
    for (const dir of requiredDirs) {
      const dirPath = path.join(this.projectPath, dir);
      if (!fs.existsSync(dirPath)) {
        missing.push(dir);
      }
    }

    // Check for Storybook files if .storybook exists
    const storybookPath = path.join(this.projectPath, '.storybook');
    if (fs.existsSync(storybookPath)) {
      const storybookFiles = ['main.js', 'preview.js'];
      for (const file of storybookFiles) {
        if (!fs.existsSync(path.join(storybookPath, file))) {
          warnings.push(`.storybook/${file} is missing`);
        }
      }
    }

    // Check package.json has required dependencies
    const pkgPath = path.join(this.projectPath, 'package.json');
    if (fs.existsSync(pkgPath)) {
      try {
        const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
        const allDeps = { ...pkg.dependencies, ...pkg.devDependencies };

        // NOTE: Only @storybook/addon-docs is needed for Storybook 10.x
        // addon-essentials is DEPRECATED (merged into core)
        const requiredDeps = [
          '@storybook/react-vite',
          '@storybook/addon-docs'
        ];

        for (const dep of requiredDeps) {
          if (!allDeps[dep]) {
            warnings.push(`Missing dependency: ${dep}`);
          }
        }
      } catch (e) {
        warnings.push(`Could not parse package.json: ${e.message}`);
      }
    }

    return {
      valid: missing.length === 0,
      missing,
      warnings
    };
  }

  /**
   * Repair missing files by creating from templates
   * @param {{ autoConfirm?: boolean }} options
   * @returns {{ repaired: string[], failed: string[] }}
   */
  async repair(options = {}) {
    const { valid, missing } = this.validate();

    if (valid) {
      return { repaired: [], failed: [] };
    }

    const repaired = [];
    const failed = [];

    for (const item of missing) {
      try {
        if (item === 'package.json') {
          await this.createPackageJson();
          repaired.push('package.json');
        } else if (item === 'tsconfig.json') {
          await this.createTsConfig();
          repaired.push('tsconfig.json');
        } else if (item === '.storybook') {
          await this.createStorybookConfig();
          repaired.push('.storybook');
        } else {
          failed.push(item);
        }
      } catch (e) {
        failed.push(`${item}: ${e.message}`);
      }
    }

    return { repaired, failed };
  }

  async createPackageJson() {
    const templatePath = path.join(this.templatesPath, 'package.json.template');
    const outputPath = path.join(this.projectPath, 'package.json');

    if (fs.existsSync(templatePath)) {
      const template = fs.readFileSync(templatePath, 'utf8');
      const projectName = path.basename(this.projectPath).toLowerCase().replace(/\s+/g, '-');
      const content = template.replace(/\{\{PROJECT_NAME\}\}/g, projectName);
      fs.writeFileSync(outputPath, content);
    } else {
      // Fallback inline template
      const pkg = {
        name: path.basename(this.projectPath).toLowerCase().replace(/\s+/g, '-'),
        version: '1.0.0',
        private: true,
        scripts: {
          storybook: 'storybook dev -p 6006',
          'build-storybook': 'storybook build'
        },
        dependencies: {
          react: '^18.2.0',
          'react-dom': '^18.2.0'
        },
        devDependencies: {
          '@storybook/react-vite': '^10.0.8',
          '@storybook/addon-docs': '^10.0.8',
          '@storybook/manager-api': '^8.4.6',
          '@storybook/theming': '^8.4.6',
          '@storybook/blocks': '^8.4.6',
          '@types/react': '^18.2.0',
          '@types/react-dom': '^18.2.0',
          typescript: '^5.3.0',
          vite: '^5.0.0',
          storybook: '^8.4.6'
        }
      };
      fs.writeFileSync(outputPath, JSON.stringify(pkg, null, 2));
    }
  }

  async createTsConfig() {
    const outputPath = path.join(this.projectPath, 'tsconfig.json');
    const tsconfig = {
      compilerOptions: {
        target: 'ES2020',
        useDefineForClassFields: true,
        lib: ['ES2020', 'DOM', 'DOM.Iterable'],
        module: 'ESNext',
        skipLibCheck: true,
        moduleResolution: 'bundler',
        allowImportingTsExtensions: true,
        resolveJsonModule: true,
        isolatedModules: true,
        noEmit: true,
        jsx: 'react-jsx',
        strict: true,
        noUnusedLocals: true,
        noUnusedParameters: true,
        noFallthroughCasesInSwitch: true
      },
      include: ['src', '.storybook']
    };
    fs.writeFileSync(outputPath, JSON.stringify(tsconfig, null, 2));
  }

  async createStorybookConfig() {
    const storybookPath = path.join(this.projectPath, '.storybook');
    fs.mkdirSync(storybookPath, { recursive: true });

    // main.js
    const mainJs = `/** @type { import('@storybook/react-vite').StorybookConfig } */
const config = {
  stories: ['../src/**/*.mdx', '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)'],
  addons: [
    '@storybook/addon-docs'
  ],
  framework: {
    name: '@storybook/react-vite',
    options: {}
  }
};

export default config;
`;
    fs.writeFileSync(path.join(storybookPath, 'main.js'), mainJs);

    // preview.js
    const previewJs = `/** @type { import('@storybook/react').Preview } */
const preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
  },
};

export default preview;
`;
    fs.writeFileSync(path.join(storybookPath, 'preview.js'), previewJs);
  }
}

module.exports = { ScaffoldValidator };
