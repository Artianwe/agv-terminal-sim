"""Dispatching policies: which AGV does which container job, and when.

All policies see the same released jobs (the next `lookahead` jobs of every QC) and must
assign each QC's jobs in sequence order. They differ in WHO gets a job and WHEN:

  fifo     - oldest released job goes to the AGV that has been idle longest. Uses no
             distance or timing information. Baseline.
  nearest  - greedy: the idle-AGV/job pair with the shortest empty drive is matched first.
             Classic distance-based rule (Egbelu & Tanchoco, 1984).
  central  - a central controller solves an assignment problem (Hungarian method) between
             all idle AGVs and the released jobs, minimising predicted QC hand-over time
             plus a small empty-travel penalty. Idle AGVs only.
  auction  - decentralised, Contract-Net style (Smith, 1980). Each QC agent announces its
             next job; every AGV agent with spare capacity bids its own predicted hand-over
             time (+ empty-travel penalty) from its local plan; the lowest bid wins.
             AGVs may bid while still busy (up to `max_commit` queued jobs), so they can
             commit to their next job before finishing the current one.
  auction_ra - risk-aware, two-way auction (this project's contribution):
             (a) when jobs outnumber free AGVs, free AGVs announce themselves and take the
                 closest job (vehicle-initiated Contract Net);
             (b) otherwise jobs are auctioned with a safety margin z * sigma on each bid, where
                 sigma is the spread of past arrival-prediction errors, learned online;
             (c) busy AGVs may pre-commit only if they can be on time and no idle AGV can.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List

import numpy as np
from scipy.optimize import linear_sum_assignment

if TYPE_CHECKING:  # pragma: no cover
    from .model import Terminal, AGV
    from .workplan import Job


class Dispatcher:
    name = "base"

    def __init__(self, term: "Terminal"):
        self.t = term

    def dispatch(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    # helpers -----------------------------------------------------------
    def idle_agvs(self) -> List["AGV"]:
        return [a for a in self.t.agvs if not a.queue]


class FIFODispatcher(Dispatcher):
    name = "fifo"

    def dispatch(self) -> None:
        t = self.t
        while True:
            jobs = t.assignable_jobs()
            idle = self.idle_agvs()
            if not jobs or not idle:
                return
            job = min(jobs, key=lambda j: (j.t_open, j.jid))
            agv = min(idle, key=lambda a: (a.idle_since, a.idx))
            t.record_choice(len(idle) * len(jobs))
            t.assign(agv, job)


class NearestDispatcher(Dispatcher):
    name = "nearest"

    def dispatch(self) -> None:
        t = self.t
        while True:
            jobs = t.assignable_jobs()
            idle = self.idle_agvs()
            if not jobs or not idle:
                return
            _, _, _, agv, job = min(
                ((t.layout.distance(a.node, j.pickup), j.t_open, a.idx, a, j)
                 for a in idle for j in jobs),
                key=lambda x: x[:3],
            )
            t.record_choice(len(idle) * len(jobs))
            t.assign(agv, job)


class CentralDispatcher(Dispatcher):
    name = "central"

    def dispatch(self) -> None:
        t = self.t
        while True:
            jobs = t.assignable_jobs()
            idle = self.idle_agvs()
            if not jobs or not idle:
                return
            cost = np.empty((len(idle), len(jobs)))
            for i, a in enumerate(idle):
                at, an = t.availability(a)
                for k, j in enumerate(jobs):
                    cost[i, k] = t.cost(at, an, j)
            rows, cols = linear_sum_assignment(cost)
            # every released job here is the head of a different QC, so assigning all
            # matched pairs at once keeps each QC's sequence order intact
            for r, c in zip(rows, cols):
                t.record_choice(len(idle) * len(jobs))
                t.assign(idle[r], jobs[c])


class AuctionDispatcher(Dispatcher):
    name = "auction"

    def dispatch(self) -> None:
        t = self.t
        cap = t.cfg.max_commit
        while True:
            jobs = t.assignable_jobs()
            bidders = [a for a in t.agvs if len(a.queue) <= cap]
            if not jobs or not bidders:
                return
            # the most urgent QC announces first
            job = min(jobs, key=lambda j: (t.est_handover_start(j), j.jid))
            best = None
            for a in bidders:
                at, an = t.availability(a)
                bid = t.cost(at, an, job)
                if best is None or (bid, a.idx) < best[:2]:
                    best = (bid, a.idx, a)
            # messages: 1 call-for-proposals + one bid per bidder + 1 award
            t.messages += 2 + len(bidders)
            t.record_choice(len(bidders))
            t.assign(best[2], job)


class RiskAwareAuctionDispatcher(Dispatcher):
    """Two-way Contract Net: whichever side is scarce makes the announcement.

    * More released jobs than free AGVs (vehicles are the bottleneck): each free AGV
      announces itself and takes the closest job - empty driving is lost capacity.
    * Otherwise the most urgent job is announced and AGVs bid with a risk margin:
      bid = max(predicted arrival + z * sigma, needed time) + w * empty drive time,
      sigma = learned spread of arrival errors (separately for idle and busy AGVs).
      A busy AGV may pre-commit only if its risk-adjusted arrival is on time, and only
      if no idle AGV is on time (adaptive commitment).
    """
    name = "auction_ra"

    def dispatch(self) -> None:
        t = self.t
        cfg = t.cfg
        while True:
            jobs = t.assignable_jobs()
            if not jobs:
                return
            idle = self.idle_agvs()

            # --- vehicle-initiated round: free AGVs pick the closest job ---
            if idle and len(jobs) > len(idle):
                agv = min(idle, key=lambda a: (a.idle_since, a.idx))
                job = min(jobs, key=lambda j: (t.layout.distance(agv.node, j.pickup), j.t_open, j.jid))
                t.messages += 1 + 2 * len(jobs)          # availability notice, offers, award + ack
                t.record_choice(len(jobs))
                t.assign(agv, job)
                continue

            # --- job-initiated round: the most urgent job is auctioned ---
            job = min(jobs, key=lambda j: (t.est_handover_start(j), j.jid))
            need = t.est_handover_start(job)
            bidders = [a for a in t.agvs if len(a.queue) <= cfg.max_commit]
            bids = []
            for a in bidders:
                busy = bool(a.queue)
                at, an = t.availability(a)
                _, empty, _, _, arrive = t.predict(at, an, job)
                safe_arrive = arrive + cfg.risk_z * t.arrival_sigma(busy)
                if busy and safe_arrive > need:
                    continue                              # would be late: no early commitment
                cost = max(safe_arrive, need) + cfg.empty_weight * empty
                bids.append((cost, a.idx, a, busy, safe_arrive))
            t.messages += 2 + len(bidders)
            if cfg.adaptive_commit and any((not b[3]) and b[4] <= need for b in bids):
                bids = [b for b in bids if not b[3]]      # an idle AGV is in time: busy AGVs withdraw
            if not bids:
                return                                    # nobody can take it now; wait for a free AGV
            t.record_choice(len(bids))
            best = min(bids, key=lambda b: (b[0], b[1]))
            t.assign(best[2], job)


REGISTRY = {
    "fifo": FIFODispatcher,
    "nearest": NearestDispatcher,
    "central": CentralDispatcher,
    "auction": AuctionDispatcher,
    "auction_ra": RiskAwareAuctionDispatcher,
}


def make_dispatcher(term: "Terminal") -> Dispatcher:
    return REGISTRY[term.cfg.policy](term)
