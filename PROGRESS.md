# Progress

One row per iteration. Every number is the worst over all sixteen cursors, so a row only improves when the weakest one does. `tip_contrast` is worst at its lowest; everything else is worst at its highest.

`reg` counts values that moved away from a target since the last committed baseline: that column has to stay at zero. `debt` counts values that miss a target but have not got worse - that is the column the work is for, and it starts at 84.

Targets: drift 0.10 logical units, gap and wander 0, delta_e 5, temporal 1.0. The full list is THRESHOLDS in tools/analyze.py, each with why it is that number.

| when | what changed | reg | debt | tip_contrast | tip_convergence | temporal_fold | inner_jitter | fold_gap | fold_wander | fold_jag | delta_e | scale_drift |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-07 | харнесс на месте, базовый замер | 0 | 84 | 0.073 | 4.800 | 1.241 | 0.321 | 2.375 | 3.606 | 206.267 | 8.970 | 0.597 |
| 2026-08-07 | убрал _tip_pinch и _straighten_fold, обе вредили острию и складке | 0 | 83 | 0.073 | 4.800 | 1.091 | 0.323 | 6.062 | 2.942 | 217.400 | 8.970 | 0.597 |
