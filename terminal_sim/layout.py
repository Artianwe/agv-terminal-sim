"""Terminal geometry: where the quay cranes and yard blocks are, and how far apart.

Coordinate system (top view):
    y = 0                 -> quay, QC transfer points (AGVs stop under the crane)
    y = quay_to_yard_m    -> seaside ends of the yard blocks, ASC transfer points
    x                     -> along the quay

A node is a tuple ("Q", i) for quay crane i or ("B", j) for yard block j.
"""
from __future__ import annotations

from typing import Dict, Tuple

from .config import Config

Node = Tuple[str, int]


class Layout:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        yard_width = (cfg.n_blocks - 1) * cfg.block_pitch_m
        quay_width = (cfg.n_qc - 1) * cfg.qc_spacing_m
        centre = yard_width / 2.0
        self.xy: Dict[Node, Tuple[float, float]] = {}
        for i in range(cfg.n_qc):
            self.xy[("Q", i)] = (centre - quay_width / 2.0 + i * cfg.qc_spacing_m, 0.0)
        for j in range(cfg.n_blocks):
            self.xy[("B", j)] = (j * cfg.block_pitch_m, cfg.quay_to_yard_m)

    def distance(self, a: Node, b: Node) -> float:
        """Route length in metres (Manhattan distance x route factor)."""
        if a == b:
            return 0.0
        (xa, ya), (xb, yb) = self.xy[a], self.xy[b]
        return self.cfg.route_factor * (abs(xa - xb) + abs(ya - yb))

    def nominal_travel_time(self, a: Node, b: Node) -> float:
        """Expected driving time without noise or congestion (used by the dispatchers)."""
        if a == b:
            return 0.0
        return self.distance(a, b) / self.cfg.agv_speed_mps + self.cfg.leg_overhead_s
