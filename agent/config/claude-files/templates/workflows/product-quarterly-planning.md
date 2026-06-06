# Workflow: Quarterly Product Planning

Complete workflow for quarterly OKR and roadmap planning.

## Steps

### 1. Market Research
```javascript
Task({
  subagent_type: "strategy-market-researcher",
  description: "Q1 2026 market analysis",
  prompt: "Analyze [your market] for Q1 2026. Focus on: trends, competitor moves, pricing evolution"
})
```
Uses WebSearch for current data. **Duration**: ~5 minutes

**Output**: `market-analysis-q1-2026.md`

### 2. Competitive Analysis
```javascript
Task({
  subagent_type: "strategy-competitive-intelligence-analyst",
  description: "Competitor feature analysis",
  prompt: "Analyze how [competitors] handle [feature area]. What gaps exist?"
})
```
**Duration**: ~4 minutes

**Output**: `competitive-analysis.md`

### 3. Brainstorm Features
```bash
/orc:brainstorm "[focus area]" --market-research --count 10
```
Spawns 3 agents (product, design, engineering) for perspectives.
Uses RICE scoring for prioritization.

**Duration**: ~3 minutes

**Output**: `brainstorm-results.md` with scored ideas

### 4. Create Roadmap
```javascript
Task({
  subagent_type: "strategy-roadmap-strategist",
  description: "Q1-Q2 roadmap",
  prompt: "Create Q1-Q2 2026 roadmap. Focus on top 3 features from brainstorm. Budget: [resources], [timeline]"
})
```
Creates Now/Next/Later structure with dependencies.

**Duration**: ~5 minutes

**Output**: `roadmap-q1-q2-2026.md`

### 5. Convert to GitHub Issues
```bash
/gh:create-issues
```
Reads roadmap and creates trackable GitHub issues with:
- Milestones
- Story point estimates
- Links to roadmap docs

**Duration**: ~2 minutes

**Output**: GitHub issues created

### 6. Stakeholder Review
```bash
/orc:review-spec roadmap-q1-q2-2026.md
```
Multi-agent review from engineering, design, QA, ops perspectives.

**Duration**: ~4 minutes

**Output**: `review-roadmap.md` with feedback

### 7. Finalize & Communicate
Update roadmap based on feedback, then optionally:
```bash
/notion-knowledge-capture
```
Creates polished Notion page for stakeholder sharing.

## Expected Duration

**Total**: ~25 minutes (vs. 4-8 hours manual)

## Artifacts Created

1. `market-analysis-q1-2026.md`
2. `competitive-analysis.md`
3. `brainstorm-results.md`
4. `roadmap-q1-q2-2026.md`
5. `review-roadmap.md`
6. 10-15 GitHub issues
7. Notion page (optional)

## Memory Integration

Hooks automatically:
- `memory-session-start.sh` - Loads previous quarter context
- `memory-session-stop.sh` - Saves decisions for next quarter

## Tips

- Run at start of each quarter
- Review previous quarter's roadmap first
- Use WebSearch for current (2026) data
- Calibrate RICE scores to your context

## Related Workflows

- [Sprint Planning](./sprint-planning.md)
- [Feature PRD Creation](./feature-prd.md)
- [Market Research Deep Dive](./market-research.md)
