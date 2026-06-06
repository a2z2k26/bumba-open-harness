# Ready Queue Filter Setup Guide

This guide explains how to configure the Ready Queue view in Notion to respect task dependencies.

## Overview

The Ready Queue view should show only tasks that are:
1. Status = "ready"
2. Have no dependencies, OR all dependency tasks are completed

This prevents tasks from appearing in the Ready Queue if they're blocked by incomplete dependencies.

## Manual Setup Steps

### Step 1: Open Tasks Master Database

1. Open your Notion workspace
2. Navigate to your Tasks Master database
3. Find the "Ready Queue" view

### Step 2: Edit View Filters

Click on the "Ready Queue" view's filter button (funnel icon) and configure:

**Basic Filter:**
```
Status | is | ready
```

**Dependency Filter (Add This):**
```
AND Dependencies | is empty
```

OR

```
OR Dependencies.Status | is | completed (for ALL)
```

### Step 3: Configure Formula (Alternative Approach)

If you want more control, create a formula property called "Is Ready":

1. Add a new property to Tasks Master
2. Name: "Is Ready"
3. Type: Formula
4. Formula:
```
if(
  prop("Status") == "ready" and (
    empty(prop("Dependencies")) or
    length(filter(prop("Dependencies"), current.prop("Status") != "completed")) == 0
  ),
  true,
  false
)
```

4. Then filter Ready Queue by:
```
Is Ready | is | checked
```

## Testing the Filter

### Test Scenario 1: Task with No Dependencies

1. Create a task with Status = "ready"
2. Leave Dependencies empty
3. ✅ Task should appear in Ready Queue

### Test Scenario 2: Task with Incomplete Dependencies

1. Create Task A with Status = "in_progress"
2. Create Task B with Status = "ready"
3. Set Task B Dependencies = [Task A]
4. ❌ Task B should NOT appear in Ready Queue (blocked by incomplete Task A)

### Test Scenario 3: Task with Completed Dependencies

1. Mark Task A as Status = "completed"
2. Task B still has Status = "ready" and Dependencies = [Task A]
3. ✅ Task B should now appear in Ready Queue (dependency completed)

## Troubleshooting

### Tasks Not Appearing in Ready Queue

**Check:**
- [ ] Status is exactly "ready" (case-sensitive)
- [ ] Dependencies property exists on the task
- [ ] If has dependencies, check each dependency's status
- [ ] View filter is configured correctly

### Tasks Appearing When They Shouldn't

**Check:**
- [ ] View filter includes dependency check
- [ ] All dependency relations are set correctly
- [ ] Dependency tasks have correct status values

## Notion API Limitations

**Important:** Notion's filter API has limitations with relation properties. The recommended approach is:

1. **Option A (Simple):** Only show tasks with no dependencies
   - Filter: `Dependencies | is empty`
   - Limitation: Tasks with completed dependencies won't show

2. **Option B (Formula):** Use a formula property
   - More accurate but requires formula maintenance
   - Checks if all dependencies are completed

3. **Option C (View-Based):** Create multiple views
   - "Ready - No Dependencies" view
   - "Ready - Dependencies Complete" view
   - Combine with board view grouping

## Recommended Configuration

For most users, we recommend **Option B** (formula property):

**Advantages:**
- ✅ Accurately reflects dependency status
- ✅ Automatically updates when dependencies change
- ✅ Works with existing Ready Queue view

**Setup Time:** ~5 minutes

**Formula Template:**
```
if(prop("Status") == "ready" and (empty(prop("Dependencies")) or length(filter(prop("Dependencies"), current.prop("Status") != "completed")) == 0), true, false)
```

## Verification Checklist

After setup, verify:

- [ ] Ready Queue shows tasks with Status = "ready" and no dependencies
- [ ] Ready Queue shows tasks with Status = "ready" and all dependencies completed
- [ ] Ready Queue hides tasks with any incomplete dependencies
- [ ] Formula property (if used) updates when dependency status changes
- [ ] View refreshes automatically (no manual reload needed)

## Support

If you encounter issues:

1. Check the TROUBLESHOOTING.md guide
2. Verify Dependencies property exists in schema-definitions.json
3. Ensure /sync-github is parsing dependencies correctly
4. Test with simple scenarios first (2-3 tasks)

## Example Configuration

Here's a working Ready Queue configuration:

```
View: Ready Queue
Type: Table
Filter:
  - Status | is | ready
  - AND (
      Dependencies | is empty
      OR Dependencies.Status | is | completed (for ALL)
    )
Sort:
  - Priority | descending
Properties Shown:
  - Task ID
  - Status
  - Dependencies
  - Priority
  - Sprint ID
  - GitHub Issue
```

---

**Last Updated:** 2026-01-16
**Plugin Version:** bumba-notion v1.0.0
**Related Docs:** USAGE.md, VALIDATION-CHECKLIST.md
