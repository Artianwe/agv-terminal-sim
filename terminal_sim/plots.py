"""Figures for the README and the report (static PNGs, light background)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .config import Config  # noqa: E402
from .layout import Layout  # noqa: E402

# ---- palette (validated categorical order; text never uses series colours) ----
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

POLICY_STYLE: Dict[str, Dict] = {
    "auction_ra": {"color": "#2a78d6", "marker": "o", "label": "Risk-aware auction (new)"},
    "nearest": {"color": "#eb6834", "marker": "s", "label": "Nearest vehicle"},
    "central": {"color": "#1baf7a", "marker": "^", "label": "Central (Hungarian)"},
    "auction": {"color": "#eda100", "marker": "D", "label": "Basic auction"},
    "fifo": {"color": "#e87ba4", "marker": "v", "label": "FIFO"},
}
POLICY_ORDER = ["auction_ra", "nearest", "central", "auction", "fifo"]

STATE_STYLE = {
    "loaded_travel": ("#2a78d6", "Loaded travel"),
    "empty_travel": ("#eb6834", "Empty travel"),
    "handling": ("#1baf7a", "Handling (QC/ASC)"),
    "wait_qc": ("#eda100", "Waiting at QC"),
    "wait_asc": ("#e87ba4", "Waiting at ASC"),
    "idle": ("#e1e0d9", "Idle"),
}


def setup_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "sans-serif", "font.size": 10,
        "text.color": INK, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
        "axes.axisbelow": True, "legend.frameon": False, "legend.labelcolor": INK_2,
        "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
        "savefig.dpi": 150, "savefig.bbox": "tight",
    })


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


FACTOR_TITLES = {
    "quay_to_yard_m": "Quay-to-yard distance (m)",
    "qc_cycle_scale": "QC cycle time (x default)",
    "travel_cv": "Travel-time variability (CV)",
    "lookahead": "Jobs released ahead per QC",
    "congestion_capacity": "Congestion capacity (moving AGVs)",
    "asc_time_scale": "Stacking-crane handling time (x default)",
}


def _int_xticks(ax, values) -> None:
    vals = sorted(set(int(v) for v in values))
    step = 1 if len(vals) <= 12 else 2
    ax.set_xticks(vals[::step])


_EXTRA_STYLES = [("#008300", "P"), ("#4a3aa7", "X"), ("#e34948", "*"), ("#52514e", "h")]


def _policies(df: pd.DataFrame):
    """Known policies in fixed order, then any new ones you add (they get the next colours)."""
    present = list(dict.fromkeys(df.policy))
    extra = [p for p in present if p not in POLICY_ORDER]
    for i, p in enumerate(extra):
        if p not in POLICY_STYLE:
            color, marker = _EXTRA_STYLES[i % len(_EXTRA_STYLES)]
            POLICY_STYLE[p] = {"color": color, "marker": marker, "label": p}
    return [p for p in POLICY_ORDER if p in present] + extra


# --------------------------------------------------------------------------- fleet
def plot_fleet(summary: pd.DataFrame, cfg: Config, out: Path, target: Optional[float] = None) -> Path:
    setup_style()
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    for p in _policies(summary):
        s = summary[summary.policy == p].sort_values("n_agv")
        st = POLICY_STYLE[p]
        ax.fill_between(s.n_agv, s.qc_productivity - s.qc_productivity_ci,
                        s.qc_productivity + s.qc_productivity_ci, color=st["color"], alpha=0.12, lw=0)
        ax.plot(s.n_agv, s.qc_productivity, color=st["color"], marker=st["marker"], ms=5,
                mec=SURFACE, mew=1.2, label=st["label"])
    ax.axhline(cfg.qc_max_productivity, color=MUTED, lw=1)
    ax.text(summary.n_agv.min(), cfg.qc_max_productivity + 0.25,
            f"QC upper bound {cfg.qc_max_productivity:.1f}", color=INK_2, fontsize=9, va="bottom")
    if target:
        ax.axhline(target, color=AXIS, lw=1)
        ax.text(summary.n_agv.max(), target - 0.3, f"target {target:.1f}", color=INK_2,
                fontsize=9, ha="right", va="top")
    _int_xticks(ax, summary.n_agv)
    ax.set_xlabel("AGV fleet size")
    ax.set_ylabel("QC productivity (moves per QC-hour)")
    ax.set_title(f"Fleet sizing: {cfg.n_qc} QCs, mean ± 95% CI over replications")
    ax.legend(loc="lower right")
    return _save(fig, out)


def plot_fleet_metric(summary: pd.DataFrame, kpi: str, ylabel: str, title: str, out: Path,
                      ylim=None) -> Path:
    setup_style()
    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    for p in _policies(summary):
        s = summary[summary.policy == p].sort_values("n_agv")
        st = POLICY_STYLE[p]
        ax.fill_between(s.n_agv, s[kpi] - s[f"{kpi}_ci"], s[kpi] + s[f"{kpi}_ci"],
                        color=st["color"], alpha=0.12, lw=0)
        ax.plot(s.n_agv, s[kpi], color=st["color"], marker=st["marker"], ms=5, mec=SURFACE,
                mew=1.2, label=st["label"])
    _int_xticks(ax, summary.n_agv)
    ax.set_xlabel("AGV fleet size")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if ylim:
        ax.set_ylim(*ylim)
    else:
        ax.set_ylim(bottom=0)
    ax.legend(loc="best")
    return _save(fig, out)


# ------------------------------------------------------------------------- compare
def plot_compare(summary: pd.DataFrame, out: Path) -> Path:
    setup_style()
    panels = [("qc_productivity", "QC productivity", "moves / QC-h", "{:.1f}"),
              ("empty_m_per_move", "Empty travel per move", "m", "{:.0f}"),
              ("qc_wait_per_move_s", "QC waiting for AGV per move", "s", "{:.1f}")]
    pols = _policies(summary)
    fig, axes = plt.subplots(1, 3, figsize=(11, 2.9), sharey=True)
    y = np.arange(len(pols))[::-1]
    for ax, (kpi, title, unit, fmt) in zip(axes, panels):
        s = summary.set_index("policy").loc[pols]
        ax.barh(y, s[kpi], height=0.5, color=[POLICY_STYLE[p]["color"] for p in pols], lw=0)
        ax.errorbar(s[kpi], y, xerr=s[f"{kpi}_ci"], fmt="none", ecolor=INK_2, elinewidth=1, capsize=3)
        for yi, v, c in zip(y, s[kpi], s[f"{kpi}_ci"]):
            ax.text(v + c + s[kpi].max() * 0.03, yi, fmt.format(v), va="center", color=INK, fontsize=9)
        ax.set_title(f"{title} ({unit})", fontsize=10)
        ax.set_xlim(0, s[kpi].max() * 1.3)
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(y, [POLICY_STYLE[p]["label"] for p in pols])
    n = int(summary.n_agv.iloc[0])
    fig.suptitle(f"Policy comparison at {n} AGVs (mean ± 95% CI)", x=0.01, ha="left",
                 fontsize=11, fontweight="bold", y=1.04)
    return _save(fig, out)


def plot_agv_states(summary: pd.DataFrame, out: Path) -> Path:
    setup_style()
    pols = _policies(summary)
    s = summary.set_index("policy").loc[pols]
    fig, ax = plt.subplots(figsize=(8.5, 2.8))
    y = np.arange(len(pols))[::-1]
    left = np.zeros(len(pols))
    for state, (color, label) in STATE_STYLE.items():
        vals = s[f"agv_{state}"].values * 100
        ax.barh(y, vals, left=left, height=0.5, color=color, edgecolor=SURFACE, lw=1.5, label=label)
        for yi, l, v in zip(y, left, vals):
            if v >= 7:
                txt = INK if state in ("wait_qc", "idle", "handling", "wait_asc") else "white"
                ax.text(l + v / 2, yi, f"{v:.0f}%", ha="center", va="center", fontsize=8, color=txt)
        left += vals
    ax.set_yticks(y, [POLICY_STYLE[p]["label"] for p in pols])
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of AGV fleet time during the vessel call (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=6, loc="upper left", bbox_to_anchor=(0, -0.28), fontsize=8, handlelength=1.2)
    n = int(summary.n_agv.iloc[0])
    ax.set_title(f"What the AGVs do ({n} AGVs)")
    return _save(fig, out)


# --------------------------------------------------------------------- sensitivity
def plot_sensitivity(summary: pd.DataFrame, out: Path) -> Path:
    setup_style()
    factors = list(dict.fromkeys(summary.factor))
    ncol = 3
    nrow = int(np.ceil(len(factors) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(11, 3.2 * nrow), squeeze=False)
    for ax, fac in zip(axes.flat, factors):
        s = summary[summary.factor == fac]
        levels = sorted(set(s.level))
        xl = ["none" if v >= 1e8 else (f"{v:g}") for v in levels]
        for p in _policies(s):
            ss = s[s.policy == p].set_index("level").loc[levels]
            st = POLICY_STYLE[p]
            ax.errorbar(range(len(levels)), ss.qc_productivity, yerr=ss.qc_productivity_ci,
                        color=st["color"], marker=st["marker"], ms=5, mec=SURFACE, mew=1.2,
                        capsize=2, elinewidth=1, label=st["label"])
        ax.set_xticks(range(len(levels)), xl)
        ax.set_title(FACTOR_TITLES.get(fac, fac), fontsize=10)
        ax.set_ylabel("QC prod. (moves/QC-h)", fontsize=9)
    for ax in list(axes.flat)[len(factors):]:
        ax.axis("off")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.legend(handles, labels, ncol=len(labels), loc="upper left", bbox_to_anchor=(0.01, 1.0), fontsize=9)
    return _save(fig, out)


def plot_ablation(summary: pd.DataFrame, out: Path) -> Path:
    setup_style()
    style = {  # same colour for the same entity as in the other figures where they appear
        "basic auction (naive prediction)": ("#4a3aa7", "X"),
        "basic auction (calibrated prediction)": ("#eda100", "D"),
        "two-way auction, no risk margin (z=0)": ("#008300", "P"),
        "two-way auction, risk margin, no adaptive commit": ("#e87ba4", "v"),
        "risk-aware auction (full)": ("#2a78d6", "o"),
        "nearest vehicle (reference)": ("#eb6834", "s"),
    }
    fallback = ["#52514e", "#e34948"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for (kpi, ylab), ax in zip([("qc_productivity", "QC productivity (moves/QC-h)"),
                                ("empty_m_per_move", "Empty travel per move (m)")], axes):
        variants = [v for v in style if v in set(summary.variant)]
        variants += [v for v in dict.fromkeys(summary.variant) if v not in style]
        for i, v in enumerate(variants):
            color, marker = style.get(v, (fallback[i % 2], "h"))
            s = summary[summary.variant == v].sort_values("n_agv")
            ax.fill_between(s.n_agv, s[kpi] - s[f"{kpi}_ci"], s[kpi] + s[f"{kpi}_ci"],
                            color=color, alpha=0.12, lw=0)
            ax.plot(s.n_agv, s[kpi], color=color, marker=marker, ms=5, mec=SURFACE,
                    mew=1.2, label=v)
        _int_xticks(ax, summary.n_agv)
        ax.set_xlabel("AGV fleet size")
        ax.set_ylabel(ylab)
    axes[1].set_ylim(bottom=0)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=3, loc="upper left", bbox_to_anchor=(0.01, 1.12), fontsize=9)
    fig.suptitle("Ablation: which ingredients of the risk-aware auction matter", x=0.01, ha="left",
                 fontsize=11, fontweight="bold", y=1.17)
    fig.tight_layout()
    return _save(fig, out)


# ------------------------------------------------------------------- single run
def plot_gantt(term, out: Path, t_max: float = 3600.0) -> Path:
    setup_style()
    cfg = term.cfg
    rows = [("QC", q) for q in range(cfg.n_qc)] + [("AGV", a) for a in range(cfg.n_agv)]
    ypos = {r: len(rows) - 1 - i for i, r in enumerate(rows)}
    fig, ax = plt.subplots(figsize=(11, 0.32 * len(rows) + 1.3))
    qc_col = {"working": ("#52514e", "QC working"), "wait_agv": ("#e34948", "QC waiting for AGV")}
    seen = set()
    for who, idx, state, t0, t1 in term.segments:
        if t0 >= t_max:
            continue
        t1 = min(t1, t_max)
        color, label = (qc_col if who == "QC" else STATE_STYLE)[state]
        lab = label if label not in seen else None
        seen.add(label)
        ax.broken_barh([(t0 / 60, (t1 - t0) / 60)], (ypos[(who, idx)] - 0.35, 0.7),
                       facecolors=color, edgecolor=SURFACE, lw=0.3, label=lab)
    ax.set_yticks([ypos[r] for r in rows], [f"{w} {i}" for w, i in rows], fontsize=8)
    ax.set_xlim(0, t_max / 60)
    ax.set_xlabel("time (min)")
    ax.grid(axis="y", visible=False)
    ax.set_title(f"Activity over the first {t_max / 60:.0f} min — policy: {cfg.policy}, {cfg.n_agv} AGVs")
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, -0.12), fontsize=8)
    return _save(fig, out)


def plot_layout(cfg: Config, out: Path) -> Path:
    setup_style()
    L = Layout(cfg)
    fig, ax = plt.subplots(figsize=(8, 4.6))
    xs = [xy[0] for xy in L.xy.values()]
    x0, x1 = min(xs) - 40, max(xs) + 40
    ax.fill_between([x0, x1], -60, -12, color="#cde2fb", lw=0)
    ax.text(x0 + 5, -50, "vessel at berth", color=INK_2, fontsize=9, va="center")
    ax.fill_between([x0, x1], 8, cfg.quay_to_yard_m - 8, color="#f0efec", lw=0)
    ax.text(x1 - 5, cfg.quay_to_yard_m / 2, "AGV driving area", color=INK_2, fontsize=9,
            ha="right", va="center")
    for q in range(cfg.n_qc):
        x, y = L.xy[("Q", q)]
        ax.plot([x, x], [-35, 5], color=INK, lw=3, solid_capstyle="butt")
        ax.plot(x, y, marker="s", ms=8, color=INK, mec=SURFACE, mew=1.5)
        ax.text(x, -72, f"QC {q}", ha="center", va="top", color=INK, fontsize=9)
    for b in range(cfg.n_blocks):
        x, y = L.xy[("B", b)]
        ax.add_patch(plt.Rectangle((x - cfg.block_pitch_m * 0.35, y), cfg.block_pitch_m * 0.7, 120,
                                   color="#9ec5f4", lw=0))
        ax.plot(x, y, marker="o", ms=7, color="#1c5cab", mec=SURFACE, mew=1.5)
        ax.text(x, y + 130, f"B{b}", ha="center", color=INK, fontsize=8)
    ax.text(x0 + 5, cfg.quay_to_yard_m + 60, "yard blocks\n(1 ASC each)", color=INK_2, fontsize=9)
    qx, _ = L.xy[("Q", 0)]
    bx, by = L.xy[("B", cfg.n_blocks - 1)]
    ax.annotate("", xy=(bx, by), xytext=(qx, 0),
                arrowprops=dict(arrowstyle="-|>", color="#eb6834", lw=1.5,
                                connectionstyle="angle,angleA=0,angleB=90"))
    ax.text((qx + bx) / 2, 14, f"example route: {L.distance(('Q', 0), ('B', cfg.n_blocks - 1)):.0f} m",
            color=INK_2, fontsize=8, ha="center", va="bottom")
    ax.set_xlim(x0, x1)
    ax.set_ylim(-95, cfg.quay_to_yard_m + 150)
    ax.set_aspect("equal")
    ax.set_xlabel("x along the quay (m)")
    ax.set_ylabel("y (m)")
    ax.grid(False)
    ax.set_title("Modelled terminal layout (top view)")
    return _save(fig, out)
