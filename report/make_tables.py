"""Builds the LaTeX tables of the report from the CSV files in ../results.
Run from the project folder:  python report/make_tables.py"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from terminal_sim.experiments import paired_difference  # noqa: E402

RES = ROOT / "results"
OUT = ROOT / "report" / "tables"
NAMES = {"auction_ra": "Risk-aware auction", "nearest": "Nearest vehicle", "central": "Central (Hungarian)",
         "auction": "Basic auction", "fifo": "FIFO"}
ORDER = ["auction_ra", "nearest", "central", "auction", "fifo"]


def pm(m, c, d=2):
    return f"{m:.{d}f} $\\pm$ {c:.{d}f}"


def fleet_table():
    s = pd.read_csv(RES / "fleet_summary.csv")
    sizes = sorted(s.n_agv.unique())
    lines = [r"\begin{tabular}{r" + "c" * len(ORDER) + "}", r"\toprule",
             "AGVs & " + " & ".join(NAMES[p] for p in ORDER) + r" \\", r"\midrule"]
    for n in sizes:
        row = s[s.n_agv == n].set_index("policy")
        best = row.qc_productivity.max()
        cells = []
        for p in ORDER:
            v, c = row.loc[p, "qc_productivity"], row.loc[p, "qc_productivity_ci"]
            txt = pm(v, c)
            cells.append(r"\textbf{" + txt + "}" if v >= best - 1e-9 else txt)
        lines.append(f"{n} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def paired_table():
    f = pd.read_csv(RES / "fleet_runs.csv")
    sizes = sorted(f.n_agv.unique())
    lines = [r"\begin{tabular}{r" + "cc" * 3 + "}", r"\toprule",
             r"& \multicolumn{2}{c}{vs nearest vehicle} & \multicolumn{2}{c}{vs central} & \multicolumn{2}{c}{vs basic auction} \\",
             r"AGVs & $\Delta$ prod. & $\Delta$ empty (m) & $\Delta$ prod. & $\Delta$ empty (m) & $\Delta$ prod. & $\Delta$ empty (m) \\",
             r"\midrule"]
    tabs = {}
    for ref in ("nearest", "central", "auction"):
        for k in ("qc_productivity", "empty_m_per_move"):
            d = paired_difference(f, k, ref, ["n_agv"])
            tabs[(ref, k)] = d[d.policy == "auction_ra"].set_index("n_agv")
    for n in sizes:
        cells = []
        for ref in ("nearest", "central", "auction"):
            for k, dec in (("qc_productivity", 2), ("empty_m_per_move", 0)):
                r = tabs[(ref, k)].loc[n]
                v = r[f"diff_{k}"]
                v = 0.0 if round(v, dec) == 0 else v
                txt = f"{v:+.{dec}f} $\\pm$ {r['ci95']:.{dec}f}"
                cells.append(r"\textbf{" + txt + "}" if r["significant"] else txt)
        lines.append(f"{n} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def compare_table():
    c = pd.read_csv(RES / "compare_summary.csv").set_index("policy")
    lines = [r"\begin{tabular}{lcccc}", r"\toprule",
             r"Policy & QC prod. (moves/QC-h) & Empty travel (m/move) & Crane wait (s/move) & Messages/job \\",
             r"\midrule"]
    for p in ORDER:
        r = c.loc[p]
        msg = "--" if pd.isna(r.messages_per_job) else f"{r.messages_per_job:.0f}"
        lines.append(f"{NAMES[p]} & {pm(r.qc_productivity, r.qc_productivity_ci)} & "
                     f"{pm(r.empty_m_per_move, r.empty_m_per_move_ci, 0)} & "
                     f"{pm(r.qc_wait_per_move_s, r.qc_wait_per_move_s_ci, 1)} & {msg} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def tuning_table():
    t = pd.read_csv(RES / "tuning_summary.csv").head(8)
    lines = [r"\begin{tabular}{lccc}", r"\toprule",
             r"Setting & Worst-case regret & Mean regret & Empty travel (m/move) \\", r"\midrule"]
    for _, r in t.iterrows():
        if r.variant.startswith("auction_ra"):
            z = r.variant.split("z=")[1].split()[0]
            ad = "on" if r.variant.endswith("True") else "off"
            name = f"Risk-aware auction, $z={z}$, adaptive commit {ad}"
        else:
            name = NAMES.get(r.variant, r.variant)
        lines.append(f"{name} & {r.max_regret:.2f} & {r.mean_regret:.2f} & {r.mean_empty_m_per_move:.0f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in [("fleet", fleet_table), ("paired", paired_table), ("compare", compare_table),
                     ("tuning", tuning_table)]:
        (OUT / f"tab_{name}.tex").write_text(fn() + "\n", encoding="utf-8")
        print(f"wrote report/tables/tab_{name}.tex")
