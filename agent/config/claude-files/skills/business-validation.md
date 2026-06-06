---
name: business-validation
description: Activates when the Strategy Board evaluates a new business idea. Adds market sizing, unit economics, pre-mortem, and validation experiment design to the deliberation.
---

# Business Validation Mode

This mode activates when the CEO detects that a board brief concerns a new business idea, product concept, or market entry decision. It overlays additional validation frameworks onto the standard deliberation process.

## Detection Triggers

Activate this mode when the brief contains language about:
- New product or feature ideas
- Market entry or expansion
- Revenue model design
- "Should we build..." decisions
- Business model evaluation
- Startup concepts or product-market fit questions

## Validation Overlay

When this mode is active, the CEO should ensure the following are covered across the deliberation rounds:

### 1. Market Sizing (delegate to Revenue + Compounder)
- **TAM** (Total Addressable Market): The entire market if you captured 100%
- **SAM** (Serviceable Addressable Market): The segment you can realistically reach
- **SOM** (Serviceable Obtainable Market): What you can capture in 1-2 years
- Even rough estimates are valuable. State assumptions explicitly.

### 2. Unit Economics (delegate to Revenue)
- **Price point:** What would customers pay? (Use comparable products as anchors)
- **CAC estimate:** How much to acquire a customer? (Channel-dependent)
- **LTV estimate:** Revenue per customer over lifetime (Churn-dependent)
- **LTV:CAC ratio:** Must be > 3:1 for SaaS, > 2:1 for consumer
- **Contribution margin:** Revenue minus variable costs per unit

### 3. Competitive Moat (delegate to Compounder)
- What prevents competitors from copying this in 6 months?
- Does the advantage compound with scale/time/data?
- Is this a feature (copyable) or a platform (defensible)?

### 4. Pre-Mortem (delegate to Contrarian)
"It's one year later and this failed. Write the post-mortem."
- What went wrong?
- What assumptions turned out to be false?
- What did we underestimate?
- What competitor move killed us?

### 5. Cheapest Experiment (delegate to Technical Architect + Product Strategist)
"What is the absolute minimum viable test of the core assumption?"
- What's the one thing that must be true for this to work?
- How can we test it in < 2 weeks with < $500?
- What would prove us wrong?
- What would prove us right enough to invest more?

### 6. Moonshot Version (delegate to Moonshot)
"If this works at 10x the scale, what does it become?"
- Does the idea get more interesting at scale, or less?
- What's the platform play?
- What adjacencies open up?

## Business Validation Memo Additions

When business validation mode is active, the memo should include these additional sections:

```
## Market Analysis
### TAM / SAM / SOM
[Estimates with stated assumptions]

### Unit Economics
[Price, CAC, LTV, LTV:CAC, margin]

## Validation Plan
### Core Assumption
[The one thing that must be true]

### Cheapest Experiment
[What to test, how, timeline, cost, success criteria]

### Pre-Mortem Summary
[Top 3 failure scenarios]

## Revenue Model Sketch
[How money flows: pricing model, revenue streams, payment timeline]

## Go / No-Go Recommendation
[GO, CONDITIONAL GO (with conditions), or NO-GO with reasoning]
```
