#!/usr/bin/env node
/**
 * bin/cli.mjs — Zero-dependency NPX installer, doctor & CLI runner for `agent-orchestration`.
 *
 * Supports:
 *   npx github:haulth/agent-orchestration [install] [--dry-run] [--no-backup] [--home <dir>]
 *   npx github:haulth/agent-orchestration doctor
 *   npx github:haulth/agent-orchestration uninstall
 *   npx github:haulth/agent-orchestration <route|anatomy|run|batch|verdict|stats|sandbox|discover> [args...]
 */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const ROOT_DIR = path.resolve(path.dirname(__filename), "..");

const COPY_ITEMS = [
  "SKILL.md",
  "CATALOG.md",
  "README.md",
  "LICENSE",
  "package.json",
  "bin",
  "install",
  "assets",
  "references",
  "scripts",
];

function defaultTargets(homeDir) {
  return [
    path.join(homeDir, ".claude", "skills", "agent-orchestration"),
    path.join(homeDir, ".agents", "skills", "agent-orchestration"),
    path.join(homeDir, ".codex", "skills", "agent-orchestration"),
    path.join(homeDir, ".gemini", "config", "skills", "agent-orchestration"),
  ];
}

function findPython() {
  const candidates =
    process.platform === "win32"
      ? [
          ["python", ["-c", "import sys; assert sys.version_info >= (3, 8)"]],
          ["py", ["-3", "-c", "import sys; assert sys.version_info >= (3, 8)"]],
          ["python3", ["-c", "import sys; assert sys.version_info >= (3, 8)"]],
        ]
      : [
          ["python3", ["-c", "import sys; assert sys.version_info >= (3, 8)"]],
          ["python", ["-c", "import sys; assert sys.version_info >= (3, 8)"]],
        ];

  for (const [cmd, testArgs] of candidates) {
    const res = spawnSync(cmd, testArgs, { stdio: "ignore", windowsHide: true });
    if (res.status === 0) {
      const prefixArgs = cmd === "py" ? ["-3"] : [];
      const verRes = spawnSync(cmd, [...prefixArgs, "--version"], {
        encoding: "utf-8",
        windowsHide: true,
      });
      const ver = ((verRes.stdout || "") + (verRes.stderr || "")).trim();
      return { cmd, prefixArgs, version: ver };
    }
  }
  return null;
}

function copyTreeClean(srcDir, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  for (const item of COPY_ITEMS) {
    const s = path.join(srcDir, item);
    const d = path.join(destDir, item);
    if (!fs.existsSync(s)) continue;
    fs.cpSync(s, d, {
      recursive: true,
      force: true,
      filter: (srcPath) => {
        const base = path.basename(srcPath);
        if (base === "__pycache__" || base === ".orch" || base === ".sandbox-skills") {
          return false;
        }
        if (base.endsWith(".pyc")) return false;
        return true;
      },
    });
  }
}

function stamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function cmdInstall(args) {
  let homeDir = os.homedir();
  let dryRun = false;
  let noBackup = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--dry-run") dryRun = true;
    else if (args[i] === "--no-backup") noBackup = true;
    else if (args[i] === "--home" && args[i + 1]) {
      homeDir = path.resolve(args[++i]);
    }
  }

  const py = findPython();
  if (!py) {
    console.error("[agent-orchestration] ERROR: Python >= 3.8 is required on PATH.");
    process.exit(1);
  }

  const targets = defaultTargets(homeDir);
  const backupRoot = path.join(homeDir, ".agent-orchestration-backups");
  const stateDir = process.env.AO_HOME || path.join(homeDir, ".agent-orchestration");
  const ts = stamp();

  for (const t of targets) {
    if (fs.existsSync(t) && !noBackup) {
      const relSlug = path
        .relative(homeDir, t)
        .replace(/[^A-Za-z0-9]+/g, "_")
        .replace(/^_|_$/g, "");
      const bdest = path.join(backupRoot, `${relSlug}-${ts}`);
      console.log(`backup  ${t} -> ${bdest}`);
      if (!dryRun) {
        fs.mkdirSync(backupRoot, { recursive: true });
        fs.cpSync(t, bdest, { recursive: true, force: true });
      }
    }
    console.log(`install ${t}`);
    if (!dryRun) {
      fs.rmSync(t, { recursive: true, force: true });
      copyTreeClean(ROOT_DIR, t);
    }
  }

  console.log(`state   ${stateDir}`);
  if (!dryRun) {
    fs.mkdirSync(stateDir, { recursive: true });
    const discoverScript = path.join(targets[1], "scripts", "discover.py");
    if (fs.existsSync(discoverScript)) {
      spawnSync(py.cmd, [...py.prefixArgs, discoverScript, "--quick"], {
        stdio: "ignore",
        windowsHide: true,
      });
    }
  }
  console.log("Done. Restart Claude Code, Codex CLI, and Antigravity (agy) to reload the skill.");
}

function cmdUninstall(args) {
  let homeDir = os.homedir();
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--home" && args[i + 1]) {
      homeDir = path.resolve(args[++i]);
    }
  }
  for (const t of defaultTargets(homeDir)) {
    if (fs.existsSync(t)) {
      fs.rmSync(t, { recursive: true, force: true });
      console.log(`removed ${t}`);
    }
  }
}

function cmdDoctor() {
  console.log("=== agent-orchestration Doctor ===");
  console.log(`Node.js : ${process.version} (${process.platform}/${process.arch})`);
  const py = findPython();
  console.log(`Python  : ${py ? `${py.version} (${py.cmd})` : "NOT FOUND"}`);

  const homeDir = os.homedir();
  console.log("\nSkill Install Targets:");
  for (const t of defaultTargets(homeDir)) {
    const ok = fs.existsSync(path.join(t, "SKILL.md"));
    console.log(`  [${ok ? "OK" : "--"}] ${t}`);
  }

  if (py) {
    console.log("\nLive Models & Hardware Probe:");
    const routeScript = path.join(ROOT_DIR, "scripts", "route.py");
    spawnSync(py.cmd, [...py.prefixArgs, routeScript, "--list-models"], {
      stdio: "inherit",
      windowsHide: true,
    });
  }
}

function forwardPython(scriptName, prefixScriptArgs, passArgs) {
  const py = findPython();
  if (!py) {
    console.error("[agent-orchestration] ERROR: Python >= 3.8 is required.");
    process.exit(1);
  }
  const scriptPath = path.join(ROOT_DIR, "scripts", scriptName);
  const res = spawnSync(py.cmd, [...py.prefixArgs, scriptPath, ...prefixScriptArgs, ...passArgs], {
    stdio: "inherit",
    windowsHide: true,
  });
  process.exit(res.status ?? 1);
}

function printHelp() {
  console.log(`agent-orchestration — Multi-Agent Orchestration Skill & CLI Engine

Usage:
  npx github:haulth/agent-orchestration [install] [--dry-run] [--no-backup] [--home <dir>]
  npx github:haulth/agent-orchestration doctor
  npx github:haulth/agent-orchestration uninstall
  npx github:haulth/agent-orchestration route [args...]
  npx github:haulth/agent-orchestration anatomy <init|settle|audit|amend|inspect> [args...]
  npx github:haulth/agent-orchestration <run|batch|verdict|stats> [args...]
  npx github:haulth/agent-orchestration sandbox <check|search|install|list|remove|purge> [args...]
  npx github:haulth/agent-orchestration discover [--quick]

Also compatible with Agent Skills CLI:
  npx skills add haulth/agent-orchestration`);
}

const argv = process.argv.slice(2);
const sub = argv[0] || "install";
const rest = argv.slice(1);

if (sub === "-h" || sub === "--help" || sub === "help") {
  printHelp();
} else if (sub === "install" || sub.startsWith("--")) {
  cmdInstall(sub === "install" ? rest : argv);
} else if (sub === "uninstall") {
  cmdUninstall(rest);
} else if (sub === "doctor") {
  cmdDoctor();
} else if (sub === "route") {
  forwardPython("route.py", [], rest);
} else if (sub === "anatomy") {
  forwardPython("anatomy.py", [], rest);
} else if (sub === "sandbox") {
  forwardPython("skill_sandbox.py", [], rest);
} else if (sub === "discover") {
  forwardPython("discover.py", [], rest);
} else if (["run", "batch", "verdict", "stats"].includes(sub)) {
  forwardPython("agent_run.py", [sub], rest);
} else {
  printHelp();
  process.exit(1);
}
