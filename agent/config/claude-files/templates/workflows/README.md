# Workflow Templates

Pre-built workflow templates for common Claude Code scenarios. Each template provides step-by-step instructions with expected durations and outputs.

## Available Workflows

### Design Workflows
- **[Figma to React](./design-figma-to-react.md)** - Transform Figma designs to production React code (~15 min first time, ~5 min after)
  - Commands: `/design-init`, `/design-layout-to-jsx`, `/design-transform-react`, `/design-promote`
  - Hooks: Automatic Storybook generation
  - Output: React components, theme, stories

### Product Strategy Workflows
- **[Quarterly Planning](./product-quarterly-planning.md)** - Complete quarterly OKR and roadmap planning (~25 min)
  - Agents: market-researcher, roadmap-strategist, competitive-intelligence-analyst
  - Commands: `/orc:brainstorm`, `/gh:create-issues`, `/orc:review-spec`
  - Output: Market analysis, roadmap, GitHub issues

### Full-Stack Workflows
- **[Full-Stack Feature Development](./full-stack-feature-development.md)** - End-to-end feature from requirements to deployment (2-4 hours)
  - Phases: Planning → Design → Development → QA → Deployment
  - Departments: Product Strategy → Design → Engineering → QA → Operations
  - Output: Complete feature with tests and deployment

## How to Use Workflows

1. **Choose a workflow** that matches your current task
2. **Follow steps sequentially** - each step builds on the previous
3. **Adjust commands** to your specific context (replace placeholders)
4. **Save artifacts** - workflows create markdown docs you can reference
5. **Iterate** - most workflows support refinement loops

## Creating Custom Workflows

Template structure:
```markdown
# Workflow: [Name]

Brief description

## Steps

### 1. Step Name
Command or agent invocation
Expected duration
Output

### 2. Next Step
...

## Expected Duration
Total time estimate

## Artifacts Created
List of files/outputs

## Common Issues
Troubleshooting tips

## Related Workflows
Links to similar workflows
```

## Workflow Categories

### By Department
- **Product Strategy**: Quarterly planning, PRD creation, market research
- **Design**: Figma to code, design exploration, design systems
- **Engineering**: Full-stack development, API design, code review
- **Operations**: Deployment, monitoring, infrastructure setup
- **QA/Testing**: Test automation, code review, quality gates

### By Duration
- **Quick (< 30 min)**: Design transformations, single feature planning
- **Medium (30 min - 2 hours)**: Quarterly planning, design exploration, code review
- **Long (2+ hours)**: Full-stack feature development, architecture design

### By Complexity
- **Simple**: Single command workflows
- **Moderate**: Multi-agent orchestration
- **Complex**: Cross-department, multi-phase workflows

## Tips

- **Start with templates** - Don't reinvent workflows, use existing ones
- **Document variations** - When you customize a workflow, save it as a new template
- **Track time** - Note actual vs. expected duration to improve estimates
- **Share workflows** - Team members can use the same efficient patterns

## Adding New Workflows

1. Create markdown file: `templates/workflows/your-workflow-name.md`
2. Follow template structure above
3. Add to this README under appropriate category
4. Include:
   - Clear step-by-step instructions
   - Expected duration for each step
   - Outputs/artifacts created
   - Common issues and fixes
   - Related workflows

---

**Last Updated**: 2026-01-15
**Workflow Count**: 3
**Coverage**: Design, Product Strategy, Full-Stack
