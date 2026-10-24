# Team Shapes & Stigmergic Collaboration

Pick the lightest shape that fits the job. Combine two shapes when a job has distinct phases (for example **Explorer fan-out → Builder + Reviewer**), and connect them through the **Shared Blackboard** (`--context-file` or `.orch/` artifacts) so downstream agents read upstream discoveries first-hand without lossy manager translation.

## 0. Solo (default)
- **Use when:** delegation fails the economic gate (the brief costs as much as doing the work, or the task takes <3 tool calls).
- **Structure:** the manager does the work directly.
- **Cost:** lowest. Most routine tasks belong here.

## 1. Scout / Explorer fan-out (parallel intelligence & sensemaking)
- **Use when:** broad reading, codebase mapping, or open-ended research splits into independent territories or perspectives.
- **Two flavors:**
  - **Scout fan-out (`tight` brief, fast/standard tier):** 2–5 read-only scouts answer concrete questions across disjoint directories or docs.
  - **Sensemaking / Explorer fan-out (`exploratory` brief, standard/frontier tier):** 2–3 explorers investigate an ambiguous system or phenomenon from different angles, actively looking for **unknown unknowns** and challenging initial assumptions (`assumptions_challenged`).
- **Watch for:** overlapping write scopes (explorers stay read-only or write only to their own `.orch/` scratch file).

## 2. Builder + Reviewer (generator–verifier with direct handoff)
- **Use when:** any non-trivial code, math, or document change matters.
- **Structure:**
  - One builder owns all writes in the target scope.
  - One reviewer with a clean context checks the diff and reads the builder's `handoff_notes` / artifact directly (`--context-file`), returning findings ranked by severity.
  - The builder (resumed via `--resume` or `SendMessage`) or the manager applies one targeted revision.
- **Model:** use a different **model family** for the reviewer (`route.py --task-type review --builder <vendor>`). A clean context plus a different model family catches blind spots the builder's family rationalizes away.

## 3. Smart friend / Peer consult (advisory escalation)
- **Use when:** one hard judgment sits inside otherwise routine work (an algorithm choice, a tricky statistical check, an API contract).
- **Structure:** send a compact `exploratory` brief + relevant `--context-file` to a frontier model from another family (`gpt-6-astra`, `gemini-4-argon-high`, `claude-opus-5-5-high` / `opus`). The friend advises and challenges premises; it never writes production files.

## 4. Competing hypotheses (scientific debugging)
- **Use when:** root-cause debugging where the cause is unclear and anchoring on the first plausible theory is the main danger.
- **Structure:**
  - 2–4 read-only investigators, one hypothesis each (`exploratory` brief).
  - Each investigator must try both to **prove its own hypothesis with an empirical probe** AND to **falsify the rival hypotheses**.
  - If an investigator finds that *all* listed hypotheses are wrong and discovers the true cause elsewhere, it reports that in `assumptions_challenged`.

## 5. Frozen-interface pipeline & Isolated workspaces (parallel writers)
- **Use when:** a multi-module build where modules have clean boundaries.
- **Structure:**
  1. The manager (or an Architect) freezes the interface contract in a shared artifact (`.orch/interface-spec.md`).
  2. Builders receive the spec via `--context-file` and work on disjoint `--may-write` scopes:
     - In a shared working tree: `agent_run.py batch` runs read-only scouts in parallel, then writers sequentially so git attribution stays exact.
     - For truly parallel writers: give each worker an isolated git worktree (`isolation: "worktree"` in Claude, `--worktree` in Codex, or `Workspace: "branch"|"share"` in Antigravity `invoke_subagent`).
  3. The manager integrates, runs the full test suite, and reviews the integration seams.

## 6. Interactive Peer Mesh (native multi-agent messaging, when supported)
- **Use when:** 2–3 specialists (e.g., Frontend + Backend, or Theorist + Empirical Tester) need rapid back-and-forth alignment on a live interface without routing every sentence through the manager.
- **How:**
  - On Antigravity: spawn subagents via `invoke_subagent` and let them exchange targeted messages with `send_message` (or coordinate via shared artifacts).
  - On Claude Code: use Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) when enabled.
  - **Guardrail:** bound the exchange (explicit finish line and turn limit) so peer chat never turns into an unbounded debate.

## 7. Single-Host Orthogonal Expert Council (`Diverge → Falsify → Probe → Synthesize → Plan`)
- **Use when:**
  - Only **one agent** is available on the machine (e.g., only Antigravity `agy`, without `claude` or `codex`), OR
  - You face a complex real-world design, refactor, or investigation where your current conversation tokens risk biasing you into a narrow single-track plan or overconfident wrong conclusion.
- **Structure (`references/multi-perspective-and-single-host.md`):**
  1. **Diverge (Zero-Prior Briefs):** Spawn 2–4 clean-context sub-agents in parallel (`define_subagent` + `invoke_subagent` on `agy`, parallel `Agent()` on Claude, or `--single-host` via `route.py`). Strip your own unverified hunch from the brief and assign each sub-agent an **opposing Expert Lens**:
     - *First-Principles Architect* (invariants, clean boundaries, long-term evolution)
     - *Adversarial Red-Team Falsifier* (hunt hidden assumptions, edge cases, security/concurrency traps)
     - *Pragmatic Simplicity Minimalist* (smallest blast radius, delete unnecessary complexity)
     - *Runtime & Failure-Mode Engineer* (latency, memory, I/O, partial failure, instant rollback)
  2. **Falsify & Probe:** Require every sub-agent to cite `file:line` and answer what would prove its own proposal wrong. Run a 2-minute empirical command/spike on any factual crux.
  3. **Synthesize & Plan:** Build a quick Trade-off Matrix across the approaches, synthesize the best **Option C**, and output a phased MECE implementation plan with a clear **Reversal Trigger**.

## Choosing quickly

| Situation | Shape | Brief Mode |
|---|---|---|
| Few steps, context already in your head | Solo | n/a |
| "Find X across many places" | Scout fan-out | `tight` |
| "Map this unfamiliar architecture / find what we're missing" | Explorer fan-out | `exploratory` |
| "Explore multiple directions & de-bias before planning (even on 1 agent)" | Single-Host Orthogonal Expert Council | `exploratory` |
| "Change this and make sure it's solid" | Builder + Reviewer | `guided` |
| One hard scientific/architectural call inside routine work | Smart friend | `exploratory` |
| "Why is this broken?" with multiple plausible causes | Competing hypotheses | `exploratory` |
| Large build with separable modules | Frozen-interface pipeline | `guided` |
| Hard, irreversible or cross-cutting decision | Huddle (`huddle.md`), then one of the shapes above | `exploratory` |
