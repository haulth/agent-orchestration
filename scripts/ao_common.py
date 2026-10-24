"""Shared helpers for agent_run.py, route.py and discover.py (stdlib only).

State folder (shared by every installed copy of the skill): %USERPROFILE%\\.agent-orchestration
(override with AO_HOME): ledger.jsonl, capabilities.json, capabilities.md, changes.md.
"""
import ctypes
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
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


def probe_hardware():
    """Inspect real-time machine hardware (CPU cores, available RAM, disk space, and optional GPU VRAM)
    using Python stdlib only. Computes safe parallel worker limit (`recommended_wip`) so parallel
    sub-agents never OOM or thrash the machine."""
    cpu_cores = os.cpu_count() or 2
    ram_total_gb, ram_avail_gb, ram_used_pct = 8.0, 4.0, 50

    if os.name == "nt":
        try:
            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_total_gb = round(stat.ullTotalPhys / (1024 ** 3), 1)
                ram_avail_gb = round(stat.ullAvailPhys / (1024 ** 3), 1)
                ram_used_pct = int(stat.dwMemoryLoad)
        except Exception:
            pass
    elif Path("/proc/meminfo").exists():
        try:
            mem = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
            mt = re.search(r"^MemTotal:\s+(\d+)\s+kB", mem, re.M)
            ma = re.search(r"^MemAvailable:\s+(\d+)\s+kB", mem, re.M)
            if mt and ma:
                ram_total_gb = round(int(mt.group(1)) / (1024 ** 2), 1)
                ram_avail_gb = round(int(ma.group(1)) / (1024 ** 2), 1)
                ram_used_pct = int(round((1.0 - ram_avail_gb / max(0.1, ram_total_gb)) * 100))
        except OSError:
            pass

    try:
        du = shutil.disk_usage(Path.cwd())
        disk_free_gb = round(du.free / (1024 ** 3), 1)
    except OSError:
        disk_free_gb = 20.0

    gpu_info = None
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1.5
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
                if len(parts) >= 4:
                    gpu_info = f"{parts[0]} ({parts[2]}/{parts[1]} MiB free, {parts[3]}% util)"
        except (OSError, subprocess.SubprocessError):
            pass

    # Reserve ~2.0 GB RAM for OS/IDE; budget ~1.5 GB RAM and 2 logical threads per parallel agent worker
    by_ram = max(1, int(max(0.0, ram_avail_gb - 2.0) // 1.5))
    by_cpu = max(1, cpu_cores // 2)
    rec_wip = max(1, min(6, by_ram, by_cpu))

    if ram_avail_gb < 2.5 or ram_used_pct >= 90:
        pressure = "critical"
        rec_wip = 1
    elif ram_avail_gb < 4.5 or ram_used_pct >= 82:
        pressure = "high"
        rec_wip = min(2, rec_wip)
    else:
        pressure = "normal"

    worktree_safe = disk_free_gb >= 3.0 and pressure != "critical"
    gpu_str = f", GPU: {gpu_info}" if gpu_info else ""
    summary = (f"{cpu_cores} logical cores, {ram_avail_gb}/{ram_total_gb} GB RAM free ({ram_used_pct}% used), "
               f"{disk_free_gb} GB disk free{gpu_str} -> pressure: {pressure}, safe parallel wip: {rec_wip}")
    return {
        "cpu_cores": cpu_cores,
        "ram_total_gb": ram_total_gb,
        "ram_avail_gb": ram_avail_gb,
        "ram_used_pct": ram_used_pct,
        "disk_free_gb": disk_free_gb,
        "gpu": gpu_info,
        "pressure": pressure,
        "recommended_wip": rec_wip,
        "worktree_safe": worktree_safe,
        "summary": summary
    }


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


def list_installed_skills():
    """Scan all installed specialized skills across ~/.agents/skills, ~/.claude/skills,
    ~/.gemini/config/skills, and ~/.gemini/config/plugins/*/skills so the orchestrator can
    delegate domain-specific tasks to specialized skills instead of reinventing domain logic."""
    home = Path.home()
    roots = [
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".gemini" / "config" / "skills",
        home / ".gemini" / "antigravity" / "builtin" / "skills",
    ]
    for pdir in glob.glob(str(home / ".gemini" / "config" / "plugins" / "*" / "skills")):
        roots.append(Path(pdir))
    skills = {}
    for r in roots:
        if not r.exists():
            continue
        candidates = list(r.glob("*/SKILL.md"))
        if (r / "SKILL.md").exists():
            candidates.append(r / "SKILL.md")
        for smd in candidates:
            sdir = smd.parent
            sname = sdir.name.replace("_", "-")
            if sname == "agent-orchestration" or sname in skills:
                continue
            desc = ""
            try:
                head = smd.read_text(encoding="utf-8", errors="replace")[:2000]
                fm = re.match(r"^---\s*\n(.*?)\n---", head, re.S)
                block = fm.group(1) if fm else head
                m_name = re.search(r"^name:\s*(.+)$", block, re.M)
                if m_name:
                    sname = m_name.group(1).strip().strip("'\"")
                m_desc = re.search(r"^description:\s*(?:>[-+]?|\|[-+]?)?\s*\n((?:[ \t]+.+\n?)+)|^description:\s*(.+)$", block, re.M)
                if m_desc:
                    raw_d = m_desc.group(1) or m_desc.group(2) or ""
                    desc = " ".join(line.strip() for line in raw_d.splitlines()).strip().strip("'\"")
            except OSError:
                pass
            if sname != "agent-orchestration" and sname not in skills:
                skills[sname] = {"name": sname, "path": str(smd), "description": desc}
    return sorted(skills.values(), key=lambda x: x["name"])


def resolve_skill_path(name_or_path):
    """Resolve a skill name (e.g. 'literature-search-arxiv', 'pubmed-database') or path to its SKILL.md."""
    p = Path(name_or_path)
    if p.exists():
        return str((p / "SKILL.md") if p.is_dir() and (p / "SKILL.md").exists() else p.resolve())
    skills = {s["name"]: s for s in list_installed_skills()}
    norm = name_or_path.strip().lower().replace("_", "-")
    if norm in skills:
        return skills[norm]["path"]
    for k, info in skills.items():
        if norm in k.lower():
            return info["path"]
    return None


def match_installed_skills(keywords, limit=5):
    """Find installed specialized skills matching any keyword in `keywords`."""
    if not keywords:
        return []
    kws = [str(kw).lower() for kw in keywords if kw and len(str(kw)) >= 3]
    if not kws:
        return []
    scored = []
    for info in list_installed_skills():
        name_l = info["name"].lower()
        hay = f"{name_l} {info['description'].lower()}"
        score = sum((3 if kw in name_l else 1) for kw in kws if kw in hay)
        if score > 0:
            scored.append((score, info))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [x[1] for x in scored[:limit]]


def check_evidence_citations(obj):
    """Verify that conclusion/summary and any assumptions_challenged have concrete evidence backing
    (e.g. file:line, command output, DOI/arXiv/PMID/URL, or [E1] references). Returns grounding warnings."""
    if not isinstance(obj, dict):
        return []
    warnings = []
    ev = obj.get("evidence") or []
    status = obj.get("status")
    if status == "done" and not ev:
        warnings.append("status is 'done' but `evidence` is empty (every conclusion requires verifiable proof)")
    anchor_re = re.compile(
        r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+:\d+|https?://|`[^`]+`|\b\d+(\.\d+)?%|\bexit\s+\d+|\bline\s+\d+|\[E\d+\]|\b(?:doi|arxiv|pmid|pmcid)\s*[:/]\s*\S+)",
        re.I
    )
    if ev and not any(anchor_re.search(str(x)) for x in ev):
        warnings.append("`evidence` items lack concrete anchors (expected `file:line`, `command -> output`, DOI/arXiv/PMID/URL, or measured numbers)")
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
