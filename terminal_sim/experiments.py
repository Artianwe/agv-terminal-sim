"""Experiment runners and statistics.

Statistics in one paragraph
---------------------------
Each replication is one vessel call with its own random seed. For a KPI we report the mean
over replications and a 95 % confidence interval (Student-t, n-1 degrees of freedom).
Policies are compared on the *same* seeds (common random numbers), so the fair comparison
is the per-seed difference "policy - baseline", whose CI is much narrower than the two
separate CIs would suggest.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from .config import Config, POLICIES
from .model import simulate

KPIS = [
    "qc_productivity", "berth_productivity", "makespan_h", "qc_wait_share", "qc_wait_per_move_s",
    "empty_m_per_move", "asc_wait_per_move_s", "messages_per_job",
    "options_per_decision", "single_choice_share", "busy_assigned_share",
    "agv_loaded_travel", "agv_empty_travel", "agv_handling", "agv_wait_qc", "agv_wait_asc", "agv_idle",
]


# --------------------------------------------------------------------------- running
def _run_one(job: Dict) -> Dict:
    cfg = Config(**job["cfg"])
    res = simulate(cfg, record_segments=True)
    res.update(job.get("tags", {}))
    return res


def default_workers() -> int:
    return max(1, (os.cpu_count() or 2) - 1)


def run_batch(cfgs: Sequence[Config], tags: Optional[Sequence[Dict]] = None,
              workers: Optional[int] = None, progress: bool = True) -> pd.DataFrame:
    """Run many replications (in parallel when workers > 1)."""
    tags = tags or [{} for _ in cfgs]
    jobs = [{"cfg": asdict(c), "tags": t} for c, t in zip(cfgs, tags)]
    workers = default_workers() if workers is None else workers
    results: List[Dict] = []
    if workers <= 1 or len(jobs) < 8:
        for i, j in enumerate(jobs, 1):
            results.append(_run_one(j))
            if progress and i % 50 == 0:
                print(f"  {i}/{len(jobs)} runs", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, r in enumerate(ex.map(_run_one, jobs, chunksize=4), 1):
                results.append(r)
                if progress and i % 100 == 0:
                    print(f"  {i}/{len(jobs)} runs", flush=True)
    return pd.DataFrame(results)


# ------------------------------------------------------------------------ statistics
def ci95_halfwidth(x: Iterable[float]) -> float:
    x = np.asarray([v for v in x if not np.isnan(v)], dtype=float)
    if len(x) < 2:
        return float("nan")
    return float(stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x)))


def summarize(df: pd.DataFrame, by: List[str], kpis: Optional[List[str]] = None) -> pd.DataFrame:
    """Mean and 95 % CI half-width of each KPI per group. Columns: <kpi>, <kpi>_ci."""
    kpis = [k for k in (kpis or KPIS) if k in df.columns]
    g = df.groupby(by, sort=True)
    mean = g[kpis].mean()
    ci = g[kpis].agg(ci95_halfwidth).add_suffix("_ci")
    out = pd.concat([mean, ci], axis=1)
    out["n_reps"] = g.size()
    return out.reset_index()


def paired_difference(df: pd.DataFrame, kpi: str, baseline: str, by: List[str]) -> pd.DataFrame:
    """Per-seed difference (policy - baseline) of one KPI, summarised with a 95 % CI."""
    keys = by + ["seed"]
    base = df[df.policy == baseline].set_index(keys)[kpi]
    rows = []
    for pol, sub in df.groupby("policy"):
        d = sub.set_index(keys)[kpi] - base.reindex(sub.set_index(keys).index)
        d = d.dropna()
        for grp, dd in (d.groupby(level=by) if by else [((), d)]):
            grp = grp if isinstance(grp, tuple) else (grp,)
            rows.append({**dict(zip(by, grp)), "policy": pol, f"diff_{kpi}": dd.mean(),
                         "ci95": ci95_halfwidth(dd.values),
                         "significant": abs(dd.mean()) > ci95_halfwidth(dd.values)})
    return pd.DataFrame(rows)


def min_fleet(summary: pd.DataFrame, target: float, kpi: str = "qc_productivity") -> pd.DataFrame:
    """Smallest fleet whose mean KPI reaches `target`; also the smallest whose lower
    95 % confidence bound reaches it (the conservative answer)."""
    rows = []
    for pol, s in summary.groupby("policy"):
        s = s.sort_values("n_agv")
        ok_mean = s[s[kpi] >= target]
        ok_low = s[(s[kpi] - s[f"{kpi}_ci"]) >= target]
        rows.append({"policy": pol, "target": target,
                     "min_fleet_mean": int(ok_mean.n_agv.min()) if len(ok_mean) else None,
                     "min_fleet_conservative": int(ok_low.n_agv.min()) if len(ok_low) else None})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------ experiments
def exp_compare(base: Config, n_agv: int, reps: int, workers=None) -> pd.DataFrame:
    cfgs = [base.with_(policy=p, n_agv=n_agv, seed=s) for p in POLICIES for s in range(1, reps + 1)]
    return run_batch(cfgs, workers=workers)


def exp_fleet(base: Config, fleet_sizes: Sequence[int], reps: int, workers=None) -> pd.DataFrame:
    cfgs = [base.with_(policy=p, n_agv=n, seed=s)
            for p in POLICIES for n in fleet_sizes for s in range(1, reps + 1)]
    return run_batch(cfgs, workers=workers)


def sensitivity_factors(base: Config, quick: bool = False) -> Dict[str, Dict]:
    """One-factor-at-a-time design. Each entry: levels and how to apply a level."""
    c = base.qc_cycle_s
    f = {
        "quay_to_yard_m": {"levels": [100, 150, 200, 250], "apply": lambda cfg, v: cfg.with_(quay_to_yard_m=float(v))},
        "qc_cycle_scale": {"levels": [0.8, 1.0, 1.2],
                           "apply": lambda cfg, v: cfg.with_(qc_cycle_s=tuple(x * v for x in c))},
        "travel_cv": {"levels": [0.0, 0.1, 0.2, 0.3], "apply": lambda cfg, v: cfg.with_(travel_cv=float(v))},
        "lookahead": {"levels": [1, 2, 3, 5], "apply": lambda cfg, v: cfg.with_(lookahead=int(v))},
        "congestion_capacity": {"levels": [12, 20, 1e9],
                                "apply": lambda cfg, v: cfg.with_(congestion_capacity=float(v))},
        "asc_time_scale": {"levels": [0.8, 1.0, 1.25],
                           "apply": lambda cfg, v: cfg.with_(
                               asc_handover_s=tuple(x * v for x in base.asc_handover_s),
                               asc_store_s=tuple(x * v for x in base.asc_store_s),
                               asc_retrieve_s=tuple(x * v for x in base.asc_retrieve_s))},
    }
    if quick:
        for v in f.values():
            v["levels"] = [v["levels"][0], v["levels"][-1]]
    return f


def exp_sensitivity(base: Config, n_agv: int, reps: int, workers=None, quick: bool = False) -> pd.DataFrame:
    cfgs, tags = [], []
    for name, spec in sensitivity_factors(base, quick).items():
        for lvl in spec["levels"]:
            for p in POLICIES:
                for s in range(1, reps + 1):
                    cfgs.append(spec["apply"](base.with_(policy=p, n_agv=n_agv, seed=s), lvl))
                    tags.append({"factor": name, "level": lvl})
    return run_batch(cfgs, tags=tags, workers=workers)


def exp_ablation(base: Config, fleet_sizes: Sequence[int], reps: int, workers=None) -> pd.DataFrame:
    """What makes the auction work? Switch the ingredients on one at a time."""
    variants = {
        "basic auction (naive prediction)": dict(policy="auction", predictor="naive"),
        "basic auction (calibrated prediction)": dict(policy="auction"),
        "two-way auction, no risk margin (z=0)": dict(policy="auction_ra", risk_z=0.0),
        "two-way auction, risk margin, no adaptive commit": dict(policy="auction_ra", adaptive_commit=False),
        "risk-aware auction (full)": dict(policy="auction_ra"),
        "nearest vehicle (reference)": dict(policy="nearest"),
    }
    cfgs, tags = [], []
    for name, kw in variants.items():
        for n in fleet_sizes:
            for s in range(1, reps + 1):
                cfgs.append(base.with_(n_agv=n, seed=s, **kw))
                tags.append({"variant": name})
    return run_batch(cfgs, tags=tags, workers=workers)


TUNING_SEEDS = range(101, 111)   # separate from the evaluation seeds 1..reps


def exp_tune(base: Config, fleet_sizes: Sequence[int], workers=None,
             z_grid=(0.5, 1.0, 1.5, 2.0, 2.5, 3.0)) -> pd.DataFrame:
    """Choose the risk-aware auction's settings on TUNING seeds (101-110), never on the
    evaluation seeds, so the reported results are not tuned to the test data.
    Criterion (fixed before running): smallest worst-case shortfall ("regret") in QC
    productivity versus the best baseline policy at each fleet size."""
    cfgs, tags = [], []
    for p in ("fifo", "nearest", "central", "auction"):
        for n in fleet_sizes:
            for s in TUNING_SEEDS:
                cfgs.append(base.with_(policy=p, n_agv=n, seed=s))
                tags.append({"variant": p, "risk_z": None, "adaptive_commit": None})
    for z in z_grid:
        for ad in (False, True):
            for n in fleet_sizes:
                for s in TUNING_SEEDS:
                    cfgs.append(base.with_(policy="auction_ra", n_agv=n, seed=s, risk_z=z, adaptive_commit=ad))
                    tags.append({"variant": f"auction_ra z={z} adaptive={ad}", "risk_z": z, "adaptive_commit": ad})
    return run_batch(cfgs, tags=tags, workers=workers)


def tuning_table(df: pd.DataFrame) -> pd.DataFrame:
    piv = df.pivot_table(index="variant", columns="n_agv", values="qc_productivity")
    best = piv.loc[["fifo", "nearest", "central", "auction"]].max()
    regret = (best - piv).clip(lower=0)
    emp = df.pivot_table(index="variant", columns="n_agv", values="empty_m_per_move")
    out = pd.DataFrame({"max_regret": regret.max(axis=1), "mean_regret": regret.mean(axis=1),
                        "mean_empty_m_per_move": emp.mean(axis=1)})
    return out.sort_values(["max_regret", "mean_regret"]).reset_index()
