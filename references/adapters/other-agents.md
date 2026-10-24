# Adapter: Other Agents (porting guide)

The core skill is platform-neutral. To run it elsewhere, map these primitives: **spawn worker, choose model, restrict tools, cap turns and time, run in parallel, isolate writes, resume, structured result**. Facts below come from official docs as of 2026-09; verify them before relying on details.

## Skill portability (Agent Skills open standard)
- **Spec:** https://agentskills.io/specification
  - A skill is a folder containing `SKILL.md` and optionally `scripts/`, `references/` and `assets/`.
  - Required frontmatter: `name` (≤64 characters, lowercase letters, digits and hyphens, matching the folder name) and `description` (≤1024 characters).
  - Optional frontmatter: `license`, `compatibility`, `metadata`, `allowed-tools`.
  - Keep the body under about 5k tokens and 500 lines, with references one level deep.
- **Where tools look for skills:**

| Tool | User scope | Project scope |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex CLI | `~/.agents/skills/` | `.agents/skills/` (cwd, parent, repo root) |
| Windsurf / Devin Desktop | `~/.codeium/windsurf/skills/`; also reads `~/.agents/skills/` | `.windsurf/skills/`, `.agents/skills/`, `.claude/skills/` |
| Cursor | `~/.cursor/skills/` (verify) | `.cursor/skills/` (verify) |
| Gemini CLI | `~/.gemini/skills/` | `.gemini/skills/` |
| Antigravity CLI (`agy`) | `~/.gemini/config/skills/` (verified 2026-09-17; the `~/.gemini/antigravity-cli/skills/` path one doc page lists was **not** loaded) | `.agents/skills/` |

- **`~/.agents/skills/` is the most portable location.** Keep one source copy and sync it to the others.
- **Always-on instruction files:**
  - `AGENTS.md` is read by Codex, Cursor CLI and Windsurf. Codex caps it at 32 KiB by default.
  - Claude Code reads `CLAUDE.md`; Gemini CLI reads `GEMINI.md`.
  - Keep them short, and move workflow detail into skills, which load on demand.

## Cursor
- **Subagents:** markdown with YAML frontmatter in `.cursor/agents/`, `.claude/agents/` or `.codex/agents/`, at project or user (`~/`) scope.
  - Built-in subagents: `explore`, `bash`, `browser`.
  - `model`: `inherit`, or a model id with inline options, for example `claude-opus-5[effort=high]`.
- **Parallel:** several Task calls in one message. `is_background` lets a subagent run asynchronously.
- **Cost (documented):** five parallel subagents cost about 5x the tokens, and subagents start slower. For single-shot tasks, prefer skills or commands over subagents.
- **Isolation:**
  - worktrees (one branch and working directory per task);
  - Cloud Agents (isolated VMs, run in parallel);
  - `/multitask` auto-splits a request across async subagents. Apply the WIP limit anyway.
- **Plan Mode:** Shift+Tab produces an editable markdown plan. Use it for the plan-first gate.
- Docs: https://cursor.com/docs/subagents, https://cursor.com/docs/skills, https://cursor.com/docs/configuration/worktrees

## Windsurf (Cascade) / Devin
- Cascade provides skills (Devin skills format), workflows (`.windsurf/workflows/`), rules, `AGENTS.md` (directory-scoped), local memories, parallel Cascade sessions with git worktrees, and a built-in retrieval subagent ("Fast Context") that protects the main context.
- There is no general user-defined subagent system comparable to Cursor's (as of this check). Run shapes as parallel sessions in worktrees, with you as the manager.
- **Devin managed child sessions:**
  - The parent splits the work into scoped pieces.
  - Each child gets "a clean slate, a narrow focus, its own shell, and its own test runner", and verifies its own work before reporting.
  - The parent can message, monitor (in ACUs), pause or terminate a child.
  - Playbooks work like reusable briefs; Knowledge works like persistent memory.
- Docs: https://docs.devin.ai/desktop/cascade/skills, https://docs.windsurf.com/windsurf/cascade/agents-md, https://cognition.com/blog/devin-can-now-manage-devins

## Google
### Gemini CLI
- **Subagents:** `.gemini/agents/*.md` or `~/.gemini/agents/*.md`.
  - Fields: `name`, `description`, `tools` (wildcards allowed), `model`, `temperature`, `max_turns` (default 30), `timeout_mins` (default 10).
  - Invoke with `@agent_name`. Enable with `enableAgents`.
- **Headless worker:** `gemini -p "<brief>" --output-format json` returns the response plus usage stats; `stream-json` streams events instead. Use it like `codex exec`: brief in, then read the envelope.
- Docs: https://geminicli.com/docs/core/subagents/, https://geminicli.com/docs/cli/headless/, https://geminicli.com/docs/cli/skills/

### Google ADK (framework patterns, useful when building your own orchestrator)
- **Primitives:** `SequentialAgent`, `ParallelAgent`, `LoopAgent`, plus LLM-driven transfer (`sub_agents`) or `AgentTool` (the sub-agent behaves as a single function call and returns a result, which matches our worker model).
- **Patterns and how they map to this skill:**

| ADK pattern | This skill |
|---|---|
| Parallel fan-out/gather | Scout fan-out |
| Generator-Critic | Builder + Reviewer |
| Coordinator/Dispatcher | Manager plus the model gate |
| Sequential pipeline | Frozen-interface pipeline |
| Human-in-the-loop | Escalate to user |

- **Shared state:**
  - `session.state` is the shared whiteboard.
  - Parallel workers must use **unique output keys** to avoid races. In this skill, give every worker a unique output path.
  - Loops need `max_iterations` plus an early exit, which matches our revision cap.
- **Context:** token-triggered compaction, context caching with a `min_tokens` threshold, and passing the narrowest context object.
- Docs: https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/, https://google.github.io/adk-docs/context/compaction/

### Antigravity CLI (`agy`)
Headless worker details (flags, permissions, parsing, measured cost and quality) moved to `antigravity-cli.md`. Call it through `scripts/agent_run.py --agent agy`.

### Antigravity / Jules (IDE and cloud)
- **Antigravity Manager view:** up to 5 parallel agents.
  - Each agent produces **artifacts** (plan, task list, diffs, screenshots, recordings), and the artifacts are the review surface.
  - Feedback is left inline on artifacts, asynchronously, without stopping the agent.
- **Jules:** shows an editable plan before editing; `--parallel` runs several tasks at once.
- **Lesson adopted:** review artifacts, not transcripts. Workers put plans, diffs and evidence in files, and the manager reviews those files.
- Docs: https://antigravity.google/docs/artifacts/, https://developers.google.com/jules/api

## Minimal port checklist
1. Put the skill folder where the tool looks for skills (see the table above).
2. Map "spawn worker" to the tool's subagent, child session or headless CLI.
3. Map budget caps to the tool's native limits (`maxTurns`, `max_turns`/`timeout_mins`, a wrapper timeout).
4. Map isolation to worktrees, sandboxes or VMs.
5. Keep the result envelope (`assets/result.schema.json`) as the common contract. Enforce it natively if the tool supports schemas; otherwise ask for it in the brief and validate it yourself.
6. Update the model mapping table in `gates-and-routing.md` with the tool's own models.
