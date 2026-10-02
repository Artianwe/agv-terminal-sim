"""One-click runner for VS Code (open this file and press the Run button, top right).

What it does, in order:
  1. creates a virtual environment in .venv (first time only) and installs requirements.txt
  2. runs the verification tests
  3. runs every experiment (python run.py all --step 2) and rebuilds the report tables
     - files from an earlier run are first moved to results/_previous_runs/<time>/
  4. checks which publishing tools exist (git, GitHub CLI)
Everything printed is also saved to results/laptop_run_log.txt.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "results" / "laptop_run_log.txt"
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def log(msg: str = "") -> None:
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def run(cmd, check: bool = True) -> int:
    log("\n$ " + " ".join(str(c) for c in cmd))
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.Popen([str(c) for c in cmd], cwd=ROOT, stdout=subprocess.PIPE, env=env,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        log(line.rstrip())
    proc.wait()
    log(f"[exit code {proc.returncode}]")
    if check and proc.returncode != 0:
        log("STOPPED: the step above failed.")
        sys.exit(proc.returncode)
    return proc.returncode


def main() -> None:
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    t0 = time.time()
    log(f"Run started {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Machine: {platform.platform()} | CPUs: {os.cpu_count()} | Python: {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 10):
        log("Python 3.10 or newer is needed.")
        sys.exit(1)

    log("\n== 1. Environment ==")
    if not VENV_PY.exists():
        log("Creating .venv ...")
        venv.create(ROOT / ".venv", with_pip=True)
    run([VENV_PY, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", "requirements.txt"])
    run([VENV_PY, "-c", "import simpy, numpy, scipy, pandas, matplotlib; "
         "print('simpy', simpy.__version__, '| numpy', numpy.__version__, '| scipy', scipy.__version__, "
         "'| pandas', pandas.__version__, '| matplotlib', matplotlib.__version__)"])

    log("\n== 2. Verification tests ==")
    run([VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"])

    log("\n== 3. Experiments ==")
    res = ROOT / "results"
    old = [f for f in res.iterdir() if f.is_file() and f.name != LOG.name]
    if old:
        keep = res / "_previous_runs" / time.strftime("%Y%m%d-%H%M%S")
        keep.mkdir(parents=True, exist_ok=True)
        for f in old:
            f.rename(keep / f.name)
        log(f"Moved {len(old)} files from the previous run to {keep.relative_to(ROOT)}")
    run([VENV_PY, "run.py", "all", "--step", "2"])
    run([VENV_PY, "report/make_tables.py"])

    log("\n== 4. Publishing tools ==")
    for tool in ("git", "gh"):
        path = shutil.which(tool)
        log(f"{tool}: {path or 'NOT FOUND'}")
        if path:
            run([path, "--version"], check=False)
    if shutil.which("gh"):
        run(["gh", "auth", "status"], check=False)
    if shutil.which("git"):
        run(["git", "config", "--global", "user.name"], check=False)
        run(["git", "config", "--global", "user.email"], check=False)

    log(f"\nALL DONE in {time.time() - t0:.0f} s. Figures and tables are in {ROOT / 'results'}")


if __name__ == "__main__":
    main()
