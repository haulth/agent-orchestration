#!/usr/bin/env python3
"""Run one Codex CLI work order with a hard timeout, schema check and a compact run record.

Usage:
  python codex_run.py --brief brief.md --out runs/task-1 [--model M] [--effort low]
                      [--sandbox read-only] [--cd DIR] [--add-dir DIR]
                      [--timeout 900] [--schema PATH|none] [--resume SESSION_ID]

Each call writes a fresh attempt directory: <out>/attempt-<n>/ with
  result.json|result.txt  final message
  run.log                 full Codex output (keep it out of the manager's context)
  meta.json               exit code, failure class, duration, tokens, session id, settings
Prints only meta.json plus the (truncated) final message. Exit code 0 only for a valid result.

Enforced here: wall-clock timeout (whole process tree), result presence, schema validity.
Advisory only (enforced by the brief, not by this script): tool-call and token budgets.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_SCHEMA = Path(__file__).resolve().parent.parent / "assets" / "result.schema.json"
PRINT_LIMIT = 4000
TYPES = {"string": str, "array": list, "object": dict, "boolean": bool,
         "integer": int, "number": (int, float)}


def validate(value, schema, path="$"):
    """Minimal JSON-schema check: type, enum, required, properties, additionalProperties, items."""
    errors = []
    t = schema.get("type")
    if t and (not isinstance(value, TYPES[t])
              or (t in ("integer", "number") and isinstance(value, bool))):
        return [f"{path}: expected {t}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing '{key}'")
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: unexpected '{k}'" for k in value if k not in props]
        for k, sub in props.items():
            if k in value:
                errors += validate(value[k], sub, f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += validate(item, schema["items"], f"{path}[{i}]")
    return errors


def kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def parse_log(text):
    tokens = sid = None
    m = re.search(r"tokens used\s*[\r\n]+\s*([\d,]+)", text)
    if m:
        tokens = int(m.group(1).replace(",", ""))
    m = re.search(r"session id:\s*([0-9a-fA-F-]{8,})", text)
    if m:
        sid = m.group(1)
    return tokens, sid


def classify(code, timed_out, result, errors, log):
    if timed_out:
        return "timeout"
    if code != 0:
        # classify only from error records, never from the model's own transcript text
        err = "\n".join(l for l in log.splitlines()
                        if re.match(r"\s*(error|fatal)\b", l, re.I)).lower()
        if re.search(r"\b(401|403|unauthorized|invalid api key|not logged in)\b", err):
            return "auth"
        if re.search(r"(permission denied|access is denied|operation not permitted)", err):
            return "permission"
        if re.search(r"(model[^\n]*(not found|not supported|unsupported|does not exist)"
                     r"|unknown model|invalid config|failed to (load|parse) config)", err):
            return "model_or_config"
        return "process_error"
    if not result:
        return "no_result"
    if errors:
        return "invalid_result"
    return None


def next_attempt_dir(out):
    out.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        d = out / f"attempt-{n}"
        try:
            d.mkdir()  # atomic: concurrent callers never share a directory
            return d
        except FileExistsError:
            n += 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brief", required=True, help="work order file, sent via stdin")
    p.add_argument("--out", required=True, help="run directory; each call adds attempt-<n>/")
    p.add_argument("--model")
    p.add_argument("--effort", help="model_reasoning_effort, e.g. low|medium|high|xhigh")
    p.add_argument("--sandbox", choices=["read-only", "workspace-write", "danger-full-access"])
    p.add_argument("--cd")
    p.add_argument("--add-dir", action="append", default=[],
                   help="extra WRITABLE directory (only meaningful with workspace-write)")
    p.add_argument("--timeout", type=int, default=900, help="seconds, whole process tree")
    p.add_argument("--schema", default=str(DEFAULT_SCHEMA),
                   help="JSON schema for the final message; 'none' disables")
    p.add_argument("--resume", help="session id to continue instead of starting fresh")
    a = p.parse_args()

    if a.resume and (a.sandbox or a.cd or a.add_dir):
        sys.exit("error: --resume inherits the original session's sandbox, cwd and dirs; "
                 "start a fresh run to change scope or permissions")
    if a.sandbox == "danger-full-access":
        print("warning: danger-full-access requires explicit user approval", file=sys.stderr)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ao_common as ao
    codex = ao.resolve_exe("codex") or shutil.which("codex")
    if not codex:
        sys.exit("codex CLI not found on PATH")

    run_dir = next_attempt_dir(Path(a.out))
    use_schema = a.schema.lower() != "none"
    schema = json.loads(Path(a.schema).read_text(encoding="utf-8")) if use_schema else None
    result_path = run_dir / ("result.json" if use_schema else "result.txt")

    cmd = [codex, "exec"]
    if a.resume:
        cmd += ["resume", a.resume]
    else:
        cmd += ["-s", a.sandbox or "read-only", "-C", a.cd or "."]
        for d in a.add_dir:
            cmd += ["--add-dir", d]
    cmd += ["--skip-git-repo-check", "-o", str(result_path)]
    if a.model:
        cmd += ["-m", a.model]
    if a.effort:
        cmd += ["-c", f'model_reasoning_effort="{a.effort}"']
    if use_schema:
        cmd += ["--output-schema", a.schema]
    cmd.append("-")

    brief = Path(a.brief).read_text(encoding="utf-8")
    popen_kw = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    start = time.time()
    timed_out = False
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **popen_kw)
    try:
        out_b, err_b = proc.communicate(brief.encode("utf-8"), timeout=a.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
        try:
            out_b, err_b = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            out_b, err_b = b"", b"[runner: process tree did not release its pipes after kill]"
    code = proc.returncode if not timed_out else -1
    log = (out_b or b"").decode("utf-8", "replace") + (err_b or b"").decode("utf-8", "replace")
    duration = round(time.time() - start, 1)
    (run_dir / "run.log").write_text(log, encoding="utf-8")

    tokens, sid = parse_log(log)
    result = result_path.read_text(encoding="utf-8") if result_path.exists() else ""
    errors = []
    if use_schema and result:
        try:
            errors = validate(json.loads(result), schema)
        except ValueError as e:
            errors = [f"invalid JSON: {e}"]
    failure = classify(code, timed_out, result, errors, log)

    meta = {
        "ok": failure is None,
        "failure": failure,
        "schema_errors": errors[:10],
        "exit_code": code,
        "timed_out": timed_out,
        "duration_s": duration,
        "tokens_used": tokens,
        "tokens_note": "cumulative for the session" if a.resume else "this run",
        "session_id": sid or a.resume,
        "resumed": bool(a.resume),
        "model": a.model or "config default",
        "effort": a.effort or "config default",
        "sandbox": "inherited" if a.resume else (a.sandbox or "read-only"),
        "cwd": "inherited" if a.resume else str(Path(a.cd or ".").resolve()),
        "run_dir": str(run_dir),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(json.dumps(meta, indent=2))
    print("--- result ---")
    print(result[:PRINT_LIMIT] + ("\n[truncated, see result file]" if len(result) > PRINT_LIMIT else ""))
    if failure:
        print("--- log tail ---")
        print(log[-1500:])
        sys.exit(1)


if __name__ == "__main__":
    main()
