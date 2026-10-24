#!/usr/bin/env python3
"""Keep the manager's knowledge of codex, agy and claude current.

  discover.py --quick [--force]   versions only; exit 10 if any changed (or no snapshot yet).
                                  Checked at most once a day unless --force.
  discover.py                     full zero-token probe (--help, models, mcp, plugins, skills) + diff
  discover.py --deep AGENT --yes  ask the agent to list its built-in tools (COSTS TOKENS, ~12-20k)

State (shared by every installed copy): ~/.agent-orchestration/ (AO_HOME)
  capabilities.json  machine snapshot      capabilities.md  compact human-readable view
  changes.md         append-only diff log  candidates.json  new models seen, never auto-promoted
"""
import argparse
import glob
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ao_common as ao  # noqa: E402

HERE = Path(__file__).resolve().parent
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PROBES = {
    "codex": {"version": ["--version"], "help": ["--help"], "exec_help": ["exec", "--help"],
              "review_help": ["review", "--help"], "features": ["features", "list"], "mcp": ["mcp", "list"]},
    "agy": {"version": ["--version"], "help": ["--help"], "models": ["models"], "mcp": ["mcp", "list"],
            "plugin": ["plugin", "list"]},
    "claude": {"version": ["--version"], "help": ["--help"], "mcp": ["mcp", "list"],
               "auth": ["auth", "status"]},
}
LIST_FIELDS = ("flags", "subcommands", "models", "mcp", "plugins", "features")
SKILL_DIRS = {"claude": ["~/.claude/skills"], "codex": ["~/.agents/skills"],
              "agy": ["~/.gemini/config/skills", "~/.gemini/antigravity/builtin/skills",
                      "~/.gemini/antigravity-cli/builtin/skills"]}


def probe(exe, args, timeout=30):
    try:
        r = subprocess.run(exe + args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        text = ANSI.sub("", (r.stdout + b"\n" + r.stderr).decode("utf-8", "replace"))
        return text, None if r.returncode == 0 or text.strip() else f"exit {r.returncode}"
    except subprocess.TimeoutExpired:
        return "", f"timeout after {timeout}s"
    except OSError as e:
        return "", str(e)


def parse_flags(text):
    return sorted(set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", text)))


def parse_subcommands(text):
    out, on = [], False
    for line in text.splitlines():
        if re.match(r"^\s*(Available subcommands|Subcommands|Commands):?\s*$", line, re.I):
            on = True
            continue
        if on:
            if not line.strip():
                if out:
                    on = False
                continue
            m = re.match(r"^ {1,4}([a-z][\w-]*)(?:\s|$)", line)
            if m:
                out.append(m.group(1))
    return sorted(set(out) - {"help"})


def parse_names(text):
    """First token of each row in a list/table output (MCP servers, plugins)."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or re.match(r"(name\b|no |checking|fetching|loading|components\b|installed\b|source\b)", s, re.I) or s.startswith(("-", "=")):
            continue
        m = re.match(r"^([A-Za-z0-9_.@/-]+)[:\s]", s + " ")
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def parse_models_agy(text):
    return sorted(set(re.findall(r"^([a-z0-9][\w.\-]*)[ \t]+\S", text, re.M)))


def codex_models():
    """Dynamically discover all Codex models from local caches, global state, OpenAI docs, and config.toml."""
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
        # Also check electron-persisted-atom-state seen-model-upgrade-list
        gs = codex_dir / ".codex-global-state.json"
        if gs.exists():
            try:
                atom = (json.loads(gs.read_text(encoding="utf-8", errors="replace")).get("electron-persisted-atom-state") or {})
                for u in atom.get("seen-model-upgrade-list") or []:
                    if isinstance(u, str):
                        found.append(u)
            except ValueError:
                pass
        # Check built-in OpenAI docs model table if present
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


def claude_models():
    """Dynamically discover all Claude models from ~/.claude/settings.json, gateway-models.json, and model-catalog."""
    found = []
    cdir = Path.home() / ".claude"
    try:
        # 1) Custom gateway or env models in settings.json
        sp = cdir / "settings.json"
        if sp.exists():
            env = (json.loads(sp.read_text(encoding="utf-8", errors="replace")).get("env") or {})
            for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                      "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
                if env.get(k):
                    found.append(env[k])
        # 2) Cached gateway models
        gp = cdir / "cache" / "gateway-models.json"
        if gp.exists():
            gdata = json.loads(gp.read_text(encoding="utf-8", errors="replace"))
            for m in gdata.get("models") or []:
                if isinstance(m, dict) and m.get("id"):
                    found.append(m["id"])
        # 3) Latest model-catalog cache
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


def parse_features(text):
    return sorted(m.group(1) for m in re.finditer(r"^(\S+)\s+stable\b", text, re.M))


def scan_skills():
    out = {}
    for vendor, dirs in SKILL_DIRS.items():
        skills = {}
        for d in dirs:
            base = Path(d).expanduser()
            if not base.is_dir():
                continue
            for f in sorted(base.glob("*/SKILL.md")):
                try:
                    txt = f.read_text(encoding="utf-8", errors="replace")[:3000]
                except OSError:
                    continue
                m = re.search(r"^description:\s*(.+)$", txt, re.M)
                skills[f.parent.name] = (m.group(1).strip().strip("\"'")[:110] if m else "")
        out[vendor] = skills
    return out


def scan_agy_plugin_dirs():
    base = Path.home() / ".gemini" / "config" / "plugins"
    return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []


def probe_agent(name):
    exe = ao.resolve_exe(name)
    snap = {"available": bool(exe), "exe": " ".join(exe) if exe else None, "probe_errors": {}}
    if not exe:
        return snap
    raw = {}
    for key, args in PROBES[name].items():
        raw[key], err = probe(exe, args)
        if err:
            snap["probe_errors"][key] = err
    first = raw.get("version", "").strip().splitlines()
    snap["version"] = (re.search(r"\d+\.\d+\.\d+\S*", first[0]).group(0)
                       if first and re.search(r"\d+\.\d+\.\d+", first[0]) else (first[0] if first else None))
    snap["flags"] = parse_flags(raw.get("help", "") + "\n" + raw.get("exec_help", "") + "\n" + raw.get("review_help", ""))
    snap["subcommands"] = parse_subcommands(raw.get("help", ""))
    snap["mcp"] = parse_names(raw.get("mcp", ""))
    if name == "agy":
        snap["models"] = parse_models_agy(raw.get("models", ""))
    elif name == "codex":
        snap["models"] = ao.live_models_codex()
    elif name == "claude":
        snap["models"] = ao.live_models_claude()
    else:
        snap["models"] = []
    snap["plugins"] = sorted(set(parse_names(raw.get("plugin", ""))) | set(scan_agy_plugin_dirs())) \
        if name == "agy" else []
    snap["features"] = parse_features(raw.get("features", "")) if name == "codex" else []
    m = re.search(r'"loggedIn"\s*:\s*(true|false)', raw.get("auth", ""))
    if m:  # only claude reports this without a model call; None means unknown
        snap["authenticated"] = m.group(1) == "true"
    return snap


def full_snapshot(prev):
    snap = {"schema": 1, "updated": ao.now(), "agents": {}, "skills": scan_skills()}
    for name in PROBES:
        snap["agents"][name] = probe_agent(name)
        keep = ((prev.get("agents") or {}).get(name) or {}).get("self_report")
        if keep:
            snap["agents"][name]["self_report"] = keep
    return snap


def diff(prev, cur):
    lines = []
    for name, c in cur["agents"].items():
        p = (prev.get("agents") or {}).get(name) or {}
        if p.get("version") != c.get("version"):
            lines.append(f"{name} version {p.get('version')} -> {c.get('version')}")
        if p.get("authenticated") != c.get("authenticated"):
            lines.append(f"{name} authenticated {p.get('authenticated')} -> {c.get('authenticated')}")
        if p.get("available") != c.get("available"):
            lines.append(f"{name} available {p.get('available')} -> {c.get('available')}")
        if not c.get("available"):
            continue
        for f in LIST_FIELDS:
            a, b = set(p.get(f) or []), set(c.get(f) or [])
            lines += [f"{name} + {f[:-1] if f.endswith('s') else f} {x}" for x in sorted(b - a)]
            lines += [f"{name} - {f[:-1] if f.endswith('s') else f} {x}" for x in sorted(a - b)]
    for v, sk in cur["skills"].items():
        old = set(((prev.get("skills") or {}).get(v)) or {})
        lines += [f"{v} + skill {x}" for x in sorted(set(sk) - old)]
        lines += [f"{v} - skill {x}" for x in sorted(old - set(sk))]
    return lines


def record_candidates(cur):
    models = ao.load_models()
    known = set()
    for v in models["vendors"].values():
        known |= {t["model"] for t in v["tiers"].values()} | {v["fallback_model"]}
    path = ao.ao_home() / "candidates.json"
    try:
        cands = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cands = []
    seen = {(c["vendor"], c["model"]) for c in cands}
    new = []
    for name in ("codex", "agy", "claude"):
        for m in cur["agents"][name].get("models") or []:
            if m not in known and (name, m) not in seen:
                cands.append({"vendor": name, "model": m, "first_seen": ao.now()[:10],
                              "inferred_tier": ao.infer_tier(name, m, models),
                              "family": ao.model_family(name, m, models),
                              "note": "dynamically discovered; scored automatically by route.py"})
                new.append(f"{name} candidate model {m}")
    if new:
        path.write_text(json.dumps(cands, indent=1), encoding="utf-8")
    return new


def render_md(snap):
    models_cfg = ao.load_models()
    L = [f"# Capabilities & Live Model Matrix (updated {snap['updated']})", ""]
    for name, a in snap["agents"].items():
        if not a.get("available"):
            L += [f"## {name}: not found", ""]
            continue
        L.append(f"## {name} {a.get('version')}" + (" (NOT LOGGED IN: `claude auth login`)"
                                                       if a.get("authenticated") is False else ""))
        L.append(f"- subcommands: {', '.join(a['subcommands']) or '-'}")
        L.append(f"- flags: {len(a['flags'])} known (see capabilities.json)")
        if a["models"]:
            L.append(f"- live discovered models ({len(a['models'])}): {', '.join(a['models'])}")
            active_tiers = []
            for t in models_cfg["tier_order"]:
                dcfg = ao.dynamic_tier_config(models_cfg, snap, name, t)
                active_tiers.append(f"{t}={dcfg['model']}")
            L.append(f"- auto-selected tiers: {', '.join(active_tiers)}")
        if a["features"]:
            L.append(f"- stable features: {len(a['features'])}")
        L.append(f"- mcp: {', '.join(a['mcp']) or '-'}")
        if a["plugins"]:
            L.append(f"- plugins: {', '.join(a['plugins'])}")
        if a.get("self_report"):
            L.append("- built-in tools (self-reported):")
            L += [f"  - {x}" for x in a["self_report"]]
        if a["probe_errors"]:
            L.append(f"- probe errors: {a['probe_errors']}")
        L.append("")
    L.append("## Skills a brief can name (\"Required skill\")")
    for v, sk in snap["skills"].items():
        L.append(f"- {v}: {', '.join(sk) or '-'}")
    return "\n".join(L) + "\n"


def load_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cmd_quick(force):
    home = ao.ao_home()
    state = load_json(home / "state.json")
    if not force and state.get("quick_checked", 0) > time.time() - 86400:
        print("quick: checked within 24h, skipping (use --force)")
        return 0
    prev = load_json(home / "capabilities.json")
    if not prev:
        print("quick: no snapshot yet -> run discover.py")
        return 10
    changed = []
    for name in PROBES:
        exe = ao.resolve_exe(name)
        text, err = probe(exe, ["--version"]) if exe else ("", "missing")
        m = re.search(r"\d+\.\d+\.\d+\S*", text)
        cur = m.group(0) if m else None
        old = (prev.get("agents", {}).get(name) or {}).get("version")
        if cur != old:
            changed.append(f"{name}: {old} -> {cur}")
    if changed:
        print("quick: changed -> run discover.py: " + "; ".join(changed))
        return 10
    state["quick_checked"] = time.time()
    (home / "state.json").write_text(json.dumps(state), encoding="utf-8")
    print("quick: no version change")
    return 0


def cmd_full():
    home = ao.ao_home()
    prev = load_json(home / "capabilities.json")
    cur = full_snapshot(prev)
    lines = diff(prev, cur) if prev else []
    lines += record_candidates(cur)
    (home / "capabilities.json").write_text(json.dumps(cur, indent=1), encoding="utf-8")
    (home / "capabilities.md").write_text(render_md(cur), encoding="utf-8")
    if lines or not prev:
        with open(home / "changes.md", "a", encoding="utf-8") as f:
            f.write(f"\n## {cur['updated']}\n")
            f.write("- baseline captured\n" if not prev and not lines else "")
            f.writelines(f"- {x}\n" for x in lines)
    st = load_json(home / "state.json")
    st["quick_checked"] = time.time()
    (home / "state.json").write_text(json.dumps(st), encoding="utf-8")
    print(f"snapshot saved; {len(lines)} change(s)" + (" (baseline)" if not prev else ""))
    for x in lines[:40]:
        print("  " + x)
    return 0


DEEP_BRIEF = """## Role
Inventory clerk: list what this agent can do that a manager could delegate.
## Intent
The manager routes work by capability. It needs your built-in tools and features, including ones that
`--help` does not show (for example media generation, browsing, image/video tools, code execution).
## Definition of Done
`evidence` has one item per built-in tool or capability, formatted `tool_name: one-line purpose`.
## Scope
Answer from what you know about your own tool set. Do NOT call any tool, read files or run commands.
## Authority
propose-only. Never modify anything.
## Output
Return the result envelope. status "done"; summary one sentence; deliverables []; evidence as above;
risks []; next_action "".
"""


def cmd_deep(agent, yes):
    if agent not in PROBES:
        sys.exit(f"agent must be one of {list(PROBES)}")
    if not yes:
        sys.exit("--deep runs a real model call (~12-20k tokens). Get the user's OK, then add --yes.")
    home = ao.ao_home()
    work = home / "deep"
    work.mkdir(exist_ok=True)
    brief = work / f"brief-{agent}.md"
    brief.write_text(DEEP_BRIEF, encoding="utf-8")
    snap = load_json(home / "capabilities.json")
    tier = ao.dynamic_tier_config(ao.load_models(), snap, agent, "fast")
    cmd = [sys.executable, str(HERE / "agent_run.py"), "run", "--agent", agent, "--brief", str(brief),
           "--out", str(work / "runs" / f"{agent}-{time.strftime('%Y%m%d-%H%M%S')}"), "--cd", str(work),
           "--mode", "read", "--tier", "fast", "--task-type", "discover", "--no-ledger", "--timeout", "300",
           "--model", tier["model"]] + (["--effort", tier["effort"]] if tier.get("effort") else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    first = r.stdout.splitlines()[0] if r.stdout.strip().startswith("{") else "{}"
    meta = json.loads(first)
    rd = Path(meta.get("run_dir", ""))
    if not meta.get("ok") or not (rd / "result.json").exists():
        print(f"deep failed: {meta.get('failure') or r.stderr[-300:]}")
        return 1
    items = json.loads((rd / "result.json").read_text(encoding="utf-8")).get("evidence") or []
    snap = snap or full_snapshot({})
    snap["agents"][agent]["self_report"] = items
    snap["updated"] = ao.now()
    (home / "capabilities.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
    (home / "capabilities.md").write_text(render_md(snap), encoding="utf-8")
    with open(home / "changes.md", "a", encoding="utf-8") as f:
        f.write(f"\n## {snap['updated']}\n- {agent} self-report: {len(items)} tool(s) recorded\n")
    print(f"{agent}: {len(items)} tool(s) recorded (tokens={meta.get('tokens_used')})")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--deep", metavar="AGENT")
    p.add_argument("--yes", action="store_true")
    a = p.parse_args()
    sys.exit(cmd_quick(a.force) if a.quick else cmd_deep(a.deep, a.yes) if a.deep else cmd_full())


if __name__ == "__main__":
    main()
