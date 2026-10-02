"""All model parameters in one place.

Every number below is an *assumption*. Before you put any result on your CV you must
be able to say where each value comes from (see docs/PROJECT_GUIDE.md, section
"Parameter table"). Times are in seconds, distances in metres.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace, fields
from pathlib import Path
from typing import Tuple

import yaml

Tri = Tuple[float, float, float]  # triangular distribution (min, mode, max)


def tri_mean(t: Tri) -> float:
    return (t[0] + t[1] + t[2]) / 3.0


POLICIES = ("fifo", "nearest", "central", "auction", "auction_ra")


@dataclass(frozen=True)
class Config:
    # ---------------- Vessel & quay cranes (QC) ----------------
    n_qc: int = 4                      # quay cranes working the vessel
    moves_per_qc: int = 300            # container moves per QC in this vessel call
    discharge_fraction: float = 0.5    # share of each QC's moves that are discharge (vessel -> yard)
    phase_pattern: str = "staggered"   # "staggered": even QCs discharge first, odd QCs load first
                                       # "discharge_first": every QC discharges, then loads
    qc_cycle_s: Tri = (70.0, 90.0, 130.0)  # QC cycle excluding the AGV hand-over
    qc_handover_s: float = 10.0        # time the QC needs the AGV underneath (set-down / pick-up)

    # ---------------- Layout ----------------
    qc_spacing_m: float = 80.0         # distance between neighbouring QCs along the quay
    n_blocks: int = 8                  # yard blocks (one automated stacking crane each)
    block_pitch_m: float = 40.0        # distance between neighbouring block transfer points
    quay_to_yard_m: float = 150.0      # depth of the AGV area between quay and yard
    route_factor: float = 1.3          # real lane routes are longer than Manhattan distance

    # ---------------- AGVs ----------------
    n_agv: int = 12
    agv_speed_mps: float = 5.0         # average cruising speed
    leg_overhead_s: float = 20.0       # acceleration, turning, positioning per driven leg
    travel_cv: float = 0.10            # random variation of each leg (coefficient of variation)
    congestion_alpha: float = 0.15     # BPR congestion function t = t0 * (1 + a (n/c)^b)
    congestion_beta: float = 4.0
    congestion_capacity: float = 20.0  # number of simultaneously moving AGVs that gives +a delay

    # ---------------- Yard: automated stacking cranes (ASC) ----------------
    asc_handover_s: Tri = (20.0, 30.0, 45.0)   # ASC <-> AGV transfer (AGV is held)
    asc_store_s: Tri = (40.0, 60.0, 90.0)      # after a discharge drop-off (AGV already gone)
    asc_retrieve_s: Tri = (40.0, 60.0, 90.0)   # before a load pick-up (AGV waits)

    # ---------------- Control / dispatching ----------------
    policy: str = "auction_ra"         # fifo | nearest | central | auction | auction_ra
    lookahead: int = 3                 # how many upcoming jobs of each QC are released to dispatching
    max_commit: int = 1                # auction: extra jobs an AGV may accept while still busy
    empty_weight: float = 0.2          # cost = predicted QC hand-over time + w * empty travel time
    predictor: str = "calibrated"      # how central/auction predict AGV timing:
                                       #   "naive": mean times only (ignores ASC queues and delays)
                                       #   "calibrated": + current ASC queue + learned bias (EMA)
    learn_rate: float = 0.05           # EMA weight for the learned prediction bias
    risk_z: float = 2.5                # auction_ra: bid with arrival + z * (learned spread of arrival error)
    adaptive_commit: bool = True       # auction_ra: busy AGVs only compete if no idle AGV is in time

    # ---------------- Experiment ----------------
    seed: int = 1

    # ---------------- helpers ----------------
    @property
    def total_moves(self) -> int:
        return self.n_qc * self.moves_per_qc

    @property
    def qc_mean_cycle_s(self) -> float:
        """Expected QC time per move when it never waits for an AGV."""
        return tri_mean(self.qc_cycle_s) + self.qc_handover_s

    @property
    def qc_max_productivity(self) -> float:
        """Upper bound on QC productivity (moves per QC-hour)."""
        return 3600.0 / self.qc_mean_cycle_s

    def with_(self, **kw) -> "Config":
        return replace(self, **kw)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_yaml(cls, path: str | Path | None = None, **overrides) -> "Config":
        data = {}
        if path is not None:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        data.update(overrides)
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        for k, v in list(data.items()):
            if isinstance(v, list):
                data[k] = tuple(float(x) for x in v)
        cfg = cls(**data)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}, got {self.policy!r}")
        if self.predictor not in ("naive", "calibrated"):
            raise ValueError("predictor must be 'naive' or 'calibrated'")
        if self.phase_pattern not in ("staggered", "discharge_first"):
            raise ValueError("phase_pattern must be 'staggered' or 'discharge_first'")
        for name in ("qc_cycle_s", "asc_handover_s", "asc_store_s", "asc_retrieve_s"):
            lo, mo, hi = getattr(self, name)
            if not lo <= mo <= hi:
                raise ValueError(f"{name}: need min <= mode <= max, got {(lo, mo, hi)}")
        if self.n_agv < 1 or self.n_qc < 1 or self.n_blocks < 1:
            raise ValueError("need at least one AGV, QC and block")
        if self.lookahead < 1:
            raise ValueError("lookahead must be >= 1")
        if not 0.0 <= self.discharge_fraction <= 1.0:
            raise ValueError("discharge_fraction must be in [0, 1]")
