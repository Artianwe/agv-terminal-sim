"""The vessel work plan: every container move with all of its random times drawn up front.

Why draw everything up front? It gives *common random numbers* (CRN): for a given seed,
every dispatching policy and every fleet size sees exactly the same containers, the same
crane cycle times and the same yard blocks. Differences between policies are then caused by
the policy, not by luck, which shrinks the confidence intervals of paired comparisons a lot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from .config import Config
from .layout import Node

DISCHARGE = "D"  # vessel -> QC -> AGV -> yard block
LOAD = "L"       # yard block -> AGV -> QC -> vessel


@dataclass(eq=False)
class Job:
    jid: int
    qc: int
    seq: int                 # position in this QC's work sequence (QC handles jobs strictly in order)
    kind: str                # DISCHARGE or LOAD
    block: int               # yard block where the container goes to / comes from
    qc_t1: float             # QC time before the hand-over (trolley to transfer point)
    qc_t2: float             # QC time after the hand-over (back to the vessel)
    asc_hand: float          # ASC <-> AGV transfer time
    asc_work: float          # ASC store time (discharge) or retrieve time (load)
    noise_empty: float       # multiplicative noise on the empty leg
    noise_loaded: float      # multiplicative noise on the loaded leg

    # ---- filled in during the simulation ----
    agv: Optional[int] = None
    t_open: Optional[float] = None       # released to dispatching
    t_assigned: Optional[float] = None
    t_qc_ready: Optional[float] = None   # QC ready for the hand-over
    t_agv_at_qc: Optional[float] = None
    t_handover: Optional[float] = None   # hand-over starts
    t_done: Optional[float] = None       # AGV finished the job
    pred_arrive: Optional[float] = None  # predicted AGV arrival at the QC (made at assignment)
    pred_done: Optional[float] = None    # predicted job completion (made at assignment)
    pred_busy: bool = False              # was the AGV still busy when it got this job?
    ev_agv_at_qc: object = field(default=None, repr=False)
    ev_handover_done: object = field(default=None, repr=False)

    @property
    def pickup(self) -> Node:
        return ("Q", self.qc) if self.kind == DISCHARGE else ("B", self.block)

    @property
    def drop(self) -> Node:
        return ("B", self.block) if self.kind == DISCHARGE else ("Q", self.qc)


def _tri(rng: np.random.Generator, t, size) -> np.ndarray:
    lo, mode, hi = t
    if hi == lo:
        return np.full(size, float(lo))
    return rng.triangular(lo, mode, hi, size)


def _lognormal_mean1(rng: np.random.Generator, cv: float, size) -> np.ndarray:
    if cv <= 0:
        return np.ones(size)
    sigma2 = np.log(1.0 + cv * cv)
    return rng.lognormal(mean=-sigma2 / 2.0, sigma=np.sqrt(sigma2), size=size)


def job_kinds(cfg: Config, qc: int) -> List[str]:
    n_d = int(round(cfg.discharge_fraction * cfg.moves_per_qc))
    n_l = cfg.moves_per_qc - n_d
    if cfg.phase_pattern == "staggered" and qc % 2 == 1:
        return [LOAD] * n_l + [DISCHARGE] * n_d
    return [DISCHARGE] * n_d + [LOAD] * n_l


def build_workplan(cfg: Config) -> List[List[Job]]:
    """Return jobs_by_qc[q] = list of Jobs in QC q's handling order.

    The random draws depend only on (seed, n_qc, moves_per_qc, n_blocks and the
    distributions) - never on the policy or the number of AGVs.
    """
    rng = np.random.default_rng(cfg.seed)
    shape = (cfg.n_qc, cfg.moves_per_qc)
    block = rng.integers(0, cfg.n_blocks, size=shape)
    cycle = _tri(rng, cfg.qc_cycle_s, shape)
    asc_hand = _tri(rng, cfg.asc_handover_s, shape)
    asc_store = _tri(rng, cfg.asc_store_s, shape)
    asc_retr = _tri(rng, cfg.asc_retrieve_s, shape)
    n_empty = _lognormal_mean1(rng, cfg.travel_cv, shape)
    n_loaded = _lognormal_mean1(rng, cfg.travel_cv, shape)

    jobs_by_qc: List[List[Job]] = []
    jid = 0
    for q in range(cfg.n_qc):
        kinds = job_kinds(cfg, q)
        row = []
        for k in range(cfg.moves_per_qc):
            kind = kinds[k]
            row.append(Job(
                jid=jid, qc=q, seq=k, kind=kind, block=int(block[q, k]),
                qc_t1=float(cycle[q, k]) / 2.0, qc_t2=float(cycle[q, k]) / 2.0,
                asc_hand=float(asc_hand[q, k]),
                asc_work=float(asc_store[q, k] if kind == DISCHARGE else asc_retr[q, k]),
                noise_empty=float(n_empty[q, k]), noise_loaded=float(n_loaded[q, k]),
            ))
            jid += 1
        jobs_by_qc.append(row)
    return jobs_by_qc
