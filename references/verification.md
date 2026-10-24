# Verification, Premise Challenges, and Acceptance

The manager holds one decision gate per package. The goal is to judge the output and integrate emergent discoveries, not to replay the worker's process. Rigor is set before launch (Gate 4).

## Order of checks (cheapest first, by level)

| Check | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| Envelope & Epistemic signals: check `status`, `evidence`, `confidence`, `assumptions_challenged`, `open_questions` | yes | yes | yes | yes |
| Deterministic: relevant tests, lint or type check, grep for the claimed change, schema | skip | yes | yes | yes |
| Scope and attribution for write tasks: bounded diff against pre-launch baseline, flag files outside `--may-write` | n/a | yes | yes | yes |
| Judgment: read the changed hunks and `handoff_notes` | skip | skip | yes | yes |
| Independent cross-family reviewer, or first-hand verification of the key claim | skip | skip | skip | yes |

Stop checking as soon as the level's requirements are met.

## Handling Epistemic Signals (`assumptions_challenged` & `open_questions`)
Smart workers do more than execute blindly—they surface flaws in your plan:
1. **When `assumptions_challenged` is non-empty:** Read it before judging `status`. If the worker proved that a premise in your brief was false (e.g. "the bug is not in the LR schedule; RNG state leaks during model build"), **accept the discovery**, update your plan, and record an `accept` verdict if the worker's investigation was sound. Never penalize a worker for disproving a bad premise with evidence.
2. **When `handoff_notes` or deliverables exist:** Pass the artifact path directly to the next worker via `--context-file` instead of re-summarizing it yourself.
3. **When `confidence` is `"low"`:** Even if `status` is `"done"`, treat low confidence on a high-risk claim as a trigger for a cheap empirical check or a second opinion.

## Verdicts

| Verdict | When | Action |
|---|---|---|
| **Accept** | Criteria met (or premise validly challenged with evidence) | Integrate; record `accept` in the ledger |
| **Targeted revision** | A specific gap is fixable within scope | Resume the same worker (`--resume` or `SendMessage`) with only the delta. Uses attempt 2. |
| **Escalate model or channel** | Revision failed, or task exceeds tier's reasoning depth | Rerun with a higher tier or different model family, passing prior findings via `--context-file`. Uses attempt 3. |
| **Rollback** | A write broke tests or violated `--may-write` | Revert only the worker-attributable changes, then re-plan |
| **Take over** | Attempt budget (3) is spent, or context lives only with you | The manager finishes the work |

**Failure classes** (`meta.json` `failure` field):
- `invalid_result` or `no_result` → One format-only retry (note: `result.schema.json` v3 allows extra keys and optional epistemic fields, minimizing false schema failures).
- `timeout` → Inspect partial effects first; resume with narrower scope or re-split.
- `permission` → Fix the gate decision or ask the user; do not retry blindly.
- `auth` → Stop and report to the user.
- `model_or_config` → Switch to `fallback_model` once.
- `process_error` → Read log tail; retry once only if transient.

## Earned autonomy (track record)
After judging a package, record it once:
```bash
python <skill>/scripts/agent_run.py verdict <run-dir> accept|revise|escalate|rollback|takeover [--note "..."]
python <skill>/scripts/agent_run.py verdict - accept --agent claude --task-type lookup --tier fast
python <skill>/scripts/agent_run.py stats [--task-type T]
```
- **Automatic canonicalization:** Even if a run used a custom label (or `--name review-p1-model-core`) or omitted `--tier`, `agent_run.py` and `ao_common.py` automatically map the task to its canonical type (`review`) and infer the tier from the model slug so the ledger always learns accurately.
- ** Bounded git attribution:** `agent_run.py` uses bounded untracked directory expansion (`MAX_UNTRACKED_EXPAND=2000`) and fast `stat` signatures on large files (`>4MB`), preventing false million-file violation explosions when background training jobs write to untracked dataset/checkpoint folders.
