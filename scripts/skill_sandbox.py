#!/usr/bin/env python3
"""Ephemeral Skill Sandbox & Parent-to-Child Skill Sharing Manager for agent-orchestration.

Core Rules:
1. Parent-to-Child Path Sharing First (NO redundant installs):
   If the parent agent already has a readable skill on the machine (~/.agents/skills, ~/.claude/skills,
   ~/.codex/skills, ~/.gemini/config/skills, plugins, builtin), NEVER install it again. Pass '--skill <name>'
   in agent_run.py (or share its SKILL.md path + '--add-dir <dir>') so child agents read it directly.
2. Ephemeral Skill Memory (~/.agent-orchestration/sandbox-skills/):
   When a task needs a specialized skill not present on the machine, install it ONLY into agent-orchestration's
   isolated sandbox memory (never polluting ~/.claude, ~/.agents, or ~/.gemini). Delete anytime via 'remove' or 'purge'.
3. High-Trust / High-Reputation Only + Mandatory User Approval:
   Only accepts official vendor registries or high-reputation GitHub repositories (verified orgs or >= min_stars),
   runs a static security scan before admission, and REQUIRES explicit user approval (--approved-by-user).

Usage:
  skill_sandbox.py check <keyword> [--json]
  skill_sandbox.py search <query> [--min-stars 50] [--json]
  skill_sandbox.py install <owner/repo> [--subpath skills/foo] [--name slug] [--min-stars 50] [--ttl-hours 168] [--approved-by-user]
  skill_sandbox.py list [--json]
  skill_sandbox.py remove <name>
  skill_sandbox.py purge [--expired]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ao_common as ao  # noqa: E402

TRUSTED_REGISTRIES = [
    {"repo": "anthropics/skills", "tier": "official_vendor", "org": "Anthropic", "branch": "main",
     "desc": "Official Anthropic Claude Code & Agent Skills repository"},
    {"repo": "openai/skills", "tier": "official_vendor", "org": "OpenAI", "branch": "main",
     "desc": "Official OpenAI Codex CLI Skills catalog"},
    {"repo": "vercel-labs/agent-skills", "tier": "verified_org", "org": "Vercel Labs", "branch": "main",
     "desc": "Verified Vercel Labs Agent Skills collection"},
    {"repo": "huggingface/skills", "tier": "verified_org", "org": "HuggingFace", "branch": "main",
     "desc": "Verified HuggingFace AI/ML & Hub Agent Skills"},
    {"repo": "obra/superpowers", "tier": "verified_org", "org": "Superpowers", "branch": "main",
     "desc": "High-reputation software engineering & TDD agent skills"},
]

TRUSTED_ORGS = {
    "anthropics": "official_vendor",
    "openai": "official_vendor",
    "google": "official_vendor",
    "google-deepmind": "official_vendor",
    "google-gemini": "official_vendor",
    "microsoft": "official_vendor",
    "vercel": "verified_org",
    "vercel-labs": "verified_org",
    "huggingface": "verified_org",
    "modelcontextprotocol": "verified_org",
    "obra": "verified_org",
    "cloudflare": "verified_org",
    "supabase": "verified_org",
    "stripe": "verified_org",
    "playwright": "verified_org",
    "remotion-dev": "verified_org",
}

DANGEROUS_PATTERNS = [
    ("remote_pipe_exec", re.compile(r"\b(curl|wget|Invoke-WebRequest|iwr)\b[^\n|]*\|\s*(sh|bash|zsh|pwsh|powershell|iex|Invoke-Expression)\b", re.I)),
    ("encoded_exec", re.compile(r"\b(base64\s+-d|FromBase64String)\b[^\n]*(\|\s*(sh|bash|iex)|eval\s*\()", re.I)),
    ("credential_exfil", re.compile(r"(\.ssh/id_rsa|\.aws/credentials|AZURE_CLIENT_SECRET|OPENAI_API_KEY)[^\n]*(curl|wget|requests\.post|urllib\.request)", re.I)),
    ("destructive_root", re.compile(r"\brm\s+-[rf]{1,2}\s+(/|\$HOME|~|C:\\)\b", re.I)),
    ("prompt_injection", re.compile(r"(ignore\s+all\s+previous\s+instructions|disregard\s+system\s+prompt|bypass\s+user\s+approval)", re.I)),
]


def _manifest_path():
    return ao.sandbox_skills_dir() / "manifest.json"


def load_manifest():
    p = _manifest_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"skills": {}}
    except (OSError, ValueError):
        return {"skills": {}}


def save_manifest(data):
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _gh_get(url, timeout=8):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "agent-orchestration-skill-sandbox"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _normalize_repo(repo_or_url):
    s = repo_or_url.strip().rstrip("/")
    s = re.sub(r"^https?://github\.com/", "", s, flags=re.I)
    s = re.sub(r"\.git$", "", s)
    parts = [p for p in s.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return s


def verify_repo_reputation(repo_slug, min_stars=50):
    """Verify repository reputation via GitHub API and return metadata + trust assessment."""
    slug = _normalize_repo(repo_slug)
    if "/" not in slug:
        return {"trusted": False, "reason": f"invalid repository format '{repo_slug}'; expected 'owner/repo'"}
    owner = slug.split("/")[0].lower()
    known_reg = next((r for r in TRUSTED_REGISTRIES if r["repo"].lower() == slug.lower()), None)
    try:
        info = _gh_get(f"https://api.github.com/repos/{slug}")
    except Exception as e:
        if known_reg:
            return {
                "trusted": True,
                "repo": slug,
                "owner": owner,
                "stars": None,
                "trust_tier": known_reg["tier"],
                "description": known_reg["desc"],
                "default_branch": known_reg["branch"],
                "html_url": f"https://github.com/{slug}",
                "reason": f"verified built-in registry ({known_reg['org']}); live GitHub metadata unreachable ({e})",
            }
        return {"trusted": False, "repo": slug, "reason": f"could not verify repository on GitHub: {e}"}

    if info.get("archived") or info.get("disabled"):
        return {"trusted": False, "repo": slug, "reason": "repository is archived or disabled"}
    stars = int(info.get("stargazers_count") or 0)
    org_tier = TRUSTED_ORGS.get(owner) or (known_reg["tier"] if known_reg else None)
    if org_tier:
        tier = org_tier
        trusted = True
        reason = f"verified {tier} ('{owner}', {stars} stars)"
    elif stars >= min_stars:
        tier = "high_reputation_community"
        trusted = True
        reason = f"passes community reputation gate ({stars} stars >= {min_stars} min_stars)"
    else:
        tier = "untrusted_low_reputation"
        trusted = False
        reason = (f"rejected: '{slug}' has only {stars} stars (minimum required: {min_stars}) "
                  f"and owner '{owner}' is not in verified organizations")
    return {
        "trusted": trusted,
        "repo": slug,
        "owner": owner,
        "stars": stars,
        "trust_tier": tier,
        "description": info.get("description") or (known_reg["desc"] if known_reg else ""),
        "default_branch": info.get("default_branch") or "main",
        "license": (info.get("license") or {}).get("spdx_id"),
        "html_url": info.get("html_url") or f"https://github.com/{slug}",
        "reason": reason,
    }


def audit_skill_directory(skill_dir):
    """Static security & safety audit of a candidate skill folder before admitting to sandbox."""
    root = Path(skill_dir)
    smd = root / "SKILL.md"
    if not smd.exists():
        return {"ok": False, "scanned_files": 0, "findings": ["missing SKILL.md in target skill directory"]}
    findings = []
    scanned = 0
    for p in root.rglob("*"):
        if not p.is_file() or ".git" in p.parts:
            continue
        if p.suffix.lower() not in (".md", ".py", ".sh", ".ps1", ".js", ".ts", ".json", ".yaml", ".yml", ".toml"):
            continue
        scanned += 1
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")[:200000]
        except OSError:
            continue
        rel = p.relative_to(root).as_posix()
        for label, rx in DANGEROUS_PATTERNS:
            m = rx.search(txt)
            if m:
                snippet = m.group(0).strip().replace("\n", " ")[:90]
                findings.append(f"{rel}: [{label}] '{snippet}'")
    return {"ok": len(findings) == 0, "scanned_files": scanned, "findings": findings}


def search_trusted_remote_skills(query, min_stars=50, limit=8):
    """Search curated official skill registries first, then high-reputation GitHub repositories."""
    q_terms = [t.lower() for t in re.split(r"[\s,_-]+", query.strip()) if len(t) >= 2]
    results = []
    seen = set()

    # 1. Search inside official/verified multi-skill registries via GitHub git tree API
    for reg in TRUSTED_REGISTRIES:
        try:
            tree_url = f"https://api.github.com/repos/{reg['repo']}/git/trees/{reg['branch']}?recursive=1"
            data = _gh_get(tree_url, timeout=6)
            for item in data.get("tree") or []:
                path = item.get("path") or ""
                if not path.endswith("/SKILL.md") and path != "SKILL.md":
                    continue
                subpath = path[:-9].strip("/")
                skill_slug = subpath.split("/")[-1] if subpath else reg["repo"].split("/")[-1]
                hay = f"{skill_slug} {subpath} {reg['repo']}".lower()
                score = sum((3 if t in skill_slug.lower() else 1) for t in q_terms if t in hay)
                if score > 0:
                    key = (reg["repo"], subpath)
                    if key not in seen:
                        seen.add(key)
                        results.append({
                            "name": skill_slug,
                            "repo": reg["repo"],
                            "subpath": subpath,
                            "trust_tier": reg["tier"],
                            "stars": "official",
                            "description": f"From {reg['org']} ({reg['repo']}/{subpath})",
                            "url": f"https://github.com/{reg['repo']}/tree/{reg['branch']}/{subpath}",
                            "install_preview_cmd": (f"python {Path(__file__).resolve()} install {reg['repo']} "
                                                    f"--subpath {subpath} --name {skill_slug} --approved-by-user"),
                            "_score": score + 5,
                        })
        except Exception:
            continue

    # 2. Search high-reputation GitHub repositories matching query + agent skill
    try:
        q_enc = urllib.parse.quote(f"{query} (\"SKILL.md\" OR \"agent skill\" OR \"claude skill\" OR \"codex skill\") stars:>={min_stars}")
        gh_url = f"https://api.github.com/search/repositories?q={q_enc}&sort=stars&order=desc&per_page=8"
        sdata = _gh_get(gh_url, timeout=6)
        for item in sdata.get("items") or []:
            if item.get("archived") or item.get("disabled"):
                continue
            slug = item.get("full_name") or ""
            owner = (item.get("owner") or {}).get("login", "").lower()
            stars = int(item.get("stargazers_count") or 0)
            if stars < min_stars and owner not in TRUSTED_ORGS:
                continue
            key = (slug, "")
            if key in seen:
                continue
            seen.add(key)
            tier = TRUSTED_ORGS.get(owner, "high_reputation_community")
            sname = item.get("name", slug.split("/")[-1]).lower()
            results.append({
                "name": sname,
                "repo": slug,
                "subpath": "",
                "trust_tier": tier,
                "stars": stars,
                "description": (item.get("description") or "")[:140],
                "url": item.get("html_url") or f"https://github.com/{slug}",
                "install_preview_cmd": f"python {Path(__file__).resolve()} install {slug} --name {sname} --approved-by-user",
                "_score": 3 if tier != "high_reputation_community" else 1,
            })
    except Exception:
        pass

    results.sort(key=lambda x: (-x.get("_score", 0), str(x.get("name", ""))))
    out = []
    for r in results[:limit]:
        r = dict(r)
        r.pop("_score", None)
        out.append(r)
    return out


def cmd_check_or_search(query, min_stars=50, as_json=False, check_only=False):
    local_matches = ao.match_installed_skills([query] + query.split(), limit=8)
    parent_matches = [m for m in local_matches if m.get("scope") != "ephemeral_sandbox"]
    sandbox_matches = [m for m in local_matches if m.get("scope") == "ephemeral_sandbox"]

    if check_only and local_matches:
        payload = {
            "status": "available_locally",
            "action": "SHARE_PARENT_SKILL_PATH_DO_NOT_INSTALL",
            "message": ("Parent agent already has matching skill(s) on this machine. "
                        "Pass '--skill <name>' in agent_run.py (or share the SKILL.md path + '--add-dir <dir>') "
                        "so child agents read it directly without installing anything."),
            "local_skills": local_matches,
        }
        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("[OK - LOCAL SKILL FOUND] Do NOT install anything. Share path directly from parent to child:")
            for s in local_matches:
                print(f"  - {s['name']} [{s['scope']}] -> {s['path']}  (dir: {s['dir']})")
                print(f"    Use: agent_run.py run ... --skill {s['name']}")
        return 0

    remote = search_trusted_remote_skills(query, min_stars=min_stars)
    payload = {
        "status": "local_found" if local_matches else ("remote_candidates_found" if remote else "none_found"),
        "rule": ("If any local_skills match the task, share their path directly via --skill (DO NOT install). "
                 "If none match, ASK THE USER for approval before running 'skill_sandbox.py install ... --approved-by-user'."),
        "sandbox_dir": str(ao.sandbox_skills_dir()),
        "parent_skills": parent_matches,
        "sandbox_skills": sandbox_matches,
        "trusted_remote_candidates": remote,
    }
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if parent_matches or sandbox_matches:
        print("## 1. Local Skills Already Readable by Parent Agent (Share path via --skill; DO NOT re-install)")
        for s in parent_matches + sandbox_matches:
            print(f"  - {s['name']:34s} [{s['scope']}] -> {s['path']}")
        print()
    print(f"## 2. Trusted Remote Candidates (Min Stars: {min_stars} | Sandbox: {ao.sandbox_skills_dir()})")
    if not remote:
        print("  (No high-reputation remote candidates matched query)")
    for c in remote:
        sub = f" (subpath: {c['subpath']})" if c.get("subpath") else ""
        print(f"  - {c['name']:28s} | repo: {c['repo']}{sub} | tier: {c['trust_tier']} | stars: {c['stars']}")
        print(f"    desc: {c['description']}")
        print(f"    ASK USER FIRST, then run: {c['install_preview_cmd']}")
    return 0


def _stage_skill_from_github(repo_slug, branch, subpath, staging_root):
    """Clone only the needed skill files into staging_root using shallow sparse git checkout."""
    clone_dir = staging_root / "repo"
    url = f"https://github.com/{repo_slug}.git"
    if subpath:
        r1 = subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                             "--branch", branch, url, str(clone_dir)], capture_output=True, text=True, timeout=45)
        if r1.returncode != 0:
            raise RuntimeError(f"git clone failed: {r1.stderr.strip()}")
        r2 = subprocess.run(["git", "-C", str(clone_dir), "sparse-checkout", "set", subpath],
                            capture_output=True, text=True, timeout=30)
        if r2.returncode != 0:
            raise RuntimeError(f"git sparse-checkout failed: {r2.stderr.strip()}")
        target = clone_dir / subpath
    else:
        r1 = subprocess.run(["git", "clone", "--depth", "1", "--branch", branch, url, str(clone_dir)],
                            capture_output=True, text=True, timeout=45)
        if r1.returncode != 0:
            raise RuntimeError(f"git clone failed: {r1.stderr.strip()}")
        target = clone_dir

    r_sha = subprocess.run(["git", "-C", str(clone_dir), "rev-parse", "HEAD"], capture_output=True, text=True)
    commit_sha = r_sha.stdout.strip() if r_sha.returncode == 0 else "unknown"
    if not target.exists():
        raise RuntimeError(f"subpath '{subpath}' not found inside {repo_slug}")
    if not (target / "SKILL.md").exists():
        sub_smds = list(target.glob("*/SKILL.md"))
        if len(sub_smds) == 1:
            target = sub_smds[0].parent
        else:
            raise RuntimeError(f"no SKILL.md found at '{subpath or '/'}' in {repo_slug}")
    return target, commit_sha


def cmd_install(a):
    repo_slug = _normalize_repo(a.repo)
    inferred_name = (a.name or (a.subpath.strip("/").split("/")[-1] if a.subpath else repo_slug.split("/")[-1])).lower()
    inferred_name = re.sub(r"[^a-z0-9_-]+", "-", inferred_name).strip("-")

    # Gate 1: Check if parent agent already has this skill locally (no redundant installation)
    existing = ao.resolve_skill_info(inferred_name)
    if existing and existing["scope"] != "ephemeral_sandbox" and not a.force_sandbox:
        msg = {
            "status": "blocked_already_available_on_parent",
            "skill": existing["name"],
            "path": existing["path"],
            "dir": existing["dir"],
            "scope": existing["scope"],
            "message": (f"Parent agent already has '{existing['name']}' at {existing['path']}. "
                        f"Do NOT install a duplicate—pass '--skill {existing['name']}' so child agents read it directly."),
        }
        print(json.dumps(msg, indent=2) if a.json else msg["message"])
        return 0

    # Gate 2: Reputation & Trust Verification
    rep = verify_repo_reputation(repo_slug, min_stars=a.min_stars)
    if not rep.get("trusted"):
        err = {"status": "rejected_untrusted", "repo": repo_slug, "reason": rep.get("reason")}
        print(json.dumps(err, indent=2) if a.json else f"REJECTED (Trust Gate): {rep.get('reason')}", file=sys.stderr)
        return 3

    # Gate 3: Mandatory Human-in-the-Loop Approval (--approved-by-user)
    target_dir = ao.sandbox_skills_dir() / inferred_name
    if not a.approved_by_user:
        proposal = {
            "status": "approval_required",
            "action": "ASK_USER_BEFORE_INSTALL",
            "skill_name": inferred_name,
            "repo": repo_slug,
            "subpath": a.subpath or "",
            "trust_tier": rep["trust_tier"],
            "stars": rep["stars"],
            "license": rep.get("license"),
            "description": rep["description"],
            "sandbox_destination": str(target_dir),
            "system_impact": "None (isolated inside ~/.agent-orchestration/sandbox-skills; removable via 'skill_sandbox.py remove/purge')",
            "approve_command": (f"python {Path(__file__).resolve()} install {repo_slug}"
                                + (f" --subpath {a.subpath}" if a.subpath else "")
                                + f" --name {inferred_name} --approved-by-user"),
        }
        if a.json:
            print(json.dumps(proposal, indent=2, ensure_ascii=False))
        else:
            print("APPROVAL REQUIRED: Ask the user for permission before installing into the Ephemeral Skill Sandbox:")
            print(f"  - Skill Name:   {inferred_name}")
            print(f"  - Source Repo:  {repo_slug}" + (f" (subpath: {a.subpath})" if a.subpath else ""))
            print(f"  - Reputation:   {rep['trust_tier']} ({rep['stars']} stars, license: {rep.get('license') or 'unspecified'})")
            print(f"  - Sandbox Path: {target_dir} (ephemeral; does NOT touch system/global agent skills)")
            print(f"  - After user approves, run: {proposal['approve_command']}")
        return 4

    # Gate 4: Ephemeral Staging + Static Security Audit
    branch = a.branch or rep.get("default_branch") or "main"
    tmp_base = Path(tempfile.mkdtemp(prefix="ao-skill-stage-"))
    try:
        staged_skill_dir, commit_sha = _stage_skill_from_github(repo_slug, branch, a.subpath or "", tmp_base)
        audit = audit_skill_directory(staged_skill_dir)
        if not audit["ok"]:
            err = {
                "status": "rejected_security_audit",
                "repo": repo_slug,
                "subpath": a.subpath or "",
                "findings": audit["findings"],
            }
            print(json.dumps(err, indent=2) if a.json else f"SECURITY AUDIT FAILED: {audit['findings']}", file=sys.stderr)
            return 5

        # Gate 5: Admit into Ephemeral Sandbox Memory (~/.agent-orchestration/sandbox-skills/<name>)
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged_skill_dir, target_dir, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    except Exception as e:
        shutil.rmtree(tmp_base, ignore_errors=True)
        print(f"error staging skill from {repo_slug}: {e}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(tmp_base, ignore_errors=True)

    now_ts = int(time.time())
    exp_ts = now_ts + int(a.ttl_hours * 3600) if a.ttl_hours else None
    man = load_manifest()
    entry = {
        "name": inferred_name,
        "path": str((target_dir / "SKILL.md").resolve()),
        "dir": str(target_dir.resolve()),
        "repo": repo_slug,
        "subpath": a.subpath or "",
        "commit_sha": commit_sha,
        "trust_tier": rep["trust_tier"],
        "stars": rep["stars"],
        "installed_at": ao.now(),
        "installed_epoch": now_ts,
        "expires_epoch": exp_ts,
        "ttl_hours": a.ttl_hours,
        "security_audit": audit,
        "approved_by_user": True,
    }
    man.setdefault("skills", {})[inferred_name] = entry
    save_manifest(man)
    if a.json:
        print(json.dumps({"status": "installed_in_sandbox", **entry}, indent=2, ensure_ascii=False))
    else:
        print(f"INSTALLED IN EPHEMERAL SANDBOX: {inferred_name} -> {entry['path']}")
        print(f"  source: {repo_slug}@{commit_sha[:8]} ({rep['trust_tier']}, {rep['stars']} stars)")
        print(f"  security audit: clean ({audit['scanned_files']} files scanned)")
        print(f"  use with child agents: agent_run.py run ... --skill {inferred_name}")
        print(f"  cleanup anytime:       skill_sandbox.py remove {inferred_name}  (or 'skill_sandbox.py purge')")
    return 0


def cmd_list(as_json=False):
    sdir = ao.sandbox_skills_dir()
    man = load_manifest()
    entries = []
    now_ts = int(time.time())
    for smd in sorted(sdir.glob("*/SKILL.md")):
        name = smd.parent.name
        meta = (man.get("skills") or {}).get(name) or {}
        exp = meta.get("expires_epoch")
        entries.append({
            "name": name,
            "path": str(smd.resolve()),
            "dir": str(smd.parent.resolve()),
            "repo": meta.get("repo", "local/manual"),
            "trust_tier": meta.get("trust_tier", "unknown"),
            "stars": meta.get("stars"),
            "installed_at": meta.get("installed_at"),
            "expired": bool(exp and now_ts > exp),
        })
    if as_json:
        print(json.dumps({"sandbox_dir": str(sdir), "count": len(entries), "skills": entries}, indent=2))
        return 0
    print(f"## Ephemeral Skill Sandbox ({sdir}) — {len(entries)} skill(s) installed")
    for e in entries:
        exp_tag = " [EXPIRED]" if e["expired"] else ""
        print(f"  - {e['name']:30s} -> {e['path']}  (from {e['repo']}, tier={e['trust_tier']}, stars={e['stars']}){exp_tag}")
    return 0


def cmd_remove(name):
    sdir = ao.sandbox_skills_dir()
    target = sdir / name
    if not target.exists():
        print(f"sandbox skill '{name}' not found under {sdir}", file=sys.stderr)
        return 1
    shutil.rmtree(target, ignore_errors=True)
    man = load_manifest()
    if name in (man.get("skills") or {}):
        del man["skills"][name]
        save_manifest(man)
    print(f"removed ephemeral sandbox skill: {name} ({target})")
    return 0


def cmd_purge(expired_only=False):
    sdir = ao.sandbox_skills_dir()
    man = load_manifest()
    now_ts = int(time.time())
    removed = []
    for sub in list(sdir.iterdir()):
        if not sub.is_dir():
            continue
        meta = (man.get("skills") or {}).get(sub.name) or {}
        exp = meta.get("expires_epoch")
        if expired_only and not (exp and now_ts > exp):
            continue
        shutil.rmtree(sub, ignore_errors=True)
        removed.append(sub.name)
        if sub.name in (man.get("skills") or {}):
            del man["skills"][sub.name]
    save_manifest(man)
    print(f"purged {len(removed)} sandbox skill(s) from {sdir}: {', '.join(removed) or 'none'}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    ck = sub.add_parser("check", help="check if parent agent already has a matching skill locally; if not, suggest trusted sandbox candidates")
    ck.add_argument("query")
    ck.add_argument("--min-stars", type=int, default=50)
    ck.add_argument("--json", action="store_true")

    sr = sub.add_parser("search", help="search local parent skills first, then trusted official registries & high-reputation GitHub repos")
    sr.add_argument("query")
    sr.add_argument("--min-stars", type=int, default=50)
    sr.add_argument("--json", action="store_true")

    ins = sub.add_parser("install", help="stage, security-audit, and install a high-trust skill into ~/.agent-orchestration/sandbox-skills (requires --approved-by-user)")
    ins.add_argument("repo", help="GitHub 'owner/repo' or URL")
    ins.add_argument("--subpath", default="", help="subdirectory inside the repo containing SKILL.md (e.g. skills/pdf)")
    ins.add_argument("--name", help="slug name inside sandbox-skills")
    ins.add_argument("--branch", help="git branch (defaults to repo default_branch)")
    ins.add_argument("--min-stars", type=int, default=50, help="minimum GitHub stars required for non-official orgs (default: 50)")
    ins.add_argument("--ttl-hours", type=float, default=168.0, help="ephemeral time-to-live in hours before marked expired (default: 168h / 7d)")
    ins.add_argument("--approved-by-user", action="store_true", help="REQUIRED gate confirming the user explicitly approved installing this skill")
    ins.add_argument("--force-sandbox", action="store_true", help="install into sandbox even if parent agent already has a similarly named skill")
    ins.add_argument("--json", action="store_true")

    ls = sub.add_parser("list", help="list skills currently in the ephemeral sandbox")
    ls.add_argument("--json", action="store_true")

    rm = sub.add_parser("remove", help="delete one ephemeral skill from the sandbox")
    rm.add_argument("name")

    pg = sub.add_parser("purge", help="delete all (or only --expired) ephemeral skills from the sandbox")
    pg.add_argument("--expired", action="store_true", help="only remove sandbox skills past their TTL")

    a = p.parse_args()
    if a.cmd == "check":
        sys.exit(cmd_check_or_search(a.query, min_stars=a.min_stars, as_json=a.json, check_only=True))
    if a.cmd == "search":
        sys.exit(cmd_check_or_search(a.query, min_stars=a.min_stars, as_json=a.json, check_only=False))
    if a.cmd == "install":
        sys.exit(cmd_install(a))
    if a.cmd == "list":
        sys.exit(cmd_list(as_json=a.json))
    if a.cmd == "remove":
        sys.exit(cmd_remove(a.name))
    if a.cmd == "purge":
        sys.exit(cmd_purge(expired_only=a.expired))


if __name__ == "__main__":
    main()
