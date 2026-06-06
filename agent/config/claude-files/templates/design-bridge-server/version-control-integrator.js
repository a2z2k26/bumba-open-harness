/**
 * Version Control Integrator
 * Sprint 36: Version Control Integration
 *
 * Integrates Git version control for design changes:
 * - Auto-commit on design sync
 * - Branch management for features
 * - Diff viewing for changes
 * - Release tagging
 * - Change tracking
 */

const EventEmitter = require('events');
const { exec } = require('child_process');
const { promisify } = require('util');
const fs = require('fs').promises;
const path = require('path');

const execAsync = promisify(exec);

class VersionControlIntegrator extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      autoCommit: options.autoCommit !== false,
      autoCommitMessage: options.autoCommitMessage || 'chore(design): Sync design changes from Figma',
      branchPrefix: options.branchPrefix || 'design/',
      tagPrefix: options.tagPrefix || 'design-v',
      gitDir: options.gitDir || process.cwd(),
      commitAuthor: options.commitAuthor || 'BUMBA Design Bridge <design@bumba.dev>',
      ...options
    };

    // Commit history
    this.commitHistory = [];

    // Branch tracking
    this.branches = new Map();

    // Statistics
    this.stats = {
      totalCommits: 0,
      autoCommits: 0,
      manualCommits: 0,
      branchesCreated: 0,
      tagsCreated: 0,
      lastCommit: null
    };
  }

  /**
   * Initialize Git repository
   */
  async initialize() {
    try {
      // Check if git is available
      await execAsync('git --version', { cwd: this.options.gitDir });

      // Check if directory is a git repository
      const isGitRepo = await this.isGitRepository();

      if (!isGitRepo) {
        this.emit('git:not_repository', { dir: this.options.gitDir });
        return { initialized: false, reason: 'not a git repository' };
      }

      this.emit('git:initialized', { dir: this.options.gitDir });

      return { initialized: true, dir: this.options.gitDir };

    } catch (error) {
      this.emit('git:error', { error: error.message });
      throw new Error(`Git initialization failed: ${error.message}`);
    }
  }

  /**
   * Check if directory is a Git repository
   */
  async isGitRepository() {
    try {
      await execAsync('git rev-parse --git-dir', { cwd: this.options.gitDir });
      return true;
    } catch (error) {
      return false;
    }
  }

  /**
   * Auto-commit design changes
   */
  async autoCommit(files, metadata = {}) {
    if (!this.options.autoCommit) {
      return { committed: false, reason: 'auto-commit disabled' };
    }

    try {
      // Stage files
      await this.stageFiles(files);

      // Check if there are changes to commit
      const hasChanges = await this.hasChanges();

      if (!hasChanges) {
        return { committed: false, reason: 'no changes to commit' };
      }

      // Create commit message
      const message = this.buildCommitMessage(metadata);

      // Commit changes
      const commit = await this.commit(message, { auto: true });

      this.stats.autoCommits++;

      this.emit('auto-commit:success', {
        commit,
        files: files.length,
        timestamp: new Date().toISOString()
      });

      return { committed: true, commit };

    } catch (error) {
      this.emit('auto-commit:failed', { error: error.message });
      throw error;
    }
  }

  /**
   * Manual commit
   */
  async manualCommit(files, message, options = {}) {
    try {
      // Stage files
      await this.stageFiles(files);

      // Commit changes
      const commit = await this.commit(message, { ...options, auto: false });

      this.stats.manualCommits++;

      this.emit('manual-commit:success', {
        commit,
        files: files.length,
        timestamp: new Date().toISOString()
      });

      return commit;

    } catch (error) {
      this.emit('manual-commit:failed', { error: error.message });
      throw error;
    }
  }

  /**
   * Stage files for commit
   */
  async stageFiles(files) {
    const fileList = Array.isArray(files) ? files : [files];

    if (fileList.length === 0) {
      return { staged: 0 };
    }

    try {
      const fileArgs = fileList.map(f => `"${f}"`).join(' ');
      await execAsync(`git add ${fileArgs}`, { cwd: this.options.gitDir });

      this.emit('files:staged', { count: fileList.length });

      return { staged: fileList.length, files: fileList };

    } catch (error) {
      throw new Error(`Failed to stage files: ${error.message}`);
    }
  }

  /**
   * Create commit
   */
  async commit(message, options = {}) {
    try {
      const authorFlag = this.options.commitAuthor
        ? `--author="${this.options.commitAuthor}"`
        : '';

      const { stdout } = await execAsync(
        `git commit ${authorFlag} -m "${this.escapeMessage(message)}"`,
        { cwd: this.options.gitDir }
      );

      // Get commit hash
      const { stdout: hash } = await execAsync('git rev-parse HEAD', {
        cwd: this.options.gitDir
      });

      const commitHash = hash.trim();

      const commit = {
        hash: commitHash,
        message,
        author: this.options.commitAuthor,
        timestamp: new Date().toISOString(),
        auto: options.auto || false
      };

      this.commitHistory.push(commit);
      this.stats.totalCommits++;
      this.stats.lastCommit = commit.timestamp;

      this.emit('commit:created', commit);

      return commit;

    } catch (error) {
      throw new Error(`Commit failed: ${error.message}`);
    }
  }

  /**
   * Check if there are changes to commit
   */
  async hasChanges() {
    try {
      const { stdout } = await execAsync('git diff --cached --name-only', {
        cwd: this.options.gitDir
      });

      return stdout.trim().length > 0;
    } catch (error) {
      return false;
    }
  }

  /**
   * Create branch for feature/design
   */
  async createBranch(branchName, options = {}) {
    try {
      const fullBranchName = branchName.startsWith(this.options.branchPrefix)
        ? branchName
        : `${this.options.branchPrefix}${branchName}`;

      // Check if branch already exists
      const exists = await this.branchExists(fullBranchName);

      if (exists && !options.force) {
        throw new Error(`Branch already exists: ${fullBranchName}`);
      }

      // Create branch
      const checkoutFlag = options.checkout !== false ? '-b' : '';
      await execAsync(`git branch ${checkoutFlag} ${fullBranchName}`, {
        cwd: this.options.gitDir
      });

      const branch = {
        name: fullBranchName,
        createdAt: new Date().toISOString(),
        purpose: options.purpose || 'design changes'
      };

      this.branches.set(fullBranchName, branch);
      this.stats.branchesCreated++;

      this.emit('branch:created', branch);

      return branch;

    } catch (error) {
      throw new Error(`Branch creation failed: ${error.message}`);
    }
  }

  /**
   * Switch to branch
   */
  async switchBranch(branchName) {
    try {
      await execAsync(`git checkout ${branchName}`, { cwd: this.options.gitDir });

      this.emit('branch:switched', { branch: branchName });

      return { switched: true, branch: branchName };

    } catch (error) {
      throw new Error(`Branch switch failed: ${error.message}`);
    }
  }

  /**
   * Check if branch exists
   */
  async branchExists(branchName) {
    try {
      const { stdout } = await execAsync('git branch --list', {
        cwd: this.options.gitDir
      });

      return stdout.includes(branchName);
    } catch (error) {
      return false;
    }
  }

  /**
   * Get current branch
   */
  async getCurrentBranch() {
    try {
      const { stdout } = await execAsync('git branch --show-current', {
        cwd: this.options.gitDir
      });

      return stdout.trim();
    } catch (error) {
      return null;
    }
  }

  /**
   * View diff for files
   */
  async viewDiff(files = null, options = {}) {
    try {
      const fileArgs = files ? files.join(' ') : '';
      const stagedFlag = options.staged ? '--cached' : '';

      const { stdout } = await execAsync(
        `git diff ${stagedFlag} ${fileArgs}`,
        { cwd: this.options.gitDir }
      );

      const diff = {
        content: stdout,
        files: files || 'all',
        staged: options.staged || false,
        timestamp: new Date().toISOString()
      };

      this.emit('diff:viewed', { files: files?.length || 'all' });

      return diff;

    } catch (error) {
      throw new Error(`Diff view failed: ${error.message}`);
    }
  }

  /**
   * Create release tag
   */
  async createTag(version, message, options = {}) {
    try {
      const tagName = version.startsWith(this.options.tagPrefix)
        ? version
        : `${this.options.tagPrefix}${version}`;

      const annotatedFlag = options.annotated !== false ? '-a' : '';
      const messageFlag = message ? `-m "${this.escapeMessage(message)}"` : '';

      await execAsync(`git tag ${annotatedFlag} ${tagName} ${messageFlag}`, {
        cwd: this.options.gitDir
      });

      const tag = {
        name: tagName,
        version,
        message,
        createdAt: new Date().toISOString()
      };

      this.stats.tagsCreated++;

      this.emit('tag:created', tag);

      return tag;

    } catch (error) {
      throw new Error(`Tag creation failed: ${error.message}`);
    }
  }

  /**
   * Get commit history
   */
  async getCommitHistory(limit = 10) {
    try {
      const { stdout } = await execAsync(
        `git log -${limit} --pretty=format:"%H|%an|%ae|%ai|%s"`,
        { cwd: this.options.gitDir }
      );

      const commits = stdout.split('\n').map(line => {
        const [hash, author, email, date, message] = line.split('|');
        return { hash, author, email, date, message };
      });

      return commits;

    } catch (error) {
      return [];
    }
  }

  /**
   * Get file status
   */
  async getStatus() {
    try {
      const { stdout } = await execAsync('git status --porcelain', {
        cwd: this.options.gitDir
      });

      const files = stdout.split('\n').filter(line => line.trim()).map(line => {
        const status = line.substring(0, 2).trim();
        const file = line.substring(3).trim();
        return { status, file };
      });

      return {
        files,
        hasChanges: files.length > 0,
        count: files.length
      };

    } catch (error) {
      return { files: [], hasChanges: false, count: 0 };
    }
  }

  /**
   * Build commit message
   */
  buildCommitMessage(metadata = {}) {
    const parts = [this.options.autoCommitMessage];

    if (metadata.fileKey) {
      parts.push(`\nFile: ${metadata.fileKey}`);
    }

    if (metadata.changes) {
      parts.push(`Changes: ${metadata.changes}`);
    }

    if (metadata.tokens) {
      parts.push(`Tokens: ${metadata.tokens}`);
    }

    if (metadata.components) {
      parts.push(`Components: ${metadata.components}`);
    }

    return parts.join('\n');
  }

  /**
   * Escape commit message
   */
  escapeMessage(message) {
    return message.replace(/"/g, '\\"').replace(/\$/g, '\\$');
  }

  /**
   * Get statistics
   */
  getStats() {
    return {
      ...this.stats,
      historySize: this.commitHistory.length,
      branchCount: this.branches.size
    };
  }

  /**
   * Test Git flow
   */
  async testGitFlow() {
    console.log('🧪 Testing Git integration...\n');

    try {
      // 1. Initialize
      console.log('1. Checking Git repository...');
      const init = await this.initialize();
      console.log(`   ✓ Repository: ${init.initialized ? 'OK' : 'NOT FOUND'}\n`);

      if (!init.initialized) {
        console.log('⚠️  Not a Git repository. Skipping remaining tests.\n');
        return;
      }

      // 2. Get current branch
      console.log('2. Getting current branch...');
      const currentBranch = await this.getCurrentBranch();
      console.log(`   ✓ Current branch: ${currentBranch}\n`);

      // 3. Get status
      console.log('3. Checking status...');
      const status = await this.getStatus();
      console.log(`   ✓ Files changed: ${status.count}\n`);

      // 4. Get history
      console.log('4. Getting commit history...');
      const history = await this.getCommitHistory(5);
      console.log(`   ✓ Recent commits: ${history.length}\n`);

      console.log('✅ Git integration test complete!\n');

      return { success: true, status, history };

    } catch (error) {
      console.error('❌ Git test failed:', error.message);
      throw error;
    }
  }
}

module.exports = VersionControlIntegrator;
