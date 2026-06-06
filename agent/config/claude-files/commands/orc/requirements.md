---
name: requirements
description: Create structured PRD (Ideation stage)
---

# /create-product-requirements Command

Generates a comprehensive Product Requirements Document (PRD) through interactive conversation.

## Usage

```
/create-product-requirements [--template <template-name>]
```

## Parameters

- `--template <name>` (optional): Use a predefined PRD template (default: standard)
  - `standard`: Full-featured product PRD
  - `feature`: Single feature PRD
  - `minimal`: Lightweight requirements doc
  - `technical`: Technical specification focus

## Workflow

### Step 1: Problem Statement & Context

I'll ask you a series of questions to understand the problem:

```
📋 Product Requirements Document Creation
═══════════════════════════════════════════════

Let's start by understanding the problem you're solving.

1. What problem are you trying to solve?
   (Describe the pain point or opportunity)

2. Who experiences this problem?
   (Define your target users/customers)

3. How are they solving this problem today?
   (Current solutions, workarounds, or nothing)

4. Why is now the right time to build this?
   (Market timing, competitive advantage, user demand)
```

### Step 2: Goals & Success Metrics

```
🎯 Goals & Success Criteria

5. What are the primary goals of this product/feature?
   (List 3-5 key objectives)

6. How will you measure success?
   (Define specific, measurable metrics)
   Examples:
   - User adoption: X% of users use feature within Y days
   - Engagement: Z actions per user per week
   - Business: $W in revenue or X% cost reduction
   - Performance: Y ms response time

7. What does success look like in 3 months? 6 months? 1 year?
```

### Step 3: User Stories & Use Cases

```
👥 User Stories

8. Who are the primary user personas?
   (Name, role, goals, pain points for each)

9. What are the key user journeys?
   (Step-by-step flows for main use cases)

For each user story, I'll help you define:
   - As a [persona]
   - I want to [action]
   - So that [benefit]
   - Acceptance criteria
```

### Step 4: Feature Requirements

```
✨ Features & Capabilities

10. What are the must-have features (P0)?
    (Critical for launch, without these the product fails)

11. What are the should-have features (P1)?
    (Important but can be added shortly after launch)

12. What are the nice-to-have features (P2)?
    (Would enhance the product but not essential)

For each feature, I'll document:
   - Feature name
   - Description
   - User value/benefit
   - Priority (P0/P1/P2)
   - Dependencies
   - Estimated complexity (S/M/L/XL)
```

### Step 5: Technical Considerations

```
🔧 Technical Requirements

13. Are there specific technical constraints?
    (Platform, languages, frameworks, integrations)

14. What are the performance requirements?
    (Response time, throughput, scalability)

15. What are the security requirements?
    (Authentication, authorization, data protection)

16. What are the compliance requirements?
    (GDPR, HIPAA, accessibility, etc.)
```

### Step 6: Scope & Timeline

```
📅 Scope & Timeline

17. What is out of scope for this version?
    (Explicitly state what we're NOT building)

18. What is the target timeline?
    (MVP date, beta launch, general availability)

19. What are the key milestones?
    (Development phases, testing gates, launch stages)

20. What are the dependencies or blockers?
    (Team, resources, external factors)
```

### Step 7: Risks & Open Questions

```
⚠️ Risks & Mitigations

21. What are the main risks?
    (Technical, business, user adoption, competitive)

22. How will you mitigate these risks?
    (Specific strategies for each risk)

23. What questions remain unanswered?
    (Areas needing more research or validation)
```

### Step 8: Generate PRD Document

After gathering all information, I'll generate a comprehensive PRD in markdown format:

```markdown
# Product Requirements Document: [Product Name]

**Version**: 1.0
**Date**: [Current Date]
**Author**: [Your Name]
**Status**: Draft

---

## Executive Summary

[2-3 paragraph overview of the product, problem, and solution]

---

## Problem Statement

### The Problem
[Detailed description of the problem]

### Target Users
[User personas and segments]

### Current Solutions
[How users solve this today and why it's inadequate]

### Market Opportunity
[Why now is the right time]

---

## Goals & Success Metrics

### Primary Goals
1. [Goal 1]
2. [Goal 2]
3. [Goal 3]

### Success Metrics
| Metric | Target | Timeline |
|--------|--------|----------|
| [Metric 1] | [Target] | [When] |
| [Metric 2] | [Target] | [When] |

### Milestones
- **3 months**: [Objectives]
- **6 months**: [Objectives]
- **1 year**: [Objectives]

---

## User Personas

### Persona 1: [Name]
- **Role**: [Role]
- **Goals**: [Goals]
- **Pain Points**: [Pain points]
- **Technical Expertise**: [Level]

[Repeat for each persona]

---

## User Stories & Use Cases

### Epic 1: [Epic Name]

**User Story 1.1**:
- **As a** [persona]
- **I want to** [action]
- **So that** [benefit]
- **Acceptance Criteria**:
  - [ ] [Criterion 1]
  - [ ] [Criterion 2]

[Repeat for all stories]

---

## Feature Requirements

### Must-Have Features (P0)

#### Feature 1: [Name]
- **Description**: [What it does]
- **User Value**: [Why it matters]
- **Priority**: P0
- **Complexity**: [S/M/L/XL]
- **Dependencies**: [Other features]
- **Acceptance Criteria**:
  - [ ] [Criterion 1]
  - [ ] [Criterion 2]

[Repeat for all P0 features]

### Should-Have Features (P1)
[Same structure as P0]

### Nice-to-Have Features (P2)
[Same structure as P0]

---

## Technical Requirements

### Architecture
[High-level architecture description]

### Technology Stack
- **Frontend**: [Technologies]
- **Backend**: [Technologies]
- **Database**: [Technologies]
- **Infrastructure**: [Cloud, hosting]

### Performance Requirements
- Response time: [Target]
- Throughput: [Target]
- Scalability: [Target]

### Security Requirements
- Authentication: [Method]
- Authorization: [RBAC, etc.]
- Data protection: [Encryption, etc.]

### Compliance
- [GDPR, HIPAA, etc.]

---

## Scope

### In Scope
- [What we're building]

### Out of Scope
- [What we're explicitly NOT building]

---

## Timeline & Milestones

| Phase | Milestone | Target Date | Deliverables |
|-------|-----------|-------------|--------------|
| Phase 1 | [Name] | [Date] | [Deliverables] |
| Phase 2 | [Name] | [Date] | [Deliverables] |

---

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| [Risk 1] | High/Med/Low | High/Med/Low | [Strategy] |

---

## Open Questions

1. [Question 1]
2. [Question 2]

---

## Appendix

### References
- [Links to research, competitive analysis, etc.]

### Revision History
| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | [Date] | [Name] | Initial draft |
```

### Step 9: Save and Organize

1. **Create Directory Structure**:
   ```
   docs/
   └── prd/
       ├── main.md (generated PRD)
       ├── user-personas.md (detailed personas)
       ├── user-stories.md (all user stories)
       └── technical-spec.md (technical details)
   ```

2. **Save Generated PRD**:
   - Save main PRD to `docs/prd/main.md`
   - Save supplementary documents
   - Create a version identifier

3. **Provide Next Steps**:
   ```
   ✅ PRD Generated Successfully!

   📄 Documents Created:
     - docs/prd/main.md (4,523 words)
     - docs/prd/user-personas.md (856 words)
     - docs/prd/user-stories.md (1,234 words)
     - docs/prd/technical-spec.md (967 words)

   📋 Next Steps:
     1. Review and refine the PRD
     2. Share with stakeholders for feedback
     3. Run /plan-development-sprints to break into sprints
     4. Run /create-specifications to create GitHub issues

   💡 Tips:
     - PRDs are living documents - update as you learn
     - Get feedback from users early and often
     - Revisit success metrics quarterly
   ```

## Examples

### Example 1: Standard PRD
```
/create-product-requirements
```
Interactive session to create comprehensive PRD.

### Example 2: Feature PRD
```
/create-product-requirements --template feature
```
Focused PRD for a single feature addition.

### Example 3: Minimal PRD
```
/create-product-requirements --template minimal
```
Lightweight requirements document for simple projects.

## Templates

### Standard Template
Full-featured PRD with all sections (as shown above).

### Feature Template
Simplified PRD focused on a single feature:
- Problem statement
- Feature description
- User stories
- Acceptance criteria
- Technical requirements

### Minimal Template
Quick requirements capture:
- What we're building
- Why we're building it
- Key features
- Success metrics
- Timeline

### Technical Template
Developer-focused specification:
- Architecture
- API specifications
- Data models
- Integration requirements
- Performance requirements

## Best Practices

I'll guide you through PRD best practices:

1. **Be Specific**: Vague requirements lead to vague products
2. **Focus on Why**: Explain the user value, not just what to build
3. **Prioritize Ruthlessly**: Not everything can be P0
4. **Define Success**: Metrics must be specific and measurable
5. **Plan for Change**: PRDs evolve based on learning

## Error Handling

**Common Issues**:
- **Incomplete Answers**: I'll prompt for clarification
- **Conflicting Requirements**: I'll ask you to prioritize
- **Unclear Success Metrics**: I'll help define measurable KPIs
- **Missing User Context**: I'll guide you through persona creation
- **Scope Too Large**: I'll help break into phases

## Configuration

Configure PRD generation in `.claude/config/bumba-sandbox-config.json`:
- `prd.defaultTemplate`: Default template to use
- `prd.includePersonas`: Include detailed persona sections
- `prd.includeRisks`: Include risks section
- `prd.wordTarget`: Target word count for PRD

## Notes

- PRD creation is interactive - answer questions at your own pace
- You can skip questions and fill them in later
- PRDs should be reviewed and refined with stakeholders
- Use `/plan-development-sprints` to turn PRD into actionable work
- Use `/create-specifications` to create GitHub issues from PRD
- PRDs are living documents - update them as you learn
