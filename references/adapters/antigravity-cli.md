# Adapter: Antigravity (`agy` CLI & Native Subagents)

## Quick card
- **Native subagents (preferred when Antigravity is the manager or the ONLY agent on the machine):**
  - Use `define_subagent(Name="...", Description="...", SystemPrompt="...", EnableWriteTools=False)` to create specialized domain lenses (e.g., `First-Principles Architect`, `Adversarial Red-Team Falsifier`, `Pragmatic Minimalist`, `Runtime Engineer`).
  - Call `invoke_subagent(TypeName="self"|"research"|"<custom>", Role="...", Prompt="<Zero-Prior Brief>", Model="inherit"|"flash"|"pro", Workspace="inherit"|"branch"|"share")` in parallel (2–4 sub-agents in one turn) so each explores the problem with a **clean KV-cache (0 prior conversation bias)**.
  - Use `send_message(Recipient="<conversationId>", Message="...")` to continue a subagent or let agents exchange targeted follow-ups with zero cold-start overhead.
  - Use `Workspace: "branch"` or `"share"` when running parallel writers/prototypes so each sub-agent works in an isolated branch/worktree without conflicting!
- **Single-Host Routing (`--single-host`):**
  - `python <skill>/scripts/route.py --task-type design --manager agy --single-host`
  - `python <skill>/scripts/route.py --task-type review --builder agy --manager agy --single-host` (automatically switches from Google `gemini-4-argon-high` to Anthropic `claude-opus-5-5-high` hosted inside `agy`!).
- **External CLI read-only:** `python <skill>/scripts/agent_run.py run --agent agy --brief brief.md --mode read --model gemini-4-argon-high`
- **External CLI write, with scope:** add `--mode write --may-write src/foo/ docs/x.md`. Anything changed outside that list is reported in `meta.json` `violations`.
- **Direct artifact handoff:** add `--context-file <upstream_artifact_path>` so the worker reads upstream findings first-hand.
- **Resume:** `--resume <conversation_id>` (from `meta.json` `session_id`).
- **Measured overhead (CLI):** a trivial CLI call costs about 19.5–22k tokens. Use native `invoke_subagent` for small in-session tasks, and `agent_run.py --agent agy` when calling from Codex/Claude or when you want headless schema-checked runs.

## Models on this machine (`agy models`, updated 2026-10-24, `agy 1.4.4`)
- **Google family:**
  - Frontier: `gemini-4-argon-high`
  - Standard: `gemini-4-argon-medium`, `gemini-3.8-flash-high`
  - Fast: `gemini-3.8-flash-low`, `gemini-4-argon-low`
- **Anthropic family (hosted on `agy`):**
  - Frontier Max / Frontier: `claude-opus-5-5-high`, `claude-opus-5-5-medium`, `claude-sonnet-5-5-high`
  - Standard: `claude-sonnet-5-5-medium`
- **Open-weights:** `gpt-oss-120b-medium`
- Note: `gemini-3.1-pro-*` and `gemini-3.6/3.7-*` were retired in `agy 1.4.4`. `assets/models.json` maps `standard` → `gemini-4-argon-medium`, `frontier` → `gemini-4-argon-high`, and `frontier_max` → `claude-opus-5-5-high`.

## Headless CLI permissions & pitfalls
- Headless print mode (`agy -p`) cannot prompt, so any tool that needs confirmation is auto-denied. `agent_run.py` counts `auto-denied` in stderr and maps empty responses with denials to `permission`.
- Name exact absolute file paths in the brief (or pass `--context-file <path>`), as `agent_run.py` automatically passes `--add-dir` for the attempt folder.
- With `--json-schema`, `agy` returns `structured_output` alongside `response`. `agent_run.py` prefers `structured_output` and strips injected `toolAction`/`toolSummary` keys automatically.
