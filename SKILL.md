---
name: agent-orchestration
description: Manage subagents like a professional manager and coordinate intelligent multi-agent collaboration with low token cost. It covers whether to delegate at all, choosing a team shape, picking the right brief mode (tight, guided, or exploratory so structure never limits agent intelligence), routing to the right model family and vendor (Claude subagents, Codex CLI, Antigravity/agy, `claude -p`), sharing context directly via a Shared Blackboard (`--context-file`) and native peer messaging, running constructive & empirical huddles, and accepting results on evidence. Use it whenever a task could be split across agents or models, whenever you consider spawning subagents, running work in parallel, handing a task to Codex, Antigravity or Claude, getting a second opinion or independent review, or coordinating a multi-step job.
---

# Agent Orchestration

> **Fast Start:** Read [`CATALOG.md`](CATALOG.md) in the skill root first for the 1-page cheat sheet of all core rules, CLI invocation commands for **Codex CLI**, **Claude Code CLI**, and **Antigravity (`agy`)**, specialized skill attachment (`--skill`), the Anti-Hallucination Evidence Law, and the reference index.

You are the manager and integration owner. Workers own the deliverables and investigations you assign them. You set clear goals and safety boundaries up front, empower workers to think independently and challenge flawed premises, connect them directly to upstream artifacts so nuance is never lost, and judge results once on verifiable evidence.

Four principles drive every rule below:
1. **Multi-agent work has a real token cost — delegate only where it pays.**
   - Published figures: multi-agent systems spend ~5x–15x the tokens of single-turn chat, and external CLI calls carry fixed cold-start overhead (~12.5k tokens on `codex`, ~19.5k on `agy`).
   - Delegate only when **parallelism**, **context protection**, **epistemic independence** (a clean-context reviewer from a different model family), or **specialized capability** beats the cost of briefing and verification.
2. **Unleash parallel intelligence; isolate or sequence writes.**
   - Extra agents shine at thinking, exploring unknown unknowns, testing competing hypotheses, and auditing from diverse lenses.
   - Concurrent writes to shared files conflict over hidden style and interface assumptions. Keep writes single-threaded in a shared working tree (`agent_run.py batch`), or give parallel writers frozen interfaces and isolated workspaces (`--worktree` on Codex/Claude, Claude `isolation: "worktree"`, or Antigravity `Workspace: "branch"|"share"`).
3. **Structure must scaffold intelligence, never suffocate it.**
   - Over-prescribing steps or locking an agent into a narrow tunnel causes **cognitive tunneling**: the agent answers your literal question while stepping over the real bug or architectural flaw next door.
   - Match the brief's ceremony to the task's uncertainty (**Three Brief Modes**: `tight`, `guided`, `exploratory`), treat role checklists as a **floor rather than a ceiling**, and honor every worker's **Premise Challenge Right** (`assumptions_challenged`).
4. **Anti-Hallucination Evidence Law (No Proof = No Claim).**
   - Every critique finding, premise challenge (`assumptions_challenged`), and final conclusion (`summary`) **MUST** carry a verifiable ground-truth anchor in `evidence[]`: exact `file:line-line` + excerpt, `command -> exit code / output`, or measured numbers.
   - Unbacked claims or vague skepticism ("this might be slow", "this seems risky") are never accepted as verdicts or blockers—`agent_run.py` automatically audits result envelopes and flags unanchored claims in `meta.json` (`evidence_warnings`).
5. **De-Biased Parallel Sub-Agents & Specialized Skill Delegation (`references/multi-perspective-and-single-host.md`).**
   - In a single session, your own prior tokens create **autoregressive confirmation bias** (making you overconfident in your initial hunch). Even when only **one agent** or **one model** is used (`--single-host` / `--same-model`), break out of context bias by spawning **clean-context parallel sub-agents** (`invoke_subagent`, `Agent()`, or `agent_run.py batch`) with **Zero-Prior (Blinded) Briefs** (passing only verified facts, symptoms, and `file:line` pointers—never leaking your unverified hypothesis).
   - **Delegate domain depth to specialized skills (`--skill`):** Do not hardcode domain-specific workflows inside orchestration. Discover installed specialized skills via `route.py --list-skills` (or `route.py --need <keyword>`) and attach their `SKILL.md` to sub-agents via `--skill <name>`.

## The Adaptive Loop

1. **Frame the goal & uncertainty.** State the desired outcome and constraints. Decide whether the problem is well-specified (`tight` or `guided` mode) or open-ended with unknown unknowns (`exploratory` mode).
2. **Economic gate: delegate or do it yourself.** Do it yourself if the brief costs as much as the work, takes <3 tool calls, or requires synthesis only you hold.
3. **Pick a team shape** from `references/team-shapes.md`: Solo, Scout/Explorer fan-out, Builder + Reviewer, Smart friend, Competing hypotheses, Frozen-interface pipeline, or Interactive Peer Mesh.
4. **Split the work cleanly:**
   - For file writes and deliverables, scopes must be MECE (disjoint `--may-write` paths or isolated worktrees).
   - For research, debugging, and review, deliberate perspective overlap across model families is encouraged.
5. **Pass the four gates:** Delegation & Brief Mode → Permission & Isolation → Cognitive Model Routing → Verification (`references/gates-and-routing.md`). Run `scripts/route.py` (zero tokens) to get the recommended vendor, model family, tier, brief mode, verify level, and command. Override freely when you have context it lacks—just state why in one line.
6. **Issue work orders & connect the Shared Blackboard** (`references/brief-and-budget.md`):
   - Pick the brief mode (`tight` 4-line brief for lookups/small edits; `guided` for standard builds/reviews; `exploratory` for debugging, research, and design).
   - **Avoid lossy manager relays:** when Worker B builds on or reviews Worker A's work, pass Worker A's artifact/diff directly via `--context-file <path>` (or native `send_message`) instead of re-summarizing it yourself.
7. **Run and wait (Hardware-Aware Parallelism + Specialized Skills).** Launch independent packages in parallel (`agent_run.py batch` or native sub-agents), automatically scaling concurrency (`wip`) to the machine's live CPU cores, free RAM, GPU VRAM, and disk headroom (`ao_common.probe_hardware()`). Attach domain-specific skills via `--skill <skill_name>` when a worker needs specialized tools or workflows. Use `--name <slug>` for descriptive run folders while keeping `--task-type` canonical (`review`, `implement`, `explore`, `debug`...). Never poll or fabricate results.
8. **Accept once, on evidence & epistemic signals** (`references/verification.md`):
   - Check `assumptions_challenged`, `open_questions`, and `handoff_notes` alongside `status` and `evidence`. If a worker disproved a flawed assumption in your brief with solid evidence, **reward that discovery** and pivot the plan.
   - Run cheap deterministic checks (tests, lint, grep, bounded git diff) before LLM judgment.
   - Record your verdict (`agent_run.py verdict <run-dir> accept|revise|escalate|rollback|takeover`) so the shared ledger adapts future routing.
9. **Integrate and synthesize.** Write the final user response yourself, conclusion first.

## Three Brief Modes & Premise Challenge (`references/brief-and-budget.md`)

Never force an open-ended investigation into a rigid assembly-line checklist, and never write a 50-line brief for a 5-line lookup:

| Brief Mode | When to use | Structure |
|---|---|---|
| **`tight`** | Lookups, mechanical edits, simple unit tests | 4 compact items: **Intent & Done**, **Context/Artifacts**, **Scope/Authority**, **Output**. |
| **`guided`** | Standard implementation, focused analysis, code review | **Role lens** (`roles.md`), **Intent**, **Definition of Done**, **Context & Upstream Artifacts**, **Latitude**, **Finish line**, **Scope & Budget**. |
| **`exploratory`** | Root-cause debugging, unfamiliar codebase sensemaking, architecture design, huddles | **Role & Lens**, **Core Problem**, **Questions / Hypotheses to Test**, **Known Facts**, **Full read-only freedom to follow evidence trails & challenge premises**. |

**Roles are lenses, not blinders (`references/roles.md`):**
- The 4–6 examination angles in a Role block are a **floor, not a fence**.
- Replace rigid "Not your job" blinders with **Adjacent owners (flag, don't duplicate)**: if a worker spots a bug, RNG leak, or broken contract outside its write scope, it must not ignore it—it reports it in `assumptions_challenged`, `open_questions`, or `handoff_notes`.

## Huddle: Constructive & Empirical Consult (`references/huddle.md`)

Call a huddle when facing a hard-to-reverse (Type 1) decision, conflicting evidence, a failed escalation, or a challenged core premise. Never call one for routine work.

Protocol in 5 steps:
1. **Problem Memo (1 page):** Facts, constraints, options known, and what empirical signal would settle the question.
2. **Independent blind round:** 2–3 panelists with distinct lenses (`Architect`, `Red team`, `Domain expert`, `Implementer`, `User advocate`) and **different model families** answer in parallel without seeing each other's responses. They are explicitly invited to challenge the memo's framing and invent a synthesized **Option C**.
3. **Crux Map & Empirical Spike Gate:** Extract the cruxes. **Mandatory gate:** if any crux is a testable fact (e.g., "does X permute RNG?", "is Y slow?"), **do not debate it in prose**—run a 2-minute micro-spike or command to measure the truth first.
4. **Dialectical Synthesis (optional, 1 round, unresolved trade-offs only):** Share anonymized counterarguments and spike data. Ask panelists to concede disproved points or synthesize the best of both worlds (**Option C**).
5. **Decide & commit:** Decide on evidence (never majority vote). Record the decision, strongest dissent, and reversal trigger.

## Dynamic Model Discovery & Cognitive Routing (`references/gates-and-routing.md`)

**Models are dynamically discovered, never locked to stale hardcoded strings:**
- `discover.py` probes live available models across all 3 harnesses at zero token cost (`agy models`, `~/.codex/.codex-global-state.json` & `latest-model.md`, `~/.claude/settings.json`, `gateway-models.json`, and `model-catalog/*-ccd.json`).
- `route.py` (`ao_common.dynamic_tier_config`) analyzes and scores the live discovered models to select the best model per tier (`fast`, `standard`, `frontier`, `frontier_max`) automatically (`source: dynamic_discovered`), using `assets/models.json` only as a fallback baseline.

Match the work to the model family's cognitive strengths:
- **OpenAI (`codex`):** surgical logic, deep debugging, methodological/statistical auditing, refactoring, non-interactive `codex review`, `--worktree`, and `--search`.
- **Anthropic (`claude`):** architectural synthesis, 1M-context deep code/prose reasoning (`nghi/claude-opus-5[1m]`, `claude-opus-5-5`, `claude-sonnet-5-5`), fast `--bare` headless runs, `--worktree`, `--bg` daemons, and `claude ultrareview`.
- **Google (`agy`):** broad-context synthesis, rapid multi-file exploration, multimodal/UI, plus cross-family hosting (`gemini-4-argon-*`, `claude-opus-5-5-*`).

**Epistemic Independence:** An independent reviewer (`review`, `security-review`, `critique`) must use a **different model family** from the builder (`route.py --task-type review --builder <vendor>` enforces this automatically).

**Channels:**
- **Native subagents** (`Agent` in Claude, `invoke_subagent` + `send_message` in Antigravity, `spawn_agent` in Codex) for fast in-session work, context forking, and interactive peer messaging.
- **Unified external runner** (`scripts/agent_run.py run --agent codex|claude|agy`) for cross-family reviews, huddles, and schema-enforced out-of-session execution.
  - Supports `--worktree` (Codex/Claude isolated git worktree), `--search` (Codex live web search), `--bare` and `--max-budget-usd` (Claude fast cold-start & cost cap), `--name <slug>`, `--context-file <path>`, and `--resume <session_id>`.

## Reference Map

| File | Read when |
|---|---|
| `CATALOG.md` | **Read first:** 1-page cheat sheet of all core rules, CLI commands (`codex`, `claude`, `agy`), and Evidence Law |
| `references/multi-perspective-and-single-host.md` | **Single-agent mode (e.g., only `agy`)**, Zero-Prior de-biasing, Orthogonal Expert Council, and the 5-stage `Diverge → Falsify → Probe → Synthesize → Plan` workflow |
| `references/team-shapes.md` | Choosing the team structure or setting up parallel workspaces / peer mesh |
| `references/gates-and-routing.md` | Passing the four gates, matching cognitive strengths, and picking a channel |
| `references/brief-and-budget.md` | Writing a `tight`, `guided`, or `exploratory` work order and using `--context-file` |
| `references/roles.md` | Assigning a role lens without creating cognitive tunneling |
| `references/verification.md` | Judging results, handling `assumptions_challenged`, and recording verdicts |
| `references/huddle.md` | Running an independent-first huddle with the Empirical Spike Gate & Dialectical Synthesis |
| `references/management-models.md` | Theoretical foundations (Mission Command, Stigmergy, Sensemaking, Dialectics) |
| `references/adapters/claude-code.md` | Using Claude Code (`Agent`, `SendMessage`, worktrees, and `claude -p`) |
| `references/adapters/codex-cli.md` | Using Codex CLI (`agent_run.py --agent codex`, `codex_run.py`, `--worktree`) |
| `references/adapters/antigravity-cli.md` | Using Antigravity (`invoke_subagent`, `send_message`, `Workspace: branch/share`, `agy -p`) |
| `references/two-way.md` | Cross-agent calling matrix, Shared Blackboard handoffs, and v3 operational fixes |
| `references/self-update.md` | Discovering new models/tools (`discover.py`) and promoting candidates |
| `assets/models.json` | Source of truth for model families, tiers, cognitive strengths, and task routing |
| `assets/result.schema.json` | v3 result envelope (with optional `confidence`, `assumptions_challenged`, `open_questions`, `handoff_notes`) |
