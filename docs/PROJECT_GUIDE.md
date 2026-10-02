# Project A — Guide (status: complete, v1.0.0)

**Risk-aware AGV dispatching at an automated container terminal (discrete-event simulation)**

Owner: Anwesh Ajitabh Dash · Completed 2 October 2026 · Local copy: `D:\PROJECTS FOR CV\agv-terminal-sim`

---

## 1. The project in one paragraph

A vessel is worked by 4 quay cranes (QCs). Every container must pass between a crane and an automated guided
vehicle (AGV), and a crane cannot set a box down if no AGV is underneath. I modelled this system in Python
with SimPy, compared four dispatching policies (FIFO, nearest vehicle, a central Hungarian-assignment
controller and a Contract-Net auction), found why the auction fails at both small and large fleets, and
designed a **risk-aware two-way auction** that is as good as the best benchmark at every fleet size from 6 to 24
AGVs, without a central controller.

**Why it matters for TU Delft MME:** it sits in Theme 3 (Coordination & Logistics) of the Transport
Engineering & Logistics section: multi-machine interaction, discrete-event simulation, multi-agent control,
container terminals. It extends the peer-negotiation idea of my HVAC patent to machines that move.

---

## 2. How to run it

**On your laptop (Windows):** open `D:\PROJECTS FOR CV\agv-terminal-sim` in VS Code, open
`run_all_windows.py`, press ▷ *Run Python File*. It sets up `.venv`, runs the 23 tests and all experiments
(≈ 5 min) and writes `results/laptop_run_log.txt`.

**Individual commands** (after `.venv\Scripts\activate`):

```powershell
python -m pytest -q                       # 23 verification tests
python run.py single                      # one vessel call + Gantt chart
python run.py single --policy nearest --n-agv 8 --gantt-minutes 90
python run.py compare --reps 10           # 5 policies at 12 AGVs + paired tests
python run.py fleet --reps 10 --step 2    # fleet sweep 6..24 AGVs
python run.py sensitivity --reps 10       # one-factor-at-a-time
python run.py ablation --reps 10 --step 2 # which ingredients of the new auction matter
python run.py tune                        # choose risk_z / adaptive_commit on seeds 101-110
python run.py all --step 2                # everything
python report/make_tables.py              # LaTeX tables for the report
python run.py fleet --set quay_to_yard_m=250 lookahead=5 --out results/deep_yard
```

---

## 3. Code map (read in this order)

1. `config/default.yaml`, `terminal_sim/config.py` — every assumption.
2. `terminal_sim/layout.py` — distances and travel times.
3. `terminal_sim/workplan.py` — all randomness drawn before the run (common random numbers).
4. `terminal_sim/model.py` — QC, AGV and ASC processes; `predict()` (when can an AGV be at the crane?);
   online learning of prediction bias and spread; KPIs.
5. `terminal_sim/dispatch.py` — the five policies; `RiskAwareAuctionDispatcher` is the contribution.
6. `terminal_sim/experiments.py` — replications, 95 % CIs, paired differences, tuning, ablation, sensitivity.
7. `tests/test_model.py` — what "verified" means.

SimPy in three lines: a process is a Python generator; `yield env.timeout(t)` lets time pass; `yield event`
waits until something calls `event.succeed()`. A crane and its AGV meet through two events per job.

---

## 4. What was done (all phases complete)

| Phase | Done | Output |
|---|---|---|
| 0 Setup | project on `D:\PROJECTS FOR CV`, run in VS Code, 23 tests pass on Windows | `results/laptop_run_log.txt` |
| 1 Verify and justify | hand-calculated test case; parameter sources found (section 6) | tests, parameter table |
| 2 Baseline experiments | 4 policies, fleet sweep 6–24, three regimes explained, empty-travel peak explained by choice-set size | `fig_fleet_*`, `fig_compare.png` |
| 3 Contribution | diagnosed the basic auction (61–99 % of jobs to busy AGVs); designed and tuned the risk-aware two-way auction on separate seeds | `auction_ra`, `tuning_summary.csv`, `fig_ablation.png` |
| 4 Sensitivity | 6 factors incl. stacking-crane speed | `fig_sensitivity.png` |
| 5 Write-up | report, README, changelog | `report/report.pdf` |

---

## 5. Results checklist

| ID | Result | File | Status |
|---|---|---|---|
| F1 | Layout | `fig_layout.png` | done |
| F2 | Gantt chart, first hour | `fig_gantt_auction_ra_n12_s1.png` | done |
| F3 | QC productivity vs fleet size, 5 policies | `fig_fleet_productivity.png` | done |
| T1 | Smallest fleet for 90 % of crane capacity | `fleet_min_fleet.csv` | done: 12 AGVs (central: 14) |
| F4 | Empty travel vs fleet size | `fig_fleet_empty_travel.png` | done |
| F4b | Share of decisions with only one option | `fig_fleet_choices.png` | done |
| F5 | Comparison at 12 AGVs | `fig_compare.png`, `compare_summary.csv` | done |
| T2 | Paired differences | `compare_paired_*.csv`, report Table 4 | done |
| F6 | AGV time breakdown | `fig_agv_states.png` | done |
| F7 | Sensitivity | `fig_sensitivity.png` | done |
| F8 | Ablation of the new auction | `fig_ablation.png` | done |
| T3 | Tuning on seeds 101–110 | `tuning_summary.csv` | done |
| V1 | 23 tests incl. hand calculation | `tests/` | pass (Linux + Windows) |
| V2 | Validation vs published numbers | report §5 | done |

**Headline numbers (seeds 1–10, mean ± 95 % CI):**

| AGVs | Risk-aware auction | Nearest | Central | Basic auction | FIFO |
|---|---|---|---|---|---|
| 6 | **22.05** | 21.93 | 20.01 | 19.34 | 20.98 |
| 10 | 29.39 | **29.44** | 27.14 | 28.88 | 28.49 |
| 12 | 30.95 | 30.96 | 30.19 | **31.01** | 30.39 |
| 14 | **32.04** | 31.80 | 31.85 | 31.18 | 31.75 |
| 18 | 32.75 | 32.74 | **32.80** | 31.17 | 32.09 |
| 24 | 32.89 | 32.85 | **32.90** | 31.39 | 32.19 |

(QC productivity, moves per QC-hour; crane upper bound 33.8.) Paired with the same seeds, the risk-aware auction
is never significantly worse than any benchmark; at 14 AGVs it beats nearest vehicle by +0.23 ± 0.14 with 30 m
(13 %) less empty driving per move.

---

## 6. Parameter table with sources

| Parameter | Value | Source / argument |
|---|---|---|
| QCs per vessel | 4 | Gerrits, Mes & Schuur (2018) |
| QC cycle + hand-over | tri(70, 90, 130) s + 10 s → 33.8 moves/h | Jordan (Liftech, 2002): 72 s computed bay cycle, ≈ 100 s (36/h) with yard delays; 22–30 gross moves/h in NW Europe (Saanen, van Meel & Verbraeck, 2003); sensitivity ×0.8–1.2 |
| AGV speed | 5 m/s cruise | max 6 m/s straight, 3 m/s in bends, 2 m/s² (Saputra & Rijanto, 2021) |
| Overhead per leg | 20 s | acceleration/braking, two bends, positioning (10 s positioning in Watson, TBA 2005) |
| Route factor | 1.3 | one-way lane loops (assumption) |
| Quay-to-yard depth | 150 m | assumption; sensitivity 100–250 m |
| ASC transfer / store / retrieve | tri(20,30,45) / tri(40,60,90) / tri(40,60,90) s | ≈ 95 s per waterside move (≈ 38/h); single RMG incl. landside ≈ 30 moves/h (Watson 2005); sensitivity ×0.8–1.25 |
| Travel CV | 0.10 | assumption; sensitivity 0–0.3 |
| Congestion | BPR α 0.15, β 4, capacity 20 | standard BPR coefficients; sensitivity |
| Jobs released per QC | 3 | assumption; sensitivity 1–5 |
| AGVs per QC (check) | our knee 3–4 | 5.5 per QC in Saanen et al. (2003) — ours is lower: short yard, no landside work, simplified traffic |

---

## 7. Write-up kit

**Resume entry (Projects):**

*Risk-Aware AGV Dispatching for an Automated Container Terminal* | Python, SimPy, SciPy | Oct 2026
- Built a discrete-event simulation of an automated container terminal (4 quay cranes, 8 stacking cranes,
  6–24 AGVs) and benchmarked FIFO, nearest-vehicle, centralised Hungarian and Contract-Net auction dispatching
  over 3,800 simulated vessel calls with common random numbers and 95 % confidence intervals.
- Designed a risk-aware two-way auction (learned prediction-error margins, adaptive commitment) that matched or
  beat the best benchmark at every fleet size, beat nearest-vehicle by 0.23 moves/crane-hour with 13 % less empty
  travel at 14 AGVs, and sized the fleet at 12 AGVs for 90 % of crane capacity.

**SOP sentence (adapt):** "In my patented HVAC controller, zones negotiate with their neighbours instead of
waiting for a central computer. I wanted to know whether the same idea works for machines that move, so I built
a simulation of an automated container terminal in which AGVs bid for crane jobs. The plain auction failed in
exactly the situations where predictions were unreliable; once each vehicle learned how uncertain its own
estimates were, the decentralised fleet matched a central optimiser. Multi-Machine Engineering is where I want
to study this properly."

**Questions an interviewer may ask, and short answers:**
- *Why common random numbers?* Every policy sees the same containers and times, so paired differences isolate
  the policy effect and need far fewer replications.
- *How did you avoid tuning on the test data?* `risk_z` and adaptive commitment were chosen on seeds 101–110 with
  a criterion fixed beforehand (worst-case regret); results are reported on seeds 1–10.
- *Why does empty travel peak at 14 AGVs?* Supply ≈ demand, so half the decisions have one idle AGV and one job:
  no choice, no optimisation.
- *Biggest limitation?* No explicit lane network or collision avoidance; congestion is a BPR function.
- *What would you do next?* Explicit lane graph with deadlock avoidance, battery-aware bidding, and testing the
  protocol under communication delays and AGV failures — where decentralisation should pay off.

---

## 8. Ideas for extending it

1. Lane graph (networkx) with reservation-based traffic control instead of the BPR factor.
2. Battery state in the bid (energy-aware dispatching, cf. Xin, Negenborn & Lodewijks 2014).
3. Communication delays and AGV breakdowns: does the auction degrade more gracefully than the central controller?
4. Multi-load or lift-AGVs with buffer lanes at the crane (cf. Grunow et al. 2004).
5. Yard-block selection as a second decision (stacking policy).
