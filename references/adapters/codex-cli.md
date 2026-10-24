# Adapter: Codex CLI (`codex` 0.154.0+)

## Quick card (Unified Runner — Preferred)
- **Read-only audit / debug / review:**
  ```bash
  python <skill>/scripts/agent_run.py run --agent codex --brief brief.md --name audit-core \
         --task-type review --tier frontier --mode read [--context-file .orch/spec.md] [--search]
  ```
- **Write, with scoped attribution (or isolated Git Worktree):**
  ```bash
  python <skill>/scripts/agent_run.py run --agent codex --brief brief.md --name impl-feature \
         --task-type implement --tier standard --mode write --may-write src/foo/ [--worktree]
  ```
- **Resume an existing session (~1.5k tokens vs ~12.5k cold start):**
  ```bash
  python <skill>/scripts/agent_run.py run --agent codex --brief delta.md --resume <session_id>
  ```
- **Batch execution (parallel readers first, then sequential writers):**
  ```bash
  python <skill>/scripts/agent_run.py batch plan.json --wip 3
  ```

## Dynamic Model Discovery (`discover.py` & `route.py`)
Models are **never locked to stale hardcoded strings**. `discover.py` automatically scans:
1. `~/.codex/.codex-global-state.json` (live `composer-recent-model-configurations-v1` and `seen-model-upgrade-list`, e.g. `gpt-6-astra`, `gpt-6.1-sol`, `gpt-5.6-sol`, `gpt-5.6-terra`),
2. `~/.codex/models_cache.json`,
3. `~/.codex/skills/.system/openai-docs/references/latest-model.md` (`gpt-5.6`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex`, `gpt-5.1-codex-mini`),
4. `~/.codex/config.toml` (`model = "..."`).

`route.py` scores all live discovered models (`ao_common.dynamic_tier_config`) and automatically picks the strongest fit for `fast`, `standard`, `frontier`, and `frontier_max` (`source: dynamic_discovered`), falling back to `assets/models.json` only if no local state exists.

## Power Native Codex CLI Commands (0.154.0)

| Capability | Command / Flag | When to use |
|---|---|---|
| **Built-in Non-Interactive Code Review** | `codex review --uncommitted [PROMPT]`<br>`codex review --base <BRANCH> [PROMPT]`<br>`codex review --commit <SHA> [PROMPT]` | Fast, zero-ceremony second opinion on uncommitted diffs, a feature branch, or a specific commit. |
| **Isolated Git Worktree** | `agent_run.py run --agent codex ... --worktree`<br>(or raw `codex exec --worktree ...`) | Run parallel writers safely in a managed git worktree without dirtying the main working tree. |
| **Live Web Search** | `agent_run.py run --agent codex ... --search`<br>(or raw `codex exec --search ...`) | Enable native `web_search` tool without per-call approval prompts during research/explore tasks. |
| **Multimodal Image Input** | `codex exec -i screenshot.png - < brief.md` | Attach UI screenshots, architecture diagrams, or plots directly to the prompt. |
| **Apply Latest Agent Diff** | `codex apply` | Apply the latest diff produced by a Codex session via `git apply`. |
| **Native Subagents** | `spawn_agent` (with roles in `~/.codex/agents/*.toml`) | Cheap in-session delegation when Codex itself is the top-level manager. |

## Raw `codex exec` Reference (when not using `agent_run.py`)
```bash
codex exec -m <model> -c 'model_reasoning_effort="high"' \
  -s read-only -C <repo> [--worktree] [--search] --skip-git-repo-check \
  --output-schema <skill>/assets/result.schema.json -o result.json - < brief.md
```

## Parsing & Anti-Hallucination Verification
- Read `meta.json` first:
  - Check `ok`, `failure`, `violations`, and **`evidence_warnings`** (automatically populated by `agent_run.py` if the worker's `summary` or `assumptions_challenged` lacks verifiable `file:line` or command output anchors).
- Then read `result.json`. Every critique or conclusion must cite concrete proof in `evidence[]`.
