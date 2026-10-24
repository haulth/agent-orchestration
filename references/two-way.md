# Two-way calling & Stigmergic Collaboration: any agent as manager

The skill is loaded by Claude Code, Codex and Antigravity (`agy`). Any of them can act as the manager, spawn native subagents, or call the other two through `scripts/agent_run.py`.

## Two Complementary Modes of Multi-Agent Exchange

1. **Stigmergic Blackboard (`--context-file`, cross-vendor & in-session):**
   - Instead of forcing the manager to copy-paste and summarize Worker A's findings into Worker B's brief (which loses technical nuance), Worker A writes its analysis, interface spec, or diff to an artifact file, and the manager passes `--context-file <path>` to Worker B.
   - `agent_run.py` automatically injects a **Shared Blackboard / Upstream Artifacts** section into Worker B's brief with exact resolved paths so Worker B reads Worker A's output directly.
2. **Native Peer Messaging & Isolated Workspaces (in-session):**
   - **Antigravity (`agy` IDE/agent):** `invoke_subagent` supports `Workspace: "inherit" | "branch" | "share"` (isolated git-worktree-like workspaces for parallel writers!) and `send_message(Recipient=<conversationId>, Message=...)` for direct peer or manager-to-subagent dialogue without cold-start overhead.
   - **Claude Code:** `Agent` supports `isolation: "worktree"` and `SendMessage` to resume or steer a running/completed subagent, plus experimental Agent Teams when peers must message each other directly.
   - **Codex CLI:** `codex exec --worktree` isolates writes; `codex exec resume <id>` continues a session cheaply (~1.5k tokens).

## Who can call whom (external CLI channel)

| Manager -> worker | Command | Status (2026-10-24) |
|---|---|---|
| Claude Code -> codex | `agent_run.py run --agent codex ...` | Verified (real calls) |
| Claude Code -> agy | `agent_run.py run --agent agy ...` | Verified (real calls) |
| Codex (top-level) -> agy | same runner from Codex's shell | Verified with network on (`-c sandbox_workspace_write.network_access=true`) |
| agy -> codex | same runner via `run_command` / shell | Verified (no auto-denies) |
| anyone -> claude (`claude -p`) | `agent_run.py run --agent claude ...` | **Ready (2026-10-24):** `Claude Code 2.1.308` under `%LOCALAPPDATA%\Claude-Data` is resolved by `ao_common.py` and logged in (`loggedIn: true`) |
| Native subagents | `Agent` / `spawn_agent` / `invoke_subagent` | Fastest path for small/medium tasks; log verdicts with `agent_run.py verdict - accept --agent <vendor> --task-type T --tier X` |

## What v3 fixed from real operational logs (`ledger.jsonl` & `changes.md`)
- **Million-file untracked explosion fixed:** In v2, running `git status -uall` inside an ML repository with background dataset/checkpoint generation caused `agent_run.py` to hash 1.65M untracked files and report them as scope `violations` on read-only runs. v3 uses `git status -unormal` with bounded directory expansion (`MAX_UNTRACKED_EXPAND = 2000`) and fast `stat` signatures for files >4MB.
- **Canonical task & tier auto-inference:** Managers naturally pass descriptive task names like `--task-type review-p1-model-core` or omit `--tier`. v3 adds `--name <slug>` for custom run directory labels, automatically canonicalizes `--task-type` (`review-p1-model-core` → `review`, `judge-region-v3` → `review`, `draft-doc` → `docs`), and infers missing tiers from the model slug so Earned Autonomy in `ledger.jsonl` never drops data.
- **Model-family independence:** Since `agy 1.4.4` hosts both Google (`gemini-4-argon-*`) and Anthropic (`claude-opus-5-5-*`, `claude-sonnet-5-5-*`) models, `route.py` checks **model family** (`openai`, `google`, `anthropic`) when selecting an independent reviewer.
