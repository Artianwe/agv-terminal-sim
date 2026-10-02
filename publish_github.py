"""Publish this project to GitHub (open this file in VS Code and press Run).

Before running: create an EMPTY repository named `agv-terminal-sim` on github.com (no README,
no licence, no .gitignore). The first push may open a "Sign in to GitHub" window from Git
Credential Manager - approve it in your browser.

Steps: git init -> commit everything not excluded by .gitignore -> push to origin/main -> tag v1.0.0.
A log is written to .publish_log.txt (not committed).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_URL = "https://github.com/Artianwe/agv-terminal-sim.git"
LOG = ROOT / ".publish_log.txt"
MESSAGE = """Project A v1.0.0: risk-aware AGV dispatching at an automated container terminal

SimPy model of quay cranes, AGVs and stacking cranes; five dispatching policies incl. the new
risk-aware two-way auction; fleet sizing, sensitivity, ablation and tuning experiments; 23 tests;
report (report/report.pdf).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Y529FUyHzEECWsKkJEb5iB"""


UPDATE_MESSAGE = """Update Project A files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Y529FUyHzEECWsKkJEb5iB"""


def log(msg: str) -> None:
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    log("$ git " + " ".join(args))
    p = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    if p.stdout.strip():
        log(p.stdout.rstrip())
    if p.stderr.strip():
        log(p.stderr.rstrip())
    if check and p.returncode != 0:
        log(f"STOPPED: git {' '.join(args)} failed (exit {p.returncode}).")
        sys.exit(p.returncode)
    return p


def main() -> None:
    LOG.write_text("", encoding="utf-8")
    first = not (ROOT / ".git").exists()
    if first:
        git("init", "-b", "main")
    # never publish this log (older versions of .gitignore did not list it)
    git("rm", "--cached", "--quiet", "--ignore-unmatch", LOG.name)
    git("add", "-A")
    git("status", "--short")
    if git("diff", "--cached", "--quiet", check=False).returncode != 0:
        has_commits = git("rev-parse", "--verify", "HEAD", check=False).returncode == 0
        git("commit", "-m", UPDATE_MESSAGE if has_commits else MESSAGE)
    else:
        log("Nothing new to commit.")
    if git("remote", "get-url", "origin", check=False).returncode != 0:
        git("remote", "add", "origin", REPO_URL)
    git("push", "-u", "origin", "main")
    if git("tag", "--list", "v1.0.0").stdout.strip() == "":
        git("tag", "-a", "v1.0.0", "-m", "Project A complete")
    git("push", "origin", "v1.0.0")
    log(f"\nPUBLISHED: {REPO_URL.removesuffix('.git')}")


if __name__ == "__main__":
    main()
