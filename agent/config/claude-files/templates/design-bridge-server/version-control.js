/**
 * Version Control System
 * Manages design and code versioning with Git-like functionality
 * Sprint 18: Version Control
 */

const EventEmitter = require('events');
const crypto = require('crypto');
const fs = require('fs').promises;
const path = require('path');

class VersionControl extends EventEmitter {
  constructor() {
    super();
    this.name = 'VersionControl';
    this.version = '1.0.0';

    // Version control state
    this.repository = null;
    this.branches = new Map();
    this.commits = new Map();
    this.tags = new Map();
    this.stash = [];

    // Current state
    this.currentBranch = 'main';
    this.head = null;
    this.workingDirectory = new Map();
    this.stagingArea = new Map();

    // Configuration
    this.config = {
      autoCommit: false,
      autoMerge: true,
      conflictResolution: 'manual', // manual, theirs, ours, merge
      compression: true,
      maxHistorySize: 1000,
      gcInterval: 100, // Garbage collection after N commits
      diffAlgorithm: 'myers', // myers, patience, histogram
      mergeStrategy: '3-way', // 3-way, recursive, octopus
      hooks: {
        preCommit: true,
        postCommit: true,
        preMerge: true,
        postMerge: true
      }
    };

    // Statistics
    this.stats = {
      totalCommits: 0,
      totalBranches: 0,
      totalMerges: 0,
      totalConflicts: 0
    };

    // Initialize repository
    this.initializeRepository();
  }

  /**
   * Initialize repository
   */
  async initializeRepository(repoPath = '.bumba-vcs') {
    this.repository = {
      path: repoPath,
      created: new Date(),
      config: { ...this.config }
    };

    // Create initial branch
    await this.createBranch('main');
    this.currentBranch = 'main';

    // Create initial commit
    const initialCommit = await this.createCommit('Initial commit', []);
    this.head = initialCommit.hash;

    this.emit('repository:initialized', this.repository);
    return this.repository;
  }

  /**
   * Create a new commit
   */
  async commit(message, author = 'System') {
    // Check if there are staged changes
    if (this.stagingArea.size === 0) {
      throw new Error('No changes staged for commit');
    }

    // Run pre-commit hook
    if (this.config.hooks.preCommit) {
      await this.runHook('pre-commit', { staging: this.stagingArea });
    }

    // Create commit object
    const commit = await this.createCommit(message, Array.from(this.stagingArea.values()), author);

    // Update branch pointer
    const branch = this.branches.get(this.currentBranch);
    if (branch) {
      branch.head = commit.hash;
      branch.commits.push(commit.hash);
    }

    // Update HEAD
    this.head = commit.hash;

    // Clear staging area
    this.stagingArea.clear();

    // Update stats
    this.stats.totalCommits++;

    // Run post-commit hook
    if (this.config.hooks.postCommit) {
      await this.runHook('post-commit', { commit });
    }

    // Garbage collection
    if (this.stats.totalCommits % this.config.gcInterval === 0) {
      await this.garbageCollection();
    }

    this.emit('commit:created', commit);
    return commit;
  }

  /**
   * Stage changes
   */
  async stage(changes) {
    const stagedChanges = [];

    for (const change of Array.isArray(changes) ? changes : [changes]) {
      const changeId = this.generateChangeId(change);

      // Create change object
      const changeObj = {
        id: changeId,
        type: change.type || 'modify',
        path: change.path,
        content: change.content,
        diff: await this.createDiff(change),
        timestamp: new Date(),
        metadata: change.metadata || {}
      };

      // Add to staging area
      this.stagingArea.set(changeId, changeObj);
      stagedChanges.push(changeObj);
    }

    this.emit('changes:staged', stagedChanges);
    return stagedChanges;
  }

  /**
   * Unstage changes
   */
  async unstage(changeIds = []) {
    if (changeIds.length === 0) {
      // Unstage all
      this.stagingArea.clear();
      this.emit('changes:unstaged', { all: true });
    } else {
      // Unstage specific changes
      for (const id of changeIds) {
        this.stagingArea.delete(id);
      }
      this.emit('changes:unstaged', { ids: changeIds });
    }
  }

  /**
   * Create a new branch
   */
  async createBranch(name, fromCommit = null) {
    if (this.branches.has(name)) {
      throw new Error(`Branch ${name} already exists`);
    }

    const branch = {
      name,
      created: new Date(),
      head: fromCommit || this.head,
      commits: fromCommit ? [fromCommit] : [],
      metadata: {}
    };

    this.branches.set(name, branch);
    this.stats.totalBranches++;

    this.emit('branch:created', branch);
    return branch;
  }

  /**
   * Switch branch
   */
  async checkout(branchName) {
    if (!this.branches.has(branchName)) {
      throw new Error(`Branch ${branchName} does not exist`);
    }

    // Check for uncommitted changes
    if (this.stagingArea.size > 0) {
      const shouldStash = await this.promptStash();
      if (shouldStash) {
        await this.stashChanges();
      }
    }

    // Switch branch
    const branch = this.branches.get(branchName);
    this.currentBranch = branchName;
    this.head = branch.head;

    // Update working directory
    await this.updateWorkingDirectory(branch.head);

    this.emit('branch:switched', { from: this.currentBranch, to: branchName });
    return branch;
  }

  /**
   * Merge branches
   */
  async merge(sourceBranch, targetBranch = this.currentBranch, options = {}) {
    const source = this.branches.get(sourceBranch);
    const target = this.branches.get(targetBranch);

    if (!source || !target) {
      throw new Error('Invalid branch names');
    }

    // Run pre-merge hook
    if (this.config.hooks.preMerge) {
      await this.runHook('pre-merge', { source, target });
    }

    // Find common ancestor
    const commonAncestor = await this.findCommonAncestor(source.head, target.head);

    // Check if fast-forward is possible
    if (await this.canFastForward(source.head, target.head, commonAncestor)) {
      return this.fastForwardMerge(source, target);
    }

    // Perform 3-way merge
    const mergeResult = await this.threeWayMerge(
      source.head,
      target.head,
      commonAncestor,
      options
    );

    if (mergeResult.conflicts.length > 0) {
      // Handle conflicts
      const resolved = await this.resolveConflicts(mergeResult.conflicts, options);
      mergeResult.changes.push(...resolved);
    }

    // Create merge commit
    const mergeCommit = await this.createMergeCommit(
      `Merge ${sourceBranch} into ${targetBranch}`,
      mergeResult.changes,
      [source.head, target.head]
    );

    // Update branch
    target.head = mergeCommit.hash;
    target.commits.push(mergeCommit.hash);

    // Update stats
    this.stats.totalMerges++;
    if (mergeResult.conflicts.length > 0) {
      this.stats.totalConflicts += mergeResult.conflicts.length;
    }

    // Run post-merge hook
    if (this.config.hooks.postMerge) {
      await this.runHook('post-merge', { commit: mergeCommit, result: mergeResult });
    }

    this.emit('branch:merged', { source: sourceBranch, target: targetBranch, commit: mergeCommit });
    return mergeCommit;
  }

  /**
   * Create a tag
   */
  async createTag(name, commitHash = null, annotation = '') {
    if (this.tags.has(name)) {
      throw new Error(`Tag ${name} already exists`);
    }

    const tag = {
      name,
      commit: commitHash || this.head,
      annotation,
      created: new Date(),
      author: 'System'
    };

    this.tags.set(name, tag);

    this.emit('tag:created', tag);
    return tag;
  }

  /**
   * Get commit history
   */
  async getHistory(branch = this.currentBranch, limit = 50) {
    const branchObj = this.branches.get(branch);
    if (!branchObj) {
      throw new Error(`Branch ${branch} not found`);
    }

    const history = [];
    let currentHash = branchObj.head;
    let count = 0;

    while (currentHash && count < limit) {
      const commit = this.commits.get(currentHash);
      if (!commit) break;

      history.push(commit);
      currentHash = commit.parent;
      count++;
    }

    return history;
  }

  /**
   * Get diff between commits
   */
  async getDiff(fromCommit, toCommit) {
    const from = this.commits.get(fromCommit);
    const to = this.commits.get(toCommit);

    if (!from || !to) {
      throw new Error('Invalid commit hashes');
    }

    return this.calculateDiff(from.tree, to.tree);
  }

  /**
   * Cherry-pick commit
   */
  async cherryPick(commitHash) {
    const commit = this.commits.get(commitHash);
    if (!commit) {
      throw new Error('Commit not found');
    }

    // Apply commit changes to current branch
    const changes = await this.applyCommitChanges(commit);

    // Create new commit
    const newCommit = await this.createCommit(
      `Cherry-pick: ${commit.message}`,
      changes,
      commit.author
    );

    // Update branch
    const branch = this.branches.get(this.currentBranch);
    branch.head = newCommit.hash;
    branch.commits.push(newCommit.hash);

    this.head = newCommit.hash;

    this.emit('commit:cherry-picked', { original: commit, new: newCommit });
    return newCommit;
  }

  /**
   * Rebase branch
   */
  async rebase(targetBranch) {
    const currentBranchObj = this.branches.get(this.currentBranch);
    const targetBranchObj = this.branches.get(targetBranch);

    if (!targetBranchObj) {
      throw new Error(`Branch ${targetBranch} not found`);
    }

    // Find divergence point
    const divergencePoint = await this.findCommonAncestor(
      currentBranchObj.head,
      targetBranchObj.head
    );

    // Get commits to rebase
    const commitsToRebase = await this.getCommitsSince(
      this.currentBranch,
      divergencePoint
    );

    // Apply commits on top of target branch
    let newHead = targetBranchObj.head;

    for (const commit of commitsToRebase) {
      const changes = await this.applyCommitChanges(commit);
      const newCommit = await this.createCommit(
        commit.message,
        changes,
        commit.author
      );
      newHead = newCommit.hash;
    }

    // Update current branch
    currentBranchObj.head = newHead;

    this.head = newHead;

    this.emit('branch:rebased', {
      branch: this.currentBranch,
      onto: targetBranch,
      commits: commitsToRebase.length
    });

    return newHead;
  }

  /**
   * Stash changes
   */
  async stashChanges(message = '') {
    if (this.stagingArea.size === 0) {
      throw new Error('No changes to stash');
    }

    const stashEntry = {
      id: crypto.randomBytes(8).toString('hex'),
      message: message || `WIP on ${this.currentBranch}`,
      branch: this.currentBranch,
      changes: Array.from(this.stagingArea.values()),
      created: new Date()
    };

    this.stash.push(stashEntry);
    this.stagingArea.clear();

    this.emit('changes:stashed', stashEntry);
    return stashEntry;
  }

  /**
   * Apply stashed changes
   */
  async stashPop(stashId = null) {
    let stashEntry;

    if (stashId) {
      const index = this.stash.findIndex(s => s.id === stashId);
      if (index === -1) throw new Error('Stash entry not found');
      stashEntry = this.stash.splice(index, 1)[0];
    } else {
      stashEntry = this.stash.pop();
    }

    if (!stashEntry) {
      throw new Error('No stash entries');
    }

    // Apply changes to staging area
    for (const change of stashEntry.changes) {
      this.stagingArea.set(change.id, change);
    }

    this.emit('stash:applied', stashEntry);
    return stashEntry;
  }

  /**
   * Reset to commit
   */
  async reset(commitHash, mode = 'mixed') {
    const commit = this.commits.get(commitHash);
    if (!commit) {
      throw new Error('Commit not found');
    }

    switch (mode) {
      case 'soft':
        // Move HEAD only
        this.head = commitHash;
        break;

      case 'mixed':
        // Move HEAD and reset staging area
        this.head = commitHash;
        this.stagingArea.clear();
        break;

      case 'hard':
        // Move HEAD, reset staging area and working directory
        this.head = commitHash;
        this.stagingArea.clear();
        await this.updateWorkingDirectory(commitHash);
        break;
    }

    // Update current branch
    const branch = this.branches.get(this.currentBranch);
    if (branch) {
      branch.head = commitHash;
    }

    this.emit('reset', { commit: commitHash, mode });
    return commit;
  }

  /**
   * Revert commit
   */
  async revert(commitHash) {
    const commit = this.commits.get(commitHash);
    if (!commit) {
      throw new Error('Commit not found');
    }

    // Create inverse changes
    const inverseChanges = await this.createInverseChanges(commit.changes);

    // Create revert commit
    const revertCommit = await this.createCommit(
      `Revert "${commit.message}"`,
      inverseChanges
    );

    // Update branch
    const branch = this.branches.get(this.currentBranch);
    branch.head = revertCommit.hash;
    branch.commits.push(revertCommit.hash);

    this.head = revertCommit.hash;

    this.emit('commit:reverted', { original: commit, revert: revertCommit });
    return revertCommit;
  }

  /**
   * Helper: Create commit object
   */
  async createCommit(message, changes, author = 'System') {
    const tree = await this.createTree(changes);

    const commit = {
      hash: this.generateCommitHash(message, tree, author),
      message,
      author,
      timestamp: new Date(),
      parent: this.head,
      tree,
      changes
    };

    this.commits.set(commit.hash, commit);
    return commit;
  }

  /**
   * Helper: Create merge commit
   */
  async createMergeCommit(message, changes, parents) {
    const tree = await this.createTree(changes);

    const commit = {
      hash: this.generateCommitHash(message, tree, 'System'),
      message,
      author: 'System',
      timestamp: new Date(),
      parents, // Multiple parents for merge commit
      tree,
      changes
    };

    this.commits.set(commit.hash, commit);
    return commit;
  }

  /**
   * Helper: Generate commit hash
   */
  generateCommitHash(message, tree, author) {
    const data = `${message}${JSON.stringify(tree)}${author}${Date.now()}`;
    return crypto.createHash('sha256').update(data).digest('hex');
  }

  /**
   * Helper: Generate change ID
   */
  generateChangeId(change) {
    const data = `${change.path}${change.type}${Date.now()}`;
    return crypto.createHash('md5').update(data).digest('hex');
  }

  /**
   * Helper: Create tree from changes
   */
  async createTree(changes) {
    const tree = {};

    for (const change of changes) {
      tree[change.path] = {
        type: change.type,
        content: change.content,
        hash: crypto.createHash('sha1').update(JSON.stringify(change.content)).digest('hex')
      };
    }

    return tree;
  }

  /**
   * Helper: Create diff
   */
  async createDiff(change) {
    // Implement diff algorithm
    return {
      added: [],
      removed: [],
      modified: []
    };
  }

  /**
   * Helper: Calculate diff between trees
   */
  async calculateDiff(fromTree, toTree) {
    const diff = {
      added: [],
      removed: [],
      modified: []
    };

    // Find added and modified
    for (const [path, toNode] of Object.entries(toTree)) {
      if (!fromTree[path]) {
        diff.added.push({ path, content: toNode.content });
      } else if (fromTree[path].hash !== toNode.hash) {
        diff.modified.push({ path, from: fromTree[path].content, to: toNode.content });
      }
    }

    // Find removed
    for (const [path, fromNode] of Object.entries(fromTree)) {
      if (!toTree[path]) {
        diff.removed.push({ path, content: fromNode.content });
      }
    }

    return diff;
  }

  /**
   * Helper: Find common ancestor
   */
  async findCommonAncestor(hash1, hash2) {
    const ancestors1 = await this.getAncestors(hash1);
    const ancestors2 = await this.getAncestors(hash2);

    for (const ancestor of ancestors1) {
      if (ancestors2.includes(ancestor)) {
        return ancestor;
      }
    }

    return null;
  }

  /**
   * Helper: Get ancestors of a commit
   */
  async getAncestors(commitHash) {
    const ancestors = [];
    let current = commitHash;

    while (current) {
      ancestors.push(current);
      const commit = this.commits.get(current);
      if (!commit) break;
      current = commit.parent;
    }

    return ancestors;
  }

  /**
   * Helper: Check if fast-forward is possible
   */
  async canFastForward(sourceHead, targetHead, commonAncestor) {
    return commonAncestor === targetHead;
  }

  /**
   * Helper: Fast-forward merge
   */
  async fastForwardMerge(source, target) {
    target.head = source.head;
    target.commits.push(...source.commits);

    this.emit('merge:fast-forward', { source: source.name, target: target.name });
    return source.head;
  }

  /**
   * Helper: Three-way merge
   */
  async threeWayMerge(sourceHead, targetHead, commonAncestor, options) {
    const sourceCommit = this.commits.get(sourceHead);
    const targetCommit = this.commits.get(targetHead);
    const ancestorCommit = this.commits.get(commonAncestor);

    const result = {
      changes: [],
      conflicts: []
    };

    // Implement 3-way merge algorithm
    // This is a simplified version
    const sourceDiff = await this.calculateDiff(ancestorCommit.tree, sourceCommit.tree);
    const targetDiff = await this.calculateDiff(ancestorCommit.tree, targetCommit.tree);

    // Merge non-conflicting changes
    result.changes.push(...sourceDiff.added, ...targetDiff.added);

    // Detect conflicts
    for (const sourceModified of sourceDiff.modified) {
      const targetModified = targetDiff.modified.find(t => t.path === sourceModified.path);
      if (targetModified) {
        result.conflicts.push({
          path: sourceModified.path,
          source: sourceModified.to,
          target: targetModified.to
        });
      } else {
        result.changes.push(sourceModified);
      }
    }

    return result;
  }

  /**
   * Helper: Resolve conflicts
   */
  async resolveConflicts(conflicts, options) {
    const resolved = [];
    const strategy = options.strategy || this.config.conflictResolution;

    for (const conflict of conflicts) {
      let resolution;

      switch (strategy) {
        case 'ours':
          resolution = conflict.target;
          break;
        case 'theirs':
          resolution = conflict.source;
          break;
        case 'merge':
          resolution = await this.mergeContent(conflict.source, conflict.target);
          break;
        case 'manual':
        default:
          resolution = await this.promptConflictResolution(conflict);
      }

      resolved.push({
        path: conflict.path,
        content: resolution,
        type: 'modify'
      });
    }

    return resolved;
  }

  /**
   * Helper: Other methods
   */
  async updateWorkingDirectory(commitHash) {
    // Update working directory to match commit
    const commit = this.commits.get(commitHash);
    if (commit) {
      this.workingDirectory.clear();
      for (const [path, node] of Object.entries(commit.tree)) {
        this.workingDirectory.set(path, node.content);
      }
    }
  }

  async getCommitsSince(branch, sinceHash) {
    const commits = [];
    const branchObj = this.branches.get(branch);
    let current = branchObj.head;

    while (current && current !== sinceHash) {
      const commit = this.commits.get(current);
      if (!commit) break;
      commits.push(commit);
      current = commit.parent;
    }

    return commits.reverse();
  }

  async applyCommitChanges(commit) {
    // Apply commit's changes to working directory
    return commit.changes;
  }

  async createInverseChanges(changes) {
    // Create inverse of changes for revert
    return changes.map(change => ({
      ...change,
      type: change.type === 'add' ? 'delete' : change.type === 'delete' ? 'add' : 'modify',
      content: change.oldContent || null
    }));
  }

  async promptStash() {
    // Prompt user to stash changes
    this.emit('prompt:stash');
    return true; // Auto-stash for now
  }

  async promptConflictResolution(conflict) {
    // Prompt user to resolve conflict
    this.emit('prompt:conflict', conflict);
    return conflict.source; // Default to source for now
  }

  async mergeContent(source, target) {
    // Attempt to merge content automatically
    return source; // Simplified
  }

  async runHook(hookName, data) {
    this.emit(`hook:${hookName}`, data);
  }

  async garbageCollection() {
    // Clean up old commits beyond maxHistorySize
    this.emit('gc:start');
    // Implementation would clean up unreachable commits
    this.emit('gc:complete');
  }
}

module.exports = VersionControl;