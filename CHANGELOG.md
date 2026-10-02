# Changelog

## v1.0.0 — 2 October 2026 · Project A complete

### Model and code
| Change | Where | Why |
|---|---|---|
| New policy `auction_ra`: risk-aware **two-way** auction | `dispatch.py` (`RiskAwareAuctionDispatcher`) | The basic auction lost 1.5–3.3 moves/QC-h because it committed jobs to busy AGVs on over-confident predictions. Three fixes: the scarce side announces (free AGVs pick the closest job when jobs outnumber them); bids add a learned safety margin `z·σ`; busy AGVs may only pre-commit when on time and no idle AGV is. |
| Learned spread of arrival-prediction errors (EMA of squared error, separately for idle/busy AGVs) | `model.py` (`arrival_mse`, `arrival_sigma`) | Supplies σ for the risk margin; computed online from what the fleet observes, no oracle information. |
| `pred_busy` flag on every job | `workplan.py`, `model.py` | Needed to learn idle and busy errors separately and to measure how often busy AGVs win jobs. |
| New KPIs `options_per_decision`, `single_choice_share`, `busy_assigned_share` | `model.py`, `experiments.py` | Tests the explanation of the empty-travel peak at 14 AGVs (the dispatcher has no choice) and diagnoses over-commitment. All dispatchers now call `record_choice()`. |
| `risk_z` (2.5) and `adaptive_commit` (true) parameters; default policy is now `auction_ra` | `config.py`, `config/default.yaml` | Settings of the new policy, chosen by the tuning experiment below. |
| Tuning experiment on **separate seeds 101–110**, worst-case-regret criterion | `experiments.py` (`exp_tune`, `tuning_table`), `run.py tune` | Avoids tuning on the evaluation data (seeds 1–10). The criterion was fixed before running. |
| Ablation rewritten to switch on the new ingredients one at a time | `experiments.py` (`exp_ablation`) | Shows which part fixes which regime. |
| Sensitivity factor `asc_time_scale` (×0.8, 1.0, ×1.25) | `experiments.py` | ASC times were the least-sourced parameters; ×1.25 matches ~30 moves/h per stacking crane. |
| Paired comparison of the new auction vs nearest and the basic auction | `run.py compare` → `compare_paired_new_auction.csv` | The right test with common random numbers. |
| New figure `fig_fleet_choices.png`; consistent colours per policy across all figures; legend/label fixes | `plots.py` | Readability; the same policy always has the same colour. |
| One-click Windows runner | `run_all_windows.py` | Runs setup, tests, all experiments and the report tables from VS Code's Run button; logs to `results/laptop_run_log.txt`; moves old outputs to `results/_previous_runs/` instead of deleting them. |
| PowerShell setup script (alternative to the runner) | `scripts/setup.ps1` | Manual setup option. |
| Report | `report/report.tex`, `report/report.pdf`, `report/make_tables.py` | Tables are generated from the CSVs, so numbers in the report cannot drift from the results. |
| 3 new tests (23 total) | `tests/test_model.py` | New auction avoids busy AGVs when the fleet is large; choice diagnostics are sane; tuning and evaluation seeds never overlap. |

### Parameters
No default value changed. Sources were found and documented for QC cycle (Jordan 2002; Saanen et al. 2003),
AGV speed/acceleration (Saputra & Rijanto 2021), AGV positioning and stacking-crane productivity (Watson 2005),
and AGVs per crane (Saanen et al. 2003). The remaining assumptions are covered by the sensitivity analysis.

### Verification
* 23/23 tests pass on Linux and on Windows 11 (Python 3.13).
* The full experiment set gives the same summary tables on both machines.

## v0.1.0 — 2 October 2026 · baseline
SimPy model of quay cranes, AGVs and stacking cranes; FIFO, nearest-vehicle, central (Hungarian) and basic
auction policies; calibrated predictor; experiments for comparison, fleet sizing, sensitivity and ablation;
17 tests.
