#!/usr/bin/env node

/**
 * sync-github-runner.js
 *
 * Executable script for /sync-github command
 * This script is called by Claude Code and performs the actual GitHub → Notion sync
 *
 * Usage: node sync-github-runner.js <github-repo-url> <project-metadata-json>
 */

const syncHelper = require('./sync-helper.js');

/**
 * Main sync function
 */
async function runSync() {
  const startTime = Date.now();

  try {
    // Parse command line arguments
    if (process.argv.length < 4) {
      console.error('Usage: node sync-github-runner.js <github-repo-url> <project-metadata-json>');
      process.exit(1);
    }

    const githubRepoUrl = process.argv[2];
    const projectMetadataJson = process.argv[3];

    console.log(`\n🔄 Starting GitHub → Notion sync...`);
    console.log(`📦 Repository: ${githubRepoUrl}\n`);

    // Step 1: Validate GitHub URL
    const { owner, repo } = syncHelper.parseGitHubUrl(githubRepoUrl);
    console.log(`✓ Validated GitHub URL: ${owner}/${repo}`);

    // Step 2: Parse project metadata (passed from Claude Code after MCP lookup)
    let projectMetadata;
    try {
      projectMetadata = JSON.parse(projectMetadataJson);
    } catch (error) {
      console.error(`❌ Failed to parse project metadata: ${error.message}`);
      process.exit(1);
    }

    console.log(`✓ Found project: ${projectMetadata.projectName}`);
    console.log(`  Dashboard: ${projectMetadata.dashboardUrl}`);

    const projectEntryId = projectMetadata.projectMasterEntryId;
    if (!projectEntryId) {
      console.error(`❌ Project metadata missing projectMasterEntryId`);
      console.error(`   This is required to link tasks to the project`);
      process.exit(1);
    }

    // Step 3: Load configuration
    const { workspaceMapping, syncRules } = syncHelper.loadConfig();
    console.log(`✓ Loaded configuration`);

    // Step 4: Fetch and sync GitHub milestones to Sprints
    console.log(`\n📅 Fetching GitHub milestones...`);
    const milestones = syncHelper.fetchGitHubMilestones(owner, repo);
    console.log(`✓ Found ${milestones.length} milestones`);

    const sprintsDbId = workspaceMapping.masterDatabases.sprints;
    const tasksDbId = workspaceMapping.masterDatabases.tasks;
    const notionToken = workspaceMapping.notionToken;
    const epicEntryId = projectMetadata.epicMasterEntryId;

    // Create a map of milestone number to sprint ID for linking tasks
    const milestoneToSprintMap = {};

    if (milestones.length > 0) {
      console.log(`\n🔄 Syncing milestones to Sprints...`);

      for (const milestone of milestones) {
        const result = await syncHelper.syncNotionSprint(
          notionToken,
          sprintsDbId,
          milestone,
          epicEntryId,
          projectEntryId
        );

        if (result.success) {
          milestoneToSprintMap[milestone.number] = result.sprintId;
          console.log(`  ✓ ${result.action === 'created' ? 'Created' : 'Updated'} Sprint: ${milestone.title}`);
        } else {
          console.log(`  ❌ Failed to sync milestone #${milestone.number}: ${result.error}`);
        }
      }

      console.log(`✓ Synced ${Object.keys(milestoneToSprintMap).length} sprints`);
    }

    // Step 5: Fetch GitHub issues
    console.log(`\n📥 Fetching GitHub issues...`);
    const issues = syncHelper.fetchGitHubIssues(owner, repo, 100);
    console.log(`✓ Found ${issues.length} open issues`);

    if (issues.length === 0) {
      console.log(`\n✅ No open issues to sync`);
      process.exit(0);
    }

    // Step 6: Check for duplicates and create tasks (Two-pass approach)
    console.log(`\n🔍 Checking for existing tasks...`);

    let createdCount = 0;
    let skippedCount = 0;
    let errorCount = 0;
    const errors = [];
    const createdTaskMap = new Map(); // Map issue URL to Notion task ID

    // PASS 1: Create all tasks without dependencies
    console.log(`\n📝 Pass 1: Creating tasks...`);
    for (const issue of issues) {
      // Check if task already exists
      const exists = await syncHelper.checkDuplicateTask(notionToken, tasksDbId, issue.url);

      if (exists) {
        skippedCount++;
        console.log(`  ⏭  Skipped #${issue.number}: ${issue.title} (already exists)`);
        continue;
      }

      // Get sprint ID if issue has a milestone
      const sprintId = issue.milestone ? milestoneToSprintMap[issue.milestone.number] : null;

      // Create new task WITHOUT dependencies (will add in pass 2)
      console.log(`  ✨ Creating #${issue.number}: ${issue.title}${sprintId ? ` (Sprint: ${issue.milestone.title})` : ''}`);
      const result = await syncHelper.createNotionTaskWithRetry(
        notionToken,
        tasksDbId,
        issue,
        githubRepoUrl,
        syncRules.statusMapping,
        syncRules.syncBehavior,
        projectEntryId,      // Link task to project
        sprintId,            // Link task to sprint (if has milestone)
        null                 // No dependencies yet
      );

      if (result.success) {
        createdCount++;
        createdTaskMap.set(issue.url, result.taskId);
        console.log(`     ✓ Created successfully`);
      } else {
        errorCount++;
        errors.push({
          issueNumber: issue.number,
          issueTitle: issue.title,
          error: result.error,
          timestamp: new Date().toISOString()
        });
        console.log(`     ❌ Failed: ${result.error}`);
      }
    }

    // PASS 2: Update tasks with dependencies
    if (createdCount > 0) {
      console.log(`\n🔗 Pass 2: Setting dependencies...`);
      let dependenciesSetCount = 0;

      for (const issue of issues) {
        // Skip if this issue wasn't just created
        if (!createdTaskMap.has(issue.url)) {
          continue;
        }

        // Parse dependencies from issue body
        const dependencyUrls = syncHelper.parseDependencies(issue.body, githubRepoUrl);

        if (dependencyUrls.length === 0) {
          continue;
        }

        console.log(`  🔗 Setting ${dependencyUrls.length} dependencies for #${issue.number}...`);

        // Look up dependency task IDs (including newly created ones)
        const dependencyTaskIds = await syncHelper.findTasksByGitHubUrls(notionToken, tasksDbId, dependencyUrls);

        if (dependencyTaskIds.length > 0) {
          // Update the task with dependencies
          const taskId = createdTaskMap.get(issue.url);
          const updateResult = await syncHelper.updateTaskDependencies(notionToken, taskId, dependencyTaskIds);

          if (updateResult.success) {
            dependenciesSetCount++;
            console.log(`     ✓ Set ${dependencyTaskIds.length} dependencies`);
          } else {
            console.log(`     ⚠️  Failed to set dependencies: ${updateResult.error}`);
          }
        } else {
          console.log(`     ⚠️  Dependencies not found in Notion`);
        }
      }

      if (dependenciesSetCount > 0) {
        console.log(`✓ Set dependencies for ${dependenciesSetCount} tasks`);
      }
    }

    const duration = Date.now() - startTime;

    // Step 6: Update sync state
    const syncResult = {
      projectName: projectMetadata.projectName,
      githubRepo: githubRepoUrl,
      dashboardPageId: projectMetadata.dashboardPageId,
      dashboardUrl: projectMetadata.dashboardUrl,
      totalIssues: issues.length,
      createdCount,
      skippedCount,
      errorCount,
      errors,
      duration
    };

    const syncStatePath = syncHelper.updateSyncState(projectMetadata.projectSlug, syncResult);
    console.log(`\n✓ Updated sync state: ${syncStatePath}`);

    // Step 7: Display summary
    console.log(`\n${'='.repeat(60)}`);
    console.log(syncHelper.formatSyncSummary(syncResult));
    console.log('='.repeat(60));

    // Output structured result for Claude Code to store in bumba-memory
    const mcpData = {
      mcpKey: `bumba-notion:sync:${projectMetadata.projectSlug}`,
      syncState: {
        projectSlug: projectMetadata.projectSlug,
        projectName: projectMetadata.projectName,
        githubRepo: githubRepoUrl,
        dashboardPageId: projectMetadata.dashboardPageId,
        lastSync: new Date().toISOString(),
        stats: {
          totalSyncs: 1, // Claude Code should increment this from existing state
          totalIssuesCreated: createdCount,
          lastError: errorCount > 0 ? new Date().toISOString() : null
        },
        lastSyncResult: syncResult
      }
    };

    console.log(`\n📋 MCP Storage Data (for bumba-memory):`);
    console.log(JSON.stringify(mcpData, null, 2));

    process.exit(errorCount > 0 ? 1 : 0);

  } catch (error) {
    console.error(`\n❌ Sync failed: ${error.message}`);
    console.error(error.stack);
    process.exit(1);
  }
}

// Run the sync
runSync();
