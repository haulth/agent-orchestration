# Adapter: Claude Code (Native Subagents & `claude` CLI 2.1.308+)

## Quick card
### 1. Calling Claude CLI (`claude -p`) as a Worker from ANY Manager (Codex, Antigravity, or Shell)
- **Read-only audit / review / architecture consult:**
  ```bash
  python <skill>/scripts/agent_run.py run --agent claude --brief brief.md --name arch-review \
         --task-type review --tier frontier --mode read [--context-file .orch/spec.md]
  ```
- **Fast cold-start mode (`--bare`) & hard USD budget cap (`--max-budget-usd`):**
  ```bash
  python <skill>/scripts/agent_run.py run --agent claude --brief brief.md --name fast-check \
         --task-type lookup --tier fast --mode read --bare --max-budget-usd 0.25
  ```
- **Scoped write (or isolated Git Worktree `--worktree`):**
  ```bash
  python <skill>/scripts/agent_run.py run --agent claude --brief brief.md --name impl-ui \
         --task-type implement --tier standard --mode write --may-write src/ui/ [--worktree]
  ```
- **Resume an existing session:**
  ```bash
  python <skill>/scripts/agent_run.py run --agent claude --brief delta.md --resume <session_id>
  ```

### 2. Claude Code as the In-Session Manager
- **Read-only worker:** `Agent(subagent_type: "Explore" | "general-purpose", model: "haiku"|"sonnet"|"opus", prompt: <brief>)`
- **Isolated write worker:** `Agent(subagent_type: "general-purpose", model: "sonnet", isolation: "worktree", prompt: <brief>)`
- **Resume / Direct Follow-up:** `SendMessage(to: "<agent_id>", message: "<delta>")`

---

## Dynamic Model Discovery (`discover.py` & `route.py`)
`discover.py` automatically discovers all models available to your Claude Code installation without spending tokens by scanning:
1. **`~/.claude/settings.json` (`env`):** Custom gateway/proxy models such as `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` (`nghi/claude-opus-5[1m]`), `ANTHROPIC_DEFAULT_SONNET_MODEL` (`nghi/claude-sonnet-5[1m]`), `ANTHROPIC_SMALL_FAST_MODEL` (`claude-haiku-5-5`).
2. **`~/.claude/cache/gateway-models.json`:** All models advertised by your configured gateway (`nghi/claude-opus-5[1m]`, `nghi/claude-sonnet-5[1m]`, `nghi/claude-opus-4.8[1m]`, `nghi/claude-haiku-4.5[1m]`, etc.).
3. **`~/.claude/cache/model-catalog/*-ccd.json`:** Official Claude Code catalog (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-fable-5-1`, `claude-haiku-5-5` with 1M context window metadata and effort levels `low|medium|high|xhigh|max`).

`route.py` scores these live discovered models (`ao_common.dynamic_tier_config`) and automatically selects the best model per tier (`fast`, `standard`, `frontier`, `frontier_max`), falling back to `assets/models.json` only if no local cache exists.

---

## Power Native Claude CLI Commands (2.1.308+)

| Capability | Command / Flag | When to use |
|---|---|---|
| **Fast Minimal Mode (`--bare`)** | `agent_run.py run --agent claude ... --bare`<br>(or `claude -p --bare ...`) | Skips hooks, LSP, plugin sync, auto-memory, and `CLAUDE.md` auto-discovery for ultra-fast, low-overhead worker execution (uses `ANTHROPIC_API_KEY` / settings helper). |
| **Isolated Git Worktree (`-w`, `--worktree`)** | `agent_run.py run --agent claude ... --worktree`<br>(or `claude -p --worktree <name> ...`) | Runs the worker in a fresh git worktree so parallel writers never collide. |
| **Hard Cost Cap (`--max-budget-usd`)** | `agent_run.py run --agent claude ... --max-budget-usd 0.50` | Enforces a strict dollar ceiling on API calls in `--print` mode. |
| **Background Daemon Sessions (`--bg`)** | `claude --bg -p "<prompt>"`<br>`claude agents` / `claude logs <id>` / `claude stop <id>` | Launch long-running background agents, inspect their live logs, attach to them, or stop them. |
| **Cloud Multi-Agent Review (`ultrareview`)** | `claude ultrareview [PR_or_branch]` | Run a cloud-hosted multi-agent code review on the current branch or a PR. |
| **Custom Inline Agent Definitions (`--agents`)** | `claude -p --agents '{"auditor": {"description": "...", "prompt": "..."}}' --agent auditor` | Define specialized worker roles on the fly without editing `.claude/agents/`. |
| **Fork on Resume (`--fork-session`)** | `claude -p --resume <id> --fork-session` | Branch an existing conversation into a new session ID to test an alternative approach without mutating the original thread. |

## Raw Headless Command (`claude -p`)
```bash
claude -p --output-format json --permission-mode plan --model "nghi/claude-opus-5[1m]" --effort high \
       [--bare] [--worktree] [--max-budget-usd 1.00] [--resume <session_id>] \
       [--add-dir <dir>] [--allowedTools "Read,Grep,Glob"] \
       --json-schema '<schema_json>' < brief.md
```
