"""Shared helpers for agent_run.py, route.py and discover.py (stdlib only).

State folder (shared by every installed copy of the skill): %USERPROFILE%\\.agent-orchestration
(override with AO_HOME): ledger.jsonl, capabilities.json, capabilities.md, changes.md.
"""
import ctypes
import glob
import hashlib
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
    elif shutil.which("sysctl") and shutil.which("vm_stat"):
        try:
            r_tot = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=1.5)
            r_vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=1.5)
            if r_tot.returncode == 0 and r_vm.returncode == 0:
                ram_total_gb = round(int(r_tot.stdout.strip()) / (1024 ** 3), 1)
                ps_m = re.search(r"page size of (\d+) bytes", r_vm.stdout)
                page_sz = int(ps_m.group(1)) if ps_m else 4096
                free_pages = 0
                for key in ("Pages free", "Pages inactive", "Pages speculative"):
                    m_pg = re.search(rf"^{key}:\s+(\d+)", r_vm.stdout, re.M)
                    if m_pg:
                        free_pages += int(m_pg.group(1))
                if free_pages > 0:
                    ram_avail_gb = round((free_pages * page_sz) / (1024 ** 3), 1)
                    ram_used_pct = int(round((1.0 - ram_avail_gb / max(0.1, ram_total_gb)) * 100))
        except Exception:
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


def sandbox_skills_dir():
    """Isolated ephemeral skill memory owned by agent-orchestration. Never touches global host directories."""
    custom = os.environ.get("AO_SANDBOX_DIR")
    d = Path(custom) if custom else (ao_home() / "sandbox-skills")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def list_installed_skills(include_sandbox=True, project_dir=None):
    """Scan all skills readable by the parent agent across host directories (~/.agents/skills,
    ~/.claude/skills, ~/.codex/skills, ~/.gemini/config/skills, plugins, builtin) plus the
    ephemeral skill sandbox (~/.agent-orchestration/sandbox-skills).
    Parent skills are prioritized first so existing readable skills are shared via path without re-installing."""
    home = Path.home()
    roots = [
        (home / ".agents" / "skills", "parent_host"),
        (home / ".claude" / "skills", "parent_host"),
        (home / ".codex" / "skills", "parent_host"),
        (home / ".codex" / "superpowers" / "skills", "parent_host"),
        (home / ".gemini" / "config" / "skills", "parent_host"),
        (home / ".gemini" / "antigravity" / "builtin" / "skills", "parent_builtin"),
    ]
    for pdir in glob.glob(str(home / ".gemini" / "config" / "plugins" / "*" / "skills")):
        roots.append((Path(pdir), "parent_plugin"))
    if project_dir:
        proj = Path(project_dir)
        for rel in (".agents/skills", ".claude/skills", "skills"):
            if (proj / rel).exists():
                roots.append((proj / rel, "project_local"))
    if include_sandbox:
        sdir = sandbox_skills_dir()
        if sdir.exists():
            roots.append((sdir, "ephemeral_sandbox"))
        local_sb = Path(__file__).resolve().parent.parent / ".sandbox-skills"
        if local_sb.exists():
            roots.append((local_sb, "ephemeral_sandbox"))

    skills = {}
    for r, scope in roots:
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
                skills[sname] = {
                    "name": sname,
                    "path": str(smd.resolve()),
                    "dir": str(sdir.resolve()),
                    "scope": scope,
                    "description": desc,
                }
    return sorted(skills.values(), key=lambda x: x["name"])


def resolve_skill_info(name_or_path, project_dir=None):
    """Resolve a skill name or path to its full metadata dict {'name', 'path', 'dir', 'scope', 'description'}."""
    p = Path(name_or_path)
    if p.exists():
        smd = (p / "SKILL.md") if p.is_dir() and (p / "SKILL.md").exists() else p
        return {
            "name": smd.parent.name.replace("_", "-"),
            "path": str(smd.resolve()),
            "dir": str(smd.parent.resolve()),
            "scope": "direct_path",
            "description": "",
        }
    all_skills = list_installed_skills(include_sandbox=True, project_dir=project_dir)
    by_name = {s["name"].lower(): s for s in all_skills}
    norm = name_or_path.strip().lower().replace("_", "-")
    if norm in by_name:
        return by_name[norm]
    for k, info in by_name.items():
        if norm in k:
            return info
    return None


def resolve_skill_path(name_or_path, project_dir=None):
    """Resolve a skill name (e.g. 'literature-search-arxiv', 'pubmed-database') or path to its SKILL.md."""
    info = resolve_skill_info(name_or_path, project_dir=project_dir)
    return info["path"] if info else None


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


# ---------- Orchestration Anatomy (Truth-First, DAG Wave Settler & Zero-Defect Audit) ----------
def _scope_overlaps(s1, s2):
    """Return True if two normalized write scopes overlap."""
    a = s1.replace("\\", "/").strip()
    b = s2.replace("\\", "/").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    if a.endswith("/") and (b.startswith(a) or a.startswith(b.rstrip("/") + "/")):
        return True
    if b.endswith("/") and (a.startswith(b) or b.startswith(a.rstrip("/") + "/")):
        return True
    return False


def size_tier_of_plan(n_pkgs):
    """Classify orchestration scale like Anatomy (micro -> figure -> hero -> epic)."""
    if n_pkgs <= 1:
        return "micro"
    if n_pkgs <= 4:
        return "figure"
    if n_pkgs <= 8:
        return "hero"
    return "epic"


# ---------- Truth Interlock, Threshold Keyholes & Change-Ripple Engine ----------
def parse_invariant_spec(spec):
    """Parse a CLI or JSON invariant/threshold specification into a normalized dict.
    Supported string formats:
      - 'MAX_LATENCY_MS<=200', 'MIN_ACC>=0.95', 'TIMEOUT_S<30', 'WORKERS>1'
      - 'API_VERSION=v2', 'EMBED_DIM=768'
      - 'must:verify_signature' (deliverables must contain pattern)
      - 'forbid:eval(' (deliverables must never contain pattern)
    """
    if isinstance(spec, dict):
        k = str(spec.get("key") or spec.get("pattern") or "").strip()
        op = str(spec.get("op") or spec.get("type") or "=").strip()
        val = str(spec.get("value") if spec.get("value") is not None else "").strip()
        if op in ("must_contain", "must"):
            return {"key": k or val, "op": "must", "value": val or k}
        if op in ("forbid_pattern", "forbid"):
            return {"key": k or val, "op": "forbid", "value": val or k}
        return {"key": k, "op": op, "value": val}
    raw = str(spec or "").strip()
    if not raw:
        raise ValueError("Empty invariant spec")
    if raw.lower().startswith("must:"):
        pat = raw[5:].strip()
        return {"key": pat, "op": "must", "value": pat}
    if raw.lower().startswith("forbid:"):
        pat = raw[7:].strip()
        return {"key": pat, "op": "forbid", "value": pat}
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*(<=|>=|==|=|<|>)\s*(.+)$", raw)
    if not m:
        raise ValueError(f"Invalid invariant spec '{raw}': expected KEY=VAL, KEY<=VAL, KEY>=VAL, must:PAT, or forbid:PAT")
    key, op, val = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    if op == "==":
        op = "="
    return {"key": key, "op": op, "value": val}


def extract_invariants(plan, project_dir=None):
    """Extract normalized list of locked prerequisites/thresholds from plan dict and truth_contract."""
    proj = Path(project_dir or ".").resolve()
    invs = []
    seen = set()
    raw_list = (plan.get("invariants") or []) if isinstance(plan, dict) else []
    for item in raw_list:
        try:
            norm = parse_invariant_spec(item)
            sig = (norm["key"], norm["op"])
            if sig not in seen:
                seen.add(sig)
                invs.append(norm)
        except ValueError:
            pass
    tc = plan.get("truth_contract") if isinstance(plan, dict) else None
    if tc:
        tc_path = Path(tc) if Path(tc).is_absolute() else (proj / tc)
        if tc_path.exists():
            try:
                txt = tc_path.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"<!--\s*INVARIANTS_JSON:\s*(\[.*?\])\s*-->", txt, re.S)
                if m:
                    for item in json.loads(m.group(1)):
                        norm = parse_invariant_spec(item)
                        sig = (norm["key"], norm["op"])
                        if sig not in seen:
                            seen.add(sig)
                            invs.append(norm)
            except (OSError, ValueError):
                pass
    return invs


def compute_truth_hash(truth_contract_path=None, invariants=None):
    """Compute deterministic SHA-256 keyhole digest over truth_contract file + locked invariants."""
    h = hashlib.sha256()
    if truth_contract_path and Path(truth_contract_path).exists():
        try:
            raw = Path(truth_contract_path).read_bytes().replace(b"\r\n", b"\n")
            h.update(raw)
        except OSError:
            pass
    norm_invs = [parse_invariant_spec(x) for x in (invariants or [])]
    norm_invs.sort(key=lambda x: (x["key"], x["op"], x["value"]))
    h.update(json.dumps(norm_invs, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:16]


def _normalize_scalar(val_str):
    s = str(val_str).strip().strip("\"'`")
    try:
        if "." in s:
            return float(s), s
        return int(s), s
    except ValueError:
        return None, s


def check_invariant_drift(invariants, file_paths, project_dir=None):
    """Scan modified/produced files against locked user prerequisites and threshold bounds.
    Returns a list of concrete violation strings with exact file:line anchors."""
    if not invariants:
        return []
    proj = Path(project_dir or ".").resolve()
    norm_invs = [parse_invariant_spec(x) for x in invariants]
    violations = []
    must_found = {inv["value"]: False for inv in norm_invs if inv["op"] == "must"}

    readable_files = []
    for fp in (file_paths or []):
        p = Path(fp) if Path(fp).is_absolute() else (proj / fp)
        if p.exists() and p.is_file():
            readable_files.append((str(fp).replace("\\", "/"), p))

    for rel_path, p in readable_files:
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lno, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith(("#", "//", "/*", "*", "<!--")):
                continue
            for inv in norm_invs:
                op = inv["op"]
                key = inv["key"]
                expected_raw = inv["value"]
                if op == "must":
                    if expected_raw in line:
                        must_found[expected_raw] = True
                elif op == "forbid":
                    if expected_raw in line:
                        violations.append(
                            f"FORBID_VIOLATION: {rel_path}:{lno} contains forbidden pattern '{expected_raw}'"
                        )
                else:
                    # Match assignments including typed Python/TS: KEY: int = val, KEY = val, "KEY": val
                    pat = (
                        rf"""(?:^|[\s"']|\b){re.escape(key)}["']?"""
                        rf"""(?:(?:\s*:\s*[A-Za-z_][A-Za-z0-9_\[\]|, ]*)?\s*(?::=|=)\s*|\s*:\s*(?![^=\n]*=))"""
                        rf"""("[^"]+"|'[^']+'|[-+]?\d+(?:\.\d+)?|\b[A-Za-z0-9_.-]+\b)"""
                    )
                    m = re.search(pat, line)
                    if not m:
                        continue
                    actual_tok = m.group(1).strip()
                    act_num, act_str = _normalize_scalar(actual_tok)
                    exp_num, exp_str = _normalize_scalar(expected_raw)
                    if op == "=":
                        mismatch = (act_num != exp_num) if (act_num is not None and exp_num is not None) else (act_str != exp_str)
                        if mismatch:
                            violations.append(
                                f"INVARIANT_DRIFT: {rel_path}:{lno} sets {key}={actual_tok} (locked prerequisite requires {key}={expected_raw})"
                            )
                    elif op in ("<=", ">=", "<", ">") and act_num is not None and exp_num is not None:
                        ok = (
                            (op == "<=" and act_num <= exp_num) or
                            (op == ">=" and act_num >= exp_num) or
                            (op == "<" and act_num < exp_num) or
                            (op == ">" and act_num > exp_num)
                        )
                        if not ok:
                            violations.append(
                                f"THRESHOLD_VIOLATION: {rel_path}:{lno} sets {key}={actual_tok} (violates locked threshold {key}{op}{expected_raw})"
                            )

    if readable_files:
        for pat, found in must_found.items():
            if not found:
                violations.append(f"MUST_VIOLATION: required pattern '{pat}' was not found in any deliverable/modified file")
    return violations


def detect_cross_package_conflicts(settled_pkgs, results_by_name, project_dir=None, invariants=None):
    """Detect when one package changes a shared constant/parameter/config key while other packages
    silently use a different/old value."""
    proj = Path(project_dir or ".").resolve()
    norm_invs = [parse_invariant_spec(x) for x in (invariants or [])]
    watched_keys = {x["key"] for x in norm_invs if x["op"] == "="}
    threshold_only_keys = {x["key"] for x in norm_invs if x["op"] in ("<=", ">=", "<", ">")}
    # Track key -> list of (pkg_name, value_str, rel_file, line_no)
    key_sightings = {}
    assign_re = re.compile(
        r"""^\s*(?:export\s+|const\s+|let\s+|var\s+|final\s+)?["']?([A-Z][A-Z0-9_]{3,}|[A-Za-z_][A-Za-z0-9_.-]*)["']?"""
        r"""(?:(?:\s*:\s*[A-Za-z_][A-Za-z0-9_\[\]|, ]*)?\s*(?::=|=)\s*|\s*:\s*(?![^=\n]*=))"""
        r"""("[^"]+"|'[^']+'|[-+]?\d+(?:\.\d+)?|\b(?:true|false|True|False|[A-Za-z0-9_.-]+)\b)"""
    )

    for p in settled_pkgs:
        pname = p["name"]
        meta = results_by_name.get(pname) or {}
        candidate_files = list(p.get("outputs") or []) + list(meta.get("changed") or [])
        seen_paths = set()
        for fp in candidate_files:
            norm_fp = str(fp).replace("\\", "/")
            if norm_fp in seen_paths or norm_fp.startswith(".orch/"):
                continue
            seen_paths.add(norm_fp)
            abs_p = Path(fp) if Path(fp).is_absolute() else (proj / fp)
            if not abs_p.exists() or not abs_p.is_file():
                continue
            try:
                lines = abs_p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for lno, line in enumerate(lines, 1):
                stripped = line.lstrip()
                if stripped.startswith(("#", "//", "/*", "*", "<!--", "-", ">")):
                    continue
                m = assign_re.match(line)
                if not m:
                    continue
                k, raw_v = m.group(1), m.group(2)
                if k in threshold_only_keys:
                    continue
                if not (k.isupper() or k in watched_keys):
                    continue
                _, clean_v = _normalize_scalar(raw_v)
                key_sightings.setdefault(k, []).append((pname, clean_v, norm_fp, lno))

    conflicts = []
    for k, sightings in sorted(key_sightings.items()):
        pkgs_involved = {s[0] for s in sightings}
        if len(pkgs_involved) < 2:
            continue
        # Look at the latest value per package
        by_pkg = {}
        for pname, clean_v, norm_fp, lno in sightings:
            by_pkg[pname] = (clean_v, norm_fp, lno)
        distinct_vals = {v[0] for v in by_pkg.values()}
        if len(distinct_vals) > 1:
            parts = [f"{pname} sets {k}={info[0]} ({info[1]}:{info[2]})" for pname, info in sorted(by_pkg.items())]
            conflicts.append(f"CROSS_PACKAGE_CONFLICT on '{k}': " + " vs. ".join(parts))
    return conflicts


def amend_truth_contract(plan_path, amendments, project_dir=None, author_pkg="manager"):
    """Formal Change-Ripple & Invalidation Engine:
    When a locked prerequisite/threshold must change (backed by empirical evidence):
      1. Validates evidence anchor (No Proof = No Amendment).
      2. Updates `invariants`, increments `truth_version`, updates `truth-contract.md`, and recomputes `truth_hash`.
      3. Broadcasts `.orch/truth-amendment-vN.md` into `context_file` of all packages so no downstream agent misses it.
      4. Scans already-completed packages to mark any package that used the old value as `stale_packages` (forcing resync instead of silent divergence).
    """
    pfile = Path(plan_path).resolve()
    proj = Path(project_dir).resolve() if project_dir else (
        pfile.parent.parent if pfile.parent.name == ".orch" else pfile.parent
    )
    plan = json.loads(pfile.read_text(encoding="utf-8-sig"))
    invs = extract_invariants(plan, proj)
    inv_map = {inv["key"]: dict(inv) for inv in invs}

    applied = []
    rejected = []
    anchor_re = re.compile(
        r"([A-Za-z0-9_./\\-]+:\d+|->|https?://|`[^`]+`|\b\d+(\.\d+)?%|\bexit\s+\d+|\bline\s+\d+|\[E\d+\])",
        re.I
    )

    for raw_am in (amendments or []):
        key = str(raw_am.get("key") or "").strip()
        prop_val = str(raw_am.get("proposed_value") if raw_am.get("proposed_value") is not None else "").strip()
        op = str(raw_am.get("op") or "=").strip()
        reason = str(raw_am.get("reason") or "").strip()
        evidence = str(raw_am.get("evidence") or "").strip()
        if not key or not prop_val:
            rejected.append(f"Amendment missing key or proposed_value: {raw_am}")
            continue
        if not evidence or not anchor_re.search(evidence):
            rejected.append(
                f"Amendment for '{key} -> {prop_val}' rejected: missing concrete evidence anchor (file:line, command output, or measurement)"
            )
            continue
        old_entry = inv_map.get(key)
        old_val = str(raw_am.get("old_value") or (old_entry["value"] if old_entry else "(unlocked)"))
        inv_map[key] = {"key": key, "op": op, "value": prop_val}
        applied.append({
            "key": key,
            "op": op,
            "old_value": old_val,
            "proposed_value": prop_val,
            "reason": reason or "Empirical adjustment",
            "evidence": evidence,
            "author": author_pkg,
            "affected_packages": list(raw_am.get("affected_packages") or []),
            "timestamp": now(),
        })

    if not applied:
        return {"ok": False, "applied": [], "rejected": rejected, "stale_packages": []}

    new_invs = list(inv_map.values())
    plan["invariants"] = new_invs
    ver = int(plan.get("truth_version") or 1) + 1
    plan["truth_version"] = ver

    tc_rel = plan.get("truth_contract") or ".orch/truth-contract.md"
    tc_abs = Path(tc_rel) if Path(tc_rel).is_absolute() else (proj / tc_rel)
    tc_abs.parent.mkdir(parents=True, exist_ok=True)
    tc_text = tc_abs.read_text(encoding="utf-8", errors="replace") if tc_abs.exists() else f"# Shared Truth Contract\n"
    inv_comment = f"<!-- INVARIANTS_JSON: {json.dumps(new_invs, ensure_ascii=False)} -->"
    if re.search(r"<!--\s*INVARIANTS_JSON:\s*\[.*?\]\s*-->", tc_text, re.S):
        tc_text = re.sub(r"<!--\s*INVARIANTS_JSON:\s*\[.*?\]\s*-->", lambda _: inv_comment, tc_text, flags=re.S)
    else:
        tc_text = tc_text.rstrip() + "\n\n" + inv_comment + "\n"

    amend_lines = [f"\n## Truth Amendment v{ver} (by `{author_pkg}` at {now()})"]
    for am in applied:
        amend_lines.append(
            f"- **`{am['key']}`**: `{am['old_value']}` -> **`{am['op']} {am['proposed_value']}`** | Reason: {am['reason']} | Evidence: `{am['evidence']}`"
        )
    tc_text = tc_text.rstrip() + "\n" + "\n".join(amend_lines) + "\n"
    tc_abs.write_text(tc_text, encoding="utf-8")

    # Write dedicated broadcast notice file and mount into every package's context_file
    notice_abs = pfile.parent / f"truth-amendment-v{ver}.md"
    notice_abs.write_text(
        "# MANDATORY TRUTH CONTRACT AMENDMENT (v" + str(ver) + ")\n\n"
        "The following shared prerequisites/thresholds/interfaces have been formally amended.\n"
        "All packages MUST obey the updated values below and discard the old values:\n"
        + "\n".join(amend_lines) + "\n",
        encoding="utf-8",
    )
    try:
        notice_rel = str(notice_abs.relative_to(proj)).replace("\\", "/")
    except ValueError:
        notice_rel = str(notice_abs)

    # Identify affected & stale packages across the plan
    stale_packages = set(plan.get("stale_packages") or [])
    affected_all = set()
    for am in applied:
        k = am["key"]
        old_v = am["old_value"]
        for ap in am["affected_packages"]:
            affected_all.add(ap)
        for pkg in plan.get("packages", []):
            pname = pkg["name"]
            cfiles = list(pkg.get("context_file") or [])
            if notice_rel not in cfiles:
                cfiles.append(notice_rel)
            pkg["context_file"] = cfiles
            if pname == author_pkg:
                continue
            # Check if package brief or existing outputs mention the amended key
            bref = pkg.get("brief") or pkg.get("brief_file")
            bp = (Path(bref) if Path(bref).is_absolute() else (proj / bref)) if bref else None
            btxt = bp.read_text(encoding="utf-8", errors="replace") if (bp and bp.exists()) else ""
            mentions_key = (k in btxt) or (pname in am["affected_packages"])
            out_files = [Path(o) if Path(o).is_absolute() else (proj / o) for o in (pkg.get("outputs") or [])]
            existing_outs = [o for o in out_files if o.exists() and o.is_file()]
            for eo in existing_outs:
                try:
                    otxt = eo.read_text(encoding="utf-8", errors="replace")
                    if k in otxt or (old_v and old_v != "(unlocked)" and old_v in otxt):
                        mentions_key = True
                        stale_packages.add(pname)
                except OSError:
                    pass
            if mentions_key:
                affected_all.add(pname)
                if existing_outs:
                    stale_packages.add(pname)

    plan["truth_hash"] = compute_truth_hash(tc_abs, new_invs)
    plan["stale_packages"] = sorted(stale_packages)
    pfile.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    # Append to amendments.jsonl ledger
    amend_log = pfile.parent / "amendments.jsonl"
    with open(amend_log, "a", encoding="utf-8") as f:
        for am in applied:
            f.write(json.dumps({"truth_version": ver, "truth_hash": plan["truth_hash"], **am,
                                "affected_packages": sorted(affected_all),
                                "stale_packages": sorted(stale_packages)}, ensure_ascii=False) + "\n")

    return {
        "ok": len(rejected) == 0,
        "truth_version": ver,
        "truth_hash": plan["truth_hash"],
        "notice_file": notice_rel,
        "applied": applied,
        "rejected": rejected,
        "affected_packages": sorted(affected_all),
        "stale_packages": sorted(stale_packages),
    }



def settle_plan(plan, project_dir=None):
    """Settle a work plan into topological parallel waves (inspired by Anatomy's A.settle).
    - Wires top-level `truth_contract` into every package's `context_file` (Truth First).
    - Resolves explicit `depends_on` plus implicit producer (`outputs`) -> consumer (`context_file`/`inputs`) edges.
    - Auto-wires upstream `outputs` into downstream `context_file` mounts so nothing is lost in relay.
    - Computes `wave` (0, 1, 2...) for each package and detects any dependency cycles.
    """
    proj = Path(project_dir or ".").resolve()
    raw_pkgs = plan.get("packages", []) if isinstance(plan, dict) else list(plan)
    truth_contract = plan.get("truth_contract") if isinstance(plan, dict) else None
    pkgs = []
    by_name = {}
    output_owner = {}

    for i, raw in enumerate(raw_pkgs):
        p = dict(raw)
        name = str(p.get("name") or p.get("id") or f"pkg{i + 1}").strip()
        p["name"] = name
        p["group"] = p.get("group") or ("verification" if p.get("task_type") in ("review", "security-review", "critique", "test") else "core")
        p["mode"] = p.get("mode") or ("write" if p.get("may_write") else "read")
        p["depends_on"] = list(p.get("depends_on") or [])
        p["outputs"] = list(p.get("outputs") or p.get("deliverables") or [])
        cfiles = list(p.get("context_file") or [])
        for inp in (p.get("inputs") or []):
            if inp not in cfiles:
                cfiles.append(inp)
        if truth_contract and truth_contract not in cfiles:
            cfiles.insert(0, truth_contract)
        p["context_file"] = cfiles
        p["may_write"] = [str(x).replace("\\", "/") for x in (p.get("may_write") or [])]
        p["skill"] = list(p.get("skill") or p.get("skills") or [])
        pkgs.append(p)
        by_name[name] = p
        for out_path in p["outputs"]:
            norm_out = str(out_path).replace("\\", "/")
            output_owner[norm_out] = name

    # Infer implicit dependencies where pkg B reads a context_file produced by pkg A's outputs
    for p in pkgs:
        for cf in p["context_file"]:
            norm_cf = str(cf).replace("\\", "/")
            owner = output_owner.get(norm_cf)
            if owner and owner != p["name"] and owner not in p["depends_on"]:
                p["depends_on"].append(owner)

    # Wire upstream outputs into downstream context_file mounts
    for p in pkgs:
        for dep_name in p["depends_on"]:
            dep_pkg = by_name.get(dep_name)
            if dep_pkg:
                for out_path in dep_pkg.get("outputs", []):
                    if out_path not in p["context_file"]:
                        p["context_file"].append(out_path)

    # Topological wave assignment & cycle detection
    waves_map = {}
    visiting = set()
    cycles = []

    def solve_wave(name, stack):
        if name in waves_map:
            return waves_map[name]
        if name in visiting:
            cycle_path = " -> ".join(stack + [name])
            if cycle_path not in cycles:
                cycles.append(cycle_path)
            return 0
        pkg = by_name.get(name)
        if not pkg:
            return 0
        visiting.add(name)
        w = 0
        for dep in pkg["depends_on"]:
            if dep in by_name:
                w = max(w, 1 + solve_wave(dep, stack + [name]))
        visiting.remove(name)
        waves_map[name] = w
        return w

    for p in pkgs:
        p["wave"] = solve_wave(p["name"], [])

    max_w = max((p["wave"] for p in pkgs), default=-1)
    waves = [[p for p in pkgs if p["wave"] == w] for w in range(max_w + 1)]
    hw = probe_hardware()
    plan_wip = (plan.get("wip") if isinstance(plan, dict) else None) or hw["recommended_wip"]
    active_wip = min(int(plan_wip), hw["recommended_wip"])
    invariants = extract_invariants(plan, proj) if isinstance(plan, dict) else []
    tc_abs = (Path(truth_contract) if Path(truth_contract).is_absolute() else (proj / truth_contract)) if truth_contract else None
    live_hash = compute_truth_hash(tc_abs, invariants) if (tc_abs or invariants) else None
    return {
        "truth_contract": truth_contract,
        "truth_version": int(plan.get("truth_version") or 1) if isinstance(plan, dict) else 1,
        "truth_hash": live_hash,
        "invariants": invariants,
        "stale_packages": list(plan.get("stale_packages") or []) if isinstance(plan, dict) else [],
        "size_tier": size_tier_of_plan(len(pkgs)),
        "wip": active_wip,
        "hardware": hw,
        "packages": pkgs,
        "waves": waves,
        "cycles": cycles,
    }


def audit_plan(plan, project_dir=None):
    """Prove the work decomposition before or during execution (inspired by Anatomy's A.audit & lines.mjs).
    Checks:
      1. clearance: 0 overlapping --may-write scopes among parallel writers in the same wave
      2. cycles: 0 circular dependencies in the DAG
      3. terminals: 0 unknown depends_on, missing write scopes, or unmounted context_file inputs
      4. support: 0 hanging intermediate packages whose work is never consumed downstream
      5. stand_in_briefs: 0 missing or hollow (<40 char / TODO) briefs
      6. skill_mounts: 0 unresolved parent/sandbox skills
      7. truth_contract & keyhole interlocks: 0 missing/tampered truth contracts, 0 worker write-locks on truth_contract, 0 un-resynced stale packages, 0 invariant violations
    """
    proj = Path(project_dir or ".").resolve()
    settled = settle_plan(plan, project_dir=proj)
    pkgs = settled["packages"]
    by_name = {p["name"]: p for p in pkgs}
    waves = settled["waves"]

    clearance = []
    terminals = []
    support = []
    stand_in_briefs = []
    skill_mounts = []
    truth_issues = []
    interlock_issues = []

    tc = settled.get("truth_contract")
    tc_norm = str(tc).replace("\\", "/") if tc else None
    if tc:
        tc_path = Path(tc) if Path(tc).is_absolute() else (proj / tc)
        if not tc_path.exists():
            truth_issues.append(f"truth_contract '{tc}' does not exist on disk (write the shared ground-truth model first)")
        elif tc_path.stat().st_size < 20:
            truth_issues.append(f"truth_contract '{tc}' is hollow (<20 bytes)")
        if isinstance(plan, dict) and plan.get("truth_hash") and settled.get("truth_hash"):
            if plan["truth_hash"] != settled["truth_hash"]:
                interlock_issues.append(
                    f"TRUTH_HASH_MISMATCH: plan.json locked truth_hash={plan['truth_hash']} but live truth_contract/invariants hash to {settled['truth_hash']} (use `anatomy.py amend` to update truth & propagate changes)"
                )

    for sp in settled.get("stale_packages") or []:
        interlock_issues.append(
            f"STALE_PACKAGE_NEEDS_RESYNC: '{sp}' used an old parameter value invalidated by a Truth Amendment (re-run or update '{sp}' and clear stale_packages)"
        )

    # Check if any existing outputs already violate locked invariants
    all_declared_outputs = [o for p in pkgs for o in (p.get("outputs") or [])]
    if settled.get("invariants") and all_declared_outputs:
        existing_outs = [o for o in all_declared_outputs if (Path(o) if Path(o).is_absolute() else (proj / o)).exists()]
        if existing_outs:
            interlock_issues.extend(check_invariant_drift(settled["invariants"], existing_outs, project_dir=proj))

    # Map every output path to the wave in which it is produced
    output_wave = {}
    for p in pkgs:
        for out_p in p.get("outputs", []):
            output_wave[str(out_p).replace("\\", "/")] = p["wave"]

    # 1. Check clearance per wave (parallel writers must have disjoint --may-write scopes)
    for w_idx, w_pkgs in enumerate(waves):
        writers = [p for p in w_pkgs if p.get("mode") == "write" and not p.get("worktree")]
        for i, w1 in enumerate(writers):
            for w2 in writers[i + 1:]:
                for s1 in w1.get("may_write", []):
                    for s2 in w2.get("may_write", []):
                        if _scope_overlaps(s1, s2):
                            clearance.append(
                                f"wave {w_idx}: '{w1['name']}' ({s1}) x '{w2['name']}' ({s2}) overlap in parallel write scope"
                            )

    # Track which packages are depended upon by downstream packages
    depended_on_by = {p["name"]: [] for p in pkgs}
    for p in pkgs:
        for dep in p.get("depends_on", []):
            if dep in depended_on_by:
                depended_on_by[dep].append(p["name"])

    max_wave = len(waves) - 1
    for p in pkgs:
        name = p["name"]
        # Keyhole lock: workers must never have write permission over the shared truth_contract
        if tc_norm:
            for mw in p.get("may_write", []):
                if _scope_overlaps(mw, tc_norm):
                    interlock_issues.append(
                        f"{name}: may_write '{mw}' overlaps shared truth_contract '{tc_norm}' (workers cannot unilaterally mutate Truth Contract; use `truth_amendments`)"
                    )
        # 2. Terminals: depends_on validity, write scope presence, context_file mounts
        for dep in p.get("depends_on", []):
            if dep not in by_name:
                terminals.append(f"{name}: depends_on '{dep}' does not exist in plan")
            elif by_name[dep]["wave"] >= p["wave"] and not settled["cycles"]:
                terminals.append(f"{name}: depends_on '{dep}' is not in an earlier wave")
        if p.get("mode") == "write" and not p.get("may_write"):
            terminals.append(f"{name}: mode is 'write' but may_write is empty (unbounded write)")
        for cf in p.get("context_file", []):
            if tc and cf == tc:
                continue
            norm_cf = str(cf).replace("\\", "/")
            cf_path = Path(cf) if Path(cf).is_absolute() else (proj / cf)
            prod_w = output_wave.get(norm_cf)
            if not cf_path.exists() and (prod_w is None or prod_w >= p["wave"]):
                terminals.append(f"{name}: context_file '{cf}' is neither on disk nor produced by an earlier wave")

        # 3. Support: intermediate read-only packages in multi-wave plans must feed a downstream package (unless marked free)
        if max_wave > 0 and p["wave"] < max_wave and p.get("mode") == "read":
            if not depended_on_by.get(name) and not p.get("free"):
                support.append(f"{name} (wave {p['wave']}): read-only package has no downstream consumer in wave > {p['wave']} (hanging output)")

        # 4. Stand-in briefs: verify brief exists and is not hollow
        brief_ref = p.get("brief") or p.get("brief_file")
        if not brief_ref:
            stand_in_briefs.append(f"{name}: missing 'brief' path")
        else:
            bp = Path(brief_ref) if Path(brief_ref).is_absolute() else (proj / brief_ref)
            if not bp.exists():
                stand_in_briefs.append(f"{name}: brief file '{brief_ref}' does not exist")
            else:
                try:
                    btxt = bp.read_text(encoding="utf-8", errors="replace").strip()
                    if len(btxt) < 40 or re.search(r"^(TODO|TBD|<fill in>)$", btxt, re.I):
                        stand_in_briefs.append(f"{name}: brief '{brief_ref}' is a stand-in stub ({len(btxt)} chars; needs real intent, scope & DoD)")
                except OSError as e:
                    stand_in_briefs.append(f"{name}: cannot read brief '{brief_ref}': {e}")

        # 5. Skill mounts: verify every requested skill exists on parent or sandbox
        for sk in p.get("skill", []):
            if not resolve_skill_info(sk, project_dir=proj):
                skill_mounts.append(f"{name}: skill '{sk}' not found on parent agent or sandbox")

    epic_notice = None
    if settled["size_tier"] == "epic" and not (isinstance(plan, dict) and plan.get("epic_approved")):
        epic_notice = (f"Epic scale ({len(pkgs)} packages > 8): per Anatomy sizing rules, propose a Hero slice (4-8 packages) "
                       "to the user first, or set \"epic_approved\": true once the user chooses the full Epic.")

    failures_total = (
        len(clearance) + len(settled["cycles"]) + len(terminals) +
        len(support) + len(stand_in_briefs) + len(skill_mounts) +
        len(truth_issues) + len(interlock_issues)
    )
    return {
        "ok": failures_total == 0,
        "failure_count": failures_total,
        "size_tier": settled["size_tier"],
        "epic_notice": epic_notice,
        "package_count": len(pkgs),
        "wave_count": len(waves),
        "writer_count": sum(1 for p in pkgs if p.get("mode") == "write"),
        "invariant_count": len(settled.get("invariants") or []),
        "truth_version": settled.get("truth_version", 1),
        "truth_hash": settled.get("truth_hash"),
        "wip": settled["wip"],
        "hardware": settled["hardware"]["summary"],
        "clearance": clearance,
        "cycles": settled["cycles"],
        "terminals": terminals,
        "support": support,
        "stand_in_briefs": stand_in_briefs,
        "skill_mounts": skill_mounts,
        "truth_contract": truth_issues,
        "interlocks": interlock_issues,
        "settled": settled,
    }


def format_anatomy_report(audit_res):
    """Format an Anatomy-style audit report where every structural line must read 0."""
    lines = []
    checks = [
        ("clearance (disjoint wave write scopes)", audit_res["clearance"]),
        ("cycles (DAG topological order)", audit_res["cycles"]),
        ("terminals (mounts, ports & context inputs)", audit_res["terminals"]),
        ("support (no hanging intermediate packages)", audit_res["support"]),
        ("stand-in briefs (work order substance)", audit_res["stand_in_briefs"]),
        ("skill mounts (parent/sandbox skill paths)", audit_res["skill_mounts"]),
        ("truth contract (single source of truth)", audit_res["truth_contract"]),
        ("interlocks (invariants, thresholds & truth lock)", audit_res.get("interlocks") or []),
    ]
    for label, probs in checks:
        lines.append(f"{label}: {len(probs)} problems")
        for item in probs[:10]:
            lines.append(f"  - {item}")
    if audit_res.get("epic_notice"):
        lines.append(f"sizing gate notice: {audit_res['epic_notice']}")
    for w_idx, w_pkgs in enumerate(audit_res["settled"]["waves"]):
        p_desc = ", ".join(
            f"{p['name']}[{p['mode']}" + (f" deps={','.join(p['depends_on'])}" if p.get("depends_on") else "") + "]"
            for p in w_pkgs
        )
        lines.append(f"wave {w_idx}: {p_desc}")
    inv_cnt = audit_res.get("invariant_count", 0)
    thash = audit_res.get("truth_hash") or "none"
    tver = audit_res.get("truth_version", 1)
    lines.append(
        f"anatomy audit · {audit_res['package_count']} packages · {audit_res['wave_count']} waves · "
        f"{audit_res['writer_count']} writers · {inv_cnt} invariants (v{tver} #{thash[:8]}) · "
        f"size {audit_res['size_tier']} · wip {audit_res['wip']}"
    )
    lines.append(
        f"audit failed: {audit_res['failure_count']} problem(s)" if not audit_res["ok"] else "audit passed"
    )
    return "\n".join(lines)


def audit_batch_junctions(settled_pkgs, results_by_name, project_dir=None, plan=None):
    """Post-flight 4x Junction, Invariant Keyhole & Cross-Package Conflict Check across completed packages.
    Checks:
      - Every declared output exists on disk (`missing_outputs`)
      - No deliverable/modified file violates locked user prerequisites or thresholds (`invariant_violations`)
      - No two packages silently define conflicting values for shared constants/parameters (`cross_package_conflicts`)
      - Surfaces `truth_amendments`, `assumptions_challenged`, `open_questions`, and `evidence_warnings`."""
    proj = Path(project_dir or ".").resolve()
    invariants = extract_invariants(plan, proj) if isinstance(plan, dict) else []
    missing_outputs = []
    invariant_violations = []
    truth_amendments = []
    challenged = []
    floating_questions = []
    ev_warnings = []

    max_wave = max((p.get("wave", 0) for p in settled_pkgs), default=0)
    for p in settled_pkgs:
        name = p["name"]
        meta = results_by_name.get(name) or {}
        pkg_files = []
        for out_p in p.get("outputs", []):
            fp = Path(out_p) if Path(out_p).is_absolute() else (proj / out_p)
            if not fp.exists():
                missing_outputs.append(f"{name}: declared output '{out_p}' was not created on disk")
            else:
                pkg_files.append(out_p)
        for ch_f in (meta.get("changed") or []):
            if ch_f not in pkg_files:
                pkg_files.append(ch_f)
        if invariants and pkg_files:
            for v in check_invariant_drift(invariants, pkg_files, project_dir=proj):
                invariant_violations.append(f"{name}: {v}")
        for ew in (meta.get("evidence_warnings") or []):
            ev_warnings.append(f"{name}: {ew}")
        run_dir = meta.get("run_dir")
        if run_dir and (Path(run_dir) / "result.json").exists():
            try:
                robj = json.loads((Path(run_dir) / "result.json").read_text(encoding="utf-8-sig"))
                for ac in (robj.get("assumptions_challenged") or []):
                    challenged.append(f"{name} (wave {p.get('wave', 0)}): {ac}")
                for oq in (robj.get("open_questions") or []):
                    floating_questions.append(f"{name} (wave {p.get('wave', 0)}): {oq}")
                for tam in (robj.get("truth_amendments") or []):
                    if isinstance(tam, dict):
                        truth_amendments.append({"author": name, "wave": p.get("wave", 0), **tam})
            except (OSError, ValueError):
                pass

    cross_conflicts = detect_cross_package_conflicts(
        settled_pkgs, results_by_name, project_dir=proj, invariants=invariants
    )

    return {
        "ok": (
            len(missing_outputs) == 0
            and len(ev_warnings) == 0
            and len(invariant_violations) == 0
            and len(cross_conflicts) == 0
        ),
        "missing_outputs": missing_outputs,
        "invariant_violations": invariant_violations,
        "cross_package_conflicts": cross_conflicts,
        "truth_amendments": truth_amendments,
        "assumptions_challenged": challenged,
        "open_questions": floating_questions,
        "evidence_warnings": ev_warnings,
        "final_wave": max_wave,
    }
