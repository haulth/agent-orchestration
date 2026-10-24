# Work Order (Brief) and Budget Contract

A worker knows only what you write here and the upstream artifacts you point it to. It starts without your conversation history (unless it is a fork) and without knowledge of the available skills. Brief it like a capable, intelligent colleague who just walked in. Keep it tight, because everything in the brief costs tokens on every one of the worker's turns.

## Three Brief Modes (match ceremony to cognitive need)

Over-specifying an exploratory problem is just as harmful as under-specifying a mechanical edit. Pick the mode that fits the package (`route.py` suggests one in `brief_mode`):

| Mode | When to use | Philosophy |
|---|---|---|
| **1. `tight`** | Lookups, mechanical edits, well-specified tests, small fixes | Fast & surgical. 4 lines: **Intent**, **Definition of Done**, **Scope / May write**, **Output**. Skip heavy role blocks. |
| **2. `guided`** (default) | Feature implementation, focused analysis, code review, docs | Balanced. Gives a clear **Role lens**, **Intent**, **Definition of Done**, **Known context**, **Scope**, and **Finish line**. |
| **3. `exploratory`** | Root-cause debugging, open-ended research, architecture design, critiques | Unleash intelligence. State **Questions to answer / Hypotheses**, **Known facts**, and **Safety boundaries**. Do NOT lock the worker into a rigid step list or narrow file tunnel; explicitly invite **Premise Challenge**. |

## Premise Challenge & Emergent Discovery (all modes)
Workers are never blind order-takers:
- **Right to challenge premises:** If evidence contradicts an assumption in your brief, or shows that solving the literal request would miss the real root cause, the worker MUST report that in `assumptions_challenged` (and may pull `stopped` / andon if continuing would waste budget or break things).
- **Follow the scent (read-only):** Even when a brief names primary files in `Scope`, a worker investigating a bug or design question may read adjacent callers, configs, or interfaces to verify its claims, and report cross-boundary discoveries in `open_questions` or `handoff_notes`. Write boundaries (`May write`) remain strict.

## Shared Blackboard & Direct Handoffs (`--context-file`)
Avoid lossy manager relays. When Worker B builds on, reviews, or tests Worker A's work:
- Have Worker A write its detailed plan, findings, or interface spec to a file (or use its `result.json` / artifact path).
- Pass that path directly to Worker B via `agent_run.py run ... --context-file <path>` (or list it under **Upstream artifacts** in the brief).
- Worker B reads Worker A's exact words and evidence first-hand, preserving nuance while keeping the manager's context clean.

---

## Templates

### Mode 1: `tight` (minimal overhead, high speed)
```markdown
## Intent & Done
<What to achieve and why, in 1-2 sentences. Bullet the exact checkable criteria.>

## Context & Upstream Artifacts
- <facts, file:line, or upstream artifact paths to read directly>

## Scope & Authority
- Read/search: <paths> | May write: <exact files/dirs, or "nothing">
- Authority: <propose-only | execute-within-scope> | Budget: up to <N> calls, <M> min.

## Output
Return the result envelope JSON (`assets/result.schema.json`).
```

### Mode 2: `guided` (standard work order)
```markdown
## Role
<Role name>: <one-line mandate>
Stand for: <interest you represent>
Primary angles (floor, not a ceiling): <4-6 angles relevant to this package>
Adjacent owners (coordinate, don't duplicate): <what another worker owns; report cross-cutting issues in open_questions/handoff_notes>
When in doubt: <which way to lean>

## Intent
<Outcome and why it matters. What success enables. 2-4 sentences.>

## Definition of Done
- <checkable criterion 1>
- <checkable criterion 2>

## Known context & Upstream artifacts
- <established facts, with paths or file:line>
- <already ruled out: ...>
- <upstream artifacts to read directly: ...>

## Latitude & Premise Challenge
<Assumptions the worker is invited to test or challenge, and decisions it may make on its own. If a premise in this brief is contradicted by code or data, record it in `assumptions_challenged` and adjust your investigation.>

## Finish line
<What "far enough" means: the smallest result that satisfies the Definition of Done. Name what NOT to polish.>

## Scope & Authority
- Focus area: <areas, questions, files>
- May write: <exact files or directories, or "nothing">
- Authority: <propose-only | execute-within-scope | ask-before-exceeding>
- Required skill: <skill name + path, or "none">
- Budget: up to <N> tool calls, <R> revision round(s), ~20% reserved for self-check.

## Stop conditions
Stop and report when: (1) Definition of Done is met; (2) 2 consecutive investigative attempts make no progress; (3) a blocker needs a manager decision; (4) budget is exhausted (`partial`); (5) anomaly/andon (`stopped`): a binding constraint is contradicted, the premise is fundamentally flawed, or continuing would be unsafe.

## Output
Return the result envelope (`status`, `summary`, `deliverables`, `evidence`, `risks`, `next_action`, plus optional `confidence`, `assumptions_challenged`, `open_questions`, `handoff_notes`). Summary first, 200-500 tokens (hard cap ~2,000); put large content in <unique output path>.
```

### Mode 3: `exploratory` (open-ended research, hard debugging, architecture)
```markdown
## Role & Lens
<Role name>: <mandate and epistemic lens>

## Core Problem & Why It Matters
<The phenomenon, bug, or design question we are trying to understand, and what decision depends on it.>

## Questions to Answer / Hypotheses to Test
1. <Primary question or hypothesis>
2. <Alternative hypothesis or open dimension>
3. What did the manager fail to ask that actually governs this problem?

## Known Facts & Ruled-Out Leads
- <facts and measurements so far>
- <what was already tried or ruled out>

## Exploration Freedom & Boundaries
- You have full read-only freedom to follow evidence across the codebase/sources wherever the trail leads.
- Actively test the premises of this brief. Record any falsified assumption in `assumptions_challenged` and any emergent insight in `open_questions`.
- May write: <"nothing", or a scratch/artifact path in `.orch/` for notes/spikes>
- Budget: up to <N> tool calls, <M> min.

## Output
Return the result envelope JSON. Include `confidence` ("low"|"med"|"high"), `assumptions_challenged`, `open_questions`, and `handoff_notes` for the next phase.
```

---

## Sizing the budget

| Package type | Brief mode | Tool calls | Revisions | Wall clock |
|---|---|---|---|---|
| Lookup or single question | `tight` | 3–10 | 0 | 5 min |
| Mechanical edit or unit test | `tight` | 8–15 | 0–1 | 5–10 min |
| Focused research or analysis | `guided` / `exploratory` | 10–15 | 0–1 | 10–15 min |
| Implementation in 1–3 files | `guided` | 15–30 | 1 | 15–30 min |
| Review of a diff | `guided` | 5–15 | 0 | 10 min |
| Hard debugging or architecture | `exploratory` | 15–25 | 0–1 | 15–20 min |
| Huddle panelist | `exploratory` | 0–10 | 0 | 5–10 min |

**Advisory vs enforced limits:**
- **Enforced:** wall-clock time and the result schema (`scripts/agent_run.py` kills the process tree on timeout); project boundary and write scope (`agent_run.py` refuses `$HOME` and drive roots, and reports any file changed outside `--may-write`); turn count (`maxTurns` on Claude agent definitions).
- **Advisory:** tool-call counts, token budgets and revision rounds live in the brief. The manager checks actual usage afterwards (`meta.json` tokens) and records any overrun.

**Attempt budget per package (shared across revisions, model changes and resumes):** at most 3 attempts by default (1 original + 1 targeted revision + 1 escalation), unless each attempt visibly closes the gap on an exploratory problem.
