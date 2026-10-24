# Roles

**Roles are lenses, not blinders.** The listed angles are a floor, not a fence: a worker must examine the core angles of its role, **and also follow whatever else its intelligence and the evidence say matters**, reporting emergent findings in `assumptions_challenged`, `open_questions`, or `handoff_notes`.

Every `guided` or `exploratory` work order names one role (`tight` briefs for mechanical lookups or edits may omit the full block). Name the role to establish an epistemic viewpoint and accountability, not as a theatrical persona:
- "You are a world-class expert" adds nothing.
- A concrete lens with examination angles makes the worker look where it otherwise would not, while **Adjacent owners** prevents parallel workers from doing duplicate writes.

## How to write the Role block
```markdown
## Role
<Role name>: <one-line mandate>
Stand for: <the interest you represent, e.g. correctness of results, the end user, security>
Examine (floor, not ceiling): <4-6 angles from the checklist below, picked for this package>
Adjacent owners (report, don't duplicate): <concerns owned by another worker or the manager; if you spot a cross-boundary defect, flag it in open_questions or handoff_notes>
When in doubt: <which way to lean, e.g. challenge premises with evidence, report rather than silently fix out of scope>
```
Guidelines:
- **No cognitive tunneling:** Never interpret "Adjacent owners" (formerly "Not your job") as "close your eyes to bugs outside your file". If a Builder notices a broken caller interface or a flawed test hypothesis while working, it must record that in `assumptions_challenged` or `handoff_notes`.
- One accountable mandate per worker. Pick the 4–6 checklist angles that matter for this package.
- A reviewer's role must differ from the builder's, so the review adds a genuinely different angle.

## Catalog

| Role | Mandate | Examine (floor, pick 4–6) | Adjacent owners (flag, don't duplicate) |
|---|---|---|---|
| **Scout** | Find facts and map territory fast | Where it is defined or used; authoritative source; versions; what is absent; exact file:line or URL; surprising couplings | Writing fixes (pass leads in `handoff_notes`) |
| **Researcher / Explorer** | Answer open questions and surface unknown unknowns | Source authority and date; conflicting evidence; method behind each claim; sample size and conditions; what the manager failed to ask | Production code changes |
| **Architect** | Choose a structure that lasts and evolves cleanly | Interfaces and contracts; coupling; data flow; failure modes; migration and rollback path; cost of change later; synthesis of competing constraints | Micro-style; routine boilerplate |
| **Builder** | Deliver a working, verified change within write scope | Definition of Done; edge cases; existing conventions; tests for the change; interface assumptions; runs its own tests | Unapproved cross-module redesign (propose in `assumptions_challenged`) |
| **Reviewer** | Find real defects and premise flaws before they ship | Correctness against Definition of Done; edge and error paths; regressions; test adequacy; readability of the diff; scope violations | Rewriting the feature from scratch; pure style nits |
| **Red team / skeptic** | Break the plan, hypothesis, or claim | Hidden assumptions; worst-case inputs; failure cascades; abuse and security; what happens when a dependency is wrong; "what would make this false" | Building the full implementation |
| **Security reviewer** | Protect secrets, data, and trust boundaries | Secrets in code or logs; injection; authz and authn; unsafe defaults; supply chain; data exposure; least privilege | Unrelated performance tuning |
| **Tester / QA** | Prove it works, or construct the minimal reproducer that breaks it | Reproduction steps; boundary values; negative cases; flaky conditions; environment differences; test-to-requirement mapping | Silently patching production code to make a test pass |
| **Performance analyst** | Keep cost, memory, and latency within budget | Hot paths; complexity; memory; I/O and network calls; batch sizes; measured numbers (never guesses) | Unrelated feature changes |
| **Domain expert** (e.g. ML methodologist, statistician) | Keep the work scientifically and mathematically valid | Method validity; data/RNG leakage; baselines and ablations; metrics chosen; seeds, variance and significance; comparison with literature | UI polish; unrelated infra |
| **Data steward** | Protect data integrity and lineage | Schema and units; splits and leakage; provenance; missing or duplicate values; irreversible operations | Model architecture |
| **Integrator** (usually the manager) | Synthesize parts into a coherent whole | Interface mismatches; conflicting implicit decisions; full test suite; attributable changes; final Definition of Done | Re-doing workers' packages from scratch |
| **User advocate** | Solve the user's real underlying goal | Does the output answer the actual intent; usability; clarity of the report; the missing "so what" | Low-level implementation ceremony |
| **Editor** (documents, reports) | Make it accurate, rigorous, and clear for its audience | Claims match evidence; numbers and units; terminology consistency; structure (conclusion first); audience fit | Altering empirical findings |

## Pairing rules
- **Builder + Reviewer:** the reviewer takes Reviewer, Domain expert, Security reviewer, or Tester—never Builder. Pass the builder's artifact/diff directly via `--context-file` so the reviewer sees full fidelity.
- **Scout / Explorer fan-out:** scouts take Scout or Researcher with disjoint primary territories, but are encouraged to flag cross-cutting discoveries in `open_questions`.
- **Huddle:** panelists take distinct lenses (e.g. Architect + Red team + Domain expert) and aim for **dialectical synthesis (Option C)** when options conflict.
- **Competing hypotheses:** each investigator is a Researcher bound to test one hypothesis AND falsify the others with empirical probes.
