"""Command-line entry point.

Examples (run from the project folder):
    python run.py single                       # one vessel call, prints KPIs, draws a Gantt chart
    python run.py single --policy fifo --n-agv 10
    python run.py compare --reps 10            # 4 policies at a fixed fleet size
    python run.py fleet --reps 10              # fleet-sizing sweep (the headline result)
    python run.py sensitivity --reps 10        # one-factor-at-a-time sensitivity analysis
    python run.py ablation --reps 10           # what makes the auction work?
    python run.py tune                         # pick the risk-aware auction settings (tuning seeds)
    python run.py all --quick                  # everything, small and fast (~1 min)
    python run.py all                          # everything, full size
    python run.py fleet --set quay_to_yard_m=250 --out results/deep_yard   # change any parameter
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

from terminal_sim import Config, Terminal
from terminal_sim import experiments as ex
from terminal_sim import plots

HERE = Path(__file__).resolve().parent


def parse_set(pairs):
    out = {}
    for p in pairs or []:
        k, v = p.split("=", 1)
        out[k.strip()] = yaml.safe_load(v)
    return out


def load_config(args) -> Config:
    over = parse_set(args.set)
    if getattr(args, "policy", None):
        over["policy"] = args.policy
    if getattr(args, "seed", None) is not None:
        over["seed"] = args.seed
    return Config.from_yaml(args.config, **over)


def cmd_single(args):
    cfg = load_config(args)
    if args.n_agv:
        cfg = cfg.with_(n_agv=args.n_agv)
    out = Path(args.out)
    term = Terminal(cfg)
    res = term.run()
    print(f"\nPolicy={cfg.policy}  AGVs={cfg.n_agv}  QCs={cfg.n_qc}  moves={cfg.total_moves}  seed={cfg.seed}")
    width = max(len(k) for k in res)
    for k, v in res.items():
        print(f"  {k:<{width}}  {v:.4g}" if isinstance(v, float) else f"  {k:<{width}}  {v}")
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{cfg.policy}_n{cfg.n_agv}_s{cfg.seed}"
    (out / f"single_{tag}.json").write_text(json.dumps(res, indent=2, default=float))
    term.job_table().to_csv(out / f"single_{tag}_jobs.csv", index=False)
    p = plots.plot_gantt(term, out / f"fig_gantt_{tag}.png", t_max=args.gantt_minutes * 60)
    print(f"\nSaved {p.name}, single_{tag}.json and the per-job table in {out}/")


def cmd_layout(args):
    cfg = load_config(args)
    p = plots.plot_layout(cfg, Path(args.out) / "fig_layout.png")
    print(f"Saved {p}")


def cmd_compare(args):
    cfg = load_config(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = args.n_agv or cfg.n_agv
    print(f"Policy comparison: {n} AGVs, {args.reps} replications per policy")
    df = ex.exp_compare(cfg, n, args.reps, args.workers)
    df.to_csv(out / "compare_runs.csv", index=False)
    summ = ex.summarize(df, ["policy", "n_agv"])
    summ.to_csv(out / "compare_summary.csv", index=False)
    diff = ex.paired_difference(df, "qc_productivity", "fifo", ["n_agv"])
    diff.to_csv(out / "compare_paired_vs_fifo.csv", index=False)
    paired = []
    for ref in ("nearest", "auction"):
        for k in ("qc_productivity", "empty_m_per_move", "qc_wait_per_move_s"):
            d = ex.paired_difference(df, k, ref, ["n_agv"])
            d = d[d.policy == "auction_ra"].rename(columns={f"diff_{k}": "difference"})
            d.insert(1, "kpi", k)
            d.insert(2, "versus", ref)
            paired.append(d)
    paired = pd.concat(paired)
    paired.to_csv(out / "compare_paired_new_auction.csv", index=False)
    plots.plot_compare(summ, out / "fig_compare.png")
    plots.plot_agv_states(summ, out / "fig_agv_states.png")
    cols = ["policy", "qc_productivity", "qc_productivity_ci", "empty_m_per_move", "qc_wait_per_move_s"]
    print(summ[cols].round(2).to_string(index=False))
    print("\nPaired difference in QC productivity vs FIFO (same seeds):")
    print(diff.round(3).to_string(index=False))
    print("\nRisk-aware auction minus reference (same seeds):")
    print(paired.round(3).to_string(index=False))


def cmd_fleet(args):
    cfg = load_config(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sizes = list(range(args.min, args.max + 1, args.step))
    print(f"Fleet sizing: AGVs {sizes}, {args.reps} replications each")
    df = ex.exp_fleet(cfg, sizes, args.reps, args.workers)
    df.to_csv(out / "fleet_runs.csv", index=False)
    summ = ex.summarize(df, ["policy", "n_agv"])
    summ.to_csv(out / "fleet_summary.csv", index=False)
    target = args.target_frac * cfg.qc_max_productivity
    mf = ex.min_fleet(summ, target)
    mf.to_csv(out / "fleet_min_fleet.csv", index=False)
    plots.plot_fleet(summ, cfg, out / "fig_fleet_productivity.png", target=target)
    plots.plot_fleet_metric(summ, "empty_m_per_move", "empty travel per move (m)",
                            "Empty driving per container move", out / "fig_fleet_empty_travel.png")
    plots.plot_fleet_metric(summ, "qc_wait_per_move_s", "QC waiting per move (s)",
                            "Time the quay cranes wait for an AGV", out / "fig_fleet_qc_wait.png")
    plots.plot_fleet_metric(summ, "single_choice_share", "share of decisions with only one option",
                            "How often the dispatcher had no real choice", out / "fig_fleet_choices.png",
                            ylim=(0, 1))
    piv = summ.pivot(index="n_agv", columns="policy", values="qc_productivity").round(2)
    print(piv.to_string())
    print(f"\nSmallest fleet reaching {target:.1f} moves/QC-h ({args.target_frac:.0%} of the QC bound):")
    print(mf.to_string(index=False))


def cmd_sensitivity(args):
    cfg = load_config(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = args.n_agv or cfg.n_agv
    print(f"Sensitivity analysis at {n} AGVs, {args.reps} replications")
    df = ex.exp_sensitivity(cfg, n, args.reps, args.workers, quick=args.quick)
    df.to_csv(out / "sensitivity_runs.csv", index=False)
    summ = ex.summarize(df, ["factor", "level", "policy"])
    summ.to_csv(out / "sensitivity_summary.csv", index=False)
    plots.plot_sensitivity(summ, out / "fig_sensitivity.png")
    print(summ.pivot_table(index=["factor", "level"], columns="policy",
                           values="qc_productivity").round(2).to_string())


def cmd_ablation(args):
    cfg = load_config(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sizes = list(range(args.min, args.max + 1, args.step))
    print(f"Auction ablation: AGVs {sizes}, {args.reps} replications")
    df = ex.exp_ablation(cfg, sizes, args.reps, args.workers)
    df.to_csv(out / "ablation_runs.csv", index=False)
    summ = ex.summarize(df, ["variant", "n_agv"])
    summ.to_csv(out / "ablation_summary.csv", index=False)
    plots.plot_ablation(summ, out / "fig_ablation.png")
    print(summ.pivot(index="n_agv", columns="variant", values="qc_productivity").round(2).to_string())


def cmd_tune(args):
    cfg = load_config(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sizes = list(range(args.min, args.max + 1, max(args.step, 2)))
    print(f"Tuning the risk-aware auction on seeds 101-110, AGVs {sizes}")
    df = ex.exp_tune(cfg, sizes, args.workers)
    df.to_csv(out / "tuning_runs.csv", index=False)
    tab = ex.tuning_table(df)
    tab.to_csv(out / "tuning_summary.csv", index=False)
    print(tab.round(3).to_string(index=False))
    best = tab[tab.variant.str.startswith("auction_ra")].iloc[0]
    print(f"\nBest setting by worst-case regret: {best.variant} (config/default.yaml should match)")


def cmd_all(args):
    t0 = time.time()
    if args.quick:
        args.reps = min(args.reps, 3)
        args.step = max(args.step, 4)
    cmd_layout(args)
    args.policy = None
    cmd_single(args)
    cmd_compare(args)
    cmd_fleet(args)
    cmd_sensitivity(args)
    cmd_ablation(args)
    if not args.quick:
        cmd_tune(args)
    print(f"\nAll experiments finished in {time.time() - t0:.0f} s. Results in {args.out}/")


def main(argv=None):
    ap = argparse.ArgumentParser(description="AGV dispatching at an automated container terminal")
    ap.add_argument("command", choices=["single", "layout", "compare", "fleet", "sensitivity", "ablation",
                                        "tune", "all"])
    ap.add_argument("--config", default=str(HERE / "config" / "default.yaml"))
    ap.add_argument("--out", default=str(HERE / "results"))
    ap.add_argument("--policy", choices=["fifo", "nearest", "central", "auction", "auction_ra"])
    ap.add_argument("--n-agv", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--reps", type=int, default=10, help="replications (vessel calls) per setting")
    ap.add_argument("--min", type=int, default=6, help="smallest fleet in sweeps")
    ap.add_argument("--max", type=int, default=24, help="largest fleet in sweeps")
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--target-frac", type=float, default=0.90,
                    help="fleet-sizing target as a fraction of the QC upper bound")
    ap.add_argument("--workers", type=int, default=None, help="parallel processes (default: CPUs-1)")
    ap.add_argument("--gantt-minutes", type=float, default=60)
    ap.add_argument("--quick", action="store_true", help="fewer replications and levels")
    ap.add_argument("--set", nargs="*", metavar="KEY=VALUE", help="override any config parameter")
    args = ap.parse_args(argv)
    if args.quick and args.command != "all":
        args.reps = min(args.reps, 3)
    {"single": cmd_single, "layout": cmd_layout, "compare": cmd_compare, "fleet": cmd_fleet,
     "sensitivity": cmd_sensitivity, "ablation": cmd_ablation, "tune": cmd_tune,
     "all": cmd_all}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
