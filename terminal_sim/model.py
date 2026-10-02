"""Discrete-event model of the waterside of an automated container terminal (SimPy).

Entities
  QC   quay crane: handles its jobs strictly in sequence. For every move it needs an AGV
       underneath during the hand-over; if none is there, the crane waits (that waiting is
       exactly what good AGV dispatching tries to avoid).
  AGV  automated guided vehicle: executes its committed jobs one after another
       (empty drive -> pick-up -> loaded drive -> drop-off).
  ASC  automated stacking crane, one per yard block (simpy.Resource, capacity 1). AGVs
       queue for it at the block's transfer point.

A *terminating* simulation: one vessel call, from first move to last move. No warm-up
period is needed; each replication is one independent vessel call.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import simpy

from .config import Config, tri_mean
from .dispatch import make_dispatcher
from .layout import Layout, Node
from .workplan import DISCHARGE, Job, build_workplan

AGV_STATES = ("loaded_travel", "empty_travel", "handling", "wait_qc", "wait_asc", "idle")


class AGV:
    def __init__(self, idx: int, node: Node):
        self.idx = idx
        self.node = node
        self.queue: deque = deque()      # committed jobs; queue[0] is being executed
        self.wake: Optional[simpy.Event] = None
        self.idle_since = 0.0
        self.plan_t = 0.0                # predicted time when all committed work is done
        self.plan_node = node            # ... and where the AGV will be then
        self.dist_empty = 0.0
        self.dist_loaded = 0.0
        self.jobs_done = 0


class Terminal:
    def __init__(self, cfg: Config, record_segments: bool = True):
        cfg.validate()
        self.cfg = cfg
        self.env = simpy.Environment()
        self.layout = Layout(cfg)
        self.jobs_by_qc: List[List[Job]] = build_workplan(cfg)
        self.all_jobs: List[Job] = [j for row in self.jobs_by_qc for j in row]
        for j in self.all_jobs:
            j.ev_agv_at_qc = self.env.event()
            j.ev_handover_done = self.env.event()

        self.next_assign = [0] * cfg.n_qc          # next job of each QC to be assigned
        self.next_handover = [0] * cfg.n_qc        # next job of each QC to be handed over
        self.last_handover_end: List[Optional[float]] = [None] * cfg.n_qc
        self.qc_wait = [0.0] * cfg.n_qc
        self.qc_finish: List[Optional[float]] = [None] * cfg.n_qc

        self.asc = [simpy.Resource(self.env, capacity=1) for _ in range(cfg.n_blocks)]
        self.asc_wait_total = 0.0

        self.agvs = [AGV(i, ("B", (i * cfg.n_blocks) // cfg.n_agv)) for i in range(cfg.n_agv)]
        self.n_moving = 0
        self.messages = 0
        self.jobs_done = 0
        self.record_segments = record_segments
        self.segments: List[Tuple[str, int, str, float, float]] = []  # (who, idx, state, t0, t1)

        # pre-computed means used by the predictive dispatchers
        self._qc_c = tri_mean(cfg.qc_cycle_s)
        self._asc_hand = tri_mean(cfg.asc_handover_s)
        self._asc_retr = tri_mean(cfg.asc_retrieve_s)
        self._asc_occupancy = self._asc_hand + (tri_mean(cfg.asc_store_s) + self._asc_retr) / 2.0
        # learned prediction bias per job type (only used with predictor="calibrated")
        self.bias_arrive = {"D": 0.0, "L": 0.0}
        self.bias_done = {"D": 0.0, "L": 0.0}
        # learned spread of the arrival error, separately for jobs given to idle / busy AGVs
        # (mean squared error, EMA; prior = (30 s)^2). Used by the risk-aware auction.
        self.arrival_mse = {False: 900.0, True: 900.0}
        # dispatch diagnostics: how much choice did the dispatcher have?
        self.n_decisions = 0
        self.sum_options = 0
        self.n_single_choice = 0

        for q in range(cfg.n_qc):
            for k in range(min(cfg.lookahead, cfg.moves_per_qc)):
                self.jobs_by_qc[q][k].t_open = 0.0

        self.dispatcher = make_dispatcher(self)
        self.makespan: Optional[float] = None

    # ------------------------------------------------------------------ run
    def run(self) -> Dict[str, float]:
        wall0 = time.perf_counter()
        env = self.env
        qc_procs = [env.process(self._qc_process(q)) for q in range(self.cfg.n_qc)]
        for a in self.agvs:
            env.process(self._agv_process(a))
        self.dispatcher.dispatch()                 # first assignments at t = 0
        env.run(until=simpy.AllOf(env, qc_procs))  # vessel finished = all QCs done
        self.makespan = env.now
        env.run()                                  # let AGVs finish the last yard deliveries
        out = self.metrics()
        out["wall_time_s"] = time.perf_counter() - wall0
        return out

    # ------------------------------------------------------- dispatch API
    def assignable_jobs(self) -> List[Job]:
        """Released, unassigned jobs that may be assigned now (the head of each QC)."""
        cfg, out = self.cfg, []
        for q in range(cfg.n_qc):
            k = self.next_assign[q]
            if k < cfg.moves_per_qc and k < self.next_handover[q] + cfg.lookahead:
                out.append(self.jobs_by_qc[q][k])
        return out

    def availability(self, agv: AGV) -> Tuple[float, Node]:
        """When and where an AGV will be free, according to its own plan."""
        if not agv.queue:
            return self.env.now, agv.node
        return max(self.env.now, agv.plan_t), agv.plan_node

    def est_handover_start(self, job: Job) -> float:
        """The QC agent's estimate of when it will be ready for this job's hand-over."""
        q = job.qc
        j = self.next_handover[q]
        full = self._qc_c + self.cfg.qc_handover_s
        if self.last_handover_end[q] is None:
            anchor = self._qc_c / 2.0
        else:
            anchor = self.last_handover_end[q] + self._qc_c
        return max(self.env.now, anchor + (job.seq - j) * full)

    def asc_wait_estimate(self, block: int) -> float:
        """Expected queueing time at a block's ASC, judged from its current queue."""
        if self.cfg.predictor == "naive":
            return 0.0
        res = self.asc[block]
        return (0.5 * res.count + len(res.queue)) * self._asc_occupancy

    def predict(self, t0: float, node: Node, job: Job) -> Tuple[float, float, float, Node, float]:
        """If an AGV that is free at (t0, node) takes `job`, predict:
        (hand-over start at the QC, empty drive time, job completion time, end node,
        AGV arrival time at the QC). Uses mean times, plus ASC queues and a learned
        bias when predictor == "calibrated"."""
        L, h = self.layout, self.cfg.qc_handover_s
        need = self.est_handover_start(job)
        empty = L.nominal_travel_time(node, job.pickup)
        loaded = L.nominal_travel_time(job.pickup, job.drop)
        b_arr, b_done = self.bias_arrive[job.kind], self.bias_done[job.kind]
        if job.kind == DISCHARGE:
            arrive = t0 + empty + b_arr
            hs = max(arrive, need)
            done = hs + h + loaded + self.asc_wait_estimate(job.block) + self._asc_hand + b_done
        else:
            arrive = (t0 + empty + self.asc_wait_estimate(job.block) + self._asc_retr
                      + self._asc_hand + loaded + b_arr)
            hs = max(arrive, need)
            done = hs + h + b_done
        return hs, empty, done, job.drop, arrive

    def cost(self, t0: float, node: Node, job: Job) -> float:
        hs, empty, _, _, _ = self.predict(t0, node, job)
        return hs + self.cfg.empty_weight * empty

    def arrival_sigma(self, busy: bool) -> float:
        """Learned standard deviation of the arrival-time prediction error (seconds)."""
        return math.sqrt(self.arrival_mse[busy])

    def record_choice(self, n_options: int) -> None:
        """Dispatchers call this once per assignment with the number of alternatives they had."""
        self.n_decisions += 1
        self.sum_options += n_options
        if n_options <= 1:
            self.n_single_choice += 1

    def _learn(self, table: Dict[str, float], kind: str, error: float) -> None:
        if self.cfg.predictor == "calibrated":
            a = self.cfg.learn_rate
            table[kind] = (1 - a) * table[kind] + a * error

    def assign(self, agv: AGV, job: Job) -> None:
        assert job.agv is None, "job assigned twice"
        assert job.seq == self.next_assign[job.qc], "QC sequence order violated"
        t0, node = self.availability(agv)
        _, _, done, end, arrive = self.predict(t0, node, job)
        job.pred_arrive, job.pred_done = arrive, done
        job.pred_busy = bool(agv.queue)
        job.agv = agv.idx
        job.t_assigned = self.env.now
        self.next_assign[job.qc] += 1
        agv.queue.append(job)
        agv.plan_t, agv.plan_node = done, end
        if agv.wake is not None and not agv.wake.triggered:
            agv.wake.succeed()

    def _replan(self, agv: AGV) -> None:
        t, node = self.env.now, agv.node
        for job in agv.queue:
            _, _, t, node, _ = self.predict(t, node, job)
        agv.plan_t, agv.plan_node = t, node

    # ------------------------------------------------------------ processes
    def _seg(self, who: str, idx: int, state: str, t0: float, t1: float) -> None:
        if self.record_segments and t1 > t0:
            self.segments.append((who, idx, state, t0, t1))

    def _qc_process(self, q: int):
        env, cfg = self.env, self.cfg
        for job in self.jobs_by_qc[q]:
            t0 = env.now
            yield env.timeout(job.qc_t1)
            job.t_qc_ready = env.now
            if not job.ev_agv_at_qc.triggered:
                yield job.ev_agv_at_qc
            self.qc_wait[q] += env.now - job.t_qc_ready
            self._seg("QC", q, "working", t0, job.t_qc_ready)
            self._seg("QC", q, "wait_agv", job.t_qc_ready, env.now)
            job.t_handover = env.now
            yield env.timeout(cfg.qc_handover_s)
            job.ev_handover_done.succeed()
            self.next_handover[q] += 1
            self.last_handover_end[q] = env.now
            nxt = job.seq + cfg.lookahead
            if nxt < cfg.moves_per_qc:
                self.jobs_by_qc[q][nxt].t_open = env.now
            self.dispatcher.dispatch()               # the release window moved on
            yield env.timeout(job.qc_t2)
            self._seg("QC", q, "working", job.t_handover, env.now)
        self.qc_finish[q] = env.now

    def _drive(self, agv: AGV, dest: Node, noise: float, loaded: bool):
        if agv.node == dest:
            return
        cfg, env = self.cfg, self.env
        dist = self.layout.distance(agv.node, dest)
        self.n_moving += 1
        congestion = 1.0 + cfg.congestion_alpha * (self.n_moving / cfg.congestion_capacity) ** cfg.congestion_beta
        dt = (dist / cfg.agv_speed_mps + cfg.leg_overhead_s) * noise * congestion
        t0 = env.now
        yield env.timeout(dt)
        self.n_moving -= 1
        self._seg("AGV", agv.idx, "loaded_travel" if loaded else "empty_travel", t0, env.now)
        agv.node = dest
        if loaded:
            agv.dist_loaded += dist
        else:
            agv.dist_empty += dist

    def _use_asc(self, agv: AGV, job: Job):
        """Queue for the block's ASC and do the transfer."""
        env = self.env
        res = self.asc[job.block]
        t0 = env.now
        req = res.request()
        yield req
        self.asc_wait_total += env.now - t0
        self._seg("AGV", agv.idx, "wait_asc", t0, env.now)
        t1 = env.now
        if job.kind == DISCHARGE:
            yield env.timeout(job.asc_hand)            # ASC lifts the box off the AGV
            env.process(self._asc_finish(res, req, job.asc_work))  # ASC stores it; AGV leaves
        else:
            yield env.timeout(job.asc_work + job.asc_hand)  # ASC fetches the box, puts it on the AGV
            res.release(req)
        self._seg("AGV", agv.idx, "handling", t1, env.now)

    def _asc_finish(self, res: simpy.Resource, req, duration: float):
        yield self.env.timeout(duration)
        res.release(req)

    def _at_qc(self, agv: AGV, job: Job):
        env = self.env
        t0 = env.now
        job.t_agv_at_qc = t0
        err = t0 - job.pred_arrive
        self._learn(self.bias_arrive, job.kind, err)
        a = self.cfg.learn_rate
        self.arrival_mse[job.pred_busy] = (1 - a) * self.arrival_mse[job.pred_busy] + a * err * err
        job.ev_agv_at_qc.succeed()
        yield job.ev_handover_done
        self._seg("AGV", agv.idx, "wait_qc", t0, job.t_handover)
        self._seg("AGV", agv.idx, "handling", job.t_handover, env.now)

    def _agv_process(self, agv: AGV):
        env = self.env
        while True:
            if not agv.queue:
                agv.idle_since = env.now
                agv.wake = env.event()
                yield agv.wake
                agv.wake = None
                self._seg("AGV", agv.idx, "idle", agv.idle_since, env.now)
            job: Job = agv.queue[0]
            if job.kind == DISCHARGE:
                yield from self._drive(agv, job.pickup, job.noise_empty, loaded=False)
                yield from self._at_qc(agv, job)
                yield from self._drive(agv, job.drop, job.noise_loaded, loaded=True)
                yield from self._use_asc(agv, job)
            else:
                yield from self._drive(agv, job.pickup, job.noise_empty, loaded=False)
                yield from self._use_asc(agv, job)
                yield from self._drive(agv, job.drop, job.noise_loaded, loaded=True)
                yield from self._at_qc(agv, job)
            agv.queue.popleft()
            job.t_done = env.now
            self._learn(self.bias_done, job.kind, env.now - job.pred_done)
            agv.jobs_done += 1
            self.jobs_done += 1
            self._replan(agv)
            self.dispatcher.dispatch()               # this AGV has capacity again

    # -------------------------------------------------------------- metrics
    def metrics(self) -> Dict[str, float]:
        cfg = self.cfg
        M = self.makespan
        n = cfg.total_moves
        qc_prod = [cfg.moves_per_qc / (f / 3600.0) for f in self.qc_finish]
        out: Dict[str, float] = {
            "makespan_h": M / 3600.0,
            "qc_productivity": sum(qc_prod) / len(qc_prod),        # moves per QC-hour
            "qc_productivity_max": cfg.qc_max_productivity,
            "berth_productivity": n / (M / 3600.0),               # moves per hour, whole vessel
            "qc_wait_share": sum(self.qc_wait) / sum(self.qc_finish),
            "qc_wait_per_move_s": sum(self.qc_wait) / n,
            "empty_m_per_move": sum(a.dist_empty for a in self.agvs) / n,
            "loaded_m_per_move": sum(a.dist_loaded for a in self.agvs) / n,
            "asc_wait_per_move_s": self.asc_wait_total / n,
            "messages_per_job": self.messages / n if cfg.policy.startswith("auction") else math.nan,
            "options_per_decision": self.sum_options / max(1, self.n_decisions),
            "single_choice_share": self.n_single_choice / max(1, self.n_decisions),
            "busy_assigned_share": sum(j.pred_busy for j in self.all_jobs) / n,
            "jobs_done": self.jobs_done,
        }
        if self.record_segments:
            tot = {s: 0.0 for s in AGV_STATES}
            for who, _, state, t0, t1 in self.segments:
                if who == "AGV" and state != "idle":
                    tot[state] += max(0.0, min(t1, M) - max(t0, 0.0))
            fleet_time = cfg.n_agv * M
            tot["idle"] = fleet_time - sum(v for k, v in tot.items() if k != "idle")
            for s in AGV_STATES:
                out[f"agv_{s}"] = tot[s] / fleet_time
        return out

    def job_table(self):
        """One row per container move (for debugging and plots)."""
        import pandas as pd
        rows = []
        for j in self.all_jobs:
            rows.append(dict(
                jid=j.jid, qc=j.qc, seq=j.seq, kind=j.kind, block=j.block, agv=j.agv,
                t_open=j.t_open, t_assigned=j.t_assigned, t_qc_ready=j.t_qc_ready,
                t_agv_at_qc=j.t_agv_at_qc, t_handover=j.t_handover, t_done=j.t_done,
                qc_delay=(j.t_handover - j.t_qc_ready),
            ))
        return pd.DataFrame(rows)


def simulate(cfg: Config, record_segments: bool = True) -> Dict[str, float]:
    """Run one replication and return its KPIs together with its key settings."""
    term = Terminal(cfg, record_segments=record_segments)
    res = term.run()
    res.update(policy=cfg.policy, n_agv=cfg.n_agv, seed=cfg.seed)
    return res
