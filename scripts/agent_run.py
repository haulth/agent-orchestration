#!/usr/bin/env python3
"""One runner for Codex, Antigravity (agy) and Claude Code workers.

  agent_run.py run --agent codex|agy|claude --brief F [--name SLUG] [--out DIR]
                   [--model M] [--effort E] [--mode read|write] [--cd DIR]
                   [--may-write PATH ...] [--add-dir DIR] [--context-file PATH ...]
                   [--skill SKILL_NAME_OR_PATH ...] [--worktree] [--search] [--bare]
                   [--max-budget-usd USD] [--timeout S] [--schema PATH|none] [--resume ID]
                   [--task-type T] [--risk low|med|high] [--tier T] [--no-ledger]
  agent_run.py batch plan.json [--wip N] [--audit]
  agent_run.py verdict RUN_DIR accept|revise|escalate|rollback|takeover [--note "..."]
  agent_run.py stats [--project P] [--task-type T]

Every attempt writes <out>/attempt-<n>/{brief.md,result.json|txt,run.log,meta.json} and appends
one record to the shared ledger (~/.agent-orchestration/ledger.jsonl). Stdout is compact: one meta
line plus the truncated result. Exit: 0 ok, 1 failed, 2 usage/boundary error, 3 valid result but
files changed outside --may-write (never auto-reverted; the rollback rule in verification.md decides).

Enforced: project boundary, wall-clock timeout (whole process tree), result presence, schema,
evidence-citation audit (`evidence_warnings`), and write attribution via git.
"""
import argparse
import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ao_common as ao  # noqa: E402
from codex_run import (DEFAULT_SCHEMA, PRINT_LIMIT, classify, kill_tree,  # noqa: E402
                       next_attempt_dir, parse_log, validate)

VERDICTS = ["accept", "revise", "escalate", "rollback", "takeover"]
MAX_UNTRACKED_EXPAND = 2000  # guard against million-file dataset/checkpoint folders in ML repos
HASH_BYTES_LIMIT = 4 * 1024 * 1024  # stat signature for huge files (>4MB) to avoid I/O stalls


class Usage(Exception):
    pass


# ---------- project boundary ----------
def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True)


def resolve_project(cd):
    start = Path(cd or ".").resolve()
    r = git(start, "rev-parse", "--show-toplevel") if start.exists() else None
    root = Path(r.stdout.decode().strip()).resolve() if r is not None and r.returncode == 0 else start
    if ao.is_bad_root(root):
        raise Usage(f"refusing to work in {root}: it is $HOME or a drive root; pass --cd <project>")
    return root, (r is not None and r.returncode == 0)


def inside(child, root):
    try:
        Path(child).resolve().relative_to(root)
        return True
    except ValueError:
        return False


def ensure_excluded(root):
    r = git(root, "rev-parse", "--git-path", "info/exclude")
    if r.returncode:
        return
    p = (root / r.stdout.decode().strip()).resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        if ".orch/" not in text.split():
            p.write_text(text + ("" if text.endswith("\n") or not text else "\n") + ".orch/\n",
                         encoding="utf-8")
    except OSError:
        pass


# ---------- write attribution ----------
def _hash(p):
    try:
        st = p.stat()
        if p.is_dir():
            return f"dir:{st.st_mtime_ns}"
        if st.st_size > HASH_BYTES_LIMIT:
            return f"stat:{st.st_size}:{st.st_mtime_ns}"
        return hashlib.sha1(p.read_bytes()).hexdigest()
    except OSError:
        return "gone"


def snapshot(root):
    """Fast, bounded git working-tree snapshot. Uses -unormal first to avoid walking million-file
    untracked dataset/checkpoint folders; expands untracked directories only up to MAX_UNTRACKED_EXPAND."""
    r = git(root, "status", "--porcelain=v1", "-z", "-unormal")
    if r.returncode:
        return None
    parts = r.stdout.split(b"\0")
    files, i = {}, 0
    untracked_dirs = []
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, path = e[:2].decode(), e[3:].decode("utf-8", "replace")
        if xy[0] in "RC":
            i += 1  # skip the original path of a rename/copy
        if path.startswith(".orch/"):
            continue
        full = root / path
        if xy == "??" and path.endswith("/"):
            untracked_dirs.append((path, full))
        else:
            files[path] = _hash(full)

    budget = MAX_UNTRACKED_EXPAND
    for rel_dir, full_dir in untracked_dirs:
        if budget <= 0:
            files[rel_dir] = _hash(full_dir)
            continue
        sub_files = []
        overflow = False
        try:
            for dirpath, _, filenames in os.walk(full_dir):
                for fn in filenames:
                    sub_files.append(Path(dirpath) / fn)
                    if len(sub_files) > budget:
                        overflow = True
                        break
                if overflow:
                    break
        except OSError:
            overflow = True
        if overflow:
            files[rel_dir] = _hash(full_dir)
        else:
            budget -= len(sub_files)
            for sf in sub_files:
                rel = sf.relative_to(root).as_posix()
                files[rel] = _hash(sf)
    return files


def norm_scopes(scopes, root):
    out = []
    for s in scopes:
        t = s.replace("\\", "/")
        if os.path.isabs(s) and inside(s, root):
            t = Path(s).resolve().relative_to(root).as_posix() + ("/" if s.endswith(("/", "\\")) else "")
        out.append(t)
    return out


def in_scope(path, scopes):
    p = path.replace("\\", "/")
    for s in scopes:
        if s.endswith("/"):
            if p.startswith(s):
                return True
        elif any(c in s for c in "*?["):
            if fnmatch.fnmatch(p, s):
                return True
        elif p == s:
            return True
    return False


# ---------- output parsing ----------
def extract_json(text):
    """First JSON object in text (after stripping code fences); ignores trailing prose."""
    t = re.sub(r"```[a-zA-Z]*", "", text or "")
    dec, pos, tries = json.JSONDecoder(), 0, 0
    while tries < 50:
        i = t.find("{", pos)
        if i < 0:
            return None
        try:
            obj, _ = dec.raw_decode(t[i:])
            if isinstance(obj, dict) and "status" in obj:
                return obj
        except ValueError:
            pass
        pos, tries = i + 1, tries + 1
    return None


def classify2(timed_out, code, ok_status, result, errors, denied, err_text):
    """Failure class for agy/claude. `ok_status` is False when the tool itself reported failure."""
    if timed_out:
        return "timeout"
    if code == 0 and ok_status and result and not errors:
        return None
    low = err_text.lower()
    if not result and denied:
        return "permission"
    if re.search(r"\b(401|403|unauthorized|not logged in|invalid api key)\b", low):
        return "auth"
    if re.search(r"(model[^\n]*(not found|not supported|unsupported|does not exist)"
                 r"|unknown model|invalid config|failed to (load|parse) config)", low):
        return "model_or_config"
    if code != 0 or not ok_status:
        return "process_error"
    if not result:
        return "no_result"
    return "invalid_result"


# ---------- adapters ----------
class Job:
    """Everything an adapter needs, plus what it returns."""
    def __init__(self, a, project, attempt, brief_path, schema_path, use_schema):
        self.a, self.project, self.attempt = a, project, attempt
        self.brief_path, self.schema_path, self.use_schema = brief_path, schema_path, use_schema
        self.result_path = attempt / ("result.json" if use_schema else "result.txt")


def build_codex(j):
    a = j.a
    cmd = ao.resolve_exe("codex") + ["exec"]
    if a.resume:
        cmd += ["resume", a.resume]
    else:
        cmd += ["-s", "workspace-write" if a.mode == "write" else "read-only", "-C", str(j.project)]
        if getattr(a, "worktree", False):
            cmd += ["--worktree"]
        if getattr(a, "search", False):
            cmd += ["--search"]
        for d in a.add_dir:
            cmd += ["--add-dir", d]
    cmd += ["--skip-git-repo-check", "-o", str(j.result_path)]
    if a.model:
        cmd += ["-m", a.model]
    if a.effort:
        cmd += ["-c", f'model_reasoning_effort="{a.effort}"']
    if j.use_schema:
        cmd += ["--output-schema", j.schema_path]
    cmd.append("-")
    return cmd, j.brief_path.read_bytes()


def parse_codex(j, out, err, code, timed_out):
    log = out + err
    tokens, sid = parse_log(log)
    result = j.result_path.read_text(encoding="utf-8") if j.result_path.exists() else ""
    errors, ev_warn = [], []
    if j.use_schema and result:
        try:
            obj = json.loads(result)
            errors = validate(obj, json.loads(Path(j.schema_path).read_text("utf-8")))
            ev_warn = ao.check_evidence_citations(obj)
        except ValueError as e:
            errors = [f"invalid JSON: {e}"]
    return {"result": result, "errors": errors, "evidence_warnings": ev_warn, "tokens": tokens,
            "sid": sid, "failure": classify(code, timed_out, result, errors, log), "denied": 0}


def build_agy(j):
    a = j.a
    prompt = (f"Read the work order at {j.brief_path.resolve()} and follow it. "
              "Return only the result envelope JSON.")
    mins = max(1, math.ceil(a.timeout / 60))
    cmd = ao.resolve_exe("agy") + ["-p", prompt, "--output-format", "json", "--print-timeout", f"{mins}m",
                                   "--mode", "accept-edits" if a.mode == "write" else "plan",
                                   "--add-dir", str(j.attempt.resolve())]
    for d in a.add_dir:
        cmd += ["--add-dir", d]
    if j.use_schema:
        cmd += ["--json-schema", j.schema_path]
    if a.model:
        cmd += ["--model", a.model]
    if a.effort:
        cmd += ["--effort", a.effort]
    if a.resume:
        cmd += ["--conversation", a.resume]
    return cmd, None


def _decode_stdout(out):
    """Whole-stdout JSON, tolerating log noise around it."""
    wrapper_keys = {"status", "response", "result", "conversation_id", "session_id"}
    try:
        obj = json.loads(out)
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass
    first, i = {}, out.find("{")
    while i >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(out[i:])
            if isinstance(obj, dict):
                if wrapper_keys & set(obj):
                    return obj
                first = first or obj
        except ValueError:
            pass
        i = out.find("{", i + 1)
    return first


AGY_EXTRA_KEYS = ("toolAction", "toolSummary")


def _finish_text(j, response, structured=None):
    """Turn the model's final output into (result_text, errors, evidence_warnings)."""
    if not j.use_schema:
        return (response or "").strip(), [], []
    obj = structured if isinstance(structured, dict) else extract_json(response)
    if obj is None:
        return "", [], []
    obj = {k: v for k, v in obj.items() if k not in AGY_EXTRA_KEYS}
    schema = json.loads(Path(j.schema_path).read_text("utf-8"))
    return json.dumps(obj, indent=2, ensure_ascii=False), validate(obj, schema), ao.check_evidence_citations(obj)


def parse_agy(j, out, err, code, timed_out):
    data = _decode_stdout(out)
    response = data.get("response") or ""
    denied = len(re.findall(r"auto-denied", err, re.I))
    result, errors, ev_warn = _finish_text(j, response, data.get("structured_output"))
    ok_status = data.get("status") == "SUCCESS"
    if result:
        j.result_path.write_text(result, encoding="utf-8")
    return {"result": result, "errors": errors, "evidence_warnings": ev_warn,
            "tokens": (data.get("usage") or {}).get("total_tokens"),
            "sid": data.get("conversation_id"), "denied": denied,
            "failure": classify2(timed_out, code, ok_status, result, errors, denied, err)}


def build_claude(j):
    a = j.a
    cmd = ao.resolve_exe("claude") + ["-p", "--output-format", "json",
                                      "--permission-mode", "acceptEdits" if a.mode == "write" else "plan"]
    if a.model:
        cmd += ["--model", a.model]
    if a.effort:
        cmd += ["--effort", a.effort]
    if a.resume:
        cmd += ["--resume", a.resume]
    if getattr(a, "worktree", False):
        cmd += ["--worktree"]
    if getattr(a, "bare", False):
        cmd += ["--bare"]
    if getattr(a, "max_budget_usd", None) is not None:
        cmd += ["--max-budget-usd", str(a.max_budget_usd)]
    for d in a.add_dir:
        cmd += ["--add-dir", d]
    if a.allow_tool:
        cmd += ["--allowedTools", *a.allow_tool]
    brief = j.brief_path.read_text(encoding="utf-8")
    if j.use_schema:
        brief += ("\n\n## Final message format\nReply with ONE JSON object and nothing else: required keys "
                  "status (done|partial|blocked|stopped), summary (with [E1]/file:line citations), "
                  "deliverables[], evidence[] (verifiable file:line or command output), risks[], "
                  "next_action; optional keys confidence (low|med|high), assumptions_challenged[] "
                  "(must cite proof), open_questions[], handoff_notes.\n")
    return cmd, brief.encode("utf-8")


def parse_claude(j, out, err, code, timed_out):
    data = _decode_stdout(out)
    response = data.get("result") or ""
    result, errors, ev_warn = _finish_text(j, response, data.get("structured_output"))
    u = data.get("usage") or {}
    tokens = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) + \
        (u.get("cache_creation_input_tokens") or 0) if u else None
    if result:
        j.result_path.write_text(result, encoding="utf-8")
    ok_status = bool(data) and not data.get("is_error")
    err_text = err + ("\n" + response if data.get("is_error") else "")
    return {"result": result, "errors": errors, "evidence_warnings": ev_warn, "tokens": tokens,
            "sid": data.get("session_id"), "denied": 0, "cost": data.get("total_cost_usd"),
            "failure": classify2(timed_out, code, ok_status, result, errors, 0, err_text)}


ADAPTERS = {"codex": (build_codex, parse_codex), "agy": (build_agy, parse_agy),
            "claude": (build_claude, parse_claude)}


# ---------- core ----------
def _inject_context_and_skills(brief_bytes, context_files, skills, project):
    """Append Shared Blackboard files (--context-file) and Specialized Skills (--skill) to the brief copy."""
    lines = []
    if skills:
        lines.append("\n\n## Attached Specialized Skills (Shared directly from Parent Agent — read SKILL.md directly, DO NOT re-install)")
        for sinfo in skills:
            if isinstance(sinfo, dict):
                lines.append(f"- **{sinfo['name']}** (`{sinfo.get('scope', 'parent')}`): Read `{sinfo['path']}` (skill folder `{sinfo['dir']}` is already mounted & readable)")
            else:
                lines.append(f"- `{sinfo}`")
    if context_files:
        lines.append("\n\n## Shared Blackboard / Upstream Artifacts (read directly as needed)")
        for cf in context_files:
            p = Path(cf)
            if not p.is_absolute():
                p = (project / p).resolve()
            else:
                p = p.resolve()
            lines.append(f"- `{p}`")
    if not lines:
        return brief_bytes
    lines.append("")
    return brief_bytes + ("\n".join(lines)).encode("utf-8")


def run_one(a):
    """Run one work order; return (meta, result_text, log_path). Raises Usage on caller errors."""
    for attr, default in (("name", None), ("context_file", []), ("skill", []), ("worktree", False),
                          ("search", False), ("bare", False), ("max_budget_usd", None)):
        if not hasattr(a, attr):
            setattr(a, attr, default)
    resolved_skills = []
    skill_dirs = set()
    for s in (a.skill or []):
        sinfo = ao.resolve_skill_info(s, project_dir=a.cd)
        if not sinfo:
            raise Usage(f"specialized skill '{s}' not found on parent agent or sandbox; run 'route.py --list-skills' "
                        f"or search trusted ephemeral sandbox skills via 'skill_sandbox.py search {s}' (ask user before installing)")
        resolved_skills.append(sinfo)
        skill_dir = sinfo["dir"]
        skill_dirs.add(skill_dir)
        if skill_dir not in a.add_dir:
            a.add_dir.append(skill_dir)
    if a.resume:
        man = ao.load_session(a.agent, a.resume)
        changed_req = (a.add_dir or (a.mode and man and a.mode != man["mode"]) or (a.mode == "write" and not man)
                       or (a.cd and man and Path(a.cd).resolve() != Path(man["project"]).resolve())
                       or (a.may_write and man and sorted(norm_scopes(a.may_write, Path(man["project"])))
                           != sorted(man["may_write"])) or ((a.cd or a.may_write) and not man))
        if changed_req:
            raise Usage("a resumed session keeps its original mode, cwd, dirs and write scope; "
                        "start a fresh run to change them")
        if man:
            a.mode, a.may_write, a.cd = man["mode"], man["may_write"], man["project"]
        elif not a.allow_unknown_resume:
            raise Usage(f"no manifest for session {a.resume} (not started by agent_run.py, or its state "
                        "folder was cleared); start a fresh run, or pass --allow-unknown-resume to treat "
                        "it as read-only for attribution")
    project, is_git = resolve_project(a.cd)
    if a.agent not in ADAPTERS:
        raise Usage(f"unknown agent {a.agent}")
    if not ao.resolve_exe(a.agent):
        raise Usage(f"{a.agent} CLI not found (PATH, or AO_{a.agent.upper()} override)")
    a.mode = a.mode or "read"
    a.may_write = norm_scopes(a.may_write, project)
    if a.mode == "write" and not a.may_write:
        raise Usage("write mode needs --may-write <path|dir/|glob> so changes can be attributed")
    if a.mode == "write" and not is_git and not a.allow_unchecked_write:
        raise Usage("write mode in a non-git directory cannot be attributed or checked; use a git repo, "
                    "or pass --allow-unchecked-write to accept an unchecked scope")
    if not a.allow_outside:
        for d in a.add_dir:
            if str(Path(d).resolve()) in skill_dirs:
                continue
            if not inside(d, project):
                raise Usage(f"--add-dir {d} is outside the project {project}; needs --allow-outside "
                            "and the user's approval")
    models = ao.load_models()
    caps_p = ao.ao_home() / "capabilities.json"
    try:
        caps = json.loads(caps_p.read_text(encoding="utf-8")) if caps_p.exists() else {}
    except (OSError, ValueError):
        caps = {}
    raw_task = a.task_type
    canon_task = ao.canonical_task(raw_task, models) if raw_task else None
    run_label = a.name or raw_task or "task"

    tcfg = (ao.dynamic_tier_config(models, caps, a.agent, a.tier) if a.tier else None) or {}
    a.model = a.model or tcfg.get("model")
    a.effort = a.effort or tcfg.get("effort")
    inferred_tier = a.tier or ao.infer_tier(a.agent, a.model, models)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", run_label).strip("-") or "task"
    out = Path(a.out) if a.out else project / ".orch" / "runs" / f"{safe_label}-{stamp}"
    if is_git:
        ensure_excluded(project)
    attempt = next_attempt_dir(out)
    brief_path = attempt / "brief.md"
    brief_bytes = _inject_context_and_skills(Path(a.brief).read_bytes(), a.context_file, resolved_skills, project)
    brief_path.write_bytes(brief_bytes)

    use_schema = str(a.schema).lower() != "none"
    schema_path = str(Path(a.schema).resolve()) if use_schema else None
    j = Job(a, project, attempt, brief_path, schema_path, use_schema)
    cmd, stdin = ADAPTERS[a.agent][0](j)

    before = snapshot(project) if is_git else None
    env = dict(os.environ, AO_DEPTH=str(int(os.environ.get("AO_DEPTH", "0") or 0) + 1))
    popen_kw = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    start, timed_out = time.time(), False
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(project),
                            env=env, **popen_kw)
    try:
        out_b, err_b = proc.communicate(stdin, timeout=a.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
        try:
            out_b, err_b = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            out_b, err_b = b"", b"[runner: process tree did not release its pipes after kill]"
    code = -1 if timed_out else proc.returncode
    o, e = (out_b or b"").decode("utf-8", "replace"), (err_b or b"").decode("utf-8", "replace")
    duration = round(time.time() - start, 1)
    (attempt / "run.log").write_text(o + "\n--- stderr ---\n" + e, encoding="utf-8")

    p = ADAPTERS[a.agent][1](j, o, e, code, timed_out)

    changed, violations, git_note = [], [], "checked"
    after = snapshot(project) if (is_git and before is not None) else None
    if is_git and before is not None and after is not None:
        own = a.may_write if a.mode == "write" else []
        peer_own = getattr(a, "_peer_write_scopes", None) or []
        raw_changed = sorted(f for f in set(before) | set(after)
                             if before.get(f) != after.get(f) and not f.startswith(".orch/"))
        # In parallel batch execution, ignore files legitimately owned by another parallel writer's disjoint scope
        changed = [f for f in raw_changed if in_scope(f, own) or not in_scope(f, peer_own)]
        violations = [f for f in changed if not in_scope(f, own)]
    elif is_git:
        git_note = "unverified: git status failed before or after the run (scope unchecked)"
    else:
        git_note = "skipped: not a git repository (scope unchecked)"

    meta = {
        "ok": p["failure"] is None, "failure": p["failure"], "schema_errors": p["errors"][:10],
        "evidence_warnings": p.get("evidence_warnings") or [],
        "exit_code": code, "timed_out": timed_out, "duration_s": duration,
        "tokens_used": p["tokens"], "tokens_note": "cumulative for the session" if a.resume and a.agent == "codex" else "this run",
        "session_id": p["sid"] or a.resume, "resumed": bool(a.resume),
        "agent": a.agent, "mode": a.mode, "model": a.model or "cli default",
        "effort": a.effort or "cli default", "cwd": str(project), "run_dir": str(attempt),
        "changed": changed, "violations": violations, "scope_ok": (not violations) if git_note == "checked" else None,
        "auto_denied_count": p["denied"],
        "task_type": canon_task, "raw_task_type": raw_task, "name": a.name or raw_task,
        "risk": a.risk, "tier": inferred_tier, "project": str(project),
        "git": git_note,
    }
    if p.get("cost") is not None:
        meta["cost_usd"] = p["cost"]
    saved = ao.save_session(a.agent, meta["session_id"], {"mode": a.mode, "may_write": a.may_write,
                                                          "project": str(project)})
    logged = True
    if not a.no_ledger:
        logged = ao.ledger_append({"type": "run", **{k: meta[k] for k in (
            "agent", "model", "effort", "tier", "task_type", "risk", "project", "run_dir", "ok",
            "failure", "tokens_used", "duration_s", "auto_denied_count")}, "violations": len(violations)})
    if not (saved and logged):
        meta["state_warning"] = ("could not write session manifest/ledger under "
                                 f"{ao.ao_home()} (read-only sandbox?); set AO_HOME to a writable folder "
                                 "if resume or the ledger matter for this run")
    (attempt / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta, p["result"], (attempt / "run.log")


def guard_depth(allow_spawn):
    if int(os.environ.get("AO_DEPTH", "0") or 0) >= 1 and not allow_spawn:
        raise Usage("AO_DEPTH>=1: this process is itself a worker; workers do not spawn workers "
                    "unless the brief allows it (--allow-spawn)")


def cmd_run(a):
    guard_depth(a.allow_spawn)
    meta, result, log = run_one(a)
    print(json.dumps(meta, separators=(",", ":")))
    print("--- result ---")
    print(result[:PRINT_LIMIT] + ("\n[truncated, see result file]" if len(result) > PRINT_LIMIT else ""))
    if meta["violations"]:
        print(f"WARNING: changed outside --may-write: {meta['violations']}")
    if meta.get("evidence_warnings"):
        print(f"EVIDENCE WARNING: {meta['evidence_warnings']}")
    if meta["auto_denied_count"]:
        print(f"WARNING: {meta['auto_denied_count']} tool call(s) were auto-denied; the result may be "
              "incomplete (check the brief's file list and permissions)")
    if meta["failure"]:
        print("--- log tail ---")
        print(log.read_text(encoding="utf-8")[-1500:])
        return 1
    return 3 if meta["violations"] else 0


def cmd_batch(a):
    guard_depth(a.allow_spawn)
    plan_path = Path(a.plan).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    proj_dir = Path(a.project_dir).resolve() if getattr(a, "project_dir", None) else (
        plan_path.parent.parent if plan_path.parent.name == ".orch" else Path.cwd().resolve()
    )
    audit_res = ao.audit_plan(plan, project_dir=proj_dir)
    if getattr(a, "audit", False):
        print(ao.format_anatomy_report(audit_res))
        return 0 if audit_res["ok"] else 1
    if not audit_res["ok"]:
        print(ao.format_anatomy_report(audit_res), file=sys.stderr)
        raise Usage(f"batch plan failed pre-flight anatomy audit ({audit_res['failure_count']} problem(s)); fix the plan or run with --audit to inspect")

    settled = audit_res["settled"]
    hw = settled["hardware"]
    wip = min(a.wip, hw["recommended_wip"]) if a.wip else settled["wip"]
    print(f"[anatomy] {audit_res['package_count']} packages across {audit_res['wave_count']} wave(s) | size={audit_res['size_tier']} | audit passed")
    print(f"[hardware] {hw['summary']} -> active parallel wip={wip}")

    base = dict(agent=None, brief=None, name=None, out=None, model=None, effort=None, mode=None, cd=None,
                may_write=[], add_dir=[], context_file=[], skill=[], worktree=False, search=False, bare=False,
                max_budget_usd=None, timeout=900, schema=str(DEFAULT_SCHEMA), resume=None,
                task_type=None, risk=None, tier=None, no_ledger=False, allow_outside=False,
                allow_spawn=False, allow_tool=[], allow_unknown_resume=False, allow_unchecked_write=False)

    meta_by_name = {}
    worst = 0
    for w_idx, w_pkgs in enumerate(settled["waves"]):
        specs = []
        for i, p in enumerate(w_pkgs):
            d = {**base, **{k: v for k, v in p.items() if k in base}}
            d["cd"] = d.get("cd") or str(proj_dir)
            d["_name"] = p["name"]
            d["_depends_on"] = list(p.get("depends_on") or [])
            # Auto-wire upstream completed result.json & deliverables into downstream context_file mounts
            cfiles = list(d.get("context_file") or [])
            for dep_name in d["_depends_on"]:
                dep_m = meta_by_name.get(dep_name)
                if dep_m and dep_m.get("run_dir"):
                    res_json = Path(dep_m["run_dir"]) / "result.json"
                    if res_json.exists() and str(res_json) not in cfiles:
                        cfiles.append(str(res_json))
            d["context_file"] = cfiles
            specs.append(d)

        writers = [s for s in specs if s["mode"] == "write" and not s.get("worktree")]
        for s in specs:
            s["_peer_write_scopes"] = [p for w in writers if w["_name"] != s["_name"] for p in (w.get("may_write") or [])]

        def go(s):
            failed_deps = [dep for dep in s["_depends_on"] if not (meta_by_name.get(dep) or {}).get("ok")]
            if failed_deps:
                return s["_name"], None, f"SKIPPED (upstream dependency failed: {', '.join(failed_deps)})"
            ns = argparse.Namespace(**{k: v for k, v in s.items() if not k.startswith("_") or k == "_peer_write_scopes"})
            try:
                meta, _, _ = run_one(ns)
                return s["_name"], meta, None
            except Usage as e:
                return s["_name"], None, str(e)

        if len(settled["waves"]) > 1:
            print(f"--- wave {w_idx} ({len(specs)} parallel package(s)) ---")
        with ThreadPoolExecutor(max_workers=wip) as ex:
            done = dict(zip([s["_name"] for s in specs], ex.map(go, specs)))
        for s in specs:
            name, m, err = done[s["_name"]]
            if err:
                print(f"{name}: ERROR {err}")
                worst = max(worst, 2 if "SKIPPED" not in err else 1)
                continue
            meta_by_name[name] = m
            status = "ok" if m["ok"] else f"FAIL:{m['failure']}"
            viol = f" VIOLATIONS={m['violations']}" if m["violations"] else ""
            viol += f" auto_denied={m['auto_denied_count']}" if m["auto_denied_count"] else ""
            print(f"{name}: {m['agent']} {status} tokens={m['tokens_used']} {m['duration_s']}s "
                  f"changed={len(m['changed'])}{viol} {m['run_dir']}")
            worst = max(worst, 1 if not m["ok"] else (3 if m["violations"] else 0))

    junc = ao.audit_batch_junctions(settled["packages"], meta_by_name, project_dir=proj_dir)
    print(f"[junctions 4x] missing_outputs={len(junc['missing_outputs'])} "
          f"assumptions_challenged={len(junc['assumptions_challenged'])} "
          f"open_questions={len(junc['open_questions'])} "
          f"evidence_warnings={len(junc['evidence_warnings'])}")
    for item in junc["missing_outputs"]:
        print(f"  MISSING OUTPUT: {item}")
        worst = max(worst, 1)
    for item in junc["assumptions_challenged"]:
        print(f"  PREMISE CHALLENGED: {item}")
    for item in junc["open_questions"][:5]:
        print(f"  OPEN QUESTION AT SEAM: {item}")
    return worst


def find_meta(target):
    p = Path(target)
    if (p / "meta.json").exists():
        return p / "meta.json"
    attempts = sorted(p.glob("attempt-*"), key=lambda x: int(x.name.split("-")[1]))
    for d in reversed(attempts):
        if (d / "meta.json").exists():
            return d / "meta.json"
    return None


def cmd_verdict(a):
    models = ao.load_models()
    rec = {"type": "verdict", "verdict": a.verdict, "note": a.note}
    if a.target == "-":
        if not (a.agent and a.task_type and a.tier):
            raise Usage("target '-' needs --agent --task-type --tier")
        rec.update(agent=a.agent, task_type=ao.canonical_task(a.task_type, models),
                   tier=a.tier, project=a.project or "")
    else:
        mp = find_meta(a.target)
        if not mp:
            raise Usage(f"no meta.json under {a.target}")
        m = json.loads(mp.read_text(encoding="utf-8"))
        canon_t = ao.canonical_task(m.get("task_type"), models)
        inf_tier = m.get("tier") or ao.infer_tier(m.get("agent"), m.get("model"), models)
        rec.update(agent=m.get("agent"), model=m.get("model"), tier=inf_tier,
                   task_type=canon_t, project=m.get("project"), run_dir=m["run_dir"])
    ao.ledger_append(rec)
    print(f"recorded: {a.verdict} for {rec.get('agent')}/{rec.get('task_type')}/{rec.get('tier')}")
    return 0


def cmd_stats(a):
    models = ao.load_models()
    recs = ao.ledger_read()
    target_t = ao.canonical_task(a.task_type, models) if a.task_type else None
    keys = set()
    for r in recs:
        if r.get("type") != "verdict":
            continue
        rt = ao.canonical_task(r.get("task_type"), models)
        rtier = r.get("tier") or ao.infer_tier(r.get("agent"), r.get("model"), models)
        if target_t and rt != target_t:
            continue
        if a.project and a.project not in (r.get("project") or ""):
            continue
        keys.add((rt, r.get("agent"), rtier))
    keys = sorted(keys, key=str)
    if not keys:
        print("no verdicts recorded yet")
        return 0
    print("task_type | agent | tier | verdicts | accepted | streak | avg_tokens")
    for t, ag, tier in keys:
        s = ao.verdict_stats(recs, t, ag, tier, a.project)
        toks = [r["tokens_used"] for r in recs if r.get("type") == "run"
                and ao.canonical_task(r.get("task_type"), models) == t
                and r.get("agent") == ag
                and (r.get("tier") or ao.infer_tier(r.get("agent"), r.get("model"), models)) == tier
                and r.get("tokens_used")]
        avg = round(sum(toks) / len(toks)) if toks else "-"
        print(f"{t} | {ag} | {tier} | {s['n']} | {s['accepts']} | {s['streak']} | {avg}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--agent", required=True, choices=list(ADAPTERS))
    r.add_argument("--brief", required=True)
    r.add_argument("--name", help="human-friendly slug for the run directory (keeps --task-type canonical)")
    r.add_argument("--out")
    r.add_argument("--model")
    r.add_argument("--effort")
    r.add_argument("--mode", choices=["read", "write"])
    r.add_argument("--cd")
    r.add_argument("--may-write", action="append", default=[], nargs="+")
    r.add_argument("--add-dir", action="append", default=[])
    r.add_argument("--context-file", action="append", default=[],
                   help="shared blackboard / upstream artifact paths appended to the brief for direct reading")
    r.add_argument("--skill", action="append", default=[],
                   help="installed specialized skill name or SKILL.md path to attach to the worker's brief")
    r.add_argument("--worktree", action="store_true",
                   help="run in an isolated git worktree (supported by codex and claude)")
    r.add_argument("--search", action="store_true",
                   help="enable live web search (codex --search)")
    r.add_argument("--bare", action="store_true",
                   help="minimal cold-start mode skipping hooks/LSP/auto-discovery (claude --bare)")
    r.add_argument("--max-budget-usd", type=float,
                   help="hard USD cap for API spend on headless runs (claude --max-budget-usd)")
    r.add_argument("--allow-outside", action="store_true", help="only with the user's approval")
    r.add_argument("--allow-spawn", action="store_true", help="the brief lets this worker spawn workers")
    r.add_argument("--allow-tool", action="append", default=[], help="claude --allowedTools entry")
    r.add_argument("--timeout", type=int, default=900)
    r.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    r.add_argument("--resume")
    r.add_argument("--allow-unknown-resume", action="store_true")
    r.add_argument("--allow-unchecked-write", action="store_true",
                   help="write mode outside git: scope cannot be verified")
    r.add_argument("--task-type")
    r.add_argument("--risk", choices=["low", "med", "high"])
    r.add_argument("--tier")
    r.add_argument("--no-ledger", action="store_true")
    b = sub.add_parser("batch")
    b.add_argument("plan")
    b.add_argument("--wip", type=int)
    b.add_argument("--project-dir", default=None, help="project root directory for resolving relative paths in plan.json")
    b.add_argument("--audit", action="store_true", help="prove the batch plan (0 collisions, 0 cycles, 0 dangling mounts, 0 hollow briefs) and exit")
    b.add_argument("--allow-spawn", action="store_true")
    v = sub.add_parser("verdict")
    v.add_argument("target", help="run dir, or '-' with --agent/--task-type/--tier")
    v.add_argument("verdict", choices=VERDICTS)
    v.add_argument("--note", default="")
    v.add_argument("--agent")
    v.add_argument("--task-type")
    v.add_argument("--tier")
    v.add_argument("--project")
    s = sub.add_parser("stats")
    s.add_argument("--project")
    s.add_argument("--task-type")
    a = p.parse_args()
    if a.cmd == "run":
        a.may_write = [x for grp in a.may_write for x in grp]
    try:
        sys.exit({"run": cmd_run, "batch": cmd_batch, "verdict": cmd_verdict, "stats": cmd_stats}[a.cmd](a))
    except Usage as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
