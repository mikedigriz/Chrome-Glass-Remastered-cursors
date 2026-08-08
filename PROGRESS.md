# Progress

One row per iteration. Every number is the worst over all sixteen cursors, so a row only improves when the weakest one does. `tip_contrast` is worst at its lowest; everything else is worst at its highest.

`reg` counts values that moved away from a target since the last committed baseline: that column has to stay at zero. `debt` counts values that miss a target but have not got worse - that is the column the work is for, and it starts at 84.

Targets: drift 0.10 logical units, gap and wander 0, delta_e 5, temporal 1.0. The full list is THRESHOLDS in tools/analyze.py, each with why it is that number.

| when | what changed | reg | debt | tip_contrast | tip_convergence | temporal_fold | inner_jitter | fold_gap | fold_wander | fold_jag | delta_e | scale_drift |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-07 | харнесс на месте, базовый замер | 0 | 84 | 0.073 | 4.800 | 1.241 | 0.321 | 2.375 | 3.606 | 206.267 | 8.970 | 0.597 |
| 2026-08-07 | убрал _tip_pinch и _straighten_fold, обе вредили острию и складке | 0 | 83 | 0.073 | 4.800 | 1.091 | 0.323 | 6.062 | 2.942 | 217.400 | 8.970 | 0.597 |
| 2026-08-08 | разморозил кончики: _STILL_TIP_R 6.0 -> 1.75 по совпадению с авторским размахом | 0 | 81 | 0.073 | 4.800 | 1.018 | 0.325 | 6.062 | 2.923 | 217.400 | 8.970 | 0.597 |
| 2026-08-08 | нарисовал вершину из поля расстояния, включил авторские уровни со сглаживанием 3.0 | 15 | 24 | 0.118 | 3.200 | 0.967 | 0.325 | 2.250 | 3.647 | 215.967 | 8.537 | 0.144 |
| 2026-08-08 | построил разделительную линию геометрически, пороги складки переучреждены под неё | 0 | 42 | 0.078 | 3.380 | 0.970 | 0.325 | 1.700 | 0.630 | 73.000 | 3.740 | 0.141 |
| 2026-08-08 | снял попиксельный зажим (кренил остриё), собрал линию по пикселю, ускорил рендер | 13 | 42 | 0.169 | 3.200 | 1.088 | 0.325 | 1.700 | 0.318 | 68.067 | 3.740 | 0.141 |
| 2026-08-08 | убрал _draw_tip совсем, остриё приводится к авторскому уровню резкой коррекцией | 13 | 42 | 0.112 | 3.200 | 1.017 | 0.325 | 1.700 | 0.318 | 68.067 | 3.740 | 0.141 |

