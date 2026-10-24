"""Shared helpers for agent_run.py, route.py and discover.py (stdlib only).

State folder (shared by every installed copy of the skill): %USERPROFILE%\\.agent-orchestration
(override with AO_HOME): ledger.jsonl, capabilities.json, capabilities.md, changes.md.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
MODELS_JSON = SKILL_DIR / "assets" / "models.json"
VENDORS = ("codex", "agy", "claude")
_lock = threading.Lock()
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def ao_home():
    p = Path(os.environ.get("AO_HOME") or (Path.home() / ".agent-orchestration"))
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_models():
    return json.loads(MODELS_JSON.read_text(encoding="utf-8"))


def _ver_key(p):
    m = re.search(r"(\d+\.\d+\.\d+)", str(p))
    if m:
        return [int(x) for x in m.group(1).split(".")]
    return [int(x) for x in re.findall(r"\d+", str(p))] or [0]


def resolve_exe(vendor):
    """argv prefix for a vendor CLI, or None. AO_<VENDOR> overrides it (parts joined by '|'), which
    is how tests point at fake agents."""
    env = os.environ.get("AO_" + vendor.upper())
    if env:
        return env.split("|")
    hit = shutil.which(vendor)
    if hit:
        return [hit]
    if vendor == "agy":
        base = os.environ.get("LOCALAPPDATA")
        cand = [Path(base) / "agy" / "bin" / "agy.exe"] if base else []
    elif vendor == "claude":
        cand, globs = [], []
        appdata = os.environ.get("APPDATA")
        localapp = os.environ.get("LOCALAPPDATA")
        if localapp:
            globs += glob.glob(str(Path(localapp) / "Claude-Data" / "claude_*" / "claude-code" / "*" / "*" / "claude.exe"))
            globs += glob.glob(str(Path(localapp) / "Claude-Data" / "claude_*" / "claude-code" / "*" / "claude.exe"))
            globs += glob.glob(str(Path(localapp) / "Claude-3p" / "claude-code" / "*" / "claude.exe"))
            globs += glob.glob(str(Path(localapp) / "Claude" / "claude-code" / "*" / "claude.exe"))
        if appdata:
            globs += glob.glob(str(Path(appdata) / "Claude" / "claude-code" / "*" / "claude.exe"))
        if globs:
            found = sorted(globs, key=_ver_key)
            cand += [Path(f) for f in reversed(found)]
        cand += [Path.home() / ".local" / "bin" / n for n in ("claude.exe", "claude")]
    elif vendor == "codex":
        localapp = os.environ.get("LOCALAPPDATA")
        cand = []
        if localapp:
            found = sorted(glob.glob(str(Path(localapp) / "OpenAI" / "Codex" / "bin" / "*" / "codex.exe")))
            cand += [Path(f) for f in reversed(found)]
    else:
        cand = []
    for c in cand:
        if c.exists():
            return [str(c)]
    return None


# ---------- Real-Time Live Model Discovery (never out-of-date) ----------
def live_models_codex():
    """Inspect Codex CLI's live local state, config, and docs to list all currently available models."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("slug", "model") and isinstance(v, str) and re.match(r"^[a-z0-9][\w.\-]*$", v):
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    try:
        codex_dir = Path.home() / ".codex"
        for fn in ("models_cache.json", ".codex-global-state.json"):
            p = codex_dir / fn
            if p.exists():
                try:
                    walk(json.loads(p.read_text(encoding="utf-8", errors="replace")))
                except ValueError:
                    pass
        gs = codex_dir / ".codex-global-state.json"
        if gs.exists():
            try:
                atom = (json.loads(gs.read_text(encoding="utf-8", errors="replace")).get("electron-persisted-atom-state") or {})
                for u in atom.get("seen-model-upgrade-list") or []:
                    if isinstance(u, str):
                        found.append(u)
            except ValueError:
                pass
        doc_p = codex_dir / "skills" / ".system" / "openai-docs" / "references" / "latest-model.md"
        if doc_p.exists():
            for m in re.findall(r"^\|\s*`(gpt-[\w.\-]+)`\s*\|", doc_p.read_text(encoding="utf-8", errors="replace"), re.M):
                if not any(x in m for x in ("image", "tts", "transcribe", "realtime", "audio")):
                    found.append(m)
        cfg_p = codex_dir / "config.toml"
        if cfg_p.exists():
            cfg = cfg_p.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'^model\s*=\s*"([^"]+)"', cfg, re.M)
            if m:
                found.append(m.group(1))
    except OSError:
        pass
    return sorted(set(found))


def live_models_claude():
    """Inspect Claude Code's live model-catalog, gateway-models, and settings.json."""
    found = []
    cdir = Path.home() / ".claude"
    try:
        sp = cdir / "settings.json"
        if sp.exists():
            env = (json.loads(sp.read_text(encoding="utf-8", errors="replace")).get("env") or {})
            for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                      "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
                if env.get(k):
                    found.append(env[k])
        gp = cdir / "cache" / "gateway-models.json"
        if gp.exists():
            gdata = json.loads(gp.read_text(encoding="utf-8", errors="replace"))
            for m in gdata.get("models") or []:
                if isinstance(m, dict) and m.get("id"):
                    found.append(m["id"])
        cats = sorted(glob.glob(str(cdir / "cache" / "model-catalog" / "*-ccd.json")),
                      key=lambda x: Path(x).stat().st_mtime if Path(x).exists() else 0)
        if cats:
            cdata = json.loads(Path(cats[-1]).read_text(encoding="utf-8", errors="replace"))
            models_list = (((cdata.get("catalog") or {}).get("config") or {}).get("models")) or []
            for m in models_list:
                if isinstance(m, dict) and m.get("id"):
                    found.append(m["id"])
    except (OSError, ValueError):
        pass
    return sorted(set(found))


def live_models_agy(caps=None):
    """Return Antigravity's available models from capabilities.json or by running `agy models` live."""
    if caps:
        cached = ((caps.get("agents") or {}).get("agy") or {}).get("models")
        if cached:
            return cached
    exe = resolve_exe("agy")
    if not exe:
        return []
    try:
        r = subprocess.run(exe + ["models"], capture_output=True, timeout=15, stdin=subprocess.DEVNULL)
        text = ANSI.sub("", (r.stdout + b"\n" + r.stderr).decode("utf-8", "replace"))
        return sorted(set(re.findall(r"^([a-z0-9][\w.\-]*)[ \t]+\S", text, re.M)))
    except (OSError, subprocess.SubprocessError):
        return []


def get_available_models(vendor, caps=None):
    """Get the real-time available models for `vendor` right now (zero tokens)."""
    if os.environ.get("AO_" + vendor.upper()):  # unit-test fake agent
        return ((caps or {}).get("agents") or {}).get(vendor, {}).get("models") or []
    if vendor == "codex":
        return live_models_codex() or (((caps or {}).get("agents") or {}).get("codex") or {}).get("models") or []
    if vendor == "claude":
        return live_models_claude() or (((caps or {}).get("agents") or {}).get("claude") or {}).get("models") or []
    if vendor == "agy":
        return live_models_agy(caps)
    return []


def _extract_gen_ver(slug):
    """Extract (major, minor, patch) generation numbers from a model slug (ignoring '[1m]' or date stamps >= 20200000)."""
    clean = re.sub(r"\[.*?\]", "", slug.lower())
    nums = [int(x) for x in re.findall(r"\d+", clean) if int(x) < 20000000]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _score_model(vendor, m, tier):
    """Score a live model slug `m` for `(vendor, tier)` so the newest generation (e.g. GPT-6, Gemini 4 Argon,
    Claude Opus 5.5) always wins over older generations (GPT-5.4, Gemini 3.x, Claude 4.x)."""
    low = m.lower()
    ver = _extract_gen_ver(low)
    ctx_bonus = 1 if "[1m]" in low else 0

    if vendor == "codex":
        if tier == "fast":
            role = 4 if "luna" in low else (3 if "nano" in low else (2 if "mini" in low else (1 if "terra" in low else 0)))
            return (ver[0], role, ver[1], ver[2]) if role else None
        if tier == "standard":
            role = 4 if "sol" in low else (3 if "terra" in low else (2 if "codex" in low and "mini" not in low else 0))
            return (ver[0], role, ver[1], ver[2]) if role else None
        if tier in ("frontier", "frontier_max"):
            role = 5 if "astra" in low else (4 if "sol" in low else (3 if low in ("gpt-6", "gpt-5.6") else 0))
            return (ver[0], role, ver[1], ver[2]) if role else None

    elif vendor == "agy":
        # Prefer native Google Gemini/Argon models on agy for fast/standard/frontier so agy provides
        # true Google epistemic diversity (ver[0]=4 for Gemini 4 Argon > ver[0]=3 for Gemini 3.8 Flash).
        # Reserve hosted Claude Opus 5.5 for frontier_max or explicit override.
        is_google = 1 if ("gemini" in low or "argon" in low) else 0
        if tier == "fast":
            role = 4 if ("argon" in low and "low" in low) else (3 if "flash-low" in low else 0)
            return (is_google, ver, role) if role else None
        if tier == "standard":
            role = 5 if ("argon" in low and "medium" in low) else (4 if "flash-high" in low else (3 if ("sonnet" in low and "medium" in low) else 0))
            return (is_google, ver, role) if role else None
        if tier == "frontier":
            role = 5 if ("argon" in low and "high" in low) else (4 if "pro-high" in low else (3 if ("opus" in low and "high" in low) else 0))
            return (is_google, ver, role) if role else None
        if tier == "frontier_max":
            role = 5 if ("opus" in low and "high" in low) else (4 if ("argon" in low and "high" in low) else 0)
            return (role, ver) if role else None

    elif vendor == "claude":
        # Generation (`ver`, e.g. 5.5 > 5.0 > 4.8) is the primary key so Opus 5.5 / Haiku 5.5 beats 4.x/5.0
        if tier == "fast" and "haiku" in low:
            return (ver, ctx_bonus, 1 if "/" not in low else 0)
        if tier == "standard" and "sonnet" in low:
            return (ver, ctx_bonus, 1 if "/" not in low else 0)
        if tier == "frontier" and ("opus" in low or "fable" in low):
            role = 2 if "opus" in low else 1
            return (ver, role, ctx_bonus)
        if tier == "frontier_max" and ("opus" in low or "fable" in low):
            role = 2 if "opus" in low else 1
            return (ver, role, ctx_bonus)
    return None


def dynamic_tier_config(models, caps, vendor, tier_name):
    """Inspect currently available models of `vendor` in real time, score them by generation & tier fit,
    and pick the best model so routing is NEVER out of date."""
    static_tiers = models["vendors"][vendor]["tiers"]
    base_cfg = dict(static_tiers.get(tier_name) or static_tiers.get("frontier") or next(iter(static_tiers.values())))
    if os.environ.get("AO_" + vendor.upper()):
        return base_cfg
    live_models = get_available_models(vendor, caps)
    if not live_models:
        base_cfg["source"] = "static_fallback"
        return base_cfg
    scored = []
    for m in live_models:
        sc = _score_model(vendor, m, tier_name)
        if sc is not None:
            scored.append((sc, m))
    if not scored:
        base_cfg["source"] = "static_fallback"
        return base_cfg
    scored.sort(reverse=True)
    best_model = scored[0][1]
    top_candidates = [m for _, m in scored[:4]]
    base_cfg["model"] = best_model
    base_cfg["family"] = model_family(vendor, best_model, models)
    base_cfg["source"] = "live_discovered"
    base_cfg["available_in_tier"] = top_candidates
    base_cfg["total_live_models"] = len(live_models)
    return base_cfg


def canonical_task(raw_task, models=None):
    """Map free-form task labels (e.g. 'review-p1-model-core', 'judge-region-v3', 'draft-doc')
    to canonical task types in models.json so Earned Autonomy never loses records."""
    if not raw_task:
        return None
    models = models or load_models()
    tasks = models.get("tasks") or {}
    aliases = models.get("task_aliases") or {}
    low = raw_task.strip().lower()
    if low in tasks:
        return low
    if low in aliases:
        return aliases[low]
    tokens = [t for t in re.split(r"[^a-z0-9]+", low) if t]
    if len(tokens) >= 2 and f"{tokens[0]}-{tokens[1]}" in tasks:
        return f"{tokens[0]}-{tokens[1]}"
    for tok in tokens:
        if tok in tasks:
            return tok
        if tok in aliases:
            return aliases[tok]
    return raw_task


def infer_tier(vendor, model_slug, models=None):
    """Infer canonical tier ('fast', 'standard', 'frontier', 'frontier_max') from model slug when omitted."""
    if not vendor or not model_slug:
        return None
    models = models or load_models()
    vcfg = (models.get("vendors") or {}).get(vendor) or {}
    tiers = vcfg.get("tiers") or {}
    for tname, tcfg in tiers.items():
        if tcfg.get("model") == model_slug:
            return tname
    low = model_slug.lower()
    if any(k in low for k in ("haiku", "flash-low", "luna", "argon-low", "nano")):
        return "fast"
    if any(k in low for k in ("fable", "opus", "astra", "argon-high", "pro-high")):
        return "frontier"
    if any(k in low for k in ("sonnet", "sol", "terra", "flash-high", "argon-medium", "flash-medium")):
        return "standard"
    return None


def model_family(vendor, model_slug=None, models=None):
    """Identify the epistemic model family ('openai', 'google', 'anthropic', 'oss') regardless of CLI wrapper."""
    models = models or load_models()
    if model_slug:
        low = model_slug.lower()
        if any(k in low for k in ("claude", "haiku", "sonnet", "opus", "fable")):
            return "anthropic"
        if any(k in low for k in ("gemini", "argon")):
            return "google"
        if "gpt-oss" in low:
            return "oss"
        if any(k in low for k in ("gpt", "codex", "o1", "o3", "o4")):
            return "openai"
    vcfg = (models.get("vendors") or {}).get(vendor) or {}
    return vcfg.get("company") or vendor


def intra_host_family_models(vendor, tier_name="frontier", models=None, caps=None):
    """Return all distinct model families hosted inside a single `vendor` (e.g. `agy` hosts Google Gemini 4 Argon,
    Anthropic Claude Opus/Sonnet 5.5, and OSS GPT-120B). Useful when only 1 agent CLI is installed on the machine."""
    models = models or load_models()
    pool = list(get_available_models(vendor, caps) or [])
    vtiers = ((models.get("vendors") or {}).get(vendor) or {}).get("tiers") or {}
    for tcfg in vtiers.values():
        if tcfg.get("model") and tcfg["model"] not in pool:
            pool.append(tcfg["model"])
    by_fam = {}
    for m in pool:
        fam = model_family(vendor, m, models)
        low = m.lower()
        ver = _extract_gen_ver(low)
        tier_fit = 3 if (tier_name in ("frontier", "frontier_max") and any(k in low for k in ("high", "opus", "astra"))) else (
            2 if (tier_name == "standard" and any(k in low for k in ("medium", "sonnet", "sol", "flash-high"))) else (
            1 if (tier_name == "fast" and any(k in low for k in ("low", "haiku", "luna", "nano"))) else 0))
        score = (tier_fit, ver)
        if fam not in by_fam or score > by_fam[fam][0]:
            by_fam[fam] = (score, m)
    return [(fam, info[1]) for fam, info in sorted(by_fam.items(), key=lambda kv: kv[1][0], reverse=True)]


def intra_host_alt_family_model(vendor, avoid_family, tier_name="frontier", models=None, caps=None):
    """When only 1 agent CLI is available, pick a model from a DIFFERENT model family hosted inside `vendor`
    (if any exist, e.g. switching from `gemini-4-argon-high` [google] to `claude-opus-5-5-high` [anthropic] on `agy`)."""
    for fam, m in intra_host_family_models(vendor, tier_name=tier_name, models=models, caps=caps):
        if fam != avoid_family:
            return m, fam
    return None, None


def expert_council_for_task(task_name):
    """Return Orthogonal Expert Lenses + Zero-Prior De-Biasing rules + Multi-Horizon Planning workflow
    so a single agent (via sub-agents) can explore problems from independent expert viewpoints without
    context contamination or premature overconfidence."""
    debias_rules = [
        "Zero-Prior (Blinded) Brief: Strip your current hypothesis/opinion from the sub-agent prompt; pass ONLY verified facts, symptoms, constraints, and file:line pointers so current conversation tokens cannot bias the sub-agent.",
        "Clean-Slate Context Isolation: Spawn each sub-agent in a fresh context (`invoke_subagent`, `Agent()`, `spawn_agent`, or CLI) so autoregressive attention does not lock onto your initial tokens.",
        "Compulsory Pre-Mortem & Falsification: Every sub-agent must state what concrete condition or `file:line` evidence would prove its own proposal/hypothesis WRONG."
    ]
    planning_workflow = [
        "1. Diverge (Parallel Zero-Prior Sub-Agents): Spawn 2-4 sub-agents with orthogonal expert lenses to map approaches (A, B, C) independently with file:line citations.",
        "2. Falsify (Adversarial Red-Team & Pre-Mortem): Challenge each approach for hidden assumptions, edge cases, and failure modes.",
        "3. Probe (2-Minute Empirical Check): Settle any factual disagreement between approaches with a quick command/test spike instead of prose debate.",
        "4. Synthesize (Trade-off Matrix -> Option C): Score approaches on root-cause fit, blast radius, risk, cost, and evidence; combine the best elements.",
        "5. Plan (MECE Execution Packages): Define ordered/parallel steps with disjoint `--may-write` scopes, checkable Definition of Done, and a Reversal Trigger."
    ]
    councils = {
        "design": [
            {"lens": "First-Principles Architect", "mandate": "Design clean boundaries, data/state invariants, and long-term evolution paths.", "falsify": "Where does coupling or state drift break this structure at scale?"},
            {"lens": "Adversarial Red-Team Falsifier", "mandate": "Break the proposed design; hunt hidden assumptions, race conditions, security holes, and worst-case inputs.", "falsify": "What single assumption, if false in the real codebase, invalidates the plan?"},
            {"lens": "Pragmatic Simplicity Minimalist", "mandate": "Solve the root problem with the smallest possible blast radius and zero over-engineering, reusing existing code.", "falsify": "Which proposed components can be deleted while still achieving 100% of the user's goal?"},
            {"lens": "Runtime & Failure-Mode Engineer", "mandate": "Audit latency, memory, I/O bottlenecks, migration safety, and instant rollback paths.", "falsify": "How does the system behave when an upstream call times out or fails halfway?"}
        ],
        "explore": [
            {"lens": "Architecture & Data-Flow Mapper", "mandate": "Trace end-to-end control flow, entry points, and state mutations with exact file:line anchors.", "falsify": "What implicit caller or side channel bypasses the main path?"},
            {"lens": "Adversarial Edge-Case & Debt Hunter", "mandate": "Find unknown unknowns, fragile assumptions, tech debt, and silent failure modes.", "falsify": "What looks working on the surface but fails under boundary conditions?"},
            {"lens": "Pragmatic Solution Strategist", "mandate": "Identify 2-3 distinct implementation directions and compare their blast radius and leverage.", "falsify": "Why might the most obvious approach be a local trap?"}
        ],
        "debug": [
            {"lens": "Primary Hypothesis Prover/Falsifier", "mandate": "Test the leading root-cause hypothesis using direct code trace (`file:line`) and minimal reproduction.", "falsify": "What evidence in the logs or code contradicts this hypothesis?"},
            {"lens": "Rival Hypothesis & State Auditor", "mandate": "Assume the first hypothesis is a red herring; investigate state mutation, concurrency, env/config, and upstream callers.", "falsify": "Can the exact symptom be reproduced even when the primary suspect is bypassed?"},
            {"lens": "Empirical Probe & Fix Minimalist", "mandate": "Construct a deterministic test/command that proves the root cause and verify the minimal safe fix.", "falsify": "Does the fix merely mask the symptom instead of curing the root cause?"}
        ],
        "review": [
            {"lens": "Correctness & Invariant Auditor", "mandate": "Verify logic against Definition of Done, data invariants, boundary conditions, and test adequacy.", "falsify": "What input or state transition causes a wrong result or regression?"},
            {"lens": "Adversarial Security & Failure Skeptic", "mandate": "Audit trust boundaries, permissions, error handling, resource leaks, and failure cascades.", "falsify": "How can untrusted input or partial failure corrupt state?"},
            {"lens": "Simplicity & Contract Critic", "mandate": "Check cross-module interface contracts, dead code, and unnecessary complexity.", "falsify": "Did this diff break an unspoken assumption of an adjacent caller?"}
        ],
        "critique": [
            {"lens": "First-Principles Architect", "mandate": "Evaluate structural soundness, invariants, and synthesize a stronger Option C.", "falsify": "What false dichotomy is the current framing locked into?"},
            {"lens": "Adversarial Red-Team Falsifier", "mandate": "Try to disprove the leading option with hard repo evidence (`file:line`) or empirical counterexamples.", "falsify": "What is the fatal flaw everyone is being too polite or anchored to notice?"},
            {"lens": "Domain & Pragmatic Realist", "mandate": "Assess scientific/domain validity, implementation cost, and user-facing impact.", "falsify": "Does this solve the real problem or an imaginary theoretical one?"}
        ]
    }
    councils["security-review"] = councils["review"]
    lenses = councils.get(task_name) or councils["explore"]
    return {"lenses": lenses, "debias_rules": debias_rules, "planning_workflow": planning_workflow}


def build_same_model_council(task_name, problem_text, agent="agy", model_slug=None, effort=None,
                             out_dir=None, context_files=None):
    """Generate a complete Same-Model De-Biased Expert Council package (`.orch/council-<ts>/`).
    Allows a single agent using a SINGLE model (e.g. `Model='inherit'` or one active model) to run
    2-4 independent sub-agents with Zero-Prior Briefs and Orthogonal Expert Lenses."""
    models = load_models()
    canon_t = canonical_task(task_name, models) or "explore"
    council = expert_council_for_task(canon_t)
    if not model_slug:
        dcfg = dynamic_tier_config(models, {}, agent, "frontier")
        model_slug = dcfg.get("model") or "inherit"
        if not effort:
            effort = dcfg.get("effort")
    out_path = Path(out_dir) if out_dir else (Path.cwd() / ".orch" / f"council-{time.strftime('%Y%m%d-%H%M%S')}-{canon_t}")
    out_path.mkdir(parents=True, exist_ok=True)

    brief_paths = []
    batch_pkgs = []
    native_calls = []
    for idx_l, lobj in enumerate(council["lenses"], 1):
        slug = re.sub(r"[^a-z0-9]+", "-", lobj["lens"].lower()).strip("-")
        bpath = out_path / f"lens-{idx_l}-{slug}.md"
        sys_prompt = (
            f"You are operating under the '{lobj['lens']}' expert lens. "
            f"Mandate: {lobj['mandate']} "
            f"You have a clean context window intentionally isolated from the lead agent's prior token bias. "
            f"Do NOT agree politely or assume the problem framing is flawless. "
            f"Every claim, finding, and conclusion MUST cite verifiable ground-truth evidence (`file:line-line`, "
            f"`command -> exit/output`, or measured numbers in `evidence[]`). "
            f"You MUST answer this falsification question with evidence: '{lobj['falsify']}'"
        )
        btext = (
            f"# Zero-Prior Expert Lens Brief ({lobj['lens']})\n\n"
            f"## Role & Orthogonal Expert Lens\n"
            f"- **Lens:** {lobj['lens']}\n"
            f"- **Accountable Mandate:** {lobj['mandate']}\n"
            f"- **Mandatory Pre-Mortem / Falsification Question:** *{lobj['falsify']}*\n"
            f"- **De-Biasing Rule:** This brief intentionally omits the manager's unverified hunches so your KV-cache remains uncontaminated. Form your own independent conclusion strictly from code/data evidence.\n\n"
            f"## Core Problem, Symptoms & Verified Facts\n"
            f"{problem_text.strip()}\n\n"
            f"## Exploration & Anti-Hallucination Rules\n"
            f"- Follow evidence across the codebase (`file:line-line`).\n"
            f"- If any premise in the problem statement is contradicted by actual code/data, record it in `assumptions_challenged` with proof.\n"
            f"- Return the JSON result envelope (`status`, `summary`, `confidence`, `deliverables`, `evidence`, `assumptions_challenged`, `open_questions`, `risks`, `next_action`).\n"
        )
        bpath.write_text(btext, encoding="utf-8")
        brief_paths.append(str(bpath))

        pkg = {
            "name": f"lens-{idx_l}-{slug}",
            "agent": agent,
            "model": model_slug,
            "brief": str(bpath),
            "mode": "read",
            "task_type": canon_t,
            "risk": "med",
            "tier": "frontier",
            "context_file": list(context_files or [])
        }
        if effort:
            pkg["effort"] = effort
        batch_pkgs.append(pkg)

        if agent == "agy":
            native_calls.append({
                "lens": lobj["lens"],
                "define_subagent": {
                    "Name": f"expert-{slug}",
                    "Description": f"{lobj['lens']}: {lobj['mandate']}",
                    "SystemPrompt": sys_prompt,
                    "EnableWriteTools": False
                },
                "invoke_subagent": {
                    "TypeName": f"expert-{slug}",
                    "Role": lobj["lens"],
                    "Model": "inherit",
                    "Workspace": "inherit",
                    "Prompt": btext
                }
            })
        elif agent == "claude":
            native_calls.append({
                "lens": lobj["lens"],
                "Agent": {
                    "subagent_type": "general-purpose",
                    "description": lobj["lens"],
                    "model": model_slug if model_slug in ("haiku", "sonnet", "opus") else "opus",
                    "prompt": btext
                }
            })
        else:
            native_calls.append({
                "lens": lobj["lens"],
                "spawn_agent": {
                    "role": lobj["lens"],
                    "model": model_slug,
                    "prompt": btext
                }
            })

    batch_file = out_path / "batch_plan.json"
    batch_file.write_text(json.dumps({"wip": len(batch_pkgs), "same_model": model_slug, "packages": batch_pkgs}, indent=2), encoding="utf-8")

    native_file = out_path / "native_subagents.json"
    native_file.write_text(json.dumps({
        "agent": agent,
        "same_model": model_slug,
        "note": "Launch these sub-agents in parallel in a single turn. All use the SAME model with clean KV-cache isolation and orthogonal expert lenses.",
        "subagents": native_calls
    }, indent=2), encoding="utf-8")

    synth_file = out_path / "synthesis_plan_template.md"
    lens_headers = " | ".join(f"Approach {i} ({l['lens']})" for i, l in enumerate(council["lenses"], 1))
    lens_sep = " | ".join("---" for _ in council["lenses"])
    synth_file.write_text(
        f"# Multi-Horizon Synthesis & Implementation Plan ({canon_t})\n\n"
        f"## 1. Diverge Summary (Independent Clean-Context Sub-Agents on Same Model `{model_slug}`)\n"
        + "\n".join(f"- **{l['lens']}:** <key finding + file:line evidence>" for l in council["lenses"]) + "\n\n"
        f"## 2. Falsification & Pre-Mortem (`assumptions_challenged`)\n"
        f"- **Premises disproved by code/data:** <list with file:line>\n"
        f"- **Fatal flaws exposed by Red-Team / Minimalist:** <list>\n\n"
        f"## 3. Empirical Probe Gate (2-Minute Tie-Breaker)\n"
        f"- **Crux tested:** <command run -> measured output>\n\n"
        f"## 4. Multi-Criteria Trade-Off Matrix & Option C Synthesis\n\n"
        f"| Criterion | {lens_headers} | Synthesized Option C (Chosen) |\n"
        f"| --- | {lens_sep} | --- |\n"
        f"| **Root-Cause Fit** | | |\n"
        f"| **Blast Radius (Files)** | | |\n"
        f"| **Failure / Regression Risk** | | |\n"
        f"| **Key Evidence (`file:line`)** | | |\n\n"
        f"## 5. Actionable MECE Execution Plan\n"
        f"1. **Package 1 (`--may-write <paths>`):** <objective + Definition of Done test>\n"
        f"2. **Package 2 (`--may-write <paths>`):** <objective + Definition of Done test>\n"
        f"- **Reversal Trigger:** <observable signal during implementation that triggers an immediate pivot>\n",
        encoding="utf-8"
    )
    return {
        "council_dir": str(out_path),
        "agent": agent,
        "same_model": model_slug,
        "task_type": canon_t,
        "brief_files": brief_paths,
        "batch_plan": str(batch_file),
        "native_subagents": str(native_file),
        "synthesis_template": str(synth_file),
        "lenses": [l["lens"] for l in council["lenses"]]
    }



def check_evidence_citations(obj):
    """Verify that conclusion/summary and any assumptions_challenged have concrete evidence backing
    (e.g. file:line, command output, URL, or [E1] references). Returns a list of grounding warnings."""
    if not isinstance(obj, dict):
        return []
    warnings = []
    ev = obj.get("evidence") or []
    status = obj.get("status")
    if status == "done" and not ev:
        warnings.append("status is 'done' but `evidence` is empty (every conclusion requires verifiable proof)")
    anchor_re = re.compile(r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+:\d+|https?://|`[^`]+`|\b\d+(\.\d+)?%|\bexit\s+\d+|\bline\s+\d+|\[E\d+\])", re.I)
    if ev and not any(anchor_re.search(str(x)) for x in ev):
        warnings.append("`evidence` items lack concrete anchors (expected `file:line`, `command -> output`, measured numbers, or URL)")
    for ch in obj.get("assumptions_challenged") or []:
        if not anchor_re.search(str(ch)) and not ev:
            warnings.append(f"`assumptions_challenged` claim lacks concrete proof or spike citation: {str(ch)[:80]}")
    return warnings


def is_bad_root(p):
    p = Path(p).resolve()
    return p == Path.home().resolve() or p == p.parent or p == Path(p.anchor)


def session_path(agent, sid):
    d = ao_home() / "sessions"
    return d / (re.sub(r"[^A-Za-z0-9_.-]", "_", f"{agent}-{sid}") + ".json")


def save_session(agent, sid, manifest):
    """What a session was allowed to do, so a resume cannot quietly widen it."""
    if not sid:
        return False
    try:
        p = session_path(agent, sid)
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(manifest), encoding="utf-8")
        return True
    except OSError:
        return False


def load_session(agent, sid):
    try:
        return json.loads(session_path(agent, sid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ledger_path():
    return ao_home() / "ledger.jsonl"


def ledger_append(rec):
    rec = {"t": now(), **rec}
    try:
        with _lock, open(ledger_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def ledger_read():
    p = ledger_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def verdict_stats(recs, task_type=None, vendor=None, tier=None, project=None, window=None):
    """Verdict counts for one slice of the ledger. Earned autonomy counts manager verdicts only,
    never the worker's own status. Canonicalizes task_type and infers missing tier for historical entries."""
    models = load_models()
    target_task = canonical_task(task_type, models) if task_type else None
    v = []
    for r in recs:
        if r.get("type") != "verdict":
            continue
        rtask = canonical_task(r.get("task_type"), models)
        rtier = r.get("tier") or infer_tier(r.get("agent"), r.get("model"), models)
        if target_task is not None and rtask != target_task:
            continue
        if vendor is not None and r.get("agent") != vendor:
            continue
        if tier is not None and rtier != tier:
            continue
        if project is not None and project not in (r.get("project") or ""):
            continue
        v.append(r)
    v = v[-window:] if window else v
    accepts = sum(1 for r in v if r["verdict"] == "accept")
    streak = 0
    for r in reversed(v):
        if r["verdict"] != "accept":
            break
        streak += 1
    return {"n": len(v), "accepts": accepts, "streak": streak,
            "rate": (accepts / len(v)) if v else None}
