#!/usr/bin/env python3
"""anatomy.py — Orchestration Anatomy Engine (Size Gate, Truth Interlock, Parts BOM, Settle & Audit to Zero, Change-Ripple Amend & 4x Junction Check)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ao_common as ao  # noqa: E402


def _parse_pkg_spec(spec: str) -> dict:
    """Parse --pkg name[:brief_mode[:deps[:may_write[:skills[:outputs]]]]] safely preserving Windows drive letters."""
    parts = re.split(r":(?![\\/])", spec)
    name = (parts[0] if len(parts) > 0 else "").strip()
    if not name:
        raise ValueError(f"Invalid --pkg spec '{spec}': missing package name")
    raw_mode = (parts[1] if len(parts) > 1 and parts[1].strip() else "guided").strip().lower()
    deps = [x.strip() for x in (parts[2] if len(parts) > 2 else "").split(",") if x.strip()]
    may_write = [x.strip() for x in (parts[3] if len(parts) > 3 else "").split(",") if x.strip()]
    skills = [x.strip() for x in (parts[4] if len(parts) > 4 else "").split(",") if x.strip()]
    outputs = [x.strip() for x in (parts[5] if len(parts) > 5 else "").split(",") if x.strip()]
    exec_mode = "write" if (may_write or raw_mode == "write") else "read"
    brief_mode = raw_mode if raw_mode in ("tight", "guided", "exploratory") else ("guided" if exec_mode == "write" else "exploratory")
    return {
        "name": name,
        "mode": exec_mode,
        "brief_mode": brief_mode,
        "depends_on": deps,
        "may_write": may_write,
        "skill": skills,
        "outputs": outputs,
    }


def _scaffold_truth_contract(path: Path, goal: str, pkgs: list[dict], invariants: list[dict]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Shared Truth Contract — {goal}",
        "",
        "## 1. System Goal & Non-Negotiable Invariants (Keyhole Interlock)",
        f"- **Primary Objective**: {goal}",
        "- Every worker package MUST read and obey all names, schemas, thresholds, and constraints declared in this contract.",
        "- **NO SILENT DRIFT**: Never unilaterally change a shared constant, threshold, or interface in your files while other packages remain on the old value. If empirical evidence proves a locked value must change, emit a `truth_amendments` entry with concrete `file:line` / command proof so the orchestrator updates the Truth Contract and re-syncs all affected packages.",
        "",
        "## 2. Locked User Prerequisites & Threshold Keyholes",
    ]
    if invariants:
        for inv in invariants:
            if inv["op"] in ("must", "forbid"):
                lines.append(f"- **`{inv['op'].upper()}`**: `{inv['value']}`")
            else:
                lines.append(f"- **`{inv['key']}`** `{inv['op']}` `{inv['value']}`")
    else:
        lines.append("- *(No scalar/pattern invariants locked yet; pass `--invariant KEY=VAL` or `KEY<=VAL` to lock thresholds)*")
    lines.extend([
        f"<!-- INVARIANTS_JSON: {json.dumps(invariants, ensure_ascii=False)} -->",
        "",
        "## 3. Parts Bill of Materials (BOM) & Seam Contracts",
    ])
    for idx, p in enumerate(pkgs, 1):
        deps = ", ".join(p.get("depends_on") or []) or "(root / Wave 0)"
        writes = ", ".join(p.get("may_write") or []) or "(read-only)"
        outs = ", ".join(p.get("outputs") or []) or f".orch/{p['name']}/result.json"
        lines.append(
            f"{idx}. **`{p['name']}`** (`mode={p['mode']}`, `brief_mode={p['brief_mode']}`) — depends_on: `{deps}` | may_write: `{writes}` | outputs: `{outs}`"
        )
    lines.extend([
        "",
        "## 4. Shared Data Shapes & Result Envelope",
        "- Return the standard JSON result envelope (`status`, `summary`, `confidence`, `evidence`, `deliverables`, `assumptions_challenged`, `open_questions`, `truth_amendments`, `risks`, `next_action`).",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scaffold_pkg_brief(
    path: Path,
    goal: str,
    truth_rel: str,
    pkg: dict,
    invariants: list[dict],
) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    writes = ", ".join(pkg.get("may_write") or []) or "Read-only (no project file mutations)"
    deps = ", ".join(pkg.get("depends_on") or []) or "None (Wave 0 root package)"
    outs = ", ".join(pkg.get("outputs") or []) or f"Structured result envelope (.orch/{pkg['name']}/result.json)"
    skills = ", ".join(pkg.get("skill") or []) or "None"
    inv_summary = ", ".join(
        f"{x['op']}:{x['value']}" if x["op"] in ("must", "forbid") else f"{x['key']}{x['op']}{x['value']}"
        for x in (invariants or [])
    ) or "See Truth Contract"
    content = "\n".join([
        f"# Work Package Brief — `{pkg['name']}` ({pkg['brief_mode'].upper()} Brief / {pkg['mode'].upper()} Access)",
        "",
        "## Shared Truth & Keyhole Invariants",
        f"- **Overall Goal**: {goal}",
        f"- **Shared Truth Contract**: `{truth_rel}` (mounted in `--context-file`; write-locked)",
        f"- **Locked Prerequisites & Thresholds**: `{inv_summary}`",
        f"- **Upstream Dependencies (`depends_on`)**: {deps}",
        f"- **Delegated Specialized Skills (`--skill`)**: {skills}",
        "",
        "## Scope & Write Boundaries",
        f"- **Allowed Write Scope (`--may-write`)**: {writes}",
        f"- **Declared Deliverable Outputs (`outputs`)**: {outs}",
        "",
        "## Concrete Assignment & Acceptance Criteria",
        f"1. Execute work package `{pkg['name']}` to advance: {goal}.",
        "2. Strictly obey all locked prerequisites and thresholds in the Shared Truth Contract. Never silently change a shared parameter/interface; if a threshold is infeasible, report it in `truth_amendments` with empirical `evidence`.",
        "3. Cite exact `file:line` anchors or command outputs in `evidence`, and report any cross-seam mismatch in `assumptions_challenged`.",
    ])
    path.write_text(content + "\n", encoding="utf-8")


def cmd_init(a: argparse.Namespace) -> int:
    proj = Path(a.project_dir).resolve()
    out_path = Path(a.out) if Path(a.out).is_absolute() else (proj / a.out)
    orch_dir = out_path.parent
    orch_dir.mkdir(parents=True, exist_ok=True)

    raw_pkgs = [_parse_pkg_spec(s) for s in a.pkg]
    invariants = [ao.parse_invariant_spec(s) for s in (a.invariant or [])]
    tier = ao.size_tier_of_plan(len(raw_pkgs))
    if tier == "epic" and not a.allow_epic:
        sys.stderr.write(
            f"[anatomy] EPIC GATE: Plan has {len(raw_pkgs)} packages (>8 = epic scale). "
            "Propose a Hero slice (4-8 packages) first, or pass --allow-epic if the user explicitly approved the Epic.\n"
        )
        return 2

    if a.truth_contract:
        truth_rel = a.truth_contract
    else:
        try:
            truth_rel = str((orch_dir / "truth-contract.md").relative_to(proj)).replace("\\", "/")
        except ValueError:
            truth_rel = str(orch_dir / "truth-contract.md")
    truth_abs = Path(truth_rel) if Path(truth_rel).is_absolute() else (proj / truth_rel)
    _scaffold_truth_contract(truth_abs, a.goal, raw_pkgs, invariants)

    plan_pkgs = []
    for p in raw_pkgs:
        brief_abs = orch_dir / f"brief-{p['name']}.md"
        _scaffold_pkg_brief(brief_abs, a.goal, truth_rel, p, invariants)
        try:
            brief_rel = str(brief_abs.relative_to(proj)).replace("\\", "/")
        except ValueError:
            brief_rel = str(brief_abs)
        entry: dict = {
            "name": p["name"],
            "mode": p["mode"],
            "brief_mode": p["brief_mode"],
            "brief": brief_rel,
            "depends_on": p["depends_on"],
            "may_write": p["may_write"],
            "context_file": [truth_rel],
            "skill": p["skill"],
            "outputs": p["outputs"],
        }
        if a.agent:
            entry["agent"] = a.agent
        if a.model:
            entry["model"] = a.model
        plan_pkgs.append(entry)

    plan: dict = {
        "goal": a.goal,
        "truth_contract": truth_rel,
        "truth_version": 1,
        "invariants": invariants,
        "stale_packages": [],
        "epic_approved": bool(a.allow_epic),
        "packages": plan_pkgs,
    }
    settled = ao.settle_plan(plan, proj)
    plan["truth_hash"] = settled["truth_hash"]
    plan["size_tier"] = settled["size_tier"]
    plan["waves"] = [[p["name"] for p in w] for w in settled["waves"]]
    plan["packages"] = [
        {
            "name": p["name"],
            "mode": p["mode"],
            "brief_mode": p.get("brief_mode", "guided"),
            "wave": p["wave"],
            "brief": p.get("brief") or p.get("brief_file"),
            "depends_on": p["depends_on"],
            "may_write": p["may_write"],
            "context_file": p["context_file"],
            "skill": p["skill"],
            "outputs": p["outputs"],
            **({"agent": p["agent"]} if p.get("agent") else {}),
            **({"model": p["model"]} if p.get("model") else {}),
        }
        for p in settled["packages"]
    ]
    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    audit_res = ao.audit_plan(plan, proj)
    if a.json:
        print(json.dumps({"plan_file": str(out_path), "audit": audit_res}, indent=2))
    else:
        print(f"Scaffolded & settled plan -> {out_path}")
        print(ao.format_anatomy_report(audit_res))
    return 0 if audit_res["ok"] else 1


def cmd_settle(a: argparse.Namespace) -> int:
    proj = Path(a.project_dir).resolve()
    pfile = Path(a.plan_file).resolve()
    plan = json.loads(pfile.read_text(encoding="utf-8-sig"))
    settled = ao.settle_plan(plan, proj)
    if a.write:
        plan["truth_hash"] = settled["truth_hash"]
        plan["size_tier"] = settled["size_tier"]
        plan["waves"] = [[p["name"] for p in w] for w in settled["waves"]]
        plan["packages"] = settled["packages"]
        pfile.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    if a.json:
        print(json.dumps(settled, indent=2))
    else:
        print(
            f"Settled {len(settled['packages'])} packages ({settled['size_tier']}) into {len(settled['waves'])} waves "
            f"(wip={settled['wip']}, truth v{settled['truth_version']} #{str(settled['truth_hash'])[:8]}):"
        )
        for w_idx, w_pkgs in enumerate(settled["waves"]):
            print(f"  Wave {w_idx}: {', '.join(p['name'] for p in w_pkgs)}")
        if settled["cycles"]:
            print(f"  Cycles detected: {', '.join(settled['cycles'])}")
    return 0 if not settled["cycles"] else 1


def cmd_audit(a: argparse.Namespace) -> int:
    proj = Path(a.project_dir).resolve()
    pfile = Path(a.plan_file).resolve()
    plan = json.loads(pfile.read_text(encoding="utf-8-sig"))
    audit_res = ao.audit_plan(plan, proj)
    if a.json:
        print(json.dumps(audit_res, indent=2))
    else:
        print(ao.format_anatomy_report(audit_res))
    return 0 if audit_res["ok"] else 1


def cmd_amend(a: argparse.Namespace) -> int:
    """Formally amend locked prerequisites/thresholds in the Truth Contract, broadcast a mandatory
    notice into all packages' context_file, and mark already-executed affected packages as stale."""
    proj = Path(a.project_dir).resolve()
    pfile = Path(a.plan_file).resolve()
    plan = json.loads(pfile.read_text(encoding="utf-8-sig"))

    # Allow clearing stale package flags once resynced
    if a.clear_stale:
        to_clear = {x.strip() for s in a.clear_stale for x in s.split(",") if x.strip()}
        cur_stale = [p for p in (plan.get("stale_packages") or []) if p not in to_clear]
        plan["stale_packages"] = cur_stale
        pfile.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        if not a.set:
            if a.json:
                print(json.dumps({"ok": True, "stale_packages": cur_stale}, indent=2))
            else:
                print(f"Cleared stale status for {sorted(to_clear)}. Remaining stale_packages: {cur_stale}")
            return 0

    if not a.set:
        sys.stderr.write("error: pass --set KEY=VAL (or KEY<=VAL) or --clear-stale PKG\n")
        return 2

    affected = [x.strip() for s in (a.affect or []) for x in s.split(",") if x.strip()]
    amendments = []
    for spec in a.set:
        parsed = ao.parse_invariant_spec(spec)
        amendments.append({
            "key": parsed["key"],
            "op": parsed["op"],
            "proposed_value": parsed["value"],
            "reason": a.reason or "Updated shared threshold/prerequisite via anatomy amend",
            "evidence": a.evidence,
            "affected_packages": affected,
        })

    res = ao.amend_truth_contract(pfile, amendments, project_dir=proj, author_pkg=a.by or "manager")
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        if res["rejected"]:
            for r in res["rejected"]:
                print(f"REJECTED: {r}")
        if res["applied"]:
            print(f"Truth Contract amended -> v{res['truth_version']} (hash #{res['truth_hash'][:8]})")
            print(f"Broadcast notice mounted into all packages: {res['notice_file']}")
            if res["affected_packages"]:
                print(f"Affected packages notified: {', '.join(res['affected_packages'])}")
            if res["stale_packages"]:
                print(
                    f"RIPPLE INVALIDATION (STALE PACKAGES): {', '.join(res['stale_packages'])} "
                    "already produced outputs with the old value -> re-run/sync them and run `anatomy.py amend --clear-stale <pkg>`"
                )
    return 0 if res["ok"] else 1


def _locate_pkg_meta(results_dir: Path, proj: Path, pkg: dict) -> dict | None:
    """Locate meta.json/result.json for a package across explicit `out`, `<results_dir>/<name>`,
    and `<proj>/.orch/runs/<name>-*/attempt-*` (used by `agent_run.py batch`)."""
    name = pkg["name"]
    candidates: list[Path] = []
    if pkg.get("out"):
        out_p = Path(pkg["out"]) if Path(pkg["out"]).is_absolute() else (proj / pkg["out"])
        candidates.append(out_p)
    candidates.append(results_dir / name)
    for runs_root in (results_dir / "runs", proj / ".orch" / "runs"):
        if runs_root.exists():
            matched = sorted(runs_root.glob(f"{name}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
            candidates.extend(matched)

    for cand in candidates:
        if not cand.exists():
            continue
        # Check attempt-* subdirectories (latest attempt first)
        attempts = sorted(
            [d for d in cand.glob("attempt-*") if d.is_dir() and d.name.split("-")[-1].isdigit()],
            key=lambda x: int(x.name.split("-")[-1]),
            reverse=True,
        )
        for d in [*attempts, cand]:
            mfile = d / "meta.json"
            if mfile.exists():
                try:
                    return json.loads(mfile.read_text(encoding="utf-8-sig"))
                except Exception:
                    return {"run_dir": str(d)}
            if (d / "result.json").exists():
                return {"run_dir": str(d)}
    return None


def cmd_inspect(a: argparse.Namespace) -> int:
    proj = Path(a.project_dir).resolve()
    pfile = Path(a.plan_file).resolve()
    plan = json.loads(pfile.read_text(encoding="utf-8-sig"))
    settled = ao.settle_plan(plan, proj)
    results_dir = Path(a.results_dir).resolve() if a.results_dir else pfile.parent
    results_by_name: dict[str, dict] = {}
    for p in settled["packages"]:
        found = _locate_pkg_meta(results_dir, proj, p)
        if found:
            results_by_name[p["name"]] = found
    junctions = ao.audit_batch_junctions(settled["packages"], results_by_name, proj, plan=plan)
    if a.json:
        print(json.dumps(junctions, indent=2))
    else:
        print("=== 4x Junction, Keyhole Invariant & Cross-Package Conflict Inspection ===")
        print(f"missing_outputs         : {len(junctions['missing_outputs'])}")
        for m in junctions["missing_outputs"]:
            print(f"  ! {m}")
        print(f"invariant_violations    : {len(junctions['invariant_violations'])}")
        for v in junctions["invariant_violations"]:
            print(f"  X {v}")
        print(f"cross_package_conflicts : {len(junctions['cross_package_conflicts'])}")
        for c in junctions["cross_package_conflicts"]:
            print(f"  # {c}")
        print(f"truth_amendments        : {len(junctions['truth_amendments'])}")
        for am in junctions["truth_amendments"]:
            print(f"  @ {am.get('author')}: {am.get('key')} -> {am.get('proposed_value')} ({am.get('reason')})")
        print(f"challenged_seams        : {len(junctions['assumptions_challenged'])}")
        for c in junctions["assumptions_challenged"]:
            print(f"  ~ {c}")
        print(f"open_questions          : {len(junctions['open_questions'])}")
        for q in junctions["open_questions"]:
            print(f"  ? {q}")
        print(f"evidence_warnings       : {len(junctions['evidence_warnings'])}")
        for w in junctions["evidence_warnings"]:
            print(f"  * {w}")
        print("junction audit passed" if junctions["ok"] else "junction audit FAILED")
    return 0 if junctions["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Orchestration Anatomy Engine: Size Gate, Truth Interlock, Settle Wave DAG, Audit to Zero, Change-Ripple Amend & 4x Junction Inspection."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="Scaffold Shared Truth Contract, locked invariants, non-hollow briefs, and settled plan.json, then audit to zero")
    pi.add_argument("--goal", required=True, help="Primary system goal for the anatomy plan")
    pi.add_argument(
        "--pkg",
        action="append",
        required=True,
        help="Package spec: name[:brief_mode[:deps_csv[:may_write_csv[:skills_csv[:outputs_csv]]]]]",
    )
    pi.add_argument(
        "--invariant",
        action="append",
        default=[],
        help="Lock user prerequisite or threshold keyhole: KEY=VAL, KEY<=VAL, KEY>=VAL, must:PATTERN, or forbid:PATTERN (repeatable)",
    )
    pi.add_argument("--truth-contract", default=None, help="Relative path to shared truth contract markdown")
    pi.add_argument("--out", default=".orch/plan.json", help="Output plan.json path (default: .orch/plan.json)")
    pi.add_argument("--project-dir", default=".")
    pi.add_argument("--agent", default=None)
    pi.add_argument("--model", default=None)
    pi.add_argument("--allow-epic", action="store_true", help="Explicitly approve Epic scale (>8 packages)")
    pi.add_argument("--json", action="store_true")

    ps = sub.add_parser("settle", help="Solve topological waves and auto-wire truth_contract + upstream outputs -> downstream context_file")
    ps.add_argument("plan_file", help="Path to plan.json")
    ps.add_argument("--project-dir", default=".")
    ps.add_argument("--write", action="store_true", help="Write settled waves and context wiring back to plan_file")
    ps.add_argument("--json", action="store_true")

    pa = sub.add_parser("audit", help="Run zero-defect structural & keyhole interlock pre-flight audit on plan.json")
    pa.add_argument("plan_file", help="Path to plan.json")
    pa.add_argument("--project-dir", default=".")
    pa.add_argument("--json", action="store_true")

    pm = sub.add_parser("amend", help="Formally amend a locked prerequisite/threshold with evidence, broadcast notice to all packages, and flag stale packages")
    pm.add_argument("plan_file", help="Path to plan.json")
    pm.add_argument("--set", action="append", default=[], help="Amendment spec: KEY=NEW_VAL, KEY<=NEW_VAL, etc. (repeatable)")
    pm.add_argument("--reason", default="", help="Why the locked value must change")
    pm.add_argument("--evidence", default="", help="Verifiable proof (file:line or command -> output) justifying the change")
    pm.add_argument("--by", default="manager", help="Package or role proposing the amendment")
    pm.add_argument("--affect", action="append", default=[], help="Explicit comma-separated list of affected package names")
    pm.add_argument("--clear-stale", action="append", default=[], help="Comma-separated package names that have been re-synced and are no longer stale")
    pm.add_argument("--project-dir", default=".")
    pm.add_argument("--json", action="store_true")

    pj = sub.add_parser("inspect", help="Run 4x post-flight junction, invariant drift & cross-package silent conflict check")
    pj.add_argument("plan_file", help="Path to plan.json")
    pj.add_argument("--results-dir", default=None, help="Directory containing <pkg>/result.json (defaults to plan_file parent)")
    pj.add_argument("--project-dir", default=".")
    pj.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "settle":
        return cmd_settle(args)
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "amend":
        return cmd_amend(args)
    if args.cmd == "inspect":
        return cmd_inspect(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
