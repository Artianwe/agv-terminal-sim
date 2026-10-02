"""Verification tests: does the code do what the model description says?

Run with:  python -m pytest -q
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from terminal_sim import Config, POLICIES, Terminal, simulate  # noqa: E402
from terminal_sim.workplan import build_workplan  # noqa: E402

SMALL = dict(moves_per_qc=60, n_agv=6)


def deterministic_cfg(policy: str) -> Config:
    """1 QC, 1 AGV, 1 yard block, 5 discharge moves, no randomness, no congestion."""
    return Config(
        n_qc=1, moves_per_qc=5, discharge_fraction=1.0, phase_pattern="discharge_first",
        qc_cycle_s=(100, 100, 100), qc_handover_s=10,
        n_blocks=1, quay_to_yard_m=150, route_factor=1.3,
        n_agv=1, agv_speed_mps=5, leg_overhead_s=20, travel_cv=0.0, congestion_alpha=0.0,
        asc_handover_s=(30, 30, 30), asc_store_s=(60, 60, 60), asc_retrieve_s=(60, 60, 60),
        policy=policy,
    )


@pytest.mark.parametrize("policy", POLICIES)
def test_hand_calculation(policy):
    """Hand calculation (see PROJECT_GUIDE.md, Phase 1):
    drive QC<->block: 1.3*150 m / 5 m/s + 20 s = 59 s.
    AGV cycle = 10 (hand-over) + 59 + 30 (ASC) + 59 = 158 s  > QC cycle 110 s -> AGV-bound.
    First hand-over starts at 59 s (AGV arrives; QC was ready at 50 s), then every 158 s.
    Last (5th) hand-over starts at 59 + 4*158 = 691 s, ends 701 s, QC returns: +50 -> 751 s."""
    term = Terminal(deterministic_cfg(policy))
    term.run()
    assert [j.t_handover for j in term.all_jobs] == pytest.approx([59, 217, 375, 533, 691])
    assert term.makespan == pytest.approx(751.0)


@pytest.mark.parametrize("policy", POLICIES)
def test_every_job_done_exactly_once_in_order(policy):
    term = Terminal(Config(policy=policy, **SMALL))
    res = term.run()
    assert res["jobs_done"] == term.cfg.total_moves
    for row in term.jobs_by_qc:
        times = [j.t_handover for j in row]
        assert all(t is not None for t in times)
        assert times == sorted(times), "QC must hand over its jobs in sequence"
        assert all(j.agv is not None and j.t_done is not None for j in row)


def test_no_deadlock_with_deep_commitment():
    res = simulate(Config(policy="auction", max_commit=3, lookahead=5, n_agv=3, moves_per_qc=40))
    assert res["jobs_done"] == 4 * 40


def test_common_random_numbers():
    """Same seed -> identical work plan, whatever the policy or fleet size."""
    a = build_workplan(Config(policy="fifo", n_agv=4, seed=7))
    b = build_workplan(Config(policy="auction", n_agv=20, seed=7))
    fa = [(j.block, j.qc_t1, j.asc_hand, j.noise_empty) for row in a for j in row]
    fb = [(j.block, j.qc_t1, j.asc_hand, j.noise_empty) for row in b for j in row]
    assert fa == fb


def test_reproducible():
    r1 = simulate(Config(seed=3, **SMALL))
    r2 = simulate(Config(seed=3, **SMALL))
    r1.pop("wall_time_s"), r2.pop("wall_time_s")
    for k in r1:
        if isinstance(r1[k], float) and math.isnan(r1[k]):
            assert math.isnan(r2[k])
        else:
            assert r1[k] == r2[k]


@pytest.mark.parametrize("policy", POLICIES)
def test_never_beats_the_crane_and_huge_fleet_reaches_it(policy):
    """QC productivity can never exceed the crane's own cycle; with a huge fleet, no
    congestion and a long release horizon the cranes should almost never wait.
    (max_commit=0 so the auction only uses idle AGVs - we are testing the model here,
    not the quality of a policy.)"""
    cfg = Config(policy=policy, n_agv=60, congestion_alpha=0.0, lookahead=6, max_commit=0)
    term = Terminal(cfg)
    res = term.run()
    crane_time = [sum(j.qc_t1 + j.qc_t2 + cfg.qc_handover_s for j in row) for row in term.jobs_by_qc]
    for q, f in enumerate(term.qc_finish):
        assert f >= crane_time[q] - 1e-6
    assert res["qc_wait_share"] < 0.01


def test_agv_time_shares_sum_to_one():
    res = simulate(Config(**SMALL))
    total = sum(res[k] for k in res if k.startswith("agv_"))
    assert total == pytest.approx(1.0, abs=1e-9)
    assert res["agv_idle"] >= 0


def test_more_agvs_do_not_hurt_much_without_congestion():
    """Sanity: with congestion off, going from 6 to 14 AGVs must raise productivity."""
    lo = simulate(Config(policy="nearest", n_agv=6, congestion_alpha=0.0, seed=2))
    hi = simulate(Config(policy="nearest", n_agv=14, congestion_alpha=0.0, seed=2))
    assert hi["qc_productivity"] > lo["qc_productivity"]


def test_risk_aware_auction_prefers_idle_agvs_when_fleet_is_large():
    """With many AGVs an idle one is almost always on time, so busy AGVs should rarely
    be given a second job (adaptive commitment). The basic auction does this a lot."""
    ra = simulate(Config(policy="auction_ra", n_agv=24))
    basic = simulate(Config(policy="auction", n_agv=24))
    assert ra["busy_assigned_share"] < 0.10
    assert basic["busy_assigned_share"] > 0.30


def test_choice_diagnostics_are_sane():
    res = simulate(Config(policy="nearest", **SMALL))
    assert res["options_per_decision"] >= 1.0
    assert 0.0 <= res["single_choice_share"] <= 1.0


def test_tuning_seeds_never_overlap_evaluation_seeds():
    from terminal_sim.experiments import TUNING_SEEDS
    assert set(TUNING_SEEDS).isdisjoint(range(1, 51))
