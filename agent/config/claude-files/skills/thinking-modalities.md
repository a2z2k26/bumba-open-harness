---
name: thinking-modalities
description: Defines 12 cognitive modalities for Strategy Board deliberation. The CEO uses this to select and inject a specific thinking mode each round, producing diverse perspectives.
---

# Thinking Modalities

You have 12 cognitive modalities available. Each round of deliberation, select the most appropriate modality and inject its instruction to all board members. Members apply the modality through the lens of their own role and perspective.

## The 12 Modalities

### 1. DIVERGENT
**Instruction to members:** "Generate as many possibilities as you can. Quantity over quality. No filtering, no judgment. Every idea gets written down, no matter how wild."
**When to use:** Early rounds. When you need raw material. When the board is converging too quickly.
**What it surfaces:** Options the board hasn't considered. Non-obvious connections.

### 2. CONVERGENT
**Instruction to members:** "Narrow to the strongest 2-3 options. Apply your toughest criteria. What survives your scrutiny?"
**When to use:** After divergent rounds. When there are too many options on the table. Late in deliberation.
**What it surfaces:** The options that actually hold up. Clear winners.

### 3. LATERAL
**Instruction to members:** "What adjacent domain has solved this differently? Import a solution from an unexpected place. What would [a hospital / a game studio / a logistics company / a central bank] do?"
**When to use:** When the board is stuck. When all options feel mediocre. When you need reframing.
**What it surfaces:** Novel framings. Cross-domain solutions. Pattern transfers.

### 4. SYSTEMIC
**Instruction to members:** "Map the full system. What are the feedback loops? What are the dependencies? What are the second-order and third-order effects? Draw the system, don't just describe a feature."
**When to use:** Complex decisions with many moving parts. Infrastructure decisions. Pricing model changes.
**What it surfaces:** Hidden dependencies. Unintended consequences. Feedback loops that amplify or dampen.

### 5. ASSOCIATIVE
**Instruction to members:** "What does this remind you of? What patterns from other contexts, other products, other eras apply here? Think by analogy."
**When to use:** When you need fresh perspective. When the team is too deep in the details.
**What it surfaces:** Historical precedents. Analogous situations. Pattern recognition.

### 6. CRITICAL
**Instruction to members:** "What's wrong with the best idea on the table? Find the flaws, the gaps, the unstated assumptions. Be precise -- name the exact failure mode."
**When to use:** When a frontrunner has emerged and needs stress-testing. Before final positions.
**What it surfaces:** Weaknesses. Hidden assumptions. Failure modes. Blind spots.

### 7. ANALOGICAL
**Instruction to members:** "Find a parallel from another industry, era, or domain. What can we learn from how [company/industry] handled a similar situation? Map the analogy precisely -- where does it hold, where does it break?"
**When to use:** When facing a decision that feels unprecedented. When you need historical grounding.
**What it surfaces:** Lessons from history. Validated patterns. Where analogies break down.

### 8. ABDUCTIVE
**Instruction to members:** "Given what we've observed -- these market signals, this user behavior, these competitive moves -- what is the best explanation? What must be true for this to make sense?"
**When to use:** When you have data but no clear interpretation. Hypothesis generation.
**What it surfaces:** Root causes. Hidden explanations. Hypotheses worth testing.

### 9. FIRST PRINCIPLES
**Instruction to members:** "Strip away every assumption. What is fundamentally, provably true here? Rebuild your argument from atoms, not from convention."
**When to use:** When the discussion is stuck in incremental thinking. When assumptions need challenging.
**What it surfaces:** Fundamental truths. Radical simplifications. Assumptions exposed.

### 10. SECOND-ORDER
**Instruction to members:** "If this decision works as intended, then what happens next? What's the consequence of the consequence? Think 2-3 moves ahead."
**When to use:** Before final decisions. When evaluating strategies with long timelines.
**What it surfaces:** Downstream effects. Strategic positioning. Long-term consequences.

### 11. JANUSIAN
**Instruction to members:** "Hold two contradictory ideas simultaneously. [Idea A] AND [Idea B] are both true. What emerges from the tension? Don't resolve the contradiction -- sit in it."
**When to use:** When the board has polarized. When you need creative synthesis. When obvious compromises feel weak.
**What it surfaces:** Creative breakthroughs. Both/and solutions. Paradox resolution.

### 12. METACOGNITIVE
**Instruction to members:** "Step back from the content entirely. How are we thinking about this problem? What frames are we trapped in? What question should we be asking instead of the one we're debating?"
**When to use:** Late rounds. When the deliberation feels circular. When you suspect the wrong question is being answered.
**What it surfaces:** Frame shifts. Better questions. Process awareness.

## Modality Selection Logic

As CEO, select modalities based on the deliberation state:

**Opening rounds (1-2):** Start with DIVERGENT or FIRST PRINCIPLES to generate raw material and challenge assumptions. If the brief is about a new idea, start with FIRST PRINCIPLES. If it's about evaluating options, start with DIVERGENT.

**Middle rounds (3-4):** Use SYSTEMIC, LATERAL, or ASSOCIATIVE to deepen understanding. If there's strong disagreement, try JANUSIAN. If the board is stuck, try LATERAL.

**Closing rounds (5-6):** Use CRITICAL to stress-test the frontrunner, then CONVERGENT to narrow to a decision. If the discussion feels circular, use METACOGNITIVE to reframe.

**Adaptive rules:**
- If 4+ members agree too quickly → inject CONTRARIAN or JANUSIAN
- If discussion is scattered → inject CONVERGENT or SYSTEMIC
- If all options feel incremental → inject MOONSHOT-flavored LATERAL
- If facing a novel situation → inject ABDUCTIVE or ANALOGICAL
- If about to make a final decision → always run CRITICAL + SECOND-ORDER first

**Never repeat the same modality in consecutive rounds** unless the min_rounds constraint forces it.
