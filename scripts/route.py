#!/usr/bin/env python3
"""Recommend vendor, model, effort, verify level, brief mode and a ready-to-run command for one work package.
Zero LLM tokens. Inspects live available models per agent in real time (never out-of-date) and adapts
using the verdict ledger.

  route.py --task-type T [--risk low|med|high] [--ambiguity low|high] [--size s|m|l]
           [--manager claude|codex|agy] [--builder VENDOR] [--need KEYWORD ...]
           [--type1] [--sensitive] [--json]
  route.py --list-models                 # show all live available models and auto-selected tiers right now
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ao_common as ao  # noqa: E402

WINDOW = 10
TIMEOUT = {"s": 300, "m": 900, "l": 1800}


def load_caps():
    p = ao.ao_home() / "capabilities.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tier_for(models, caps, vendor, idx):
    order, tiers = models["tier_order"], models["vendors"][vendor]["tiers"]
    i = min(idx, len(order) - 1)
    while i > 0 and order[i] not in tiers:
        i -= 1
    tname = order[i]
    dcfg = ao.dynamic_tier_config(models, caps, vendor, tname)
    return i, tname, dcfg


def caps_text(caps, vendor):
    a = (caps.get("agents") or {}).get(vendor) or {}
    keep = {k: a.get(k) for k in ("self_report", "flags", "subcommands", "mcp", "plugins", "features")}
    keep["skills"] = (caps.get("skills") or {}).get(vendor)
    return json.dumps(keep).lower()


def adapt(models, recs, task, vendor, idx, risk, floor_idx, reasons):
    order = models["tier_order"]
    st = ao.verdict_stats(recs, task, vendor, order[idx], window=WINDOW)
    if st["n"] >= 3 and st["rate"] < 0.6:
        reasons.append(f"ledger: {st['accepts']}/{st['n']} accepted for {task}/{vendor}/{order[idx]} "
                       f"-> bumped one tier")
        return idx + 1
    if risk == "low" and idx - 1 >= floor_idx:
        low = ao.verdict_stats(recs, task, vendor, order[idx - 1], window=WINDOW)
        if low["streak"] >= 3:
            reasons.append(f"earned downshift: {low['streak']} straight accepts at {order[idx - 1]} "
                           f"for {task}/{vendor}, risk low, floor respected")
            return idx - 1
    return idx


def expand(models, pref, manager):
    """Preference entry -> (vendor, min_tier_idx, is_native)."""
    order = models["tier_order"]
    if pref == "native":
        return manager, 0, True
    al = (models.get("vendor_aliases") or {}).get(pref)
    if al:
        return al["vendor"], order.index(al["min_tier"]), False
    return pref, 0, False


def cmd_list_models(as_json=False):
    models = ao.load_models()
    caps = load_caps()
    out = {}
    for v in models["vendors"]:
        exe = ao.resolve_exe(v)
        live = ao.get_available_models(v, caps) if exe else []
        tiers = {}
        for t in models["tier_order"]:
            dcfg = ao.dynamic_tier_config(models, caps, v, t)
            tiers[t] = {"selected": dcfg["model"], "effort": dcfg.get("effort"),
                        "family": dcfg.get("family"), "candidates": dcfg.get("available_in_tier", [])}
        out[v] = {"available": bool(exe), "live_model_count": len(live), "live_models": live, "tiers": tiers}
    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    for v, info in out.items():
        if not info["available"]:
            print(f"## {v}: CLI not found")
            continue
        print(f"## {v} ({info['live_model_count']} live models available)")
        print("  all live: " + (", ".join(info["live_models"]) or "-"))
        for t, tinfo in info["tiers"].items():
            eff = f"/{tinfo['effort']}" if tinfo.get("effort") else ""
            cands = ", ".join(tinfo["candidates"][:3])
            print(f"  - {t:12s} -> {tinfo['selected']}{eff}  (top matches: {cands})")
        print()
    return 0


def route(a):
    models = ao.load_models()
    order = models["tier_order"]
    task_name = ao.canonical_task(a.task_type, models)
    task = models["tasks"].get(task_name)
    if not task:
        sys.exit(f"unknown task type '{a.task_type}'. Known: {', '.join(models['tasks'])}")
    caps, recs = load_caps(), ao.ledger_read()
    reasons = []
    if not caps:
        reasons.append("no capabilities snapshot: using real-time live model scan")

    floor_idx = order.index(models["risk_floor"][a.risk])
    base_idx = order.index(task["base_tier"])
    idx = max(base_idx, floor_idx)
    reasons.append(f"base {task['base_tier']}, {a.risk}-risk floor {order[floor_idx]}")
    if a.ambiguity == "high":
        idx += 1
        reasons.append("high ambiguity: +1 tier")

    cands, seen = [], set()
    for pref in task["vendor_preference"] + list(models["vendors"]):
        v, min_idx, native = expand(models, pref, a.manager)
        if (v, native) in seen or v not in models["vendors"]:
            continue
        seen.add((v, native))
        cands.append((v, min_idx, native, pref in task["vendor_preference"]))
    agents = caps.get("agents") or {}
    same_model_req = getattr(a, "same_model", False)
    single_host_req = getattr(a, "single_host", False) or same_model_req
    if single_host_req:
        avail = [c for c in cands if c[0] == a.manager]
        mode_desc = "same-model clean-context sub-agents" if same_model_req else "clean-context sub-agents & intra-host models"
        reasons.append(f"single-host mode ({a.manager} only): using {mode_desc}")
    else:
        avail = [c for c in cands if c[2] or (ao.resolve_exe(c[0]) and agents.get(c[0], {}).get("authenticated") is not False)]
    if a.need:
        matched = [c for c in avail if all(k.lower() in caps_text(caps, c[0]) for k in a.need)]
        if not matched:
            return {"error": f"no known vendor advertises {a.need}. Run: discover.py --deep <agent> "
                             "(costs tokens; ask the user first), then retry."}
        avail = matched
    else:
        pref_avail = [c for c in avail if c[3]]
        avail = pref_avail or avail

    unique_hosts = list(dict.fromkeys(c[0] for c in avail))
    single_host_active = single_host_req or len(unique_hosts) == 1

    builder = a.builder
    single_host_indep_fallback = False
    bfam = ao.model_family(builder, None, models) if builder else None
    if task["independent"] and builder:
        other = [c for c in avail if ao.model_family(c[0], tier_for(models, caps, c[0], max(idx, c[1]))[2].get("model"), models) != bfam]
        diff_vendor = other or [c for c in avail if c[0] != builder]
        if diff_vendor and not single_host_req:
            avail = diff_vendor
            reasons.append(f"independent review: not {builder}" + (" (different company/family)" if other else ""))
        else:
            # Only 1 vendor is available (e.g. only Antigravity is installed, or --single-host / --same-model requested)
            single_host_indep_fallback = True
            single_host_active = True
    elif task["independent"]:
        reasons.append("independence NOT established: no --builder given, so the reviewer may share "
                       "the builder's vendor")
    if not avail:
        return {"error": "no available vendor satisfies the constraints"}

    def pick(c):
        v, min_idx, native, _ = c
        i = adapt(models, recs, task_name, v, max(idx, min_idx), a.risk, floor_idx, reasons)
        return v, native, tier_for(models, caps, v, max(i, min_idx))

    out = {"task": task_name, "risk": a.risk, "single_host": single_host_active, "same_model": same_model_req}
    v, native, (ti, tname, tcfg) = pick(avail[0])
    if single_host_indep_fallback:
        alt_model, alt_fam = (None, None) if same_model_req else ao.intra_host_alt_family_model(v, bfam, tname, models, caps)
        if alt_model and alt_fam != bfam:
            tcfg = dict(tcfg)
            tcfg["model"] = alt_model
            tcfg["family"] = alt_fam
            reasons.append(f"single-host independent review on {v}: switched to intra-host alternate family "
                           f"'{alt_fam}' ({alt_model}) + Zero-Prior Clean-Context Sub-Agent (or pass --same-model to keep '{tier_for(models, caps, v, ti)[2]['model']}')")
        else:
            native = True
            reasons.append(f"same-model independent review on {v} ({tcfg['model']}): enforce Zero-Prior Clean-Context Sub-Agent "
                           "Isolation + Adversarial Expert Lens (fresh KV-cache without builder's reasoning tokens)")
    elif tcfg.get("source") == "live_discovered":
        reasons.append(f"live scan ({tcfg.get('total_live_models', '?')} models on {v}): picked '{tcfg['model']}' "
                       f"over {tcfg.get('available_in_tier', [])[1:3]}")
    ext = models["vendors"]
    overhead = {k: ext[k]["overhead_tokens"] for k in ext if ext[k]["overhead_tokens"]}
    gate = None
    if (a.size == "s" and not native and not task["independent"] and not a.need):
        gate = (f"size s: external call costs ~{ext[v]['overhead_tokens'] or '?'} tokens of fixed overhead "
                f"({', '.join(f'{k} ~{n}' for k, n in overhead.items())}); use a native subagent "
                "or do it yourself")
        v, native = a.manager, True
        ti, tname, tcfg = tier_for(models, caps, v, idx)
        reasons.append("overhead gate -> native")
    elif a.size == "s" and native:
        gate = (f"size s: keep it native; external calls cost ~{', '.join(f'{k} {n}' for k, n in overhead.items())}"
                " tokens of fixed overhead each")

    writes = task.get("writes")
    verify = task["verify_floor"]
    if a.type1 and task.get("type1_verify"):
        verify = task["type1_verify"]
    if a.type1 or a.sensitive or task_name == "security-review":
        verify = "L3"
    if verify == "n/a" and (a.type1 or a.sensitive):
        verify = "L3"

    brief_mode = task.get("brief_mode") or ("exploratory" if a.ambiguity == "high" else "guided")
    if a.ambiguity == "high" and brief_mode == "tight":
        brief_mode = "guided"

    cmd = None
    cli_mode_flags = " --mode write --may-write PATH/ [--worktree]" if writes else " --mode read"
    if native:
        chan = {
            "claude": f'Agent(model="{tcfg["model"]}"' + (', isolation="worktree"' if writes else '') + f')  [or CLI: agent_run.py run --agent claude --brief BRIEF.md --model {tcfg["model"]}{cli_mode_flags}]',
            "codex": f'spawn_agent  [or CLI: agent_run.py run --agent codex --brief BRIEF.md --model {tcfg["model"]}{cli_mode_flags}]',
            "agy": (f"agy define_subagent(EnableWriteTools={bool(writes)}) + invoke_subagent(Model='inherit'|'pro', Workspace='branch'|'inherit')  "
                    f"[or CLI: agent_run.py run --agent agy --brief BRIEF.md --model {tcfg['model']}{cli_mode_flags}]")
        }[v]
        cmd = f"{chan} - or do it yourself if the brief costs as much as the work"
    else:
        cmd = (f"python {Path(__file__).resolve().parent / 'agent_run.py'} run --agent {v} --brief BRIEF.md "
               f"--model {tcfg['model']}" + (f" --effort {tcfg['effort']}" if tcfg.get("effort") else "") +
               (" --mode write --may-write PATH/" if writes else " --mode read") +
               f" --task-type {task_name} --risk {a.risk} --tier {tname} --timeout {TIMEOUT[a.size]}")

    ladder = []
    if ti + 1 < len(order):
        ni, nn, nc = tier_for(models, caps, v, ti + 1)
        if nn != tname:
            ladder.append(f"{v} {nn} ({nc['model']})")
    for c in avail:
        if c[0] != v:
            _, cn, cc = tier_for(models, caps, c[0], ti)
            ladder.append(f"{c[0]} {cn} ({cc['model']})")
            break

    council = ao.expert_council_for_task(task_name)
    hw = ao.probe_hardware()
    rec_wip = hw["recommended_wip"]
    same_model_panel = [f"{v}/{tcfg['model']} [{lobj['lens']}" + (" (WRITE)" if lobj.get("writes") else "") + "]"
                        for lobj in council["lenses"][:min(4, rec_wip)]]
    scope_args = " --scope core:src/core/ --scope api:src/api/" + (" --worktree" if writes and hw["worktree_safe"] else "") if writes else ""
    parallel_cmd = (f"python {Path(__file__).resolve().parent / 'agent_run.py'} parallel "
                    f"--brief BRIEF.md --task-type {task_name}{scope_args} --agent {v} --model {tcfg['model']} --wip {rec_wip} [--execute]")
    fanout_guide = {
        "agy": f"Parallel sub-agents (hardware-capped wip={rec_wip}): call `define_subagent(EnableWriteTools={bool(writes)})` + up to {rec_wip} parallel `invoke_subagent(Model='inherit', Workspace='{'branch' if writes and hw['worktree_safe'] else 'inherit'}')` with Zero-Prior Briefs" + (" & disjoint `--may-write` scopes" if writes else "") + f", OR run `{parallel_cmd}`.",
        "claude": f"Parallel sub-agents (hardware-capped wip={rec_wip}): call up to {rec_wip} parallel `Agent(subagent_type='general-purpose', model='{tcfg['model']}'" + (", isolation='worktree'" if writes and hw["worktree_safe"] else "") + f")`, OR run `{parallel_cmd}`.",
        "codex": f"Parallel sub-agents (hardware-capped wip={rec_wip}): call up to {rec_wip} parallel `spawn_agent` on `{tcfg['model']}`, OR run `{parallel_cmd}`."
    }.get(v, "")

    out.update(vendor=v, native=native, tier=tname, model=tcfg["model"], effort=tcfg.get("effort"),
               family=tcfg.get("family") or ao.model_family(v, tcfg["model"], models),
               model_source=tcfg.get("source", "static_default"),
               available_in_tier=tcfg.get("available_in_tier", [tcfg["model"]]),
               brief_mode=brief_mode, verify=verify, why=reasons, overhead_gate=gate,
               escalation=ladder, command=cmd, fallback=models["vendors"][v]["fallback_model"],
               overhead_tokens=ext[v]["overhead_tokens"],
               writes=bool(writes),
               hardware=hw,
               recommended_wip=rec_wip,
               expert_lenses=council["lenses"],
               debias_rules=council["debias_rules"],
               planning_workflow=council["planning_workflow"],
               same_model_panel=same_model_panel,
               parallel_command=parallel_cmd,
               single_host_fanout=fanout_guide)
    if task.get("panel") or single_host_req:
        if not single_host_active and len(unique_hosts) > 1:
            out["panel"] = [f"{k} {tier_for(models, caps, k, idx)[2]['model']}"
                            for k in unique_hosts]
        elif same_model_req:
            out["panel"] = same_model_panel[:3]
        else:
            # Single-host panel: combine intra-host model families (if multiple exist) with Orthogonal Expert Lenses
            fam_models = ao.intra_host_family_models(v, tier_name=tname, models=models, caps=caps)
            lenses = council["lenses"][:3]
            panel_items = []
            for i_l, lobj in enumerate(lenses):
                m_pick = fam_models[i_l % len(fam_models)][1] if fam_models else tcfg["model"]
                panel_items.append(f"{v}/{m_pick} [{lobj['lens']}]")
            out["panel"] = panel_items
    return out


def render(o):
    if "error" in o:
        return "NONE FOUND: " + o["error"]
    eff = f"/{o['effort']}" if o["effort"] else ""
    ov = f"~{o['overhead_tokens']} tokens fixed overhead" if o["overhead_tokens"] else "small overhead"
    cands = ", ".join(o.get("available_in_tier") or [])
    lines = [f"primary: {o['vendor']}{' (native)' if o['native'] else ''} {o['model']}{eff}  [tier {o['tier']}, brief: {o['brief_mode']}, source: {o['model_source']}]",
             f"live tier candidates on {o['vendor']}: [{cands}]",
             "why: " + "; ".join(o["why"])]
    if o["overhead_gate"]:
        lines.append("gate: " + o["overhead_gate"])
    lines += [f"fallback: {o['fallback']}   escalate (max 3 attempts total): " +
              (" -> ".join(o["escalation"]) or "take over"),
              f"verify: {o['verify']}   {ov}"]
    if o.get("hardware"):
        lines.append("hardware: " + o["hardware"]["summary"])
    if o.get("panel"):
        label = ("same-model sub-agent panel" if o.get("same_model") else
                 ("single-host multi-lens panel" if o.get("single_host") else "panel (one per vendor)"))
        lines.append(f"{label}: " + " | ".join(o["panel"]))
    if o.get("same_model_panel") and o.get("single_host") and not o.get("same_model"):
        lines.append("same-model panel (1 model, clean KV-cache per lens): " + " | ".join(o["same_model_panel"]))
    if o.get("expert_lenses") and (o.get("single_host") or o.get("writes") or o["task"] in ("explore", "design", "debug", "critique", "review", "security-review")):
        lens_str = " | ".join(f"{x['lens']}{'[WRITE]' if x.get('writes') else '[READ]'} ({x['mandate'][:44]}...)" for x in o["expert_lenses"][:4])
        lines.append(f"parallel roles (clean-context sub-agents): {lens_str}")
        if o.get("single_host_fanout"):
            lines.append(f"parallel fan-out ({o['vendor']}): {o['single_host_fanout']}")
    lines.append("run: " + o["command"])
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list-models", action="store_true", help="inspect all live available models and tier picks across all agents")
    p.add_argument("--task-type", help="canonical or descriptive task type (required unless --list-models)")
    p.add_argument("--risk", choices=["low", "med", "high"], default="med")
    p.add_argument("--ambiguity", choices=["low", "high"], default="low")
    p.add_argument("--size", choices=["s", "m", "l"], default="m")
    p.add_argument("--manager", choices=["claude", "codex", "agy"], default="claude")
    p.add_argument("--builder", choices=["claude", "codex", "agy"])
    p.add_argument("--single-host", action="store_true", help="route using only --manager (via clean-context sub-agents, intra-host model families, and orthogonal expert lenses)")
    p.add_argument("--same-model", action="store_true", help="keep ALL sub-agents / reviewers on the exact SAME single model, achieving independence via clean KV-cache + Zero-Prior Briefs + Orthogonal Expert Lenses")
    p.add_argument("--need", action="append", default=[])
    p.add_argument("--type1", action="store_true", help="hard-to-reverse decision: forces verify L3")
    p.add_argument("--sensitive", action="store_true", help="security, data or deploy work: forces verify L3")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    if a.list_models:
        sys.exit(cmd_list_models(a.json))
    if not a.task_type:
        p.error("--task-type is required (or pass --list-models)")
    o = route(a)
    print(json.dumps(o, indent=2) if a.json else render(o))
    sys.exit(3 if "error" in o else 0)


if __name__ == "__main__":
    main()
