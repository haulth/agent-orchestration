# CATALOG.md — Fast Rules & CLI Cheat Sheet (1-Page Index)

> **Read this file first.** It gives any agent (Claude Code, Codex CLI, Antigravity `agy`) the complete operational rules, live CLI commands, anti-hallucination evidence contract, and reference index in ~150 lines so you do not have to read all `references/*.md` files.

---

## 1. Ten Golden Rules (How Agents Collaborate)

1. **Delegate only when it pays:** Multi-agent runs cost ~5x–15x chat tokens; external CLI calls add ~12.5k (`codex`) to ~19.5k (`agy`) fixed overhead. Do tiny tasks (`<3` tool calls) yourself or via native subagents.
2. **Parallel intelligence works; concurrent shared writes break:** Spawn parallel agents to explore, debug, or review. Keep writes single-threaded in a shared tree (`agent_run.py batch`) or isolate parallel writers with `--worktree` (Codex/Claude) or `Workspace: "branch"|"share"` (`agy`).
3. **Three Brief Modes (match ceremony to uncertainty):**
   - `tight` (4 lines: Intent/Done, Context, Scope, Output) → lookups, mechanical edits, small tests.
   - `guided` (Role lens, Intent, DoD, Context, Latitude, Finish line, Scope) → features, code review, docs.
   - `exploratory` (Core problem, Questions/Hypotheses, full read-only freedom) → hard debugging, unfamiliar architecture, research.
4. **Roles are lenses (a floor, never blinders):** A worker examines its role's core angles AND follows evidence trails wherever they lead, flagging cross-boundary bugs in `open_questions` or `handoff_notes`.
5. **Premise Challenge Right (`assumptions_challenged`):** If code or data disproves an assumption in the manager's brief, the worker MUST challenge it in `assumptions_challenged` with proof (`file:line` or command output).
6. **Anti-Hallucination Evidence Law (No Proof = No Claim):**
   - Every conclusion in `summary`, every critique finding, and every item in `assumptions_challenged` **MUST** cite verifiable ground truth (`file:line-line`, `command -> exit/output`, or measured numbers in `evidence[]`).
   - Unbacked skepticism is just a worry (`risks[]`), never a valid objection or blocker.
   - `agent_run.py` automatically audits envelopes and flags `evidence_warnings` in `meta.json` when claims lack concrete anchors.
7. **Shared Blackboard (`--context-file`) over Lossy Manager Relay:** Never summarize a 10-page upstream artifact into 3 sentences for the next agent. Pass `--context-file <path>` so downstream agents read upstream findings/diffs directly.
8. **Dynamic Model Discovery (never rely on stale hardcoded lists):** `discover.py` probes live models across all 3 harnesses (`agy models`, `~/.codex/.codex-global-state.json`, `~/.claude/cache/model-catalog/*` & `gateway-models.json`), and `route.py` scores and selects the best live model per tier automatically (`source: dynamic_discovered`).
9. **Epistemic Independence = Different Model Family (or Single-Host Clean-Context + Alt Family/Lens):** An independent reviewer (`review`, `security-review`, `critique`) must come from a different model family (`openai` vs `google` vs `anthropic`) than the builder (`route.py --builder <vendor>` enforces this). If only 1 agent exists on the machine (`--single-host`), `route.py` automatically switches to an intra-host alternate model family (e.g., `agy` switching from `gemini-4-argon-high` to `claude-opus-5-5-high`) + **Zero-Prior Clean-Context Sub-Agent**.
10. **Empirical Huddle (Spike before Debate, Synthesis Option C):** When panelists disagree on a testable fact, run a 2-minute micro-spike/command to measure the truth instead of running another prose debate round. On design trade-offs, ask panelists to synthesize a better **Option C**.
11. **Single-Host De-Biasing & Multi-Horizon Planning (`Diverge → Falsify → Probe → Synthesize → Plan`):**
    - **Zero-Prior (Blinded) Briefs:** Never leak your unverified hunch into a sub-agent's prompt; pass only symptoms, constraints, and `file:line` facts so your current conversation tokens cannot bias the sub-agent into overconfident confirmation.
    - **Orthogonal Expert Council:** When using sub-agents on a single host or single model (e.g., only Antigravity `agy` via `define_subagent` + `invoke_subagent`), assign opposing Expert Lenses (`First-Principles Architect`, `Adversarial Red-Team Falsifier`, `Pragmatic Simplicity Minimalist`, `Runtime/Failure Engineer`) to explore multiple directions in parallel before locking in an implementation plan.
12. **Multi-Module Code Implementation & System Development (`agent_run.py dev` / `implement` / `system-dev`):**
    - **Frozen Interface Contract (`.orch/interface-contract.md`):** Before splitting code implementation across multiple Builders, freeze shared types, signatures, and invariants in `interface-contract.md` and pass it via `--context-file`.
    - **Disjoint `--may-write` Scopes & Isolated Worktrees:** Give each Builder a strictly disjoint write scope (`--module core:src/core/ --module api:src/api/`) or an isolated branch/worktree (`--worktree` on Codex/Claude, `Workspace: "branch"` on `agy`).
    - **Zero-Prior Adversarial Test Builder:** Assign a separate clean-context sub-agent to write tests in `tests/` directly from the spec (`interface-contract.md`) so tests are never biased by the Builder's implementation shortcuts.

---

## 2. Fast CLI Command Matrix (All 3 Agents)

Replace `<skill>` with the skill folder path (e.g. `~/.agents/skills/agent-orchestration`).

### A. Zero-Token Live Model Inspection & Routing
```bash
# 1. Inspect ALL live available models right now across codex, claude, and agy (never out-of-date)
python <skill>/scripts/route.py --list-models

# 2. Refresh full capability snapshot (flags, MCPs, plugins, skills, live models)
python <skill>/scripts/discover.py --quick          # fast version check (exit 10 -> run full)
python <skill>/scripts/discover.py                  # full live model & capability snapshot

# 3. Compute optimal vendor, live-scored model, brief_mode & verify level (0 tokens)
python <skill>/scripts/route.py --task-type review --risk med --builder codex --manager claude
python <skill>/scripts/route.py --task-type explore --ambiguity high

# 4. Single-Host & Same-Model Mode (when only 1 agent or only 1 model is used across all sub-agents)
python <skill>/scripts/route.py --task-type design --manager agy --same-model
python <skill>/scripts/route.py --task-type review --builder agy --manager agy --same-model
python <skill>/scripts/route.py --task-type design --manager agy --single-host

# 5. Generate (and optionally run) a Same-Model De-Biased Expert Council (Zero-Prior Briefs + Orthogonal Lenses)
python <skill>/scripts/agent_run.py council --brief BRIEF.md --agent agy --model gemini-4-argon-high --task-type design

# 6. Multi-Module Code Implementation & System Development (Frozen Contract + Disjoint Write Builders + Zero-Prior Test Builder)
python <skill>/scripts/route.py --task-type system-dev --manager agy --same-model
python <skill>/scripts/agent_run.py dev --brief SPEC.md --module core:src/core/ --module api:src/api/ \
       --test-scope tests/ --agent codex --model gpt-6.1-sol [--worktree] [--execute]
```

### B. Unified Cross-Agent Runner (`agent_run.py`)
Works identically from **Claude Code**, **Codex CLI**, or **Antigravity (`agy`)**:
```bash
# Call CODEX CLI (surgical logic, deep debugging, refactoring, live web search, isolated worktree)
python <skill>/scripts/agent_run.py run --agent codex --brief brief.md --name audit-rng \
       --task-type review --tier frontier --mode read --context-file .orch/spec.md [--search]

# Call CODEX CLI for isolated parallel writing in a Git Worktree
python <skill>/scripts/agent_run.py run --agent codex --brief brief.md --name impl-auth \
       --task-type implement --mode write --may-write src/auth/ --worktree

# Call CLAUDE CODE CLI (`claude -p`: 1M context gateway/catalog models, bare fast start, USD budget cap, worktree)
python <skill>/scripts/agent_run.py run --agent claude --brief brief.md --name arch-review \
       --task-type review --tier frontier --mode read --context-file .orch/spec.md [--bare] [--max-budget-usd 0.50]

# Call ANTIGRAVITY CLI (`agy -p`: broad context synthesis, Gemini 4 Argon / Claude 5.5 hosting)
python <skill>/scripts/agent_run.py run --agent agy --brief brief.md --name broad-scout \
       --task-type explore --tier standard --mode read

# Resume any session cheaply with only the delta (keeps original scope/sandbox)
python <skill>/scripts/agent_run.py run --agent codex --brief delta.md --resume <session_id>

# Record manager verdict (feeds Earned Autonomy in ~/.agent-orchestration/ledger.jsonl)
python <skill>/scripts/agent_run.py verdict <run_dir> accept --note "Verified with pytest"
python <skill>/scripts/agent_run.py stats
```

### C. Power Native Commands (Direct Harness Features)
- **Codex CLI Native:**
  - Non-interactive diff/branch/commit review: `codex review --uncommitted` | `codex review --base main` | `codex review --commit <SHA>`
  - Isolated worktree execution: `codex exec --worktree -s workspace-write - < brief.md`
  - Apply latest agent diff: `codex apply`
- **Claude Code Native & CLI:**
  - In-session subagent: `Agent(subagent_type="Explore"|"general-purpose", model="haiku"|"sonnet"|"opus", isolation="worktree", prompt="...")`
  - Resume/message subagent: `SendMessage(to="<agent_id>", message="...")`
  - Cloud multi-agent PR/branch review: `claude ultrareview`
  - Background daemon agent: `claude --bg -p "<prompt>"` → manage via `claude agents`, `claude logs <id>`, `claude attach <id>`, `claude stop <id>`
  - Fast cold-start headless call (skips hooks/LSP/auto-discovery): `claude -p --bare --output-format json ...`
- **Antigravity (`agy`) Native:**
  - Spawn subagent with isolated workspace: `invoke_subagent(TypeName="self"|"research", Role="...", Prompt="...", Model="inherit"|"flash"|"pro", Workspace="inherit"|"branch"|"share")`
  - Direct peer/subagent messaging: `send_message(Recipient="<conversationId>", Message="...")`

---

## 3. Result Envelope Contract (`assets/result.schema.json`)

Every worker returns one JSON object:
- **Required:**
  - `status`: `"done" | "partial" | "blocked" | "stopped"`
  - `summary`: Conclusion first (1–5 sentences), **citing `[E1]` / `file:line`**.
  - `deliverables`: `["path/to/file", ...]` (never paste huge blobs inline).
  - `evidence`: `["[E1] src/train.py:142 — RNG seeded before optional module", "[E2] pytest tests/ -> 12 passed"]` (**must contain concrete anchors**).
  - `risks`: `["open issue or unverified worry"]`
  - `next_action`: `"what the manager should decide or run next"`
- **Optional (v3 cognitive & handoff fields):**
  - `confidence`: `"low" | "med" | "high"`
  - `assumptions_challenged`: `["Brief assumed X, but src/foo.py:88 proves Y"]`
  - `open_questions`: `["Emergent lead found in src/bar.py:19"]`
  - `handoff_notes`: `"Direct technical notes/invariants for the next agent"`

---

## 4. When to Read Deep Reference Files (`references/`)

Only open a reference file when you need its full template or edge-case rules:

| File | Open ONLY when... |
|---|---|
| [`SKILL.md`](SKILL.md) | You need the full orchestration loop and safety policy |
| [`references/multi-perspective-and-single-host.md`](references/multi-perspective-and-single-host.md) | **Single-agent mode (e.g. only `agy`)**, Zero-Prior de-biasing, Orthogonal Expert Council, and the 5-stage `Diverge → Falsify → Probe → Synthesize → Plan` workflow |
| [`references/brief-and-budget.md`](references/brief-and-budget.md) | You need copy-paste templates for `tight`, `guided`, or `exploratory` briefs |
| [`references/roles.md`](references/roles.md) | You are picking specific examination angles for a specialized role |
| [`references/huddle.md`](references/huddle.md) | You are calling a multi-model huddle on a Type 1 or deadlocked decision |
| [`references/team-shapes.md`](references/team-shapes.md) | You are designing a multi-phase pipeline, competing hypotheses, or peer mesh |
| [`references/gates-and-routing.md`](references/gates-and-routing.md) | You are overriding `route.py` or checking permission blast-radius rules |
| [`references/verification.md`](references/verification.md) | A worker failed, challenged a premise, or triggered `evidence_warnings` / `violations` |
| [`references/adapters/codex-cli.md`](references/adapters/codex-cli.md) | You need advanced Codex CLI flags (`codex review`, `--worktree`, `--search`, profiles) |
| [`references/adapters/claude-code.md`](references/adapters/claude-code.md) | You need advanced Claude CLI flags (`claude -p`, `--bare`, `--worktree`, `--bg`, `ultrareview`, gateway models) |
| [`references/adapters/antigravity-cli.md`](references/adapters/antigravity-cli.md) | You need `agy` headless permission rules or native `invoke_subagent` details |
