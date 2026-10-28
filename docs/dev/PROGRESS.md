# Progress

One row per iteration. Every number is the worst over all sixteen cursors, so a row only improves when the weakest one does. `tip_contrast` is worst at its lowest; everything else is worst at its highest.

`reg` counts values that moved away from a target since the last committed baseline: that column has to stay at zero. `debt` counts values that miss a target but have not got worse - that is the column the work is for, and it starts at 84.

Targets: drift 0.10 logical units, gap and wander 0, delta_e 5, temporal 1.0. The full list is THRESHOLDS in tools/analyze.py, each with why it is that number.

Строки до 2026-10-27 (старая цепочка) - в теге `chain-archive`.

| when | what changed | reg | debt | tip_contrast | tip_convergence | temporal_fold | inner_jitter | fold_gap | fold_wander | fold_jag | delta_e | scale_drift |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
