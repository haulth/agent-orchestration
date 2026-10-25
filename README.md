# agent-orchestration

Multi-agent and sub-agent orchestration skill for **Claude Code**, **Codex CLI**, and **Antigravity (`agy`)**. Designed for hardware-aware parallel execution, dynamic zero-token model routing, structural work decomposition (**Orchestration Anatomy**), prerequisite/threshold keyhole interlocks, direct parent-to-child skill sharing, and an ephemeral skill sandbox.

## Core Capabilities

- **Zero-Token Live Model Discovery & Routing (`discover.py` + `route.py`):** Automatically probes available models across installed harnesses (`route.py --list-models`) and selects the optimal model per tier (`fast`, `standard`, `frontier`, `frontier_max`), supporting cross-vendor, single-host (`--single-host`), and single-model (`--same-model`) operation with Zero-Prior de-biased briefs.
- **Orchestration Anatomy & Keyhole Interlocks (`anatomy.py` + `batch --audit`):**
  - **Upfront Sizing Gate (`Micro` <=1 | `Figure` 2–4 | `Hero` 5–8 | `Epic` >8):** Classifies plan scale up front and gates `Epic` plans (`>8` packages) behind a `Hero` slice proposal unless explicitly approved (`--allow-epic`).
  - **Truth Lock & Keyhole Invariants (`truth_contract` + `--invariant` + `truth_hash`):** Locks user prerequisites, shared constants, and numeric threshold bounds (`KEY=VAL`, `KEY<=VAL`, `KEY>=VAL`, `must:PAT`, `forbid:PAT`) in `.orch/truth-contract.md` with a SHA-256 `truth_hash` and write-locks the contract against unilateral worker edits.
  - **Topological Wave Settler & Audit to Zero (`settle` + `audit`):** Resolves explicit and implicit `outputs -> context_file` dependencies into parallel execution waves (`Wave 0, Wave 1, ...`) and proves **0 structural and interlock defects** across 8 checks (`clearance`, `cycles`, `terminals`, `support`, `stand_in_briefs`, `skill_mounts`, `truth_contract`, `interlocks`) before running any agent.
  - **Anti-Silent-Mutation & Change-Ripple Protocol (`amend` + `inspect`):** Scans deliverables after each wave to block threshold drift (`INVARIANT_DRIFT`, `THRESHOLD_VIOLATION`) and conflicting constants across packages (`CROSS_PACKAGE_CONFLICT`). When a locked parameter must change with empirical proof (`truth_amendments`), `anatomy.py amend` (or `batch --auto-amend`) increments `truth_version`, broadcasts `.orch/truth-amendment-vN.md` into all packages' `context_file`, and flags already-run packages with the old value in `stale_packages` for mandatory resync.
- **Direct Parent-to-Child Skill Sharing (`--skill`):** Discovers specialized skills already available on the parent agent (`route.py --list-skills`) and mounts their `SKILL.md` path and directory (`--add-dir`) directly into child agents without redundant installation.
- **Ephemeral Skill Sandbox (`skill_sandbox.py`):** When a specialized skill is not installed locally, searches trusted repositories (`anthropics/skills`, `openai/skills`, `vercel-labs/agent-skills`, `huggingface/skills`, `obra/superpowers`, or verified GitHub repositories with `>= 50` stars), requires explicit user approval (`--approved-by-user`), runs static security checks, and installs into isolated skill memory (`~/.agent-orchestration/sandbox-skills/`) that can be removed or purged at any time.
- **Hardware-Aware Parallel Execution (`probe_hardware()`):** Dynamically probes CPU cores, available RAM, free disk space, and GPU VRAM to cap parallel `wip` safely, isolating concurrent writes via disjoint `--may-write` scopes or Git worktrees (`--worktree`).
- **Anti-Hallucination Evidence Law (`No Proof = No Claim`):** Every conclusion and premise challenge (`assumptions_challenged`) must cite verifiable ground truth (`file:line`, `command -> output`, or `DOI/arXiv/PMID/URL`).

## Installation

```bash
# Option 1: Install via Agent Skills CLI
npx skills add haulth/agent-orchestration

# Option 2: Install / inspect directly via NPX (npm registry or GitHub)
npx agent-orchestration-skill
npx agent-orchestration-skill doctor
```

Or install from a local clone (syncs to `~/.claude/skills`, `~/.agents/skills`, `~/.codex/skills`, and `~/.gemini/config/skills`):

```powershell
.\install\install.ps1   # Windows PowerShell
```
```bash
./install/install.sh    # macOS / Linux
```

## Quick Start Commands

```bash
# 1. Inspect available models, parent skills, and optimal routing (0 tokens)
python <skill>/scripts/route.py --list-models
python <skill>/scripts/route.py --list-skills
python <skill>/scripts/route.py --task-type research --need arxiv --manager agy --same-model

# 2. Orchestration Anatomy: Init Truth Contract + Keyhole Invariants, Audit to Zero, Execute & Inspect 4x Seams
python <skill>/scripts/anatomy.py init --goal "Implement & verify distributed service" \
       --invariant "PORT=8080" --invariant "MAX_LATENCY_MS<=200" \
       --pkg "contract:guided::src/types.py::.orch/contract-out.md" \
       --pkg "impl:guided:contract:src/core/::src/core/engine.py" \
       --pkg "verify:exploratory:impl" --out .orch/plan.json
python <skill>/scripts/anatomy.py audit .orch/plan.json
python <skill>/scripts/agent_run.py batch .orch/plan.json [--audit] [--auto-amend]
python <skill>/scripts/anatomy.py amend .orch/plan.json --set "MAX_LATENCY_MS<=250" \
       --reason "Measured p99 cold start" --evidence "bench.py:42 -> 235ms"
python <skill>/scripts/anatomy.py inspect .orch/plan.json

# 3. Run a single worker with parent skill sharing (--skill) and shared blackboard (--context-file)
python <skill>/scripts/agent_run.py run --agent agy --brief brief.md --mode read \
       --skill literature-search-arxiv --context-file .orch/spec.md

# 4. Ephemeral Skill Sandbox (used only when parent lacks a skill; requires user approval before install)
python <skill>/scripts/skill_sandbox.py check <keyword>
python <skill>/scripts/skill_sandbox.py search <query> --min-stars 50
python <skill>/scripts/skill_sandbox.py install <owner/repo> --subpath <path> --approved-by-user
python <skill>/scripts/skill_sandbox.py list
python <skill>/scripts/skill_sandbox.py remove <name>
python <skill>/scripts/skill_sandbox.py purge [--expired]
```

## License

MIT
