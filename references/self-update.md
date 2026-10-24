# Self-update & Dynamic Model Selection

Agents evolve rapidly: new models (`claude-opus-5-5`, `nghi/claude-opus-5[1m]`, `gpt-6.1-sol`, `gemini-4-argon-high`), new CLI flags (`--bare`, `--worktree`, `--search`), new MCPs, and new skills. This skill discovers them at **zero token cost** and automatically selects the best live discovered model for each tier without waiting for manual edits to `assets/models.json`.

## Where things live
| What | Where | Owner |
|---|---|---|
| Live machine snapshot (`capabilities.json`), human-readable view + auto-selected tier matrix (`capabilities.md`), diff log (`changes.md`) | `~/.agent-orchestration/` (`AO_HOME`), shared by every installed copy | `scripts/discover.py` |
| Dynamic model scorer & selector (`dynamic_tier_config`) | `scripts/ao_common.py` (used by `route.py` and `agent_run.py`) | Automatic from live `capabilities.json` |
| Baseline fallback tiers & task routing rules | `assets/models.json` in the skill | Fallback when `capabilities.json` is absent |
| Newly discovered models log (`candidates.json`) | `~/.agent-orchestration/candidates.json` | `scripts/discover.py` |
| Manager verdicts (`ledger.jsonl`) | `~/.agent-orchestration/ledger.jsonl` | `scripts/agent_run.py` |

## How Dynamic Model Discovery Works (`discover.py` -> `route.py`)
1. **Zero-token live probing (`python <skill>/scripts/discover.py`):**
   - **Codex CLI (`codex`):** Scans `~/.codex/.codex-global-state.json` (recent models and `seen-model-upgrade-list` like `gpt-6-astra`, `gpt-6.1-sol`, `gpt-5.6-sol`, `gpt-5.6-terra`), `~/.codex/models_cache.json`, `~/.codex/skills/.system/openai-docs/references/latest-model.md`, and `~/.codex/config.toml`.
   - **Claude Code CLI (`claude`):** Scans `~/.claude/settings.json` (`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, etc.), `~/.claude/cache/gateway-models.json` (`nghi/claude-opus-5[1m]`, `nghi/claude-sonnet-5[1m]`), and `~/.claude/cache/model-catalog/*-ccd.json` (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-fable-5-1`, `claude-haiku-5-5`).
   - **Antigravity CLI (`agy`):** Runs `agy models` (`gemini-4-argon-{low,medium,high}`, `gemini-3.8-flash-*`, `claude-opus-5-5-*`, `claude-sonnet-5-5-*`).
2. **Dynamic Scoring & Tier Selection (`ao_common.dynamic_tier_config`):**
   - Whenever `route.py` or `agent_run.py --tier <T>` runs, it reads the live discovered models for that agent from `capabilities.json`, scores them by capability family, version number, and context window (e.g. `[1m]`), and picks the optimal live model for `fast`, `standard`, `frontier`, or `frontier_max` (`model_source: dynamic_discovered`).
   - `assets/models.json` serves only as the fallback baseline if `discover.py` has never been run on the machine.

## The protocol
1. **Start of an orchestration session, at most once a day:** `python <skill>/scripts/discover.py --quick`. It runs only the `--version` probes (zero tokens) and prints one line.
   - exit 0: nothing changed. Carry on.
   - exit 10: a version changed, or there is no snapshot yet. Run `python <skill>/scripts/discover.py`, then read **only the newest section of `~/.agent-orchestration/changes.md`**, not the whole file.
2. **Full probe (`discover.py`, zero tokens):** `--version`, `--help`, `exec --help`, `features list`, `models`, `mcp list`, `plugin list` per agent, plus the skill folders of each harness and agy's plugin folder. It diffs against the last snapshot and appends what is new or gone (flags, subcommands, models, MCP servers, plugins, features, skills, versions). A run with no change appends nothing.
3. **Before delegating anything unusual** (media, browser, web, a specific service): `python <skill>/scripts/route.py --need <keyword>`. It searches what each agent advertises. If nothing matches it says so and points to the next step.
4. **Deep discovery (costs tokens, ask the user first):** built-in tools such as a video generator often do not appear in `--help`. `python <skill>/scripts/discover.py --deep <agent> --yes` sends one read-only fast-tier call (about 12-20k tokens) asking the agent to list its tools, and stores the list as `self_report` in `capabilities.json`. Do this once when a `--need` search finds nothing, or when an agent's version jumps, not routinely. Treat the list as a claim: try the tool once on a small job before relying on it.

## Promotion rules (never automatic)
- **New model** (in `candidates.json`): it does not enter routing on its own. Promote it only after either a person says so or a measured trial: run one real task of a known type on it, judge the result with `agent_run.py verdict`, and compare its accept rate and tokens with the current tier holder. Then edit `assets/models.json` and mirror the table in `gates-and-routing.md`. Remove the entry from `candidates.json` if you like; it is not read by routing.
- **New tool or capability:** searchable through `route.py --need` and listed in `capabilities.md` right away. Using it for real work follows the normal gates.
- **Removed or renamed model or flag:** if `models.json` names it, fix `models.json` at once (a stale slug fails with `model_or_config`).
- **A fact in the skill that a probe contradicts** (a path, a flag, a default): update the doc, with the date and how you verified it. Measured facts in the docs win over a guess and lose to a fresh measurement.
- Editing `~/.codex/config.toml`, `~/.gemini/...settings.json` or plugin hooks always needs the user's approval.

## Files, for reference
`capabilities.md` (read this one, it is short), `capabilities.json` (full flag lists), `changes.md` (append-only), `state.json` (last quick check time), `deep/` (deep-discovery briefs and runs).
