# Huddle Protocol (structured consult & dialectical synthesis for hard problems)

When a problem is hard, strong teams consult each other briefly before deciding. Research on multi-agent reasoning shows four things:
- **Epistemic diversity** (different model families and cognitive lenses) reduces blind spots.
- **Unstructured multi-round debate** drifts off the problem and converges on confident wrong answers through social conformity.
- **Pure victory/concession debate** misses emergent third options (**Dialectical Synthesis**).
- **Empirical probes beat rhetoric:** whenever a disagreement rests on a testable fact, a 2-minute code spike or measurement settles what 10 rounds of LLM argument cannot.

So a huddle is **independent first**, **empirical on testable cruxes**, **co-creative on design trade-offs (Synthesis Option C)**, and ends with a decision owner who decides on evidence.

## Triggers (need at least one)
- A decision that is hard to reverse (Type 1): architecture, data migration, public API, experiment design that spends heavy compute.
- Conflicting evidence, or two credible options with no clear winner.
- A worker escalation already failed once, or a worker challenged a core premise (`assumptions_challenged`).
- A cross-cutting choice that affects several packages or modules.
- High ambiguity combined with high stakes.

Do not call one for routine tasks, for questions a single lookup or micro-spike answers, or to postpone a decision you can already make.

## Ambition guard (for plans and critiques)
Candor is not timidity, and "not feasible" is a claim that needs support. Every "not feasible" or "too risky" must name either:
1. a hard constraint with evidence (a limit, a measurement, a documented restriction), or
2. a cheap spike that could prove it wrong, with what result would settle it.
Otherwise it is a worry, not an objection: record it as a risk and proceed.

## Roster
2–3 panelists. **Epistemic diversity beats count.** Give each one a distinct lens and, where possible, a **different model family** (for example OpenAI `gpt-6-astra` + Google `gemini-4-argon-high` + Anthropic `claude-opus-5-5-high` / `opus`).

| Lens | Core Question |
|---|---|
| **Architect** | What is the cleanest structure? How can we synthesize competing requirements into a simpler design? |
| **Red team / skeptic** | How does this fail? What hidden premise is everyone assuming? |
| **Implementer** | What is the concrete effort, blast radius, and hidden edge-case work? |
| **Domain expert** | What does the scientific/mathematical field or data actually say? (e.g. ML methodology, statistics) |
| **User advocate** | Does this solve the user's real underlying goal without over-engineering? |

## Steps

### 1. Problem Memo (manager, at most 1 page)
Frame the problem without biasing panelists toward your favorite answer:
```markdown
Decision needed: <one sentence>
Context and verified facts: <bullets with file:line or measured data>
Constraints: <time, compute, compatibility, user requirements>
Initial options on the table: A) ... B) ... (panelists are expected to challenge premises or invent Option C)
What signal would settle the decision: <empirical test or criterion>
```

### 2. Independent round (in parallel, blind)
Each panelist receives the memo, its lens (`roles.md`), any key upstream artifact (`--context-file`), and this instruction:
```markdown
Answer independently. Do not assume other reviewers exist.
You are explicitly invited to challenge the premises of the memo and to propose a synthesized Option C if the listed options have trade-offs that can be transcended.
Return, in 300-800 tokens, the result envelope JSON:
- status: "done", or "blocked" if the memo lacks a critical fact
- summary: recommendation (Option A, B, or a new synthesized Option C) + why
- confidence: "low" | "med" | "high"
- deliverables: []
- evidence: top 3 reasons, each backed by concrete evidence or an explicit assumption
- assumptions_challenged: any flaw or false dichotomy in the manager's framing
- risks: strongest argument against your own recommendation; what evidence would change your mind
- next_action: the single cheapest empirical check (micro-spike, test, or measurement) that would settle the question
```

### 3. Crux Map & Empirical Spike Gate (manager)
Build a short crux table:

| Point of contention | Agree / Disagree | Crux (fact vs. design trade-off) | Resolution path |
|---|---|---|---|

**The Empirical Spike Gate (mandatory before Round 2):**
- If a crux is a **testable fact** (e.g., "does library X support Y?", "does this permute RNG state?", "is query Z slow?"), **DO NOT run a debate round on it.** Run a 2-minute micro-spike, command, or scout to measure the truth directly. Often, that single measurement resolves the entire huddle.

### 4. Dialectical Synthesis / Cross-examination (optional, one round, unresolved trade-offs only)
If genuine design trade-offs remain after factual cruxes are tested, send panelists the anonymized opposing arguments and any spike results:
```markdown
Here are the counterarguments and empirical findings on <crux>.
1. Where the evidence disproves your earlier point, concede it explicitly.
2. Where a real trade-off remains, do not merely defend your turf: propose how to synthesize the best of both positions (Option C) or state the exact condition under which your option wins. 200-400 tokens.
```

### 5. Decide and commit (manager)
```markdown
Decision: <chosen or synthesized option>
Why: <2-3 evidence-based reasons>
Strongest dissent: <one line>
Reversal trigger: <observable signal during implementation that would make us revisit>
Owner / next packages: <who does what, and what goes into Shared Blackboard>
```
Then commit. For a Type 1 decision the user owns, present this record as a recommendation instead of deciding unilaterally.

## Budget & Platform Notes
- Give panelists the memo and specific `--context-file` paths instead of asking them to explore the whole repo from scratch.
- Maximum 2 rounds. No open-ended "discuss until consensus".
- Use `route.py --task-type huddle` to get a cross-family panel.
