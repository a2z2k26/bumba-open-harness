# Questions the Execution Environment Will Ask

This is the reference checklist used by the `/handoff-prepare` skill to validate spec completeness. Each question represents a decision that the execution agent will need to make — ideally answered by the specs, delegated with constraints, or explicitly flagged.

## Category 1: Data & API Contracts (8 questions)

1. What's the exact shape of this API response?
2. What are the field types and constraints? (cents vs dollars, integer vs float, currency codes)
3. What's the pagination model? (cursor, offset, infinite scroll, page numbers)
4. What are the sort/filter options?
5. What's the relationship between these entities? (many-to-many, soft delete, cascade)
6. What's the max payload size / list length?
7. Are there computed/derived fields?
8. What's the real-time requirement? (websockets, SSE, polling)

## Category 2: Authentication & Authorization (6 questions)

9. Who can see this? (admin, owner, team member, public)
10. Who can edit this?
11. What happens when unauthorized? (403, redirect, hide element)
12. Is this a public or authenticated route?
13. Multi-tenancy model? (isolated teams, multiple orgs per user)
14. What's the session model? (JWT, session cookies, refresh flow)

## Category 3: State & Edge Cases (10 questions)

15. What's the empty state?
16. What's the loading state? (skeleton, spinner, shimmer, per-component vs full-page)
17. What's the error state? (toast, inline, retry button, fallback content)
18. What happens on partial failure? (3 of 5 APIs succeed)
19. What's the offline behavior? (cache, queue, stale banner)
20. What happens at 0, 1, 2, many, max?
21. What's the character limit?
22. What happens on duplicate submission? (idempotent, debounced, disabled)
23. What's the delete behavior? (soft, hard, confirmation, undo period)
24. What happens to dependent data on delete? (cascade, orphan, block)

## Category 4: Frontend Implementation (6 questions)

25. What's the routing structure?
26. Client-side or server-side rendering for this page?
27. What component library / design system?
28. What's the form validation approach? (client-only, server, real-time, on-submit)
29. Optimistic or pessimistic updates?
30. How does responsive layout work for THIS component?

## Category 5: Integration & Third-Party (6 questions)

31. Which payment provider and what flow? (Checkout, embedded, portal)
32. What email service and what templates?
33. What file storage and upload flow? (S3, R2, presigned, direct, size limit)
34. What analytics events to track?
35. What OAuth providers?
36. What notification channels? (in-app, email, push, webhook)

## Category 6: Performance & Scale (5 questions)

37. What's the expected data volume?
38. What needs to be indexed? (full-text, fuzzy, which fields)
39. What can be cached and for how long?
40. What's the acceptable latency?
41. Do we need rate limiting on this endpoint?

## Category 7: DevOps & Deployment (5 questions)

42. What's the target infrastructure?
43. What database?
44. What's the migration strategy?
45. Feature flags needed?
46. What's the CI/CD expectation?

## Category 8: Business Logic (6 questions)

47. What's the billing model? (per-seat, usage, flat, tiered, freemium)
48. What are the plan limits?
49. What's the trial flow? (duration, what happens after)
50. What's the invitation flow end-to-end?
51. What's the audit trail requirement?
52. What are the compliance requirements? (GDPR, data export, SOC 2)

---

## Sensible Defaults for Delegation

When a question is not answered by specs, use these defaults:

| Question | Default |
|----------|---------|
| Pagination | Cursor-based, 20 items per page |
| Auth model | JWT with refresh tokens |
| Session duration | 7 days, refresh on activity |
| Routes | Authenticated by default unless spec says "public" |
| Empty state | Illustrated placeholder with CTA |
| Loading state | Skeleton loaders matching content shape |
| Error state | Inline error with retry button |
| Form validation | Client-side zod + server revalidation |
| Updates | Optimistic for toggles/likes, pessimistic for creates/deletes |
| Delete behavior | Soft delete with 30-day recovery |
| Payment provider | Stripe Checkout Session |
| File storage | S3-compatible with presigned URLs, 10MB limit |
| Analytics | Track CTA clicks + page views minimum |
| Database | PostgreSQL |
| ORM | Prisma (Node) / SQLAlchemy (Python) |
| Data volume | Design for 10K-100K records per entity |
| Caching | GET responses cached 60s, invalidate on mutation |
| API latency | P95 < 500ms |
| Page load | P95 < 3s |
| Rate limiting | 100 req/min authenticated, 20 req/min unauthenticated |
| Migrations | ORM migration tool (Prisma Migrate / Alembic) |
