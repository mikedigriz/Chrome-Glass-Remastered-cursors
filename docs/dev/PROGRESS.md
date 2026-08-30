# Progress

One row per iteration. Every number is the worst over all sixteen cursors, so a row only improves when the weakest one does. `tip_contrast` is worst at its lowest; everything else is worst at its highest.

`reg` counts values that moved away from a target since the last committed baseline: that column has to stay at zero. `debt` counts values that miss a target but have not got worse - that is the column the work is for, and it starts at 84.

Targets: drift 0.10 logical units, gap and wander 0, delta_e 5, temporal 1.0. The full list is THRESHOLDS in tools/analyze.py, each with why it is that number.

The table lapsed between 2026-08-15 and 2026-08-20 - the work of those days is committed and written up, but no rows were added for it. What it covers is NEXT.md 35 to 38: the coverage double count at the rim, the fold tracker, UpArrow's apex, the glass level anchored at the author's own resolution, and `_tip_glass` measured and left alone. The `debt` column therefore steps rather than slides across that gap.

It lapsed again between 2026-08-20 and 2026-08-30, for a different reason: the fold contract itself was rebuilt in that gap (NEXT.md 49). `fold_gap`/`fold_wander`/`fold_jag` stopped deciding pass/fail and became `legacy_fold_*`, replaced by `fold_unres`/`fold_s_thin`/`fold_s_conv`/`fold_curv`/`fold_step`/`fold_notch`/`fold_jitter` - a different measurement, not a number that fits these columns, so no row was forced into the old shape. `_fold_restep` shipped (51), NO's prohibition ring was redrawn (52-56), the fold debt was traced down to three separate roots plus one real regression on NO (61-63, closed 65-68), and `NO[5] delta_e` was localized with one rejected fix candidate (69-70). The 12 positions the debt now stands at, and what would reopen each one, are tracked in STATUS.md's debt table instead of here.

| when | what changed | reg | debt | tip_contrast | tip_convergence | temporal_fold | inner_jitter | fold_gap | fold_wander | fold_jag | delta_e | scale_drift |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-07 | харнесс на месте, базовый замер | 0 | 84 | 0.073 | 4.800 | 1.241 | 0.321 | 2.375 | 3.606 | 206.267 | 8.970 | 0.597 |
| 2026-08-07 | убрал _tip_pinch и _straighten_fold, обе вредили острию и складке | 0 | 83 | 0.073 | 4.800 | 1.091 | 0.323 | 6.062 | 2.942 | 217.400 | 8.970 | 0.597 |
| 2026-08-08 | разморозил кончики: _STILL_TIP_R 6.0 -> 1.75 по совпадению с авторским размахом | 0 | 81 | 0.073 | 4.800 | 1.018 | 0.325 | 6.062 | 2.923 | 217.400 | 8.970 | 0.597 |
| 2026-08-08 | нарисовал вершину из поля расстояния, включил авторские уровни со сглаживанием 3.0 | 15 | 24 | 0.118 | 3.200 | 0.967 | 0.325 | 2.250 | 3.647 | 215.967 | 8.537 | 0.144 |
| 2026-08-08 | построил разделительную линию геометрически, пороги складки переучреждены под неё | 0 | 42 | 0.078 | 3.380 | 0.970 | 0.325 | 1.700 | 0.630 | 73.000 | 3.740 | 0.141 |
| 2026-08-08 | снял попиксельный зажим (кренил остриё), собрал линию по пикселю, ускорил рендер | 13 | 42 | 0.169 | 3.200 | 1.088 | 0.325 | 1.700 | 0.318 | 68.067 | 3.740 | 0.141 |
| 2026-08-08 | убрал _draw_tip совсем, остриё приводится к авторскому уровню резкой коррекцией | 13 | 42 | 0.112 | 3.200 | 1.017 | 0.325 | 1.700 | 0.318 | 68.067 | 3.740 | 0.141 |
| 2026-08-08 | откат рендера к одобренной предрелизной версии, оставлены только харнесс и точное ускорение | - | - | 0.200 | - | 1.047 | - | - | - | - | - | - |
| 2026-08-12 | вернул `_match_author_level` на полную силу, temper разнесён по стадиям | 14 | 69 | 0.039 | 4.800 | 1.020 | 0.040 | 1.750 | 2.400 | 193.200 | 6.751 | 0.545 |
| 2026-08-12 | убрал пол в один пиксель у радиуса `_deburr` | 14 | 53 | 0.039 | 4.800 | 1.020 | 0.040 | 1.750 | 2.400 | 193.200 | 6.751 | 0.068 |

| 2026-08-14 | три метрики контура: rim_layers, edge_straight, mirror_asym, с селфтестами | 0 | 61 | 0.040 | 2.400 | 1.006 | 0.024 | 1.875 | 1.277 | 103.750 | 6.763 | 0.068 |
| 2026-08-14 | вернул поводок трекера складки по _FOLD_CAP рендера, починил контроль fold_jag | 0 | 61 | 0.040 | 2.400 | 1.006 | 0.024 | 1.875 | 1.277 | 103.750 | 6.763 | 0.068 |
| 2026-08-14 | совместил поле расстояний с отрисованным контуром, \|d\| на кромке 0.33 -> 0.017 | 0 | 61 | 0.040 | 2.400 | 1.006 | 0.024 | 1.875 | 1.336 | 103.750 | 6.759 | 0.068 |
| 2026-08-14 | знаковый ресемпл поля, нуль кромки ближе в 1.4 раза на всех ступенях | 0 | 61 | 0.040 | 2.400 | 1.006 | 0.024 | 1.875 | 1.336 | 103.750 | 6.759 | 0.068 |
| 2026-08-14 | пустил 512 в лестницу гейта: debt вырос не от рендера, а от того, что перестали не смотреть | 0 | 59 | 0.040 | 2.400 | 1.006 | 0.024 | 2.375 | 1.337 | 134.000 | 6.759 | 0.074 |
| 2026-08-15 | посадил вершины прямых рёбер на их же прямую, дуги оставил как нарисованы | 0 | 59 | 0.037 | 2.400 | 1.006 | 0.031 | 2.375 | 1.337 | 134.000 | 6.760 | 0.073 |
| 2026-08-15 | усреднил Cross, SizeAll и IBeam с их же отражениями; пересобрал устаревший traced.json | 0 | 59 | 0.037 | 2.400 | 1.006 | 0.031 | 2.375 | 0.602 | 134.000 | 6.759 | 0.074 |
| 2026-08-20 | привязал уровень стекла и сторож альфы к авторскому разрешению; строки за 08-15..08-20 не велись | 0 | 11 | 0.039 | 2.600 | 1.120 | 0.010 | 2.500 | 0.280 | 76.000 | 6.560 | 0.083 |
