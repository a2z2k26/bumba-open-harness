---
type: read-only
domain: design
access: design-department
---

# Design Philosophy

## Core Principle

Bold, distinctive design. Generic AI aesthetics are the enemy.

## Standards

- **Immutability:** Always create new objects, never mutate existing ones.
- **Specificity:** Use specific types. Never `any`. Validate at system boundaries.
- **Simplicity:** Minimum complexity that solves the problem. Three similar lines of code is better than a premature abstraction.
- **Accessibility:** Accessible by default. Not an afterthought.

## Visual Direction

- Distinctive over generic
- Functional over decorative
- Consistent system over one-off solutions
- Dark mode as default consideration

## Component Philosophy

Prefer editing existing files to creating new ones. Only create new components when clearly required. Avoid feature flags and backwards-compatibility shims — just change the code.
