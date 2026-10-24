# Single-Host De-Biasing, Multi-Expert Lenses & Multi-Horizon Planning

When a machine only has **one agent installed** (e.g., only Antigravity `agy`, or only Claude Code, or only Codex CLI), or when you want to decompose complex analysis rapidly using in-session sub-agents, you face two cognitive hazards:
1. **Autoregressive Context Poisoning (Overconfidence in a Wrong Premise):** In a single conversation thread, every token you generate early on (an initial hunch, a quick guess at a bug's cause, or your first design idea) stays in your KV-cache. Self-attention conditions all subsequent tool calls and reasoning on those prior tokens, creating **Confirmation Bias** and **Premature Closure**—making you increasingly confident in a flawed direction.
2. **Homogeneous Mode Collapse (Narrow Tunnel Vision):** If you spawn 3 sub-agents on the same host with the same generic prompt (*"Analyze this problem and propose a plan"*), the same underlying model weights will converge on the exact same average answer, missing critical edge cases and better architectural alternatives.

This guide defines the **3 De-Biasing Laws**, the **Single-Host Multi-Subagent Playbook**, and the **5-Stage Multi-Horizon Exploration-to-Plan Workflow** (`Diverge → Falsify → Probe → Synthesize → Plan`).

---

## 1. The 3 Laws of Sub-Agent De-Biasing

### Law 1: Zero-Prior (Blinded) Briefs — Never Leak Your Hypothesis
When spawning a sub-agent to investigate a bug, evaluate a design, or review code, **strip your own unverified opinions and hypotheses from the brief**.
- **BAD (Contaminated Brief):**
  > *"I think `parse_token()` in `src/auth.py` has a regex bug causing the 401 error. Check `src/auth.py` and confirm how we should fix the regex."*
  > *(Result: The sub-agent anchors on `parse_token()`, rationalizes a regex tweak, and misses the actual clock-skew bug in `verify_jwt()`.)*
- **GOOD (Zero-Prior / Blinded Brief):**
  > *"Observed symptom: `POST /api/login` returns `401 Unauthorized` when called with payload X (`tests/test_auth.py:44`). Trace the authentication flow from entry point to token validation, identify at least 2 distinct root-cause hypotheses with exact `file:line` anchors, and run a check to falsify each one."*

### Law 2: Orthogonal Expert Council — Opposing Objective Functions
Never spawn multiple sub-agents with identical instructions. Assign each sub-agent a **distinct, orthogonal Expert Lens** with a different objective function so each searches a different subspace of the problem:

| Expert Lens | Objective Function (What it optimizes for) | Mandatory Falsification Question |
|---|---|---|
| **1. First-Principles Architect** | Clean boundaries, data/state invariants, decoupling, long-term evolvability | *"Where does coupling or state drift break this structure as requirements grow?"* |
| **2. Adversarial Red-Team Falsifier** | Breaking the hypothesis/plan; hunting race conditions, security flaws, hidden assumptions, and worst-case inputs | *"What single unspoken assumption in this codebase or plan, if false, causes a catastrophic failure?"* |
| **3. Pragmatic Simplicity Minimalist** | Solving the root problem with the **smallest possible blast radius** and zero over-engineering, reusing existing mechanisms | *"Which proposed components or abstractions can be deleted while still achieving 100% of the goal?"* |
| **4. Runtime & Failure-Mode Engineer** | Latency, memory, I/O bottlenecks, partial-failure recovery, migration safety, and instant rollback | *"What happens when an upstream dependency times out, returns corrupt data, or crashes mid-write?"* |
| **5. Domain & User-Outcome Advocate** | Mathematical/scientific validity and solving the user's real operational problem rather than a theoretical proxy | *"Does this actually solve the user's real workflow, or are we polishing the wrong layer?"* |

### Law 3: Compulsory Pre-Mortem & Evidence Anchors
Every sub-agent proposing an approach or root cause MUST include:
1. **Verifiable Ground-Truth Anchors (`evidence[]`):** Exact `file:line-line` citations or `command -> output` measurements (per the Anti-Hallucination Evidence Law).
2. **Pre-Mortem (`risks[]` / `assumptions_challenged[]`):** *"Assume my recommended approach ships and fails in production next week. What is the most likely technical cause (`file:line`), and what 2-minute check can test it right now?"*

---

## 2. Single-Host & Same-Model Playbook (When Only 1 Agent or 1 Model Exists)

You **DO NOT** need multiple model families to get genuine epistemic independence. Even when **every sub-agent runs on the exact same 1 model** (e.g., `Model="inherit"` or `gemini-4-argon-high` on Antigravity, `claude-opus-5-5` on Claude, or `gpt-6-astra` on Codex), two mechanisms eliminate confirmation bias and overconfidence:
1. **Clean KV-Cache per Sub-Agent:** Each sub-agent starts in a fresh session with 0 tokens of the Lead Agent's prior reasoning.
2. **Zero-Prior Brief + Orthogonal Expert Lenses:** Because $P(y \mid \text{SystemPrompt}_{\text{Lens}}, \text{ZeroPriorBrief})$ shifts across opposing objective functions (`First-Principles Architect` vs. `Adversarial Red-Team Falsifier` vs. `Pragmatic Simplicity Minimalist` vs. `Runtime Engineer`), the same model searches different parts of the codebase and actively falsifies weak assumptions.

### Fast Commands for Same-Model, Single-Host & Specialized Skill Orchestration
```bash
# 1. Inspect installed specialized skills and route keeping ALL sub-agents on the SAME model (--same-model)
python <skill>/scripts/route.py --list-skills
python <skill>/scripts/route.py --task-type research --need arxiv --manager agy --same-model
python <skill>/scripts/route.py --task-type review --builder agy --manager agy --same-model

# 2. Run a worker attaching specialized skills (--skill) or run a parallel batch capped by live hardware
python <skill>/scripts/agent_run.py run --agent agy --brief brief.md --mode read --skill literature-search-arxiv
python <skill>/scripts/agent_run.py batch plan.json
```

### Case A: Only Antigravity (`agy`) is Available
Antigravity has two superpowers for single-host diversity:
1. **Native Clean-Context Sub-Agents (`define_subagent` + `invoke_subagent`):**
   - Zero CLI cold-start overhead. Each `invoke_subagent` runs in an isolated conversation context (`conversationId`) completely free of your current token bias.
   - Use `define_subagent` to register specialized Expert Lenses with strict de-biased system prompts, then launch 2–4 of them **in parallel** in a single turn via `invoke_subagent`:
     ```python
     # Step 1: Define specialized expert sub-agents (or use TypeName="research" / "self" with Role + Prompt)
     define_subagent(
         Name="red-team-falsifier",
         Description="Adversarial Red-Team Auditor that hunts flawed premises, edge cases, and failure modes with file:line proof.",
         SystemPrompt="You are an adversarial falsifier. Never agree politely. Every claim must cite exact file:line or command output. Actively challenge flawed premises.",
         EnableWriteTools=False
     )
     # Step 2: Launch 3 orthogonal lenses in parallel with Zero-Prior Briefs
     invoke_subagent(TypeName="research", Role="First-Principles Architect", Model="pro",
                     Prompt="<Zero-Prior Brief + Architect Lens>")
     invoke_subagent(TypeName="red-team-falsifier", Role="Adversarial Red-Team Falsifier", Model="pro",
                     Prompt="<Zero-Prior Brief + Falsifier Lens>")
     invoke_subagent(TypeName="research", Role="Pragmatic Simplicity Minimalist", Model="pro",
                     Prompt="<Zero-Prior Brief + Minimalist Lens>")
     ```
   - For parallel prototype spikes that write files, isolate each sub-agent with `Workspace="branch"` or `Workspace="share"`.
2. **Intra-Host Cross-Family Models via `agy` CLI:**
   - Even without `codex` or `claude` installed, `agy` hosts **3 distinct model families**:
     - Google family: `gemini-4-argon-high`, `gemini-4-argon-medium`, `gemini-3.8-flash-high`
     - Anthropic family: `claude-opus-5-5-high`, `claude-sonnet-5-5-high`
     - Open-weights family: `gpt-oss-120b-medium`
   - When `route.py --task-type review --builder agy --manager agy --single-host` runs, it automatically switches the reviewer to a **different model family inside `agy`** (e.g. builder on `gemini-4-argon-high` → reviewer on `claude-opus-5-5-high`)!

### Case B: Only Claude Code (`claude`) is Available
- Spawn 2–4 parallel `Agent(subagent_type="Explore"|"general-purpose", model="opus"|"sonnet", prompt="<Zero-Prior Brief + Expert Lens>")` calls in a single assistant turn.
- Or run `agent_run.py batch` with `claude -p --bare` across `claude-opus-5-5` and `claude-sonnet-5-5` (and `isolation="worktree"` / `--worktree` for isolated parallel spikes).

### Case C: Only Codex CLI (`codex`) is Available
- Spawn parallel `spawn_agent` workers or run `agent_run.py batch` with `--agent codex` across `gpt-6-astra` (high/xhigh) and `gpt-6.1-sol` (medium), assigning each worker a distinct Expert Lens brief.

---

## 3. The 5-Stage Multi-Horizon Problem-Solving & Planning Workflow

When tackling a complex real-world task (feature architecture, system redesign, elusive bug, or performance bottleneck), **never jump straight from reading the prompt to writing a single linear plan**. Follow the 5-stage funnel:

### Stage 1: Diverge (Blinded Multi-Lens Exploration)
- Spawn 2–4 clean-context sub-agents in parallel using **Zero-Prior Briefs** and **Orthogonal Expert Lenses** (`Architect`, `Red-Team Falsifier`, `Pragmatic Minimalist`, `Runtime Engineer`).
- Require each sub-agent to map the relevant code (`file:line`) and propose at least one concrete direction (`Approach A`, `Approach B`, `Approach C`).

### Stage 2: Falsify (Cross-Critique & Anti-Overconfidence Check)
- Inspect the `assumptions_challenged`, `risks`, and `evidence` returned by each sub-agent.
- Discard any claim that lacks a concrete `file:line` or measurement anchor.
- Ask: *"Did the Red-Team Falsifier or Minimalist expose a fatal flaw or an unnecessary abstraction in the Architect's proposal?"*

### Stage 3: Probe (2-Minute Empirical Tie-Breaker)
- Whenever Approach A and Approach B disagree on a testable fact (e.g., *"Can function X handle streaming?"*, *"Is query Y the bottleneck?"*, *"Does library Z support flag W?"*), **do not guess**. Run a 1–2 minute command, micro-benchmark, or one-liner test to get the ground truth.

### Stage 4: Synthesize (Multi-Criteria Trade-off Matrix → Option C)
Compare the surviving approaches explicitly before committing:

```markdown
| Criterion | Approach A (e.g. Full Refactor) | Approach B (e.g. Minimal Hook) | Synthesized Option C (Chosen) |
|---|---|---|---|
| **Root-Cause Fit** | High | Partial | High (uses B's hook + A's invariant check) |
| **Blast Radius (Files)** | 12 files (`src/core/*`) | 2 files (`src/auth.py`) | 3 files (`src/auth.py`, `src/types.py`) |
| **Failure / Regression Risk** | Med-High (breaks callers) | Low | Low (backward-compatible) |
| **Key Evidence (`file:line`)** | `[E1] src/core/ a.py:40` | `[E2] src/auth.py:112` | Verified by spike `[E3]` |
```

### Stage 5: Plan & Execute Parallel Work (`agent_run.py batch` + Parent Skill Sharing & Ephemeral Skill Sandbox)
Turn the synthesized option into an executable parallel batch plan (`plan.json`):
1. **Shared Blackboard (`--context-file`):** Share upstream specs, contracts, or findings directly via `--context-file <path>` so parallel workers read exact ground truth.
2. **Parent-to-Child Skill Path Sharing (`--skill` — Zero Redundant Installs):**
   - If the parent agent already has a specialized skill (`~/.agents/skills`, `~/.claude/skills`, `~/.codex/skills`, `~/.gemini/config/skills`, `plugins/*/skills`, `builtin/skills`), **never re-install it**.
   - Pass `"skill": ["<skill-name>"]` in `plan.json` (or `--skill <skill-name>` on `agent_run.py run`, or the exact `SKILL.md` file path in a native sub-agent's prompt). `agent_run.py` automatically injects the parent's `SKILL.md` path and mounts the skill directory (`--add-dir <dir>`) so the child agent can read it directly.
3. **Ephemeral Skill Sandbox (`skill_sandbox.py` — Only When Parent Lacks the Skill):**
   - If a specialized skill is genuinely missing from the machine (`skill_sandbox.py check <keyword>`), search curated high-trust sources (`anthropics/skills`, `openai/skills`, `vercel-labs/agent-skills`, `huggingface/skills`, `obra/superpowers`, or GitHub repos with `>= 50` stars) via `skill_sandbox.py search <query>`.
   - **Mandatory User Consent + Static Security Audit:** Present the candidate repo, star count, trust tier, and target sandbox path (`~/.agent-orchestration/sandbox-skills/<name>`) to the user and **ask for approval before installing**.
   - Once approved, run `skill_sandbox.py install <repo> [--subpath <dir>] --name <slug> --approved-by-user`. The skill is scanned for dangerous patterns and stored strictly inside `agent-orchestration`'s own ephemeral memory (zero impact on global host directories), and can be deleted at any time via `skill_sandbox.py remove <slug>` or `skill_sandbox.py purge [--expired]`.
4. **Disjoint Write Scopes (`--may-write` / `--worktree`):** When multiple workers modify files in parallel, assign strictly disjoint `may_write` paths (or `"worktree": true` / Antigravity `Workspace="branch"`).
5. **Hardware-Aware Concurrency (`probe_hardware()`):** `agent_run.py batch plan.json` automatically measures live CPU cores, free RAM, disk space, and GPU VRAM to cap `wip` safely.
