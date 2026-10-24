# Four Gates and Cognitive Model Routing

Evaluate each work package through four gates, in order. Each gate yields a decision, not a score. Two precedence rules apply:
- **Permission fail** → stop, whatever the other gates say.
- **Suspected security issue** → escalate to the user.

## Gate 1: Delegation & Brief Mode
- **Inputs:** goal, scope, risk, ambiguity, dependencies, where the needed context lives.
- **Output:** `do-it-yourself` or `delegate` + **Brief Mode** (`tight` | `guided` | `exploratory`).
- **Questions to answer:**
  - Is briefing cheaper than doing the work?
  - Is there a real gain from parallelism, context protection, epistemic independence, or cognitive specialization?
  - Is the problem well-defined (`tight` / `guided` brief) or open-ended with unknown unknowns (`exploratory` brief)?

## Gate 2: Permission & Workspace Isolation
- **Inputs:** the actions the worker will take, the data it touches, and how reversible the effects are.
- **Output:** `allowed`, `ask-user-first` or `refuse`, plus a sandbox/workspace mode and an authority level.

| Blast radius | Sandbox / Workspace | Authority | Extra |
|---|---|---|---|
| Read-only | `read-only` (Codex) / `plan` (`agy`, `claude`) | `propose-only` | Full freedom to follow evidence trails across the repo |
| Writes, reversible, in scope | `workspace-write` / `accept-edits` / `acceptEdits` | `execute-within-scope` | Bounded git snapshot before and after (`--may-write`) |
| Parallel writers or risky multi-file refactor | Isolated worktree (`--worktree`, `isolation: "worktree"`, or `agy` `Workspace: "branch"\|"share"`) | `ask-before-exceeding` | Plan-first or frozen interface spec via `--context-file` |
| Secrets, production, deletion, external messages, money | none | `refuse`, or ask the user | User acts or explicitly approves |

## Gate 3: Cognitive Model & Channel Routing
- **Inputs:** task type, reasoning depth, sensitivity, tools needed, need for epistemic independence.
- **Output:** a primary vendor, model, effort, brief mode, fallback model, channel, and budget.
- **Compute it, don't re-derive it:** run `python <skill>/scripts/route.py --task-type T --risk R [--ambiguity low|high] [--size s|m|l] [--builder V] [--need KEYWORD]`.
  - `route.py` canonicalizes free-form task labels (e.g. `review-p1` → `review`, `draft-doc` → `docs`, `investigate` → `explore`), reads `assets/models.json` and your verdict ledger, and prints the vendor, model, brief mode, verify level, and a ready-to-run `agent_run.py` command at zero LLM tokens.

### Cognitive Strengths & Epistemic Independence
1. **Match model family to cognitive need:**
   - **OpenAI (`codex`: `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-6-astra`):** surgical logic, deep debugging, methodological/statistical auditing, and multi-file refactoring.
   - **Google (`agy`: `gemini-3.8-flash-*`, `gemini-4-argon-{low,medium,high}`):** broad-context synthesis, fast codebase exploration, multimodal/UI tasks, and cross-family hosting (`agy` can also run `claude-opus-5-5-high` and `claude-sonnet-5-5-*`).
   - **Anthropic (`claude`: `haiku`, `sonnet`, `opus`):** architectural synthesis, nuanced code/prose generation, and exploratory reasoning.
2. **Epistemic Independence = Different Model Family:**
   - When `independent: true` (reviews, critiques, security audits), `route.py` ensures the reviewer uses a **different model family** (`openai` vs `google` vs `anthropic`) from the builder (`--builder`), not merely a different CLI binary.
3. **Earned Autonomy (Ledger-driven adaptation):**
   - A `(task, vendor, tier)` slice with 3+ verdicts and <60% accept rate automatically bumps up one tier.
   - 3 consecutive accepts one tier lower (at low risk) earns a downshift, never below the risk floor.

### Current model mapping (mirrors `assets/models.json`, updated 2026-10-24)

| Tier | Claude Code (`claude`) | Codex CLI (`codex`) | Antigravity CLI (`agy`) |
|---|---|---|---|
| **fast** | `haiku` | `gpt-5.6-luna` / low | `gemini-3.8-flash-low` |
| **standard** | `sonnet` | `gpt-5.6-sol` / medium | `gemini-4-argon-medium` |
| **frontier** | `opus` | `gpt-6-astra` / high | `gemini-4-argon-high` |
| **frontier_max** | `opus` (effort max) | `gpt-6-astra` / xhigh | `claude-opus-5-5-high` |

Notes:
- Updated 2026-10-24 for `agy 1.4.4` and `Claude Code 2.1.308`. `gemini-3.1-pro-high` was retired by `agy` in favor of `gemini-4-argon-{low,medium,high}` and `claude-{sonnet,opus}-5-5-*`.
- `Claude Code 2.1.308` (`%LOCALAPPDATA%\Claude-Data\...`) is authenticated and automatically resolved by `ao_common.py`.

### Channel choice

| Need | Channel |
|---|---|
| Fast in-session work or small tasks (`--size s`) | Native subagent (`Agent`, `spawn_agent`, `invoke_subagent`) |
| Worker needs your current conversation context | Native fork (Claude fork or `agy` `Workspace: "inherit"`) |
| Isolated parallel writers | Native worktree/branch (`isolation: "worktree"`, `Workspace: "branch"\|"share"`) |
| Cross-family review, huddle panelist, or out-of-session execution | `scripts/agent_run.py run --agent codex\|agy\|claude [--name SLUG] [--context-file PATH]` |
| Direct artifact handoff between workers | Pass upstream output file via `--context-file` so the worker reads it directly |
| Finish a partial result or apply 1 targeted revision | Resume (`SendMessage`, `invoke_subagent` follow-up, or `agent_run.py --resume <id>`) |

## Gate 4: Verification
- **Output:** a verification level fixed before launch:
  - **L0:** accept on the envelope's evidence (only for low-stakes lookups with 3+ streak).
  - **L1:** cheap deterministic check (test, grep, schema, file exists).
  - **L2:** L1 plus diff review of changed hunks (floor for all code changes).
  - **L3:** L2 plus an independent cross-family reviewer, or first-hand verification of the key claim (floor for security, data, deployment, or Type 1 decisions).
