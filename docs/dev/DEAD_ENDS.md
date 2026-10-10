# Dead ends

> Выжимка. Полный текст с теми же номерами и заголовками: [archive/DEAD_ENDS.md](archive/DEAD_ENDS.md).

Rolled-back approaches and what they did. `tools/loop.py diagnose` skips a step whose name is listed here, so the loop does not rediscover `_fold_still` a third time.

First 36 entries are from PLAN.md section 5. The rest are written by `loop.py rollback`. English to match the code names.

`tip_contrast` was renamed `tip_extreme_contrast` on 2026-08-21 (NEXT.md 41). Entries keep the old name. Formula unchanged.

## Fold and the dividing line

- `_flatten_rim` (PLAN.md 1) Plateau along the contour. Lifted the author's thin outline to full opacity and drew a second bright facet down the whole silhouette.
- `_fold_still` (PLAN.md 2) High frequencies replaced by the cycle mean. The mean of a moving line is a smear: every fold it touched went soft and jitter rose from 0.19 to 1.15-1.74 px at 256.
- `anisotropic_smooth_along_fold` (PLAN.md 3) Direction estimated from the picture, so the estimate followed the jitter and smoothed the fold itself.
- `author_colour_mid_band` (PLAN.md 4) Substituting the author's frame into the middle band. That band is empty in the original.
- `_lerp_warp_blend` (PLAN.md 5) Mixing warped and unwarped gave a second ghost line inside.
- `_even_rim` (PLAN.md 6) Averaging along the rim. The line became continuous and faded almost to nothing: bright breaks lift the mean.
- `_even_rim_median` (PLAN.md 7) Median instead of mean. Level held, the border turned into a saw.

## Points

- `_tip_warp` (PLAN.md 8) Radial magnification around the point. Pulled the fold in but dragged the highlight past the apex, reading as a second, offset point.
- `_tip_boost` (PLAN.md 9) Local contrast at the point. There is no weak fold there, there is none at all, so raising contrast etched out what little existed.
- `_tip_pinch_flat` (PLAN.md 10) Pinch onto a flat edge colour. The core closed but left a smear where the inner line should be.
- `_tip_pinch_r7` (PLAN.md 11) Geometric wedge of radius 7 logical units, a quarter of the cursor. Ate half the glass and dissolved the dividing line. This is the one that read as deformed.
- `_tip_warp_outside_freeze` (PLAN.md 12) Sampling radius outside the frozen disc. Points beat against the cycle.

## Black slots

- `global_black_lift` (PLAN.md 13) Warm halo around every dark area.
- `relative_ink_suppression` (PLAN.md 14) Only lightens; the shape stays wrong. On the arrows it takes the fold off the top edge and flattens the glass.
- `_lift_blacks_mul` (PLAN.md 15) Multiplying RGB multiplies the channel difference too on near-black pixels: the slot came back as red and blue confetti.
- `_lift_blacks_linear` (PLAN.md 16) Linear lift to 0.55 of the author's floor. Bleached the top ridge, the glass turned to plastic.
- `top_hat_luma` (PLAN.md 17) The slot went, and saturated colours shifted hue: a purple cast along the fold on the yellow UpArrow.
- `morph_close_colour` (PLAN.md 18) Closing without protecting the rim ate the author's outline.
- `morph_close_guard_08` (PLAN.md 19) With a 0.8 unit rim guard the slot returned: it lies in the same 0.4-1.2 unit band as the outline.

## Bevel and the distance field

- `distance_min_filter` (PLAN.md 20) Step exactly 1 in eight directions. The field is octagonal and stepped, and its gradient draws diagonal hatching.
- `chamfer_reverse_bug` (PLAN.md 21) Backward pass read the row above. Horizontal banding.
- `bevel_no_mean_subtract` (PLAN.md 22) One-sided light raised the glass by a dozen levels.
- `bevel_smooth_box` (PLAN.md 23) Raising `_BEVEL_SMOOTH` under a box blur turned ripple into a coarser staircase, not into a line.

## Colour and sheen

- `sheen_gain_13` (PLAN.md 24) Per-channel multiply in linear light on saturated orange crushed the blacks and shifted the tone.
- `_detail_match` (PLAN.md 25) No effect at all: the `want <= have` condition held everywhere.
- `freeze_lines_following_contrast` (PLAN.md 26) Bought 0.4 levels of range and put the jitter back on the top ridge.

## Handwriting, frames 3-5

- `handwriting_geometric_bevel` (PLAN.md 27) The medial axis of the pen transition branches, dark ridges run down the barrel and read as scratches. Damaged the good frames next to them too.
- `handwriting_darkness_clamp` (PLAN.md 28) Cracks go, plate borders stay as grey facets, the sheet is still cracked.

## Tools and measurement

- `imagedraw_floodfill` (PLAN.md 29) Silently did nothing.
- `gaussianblur_mode_f` (PLAN.md 30) `GaussianBlur` does not accept mode `F`.
- `metrics_by_threshold_and_bbox` (PLAN.md 31) Measured their own edge anti-aliasing.
- `density_moving_region` (PLAN.md 32) The region being averaged over moved with the thing it was measuring.
- `_deltas_absolute_alpha` (PLAN.md 33) An absolute alpha 200 cut on glass peaking at 190 declared a live animation still.
- `morph_iou_vs_lanczos` (PLAN.md 34) Compared against a blurred Lanczos reference, which overlaps itself better than the real frames do.
- `flicker_false_alarm_sampling` (PLAN.md 35) Sampling frames 0, 4, 9, 13, 18, 22 hit different morph frames modulo a 27-frame cycle.
- `fold_points_alpha_08` (PLAN.md 36) Selecting fold rows by `alpha > 0.8 * max` cut out the interior itself. The measurement returned zeros on every cursor and the straightening had never worked at all until this was found.

## Shipped, then measured out (2026-08-07)

Were in the pipeline, not in a branch. The loop must not reach for them again.

- `_tip_pinch` Colour near every sharp corner taken to a flat edge colour. Closed the cross-section onto nothing: the seam beside Arrow's tail corners lifted from black to 69 while the lit core fell from 255 to 229, both sliding to the same flat value. Contrast on a background fell 0.325 to 0.207 and 0.347 to 0.267 at the two tail corners, and the point it was added for did not move at all. Same idea as `_tip_pinch_flat` (PLAN.md 10), shipped instead of rejected.
- `_straighten_fold` Fold warped onto a chord fitted per frame. Cost the point 0.367 to 0.266 of contrast, and was itself a source of the jitter it was aimed at, because the correction was refitted every frame: removing it moved fold smoothness on every interpolated cursor at once (Hand 1.141 to 0.962, Wait 1.215 to 1.047, AppStarting 1.241 to 1.091) and brought every fold about two logical units closer to its point. Mechanism of PLAN.md 3.
- `still_tip_r_6` The shading frozen to the cycle mean over six logical units around every sharp corner. Added at 4.0, widened to 6.0 to cover what `_tip_pinch` read its edge colour from, and left behind when the pinch went. At that radius the sweep did not reach the points at all: the cycle's swing two units from Wait's apex measured 0.07 luma levels against the author's 10.65, so the tips were dead while every smoothness metric read them as perfect - a still image is smooth. What it was bought for, the point beating as the sweep crosses the narrow wedge, turns out to be smaller than the author's own once measured (0.11 against 0.25 at the apex). Now 1.75, set by matching his swing rather than by eye, and guarded by `tip_sheen`.

## Written, measured, not shipped

- `_smooth_along_fold` Averaging the crease down its own length, along the chord's direction, with a corner exclusion. Not dead end 3: the direction comes from the outline, so it cannot chase the jitter, and it never moves the line. It works on what it aims at - section roughness falls below where it was before any of this (Arrow 98.8 to 41.7, UpArrow 71.9 to 64.4, Wait 70.7 to 58.7). It is off because it costs a few per cent of both things that were actually asked for, every time: Arrow_Down's point contrast 0.208 to 0.199, UpArrow's 0.157 to 0.149, Wait's sheen smoothness 1.047 to 1.165. Widening the exclusion to 7.5 logical units bought all of Arrow's contrast back and none of theirs. Left in hybrid.py, unwired, with the numbers: the trade is a decision, not a discovery.

## The red tip: three ways it cannot be fixed (2026-08-08)

Defect: the master's dark rim does not narrow with the wedge. Rim width 1.5/4 LU back from Wait's apex: author 0.20/1.10, master 0.90/1.20. Lit glass 0.20 of 1.48 LU, pushed to one flank. Brightest master pixel: 53 luma at 1.5 LU, 117 at 2, 151 at 3, 218 at 6. Alpha 190-205, shipped frame = master. The net painted the tip as ink, so there is no lit glass to move.

- `tip_relief_from_bevel` Flat edge colour plus the analytic bevel, in the pinch's place. The bevel is mean-removed over the whole mask, so near a thin wedge its rim term dominates and the point went darker still: contrast 0.207 to 0.183 on Arrow, 0.144 to 0.080 on UpArrow.
- `_taper_tip_rim` Fetch the colour from depth d*2 and place it at depth d, narrowing the rim while leaving the outline itself untouched (the displacement vanishes at the edge, so it cannot eat the author's own outline the way PLAN.md 18 and 19 did). It barely moved the rim - 1.12 to 1.08 at 2.5 units, nothing at 1.5 - because the whole wedge is dark there and the fetch lands on a medial axis that is itself inside the rim. Cost contrast anyway: 0.328 to 0.281.
- `_author_tip` The last 2.5 units of each point taken from the author's own colour, the way Handwriting's middle frames are. It does narrow the rim (0.90 to 0.56 at 1.5 units), and it costs 48 per cent of the point's contrast: 0.328 to 0.172 on Arrow, 0.208 to 0.123 on Arrow_Down. His colour is 32 pixels, and a point is the smallest feature in the drawing.

Вывод: only route left is analytic shading at the points, as `_SYNTH_BEVEL` does (tip_convergence 0.00), i.e. the stage 5 fork in PLAN.md: flatter glass, new look for the whole set.

## Re-running the upscale: measured, and it is not the fix (2026-08-08)

Both weights on the same input, section at the point vs the author:

- `RealESRGAN_x4plus_anime_6B` (what ships) sharpest step across the section 102 luma at 2.5 units back from Wait's apex.
- `RealESRGAN_x4plus` (general, num_block=23) the same structure, marginally softer: 79. Correlation with the author's own profile 0.64 against 0.63. It also carries the chroma noise this repo already rejected it for.

The bright ribbon is already in `src/ai` at 128px (32-to-128 upscale). Regenerating moves `traced.json` and every silhouette. Premise wrong: the author's native 32px has the same structure (y=5: 29, 112, 120, 66, 38, 23; 91-level step). The "smooth gradient" was a Lanczos stretch, invalid like `morph_iou_vs_lanczos` (PLAN.md 34). At his resolution the remaster is 5.3 luma off. The real defect is handled in `_match_author_at_tips`.

- `_match_author_at_tips` The author's level restored at the points as a low-frequency correction: his 32px frame minus ours downsampled to it, carried back up and applied inside a disc around each traced corner. By construction it cannot invent or soften detail, and frozen to frame 0 it costs nothing temporally. It works on what it aims at - the one-sided gap along the inner flank drops from 44 luma levels to 28 - and it improves four cursors' point contrast (Arrow_Down 0.208 to 0.250, UpArrow 0.157 to 0.192, Hand 0.108 to 0.182). It is off because of Wait, the cursor it was written for: matching the author there costs 44 per cent of the point's contrast, 0.170 to 0.095. Capping the correction at 10 levels keeps Wait at 0.146 but then the gap it exists to close only goes 44 to 40, which is nothing. There is no setting in between, because on Wait the two are one axis: his tip is darker than ours, so matching him is darkening, and darkening a tip is exactly what lowers its contrast on a dark background. That is a choice between faithful and crisp, not a defect with a fix, so it is the owner's to make and not a thing to ship quietly. Two collateral failures it caused on the way are worth keeping: fitted per frame it flickered (fold smoothness 0.974 to 1.009 on Wait), and applied to the synthetic-bevel cursors it subtracted their analytic relief, since there the render already is the author's colour (SizeNS point contrast 0.079 to 0.040, below the author's own).

Вывод: neither model nor the x4 pass is the problem.

## A hole in the gate, found by the above

- floor-only gate: `tip_contrast` and `tip_sheen` had no ceiling, and the baseline was only checked after a threshold miss, so Wait's -44% passed silently (0.095 clears the author's 0.066).

Вывод: both are now ratcheted against the baseline always, with 5% slack, verified by replaying 0.095.

## The line that slides right (2026-08-08)

- `_match_author_level` The author's levels restored across the whole glass, not just at the points: his 32px frame minus ours downsampled to it, capped at 12 levels, smoothed by 1.2 logical units on the way back up, frozen per cycle, skipped where the colour is already his. It fixes what it aims at - the shift's middle rows go from +0.62 to +0.21 on Hand and +0.47 to +0.31 on Arrow - and it improves the colour of every cursor it touches (Arrow's Delta-E 2.70 to 2.34, UpArrow's 3.84 to 2.99, Wait's 4.06 to 3.59) while leaving the points alone (Arrow 0.328 to 0.327, UpArrow 0.157 to 0.179). It is off for two reasons. Wait loses 16 per cent of its point contrast, which is the same unavoidable trade as everywhere else here: his tip is darker than ours. And the crease metrics regress on five cursors - fold curvature 0.21 to 1.95 on Wait, brightness step along the crease 3.5 to 10.2 on AppStarting. That second one could not be pinned down: the seam is 80 luma levels deep and the correction is 12, which cannot move a minimum that deep, and on frame 0 the curvature reads 0.11 to 0.23 rather than 1.95 - so the regression comes from frames and sizes where the tracker loses the seam, not from a line that bent. Repairing the tracker in order to clear a number that blocks a change of mine is not a thing to do, so the change stays off and the choice is the owner's.
- `_tip_beat` as a scalar. The drawn tip needs the frame's own beat carried in or
  goes dead; scalar pumps (temporal_fold 1.091).
- `want` read off the live frame. The drawn wedge's amplitude was taken from the
  live frame: pulses (temporal_fold 1.149).
- Lowering `_LEVEL_CAP` 8/5/3: colour (Arrow 2.83).
- Point above replaced colour: fades (UpArrow 0.112).
- Per-pixel clamp: tip leans right (5.63 vs 4.70).
- Smoothing tip base: jitter up (Hand 1.146).
- Whole `_draw_tip`: point brighter, bloom (Wait apex 56 vs 37).
- Raising `_LEVEL_CAP`: 32px grid limit (61 -> 58).
- Author's 32px apex as target: owner rejected (71 -> 37).
- Render-side tip lean: master defect (5 rejections).

Вывод: frame-fitted constants jitter; master defects only at upscale.

## Tempering `_match_author_level`, and `_LEVEL_CAP` as a tip knob (2026-08-12)

- Tempering `_match_author_level`: pays fold bill, corner 0.06 vs 6.15 levels; full strength restored.
- Raising `_LEVEL_CAP` for apex: blur `_LEVEL_SMOOTH` 4.5 LU > disc 1.5; at 36 Wait fails `tip_contrast`.
- Suspecting lateral reach, `_edge_shadow_declutter`: < 0.005; Hand: `taper_frac` + `_band_level` (0.121), UpArrow: trough -> step swap; both prices of accepted fixes.
- Isolating `taper_frac` via `taper` ~0: also scales `width`, `hw`; patch the one line.
- Apex failures as stale ratchet: real regression in `5a5f363` (`02363b2` gives 0.215), NEXT.md item 15.

Вывод: whole-glass corrections don't fix a point defect.

## The dark outline along the edge: three levers, all measured, all worse (2026-08-12)

- Lowering `_EDGE_SHADOW_D_LO` 0.7 -> 0.2: line gone, gate 14 -> 17 (Help `fold_gap` 0.375).
- Master unsharp `dark` 0.45 -> 0: gate 14 -> 28, folds dissolve; 0.45 is the setting.
- Regenerating upscale: moves `traced.json` and every silhouette (2026-08-08).

Вывод: line is in master (`src/ai512/cur__Arrow__0.png` darkest 1), no downstream fix; Wait's darkness is the author's, leave alone.

## `density_%`: three anchors for the alpha level, all worse (2026-08-12)

- Anchoring on solid pixels (`m > 250`): thin cursors worse (Cross 7.03%).
- Anchor fixed in LU at `_LEVEL_REF`: worse everywhere (worst 7.38%).
- Dropping the correction: `scale_drift` 0.172 > 0.10.

Вывод: settled 2026-08-20 - rim `cov^2` (NEXT.md 35) and absolute anchor vs author, 128 against 32 median (NEXT.md 37), not anchors.

## Wait's split apex: two more render-side attempts (2026-08-13)

- Trough back on sheen cursors: no change; UpArrow `fold_luma_step` 13->19
- Released `_fold_keepout`: no change, petals split along wedge
- Taper 2/5/9: seam static
- UpArrow `_tip_realign`: offset only 0.05 LU
- Refilled `src/ai512` margin: 2 levels apart
- Blend `_base128`: glow, blur
- Radial scale `_tip_advance`: rim shadow 43 levels
- Notch strip: `fold_luma_step` 10.97->25.37; positive cap, blurred diff: no change
- Normaliser solid-only: SizeAll 3.55->18.07; off: `scale_drift` 0.172 > 0.10

Вывод: UpArrow facet missing, borrow from Arrow_Down (`_apex_borrow`); `density_%` debt - deliberate trade.

## Медиана по дуге не отделяет полосу от складки, потому что полосы нет

- Медиана по дуге (`_rim_monotone`): изменено 0 пикселей, дипы срезаются вместе со складкой
- Глобальный радиальный профиль: глубина полосы разная на разных рёбрах
- Замер «68 из 280 монотонны»: монотонность после медианы против сырого профиля

Открыто: гребень на глубине ~1.0 на 188-221 против авторских ~150, рядом провал до 59.

Вывод: дипы на отдельных станциях, `_edge_shadow_declutter` оставлен (Arrow 76% против 82%).

## Спрямление рёбер: хорда не отличает пилу от дуги

- Отбор только по допуску хорды: вогнутые лучи надуваются, IoU Cross 0.8898 -> 0.8729
- Разрез Дугласа-Пекера: две хорды, каждая поверх своей половины дуги
- Знакопеременность от подогнанной прямой: TLS центрирует остатки, отвергнуто 0

Вывод: знакопеременность от хорды (`_balance`, `STRAIGHT_BALANCE = 0.4`); решает IoU 32 против `src/orig`, а не `edge_straight`.

## Симметрия: приколотый апекс и остриё, которое держит не силуэт

- Усреднение контура с отражениями (`trace.symmetrize`): `tip_contrast` SizeNS падает с 0.037 до 0.021 при поле 0.055.
- Приколоть апексы: глазом хуже обоих вариантов, остриё уезжает с оси, `tip_contrast` не восстанавливается.
- Ослабить притяжение: SizeNS теряет остриё монотонно, уже на 0.35 даёт 0.030 и не проходит. Порога, где симметрия бесплатна, нет.

Вывод: уходит не геометрия, а яркость (112.7 -> 119.3 при фоне 128), потому что тёмное ядро мастера не привязано к силуэту. Поэтому SizeNS и SizeWE меряются, но не правятся (`analyze.SYMMETRY` шире `trace.SYMMETRY`); у Cross и SizeAll остриё с притяжением растёт.

## Устаревший traced.json: фоновый прогон, который считался мёртвым

- Пустой `Get-Process python` как признак смерти фона: свип дописал файл позже, и `449ecbb` положил `traced.json` от `0.30` при `STRAIGHT_BALANCE = 0.4`. Разошлись 10 курсоров из 16.
- Проверка «байт-в-байт с коммитом»: сравнивала выход свипа с самим собой. `metrics-baseline.json` поверх него дал 4 ложные регрессии.

Вывод: воспроизводить `git show HEAD:trace.py > _tmp.py && python _tmp.py` и сравнивать с `HEAD:traced.json`, как CI, смотреть на выход, а не на дифф кода.

## Перенос формы кромки: три способа положить поправку обратно (2026-08-19)

- Рассыпать по своим лучам с нормировкой по весу: `rim_layers` Arrow 0.65 при базе 0.719, но на 512 остаются нетронутые пиксели, провалы Arrow_Down 458 -> 1184.
- То же с размытием числителя и знаменателя: 0.80, хуже базы, потому что размытие идёт и по глубине.
- Приколоть отсчёт на контуре к нулю: обрыв в 16 уровней у кромки, профиль опускается полосой, по краям два новых провала.

Вывод: живой способ - поле: глубина из `_edge_distance_at`, секция ближайшей станции, интерполяция только по глубине.

## Перенос формы вдоль складки не мирится с переносом поперёк кромки (2026-08-19)

- Перенос вдоль складки за тот же проход (потолок 18): `fold_gap` у UpArrow лучше, но у Arrow `fold_luma_step` 4.2 -> 15.9, `fold_jag` 53.9 -> 86.3, у Hand так же.
- Потолок 6 или 3: гасит обе стороны сразу.

Вывод: аналитика вдоль складки несёт свою амплитуду, и там, где мастер уже верен, любая её доля портит картинку; код выключен (`_FOLD_XFER = set()`).

## Ближайшая станция как способ чтения поправки (2026-08-19)

- Поправка от ближайшей станции: ячейки Вороного, на 512 плоские фасетки с прямыми швами, хуже всего у остриёв. `rim_layers` при этом лучше (Help 0.314 против 0.333), метрика фасеток не видит.
- Смесь станций у самой точки без гашения: нормали пересекаются, в острие печатается тёмный клин.

Вывод: смешивать станции с весом по дуге, у точки поправку гасить.

## Равномерный вынос трассированного контура наружу

- Вынос по нормали на `d=0.05`: `delta_e` лучше у 13 из 16, но IoU падает у четырёх (NO -0.022), гейт валится, потому что вдавливание неравномерное.
- Проверка на выборке Arrow/Help/NO/IBeam: выглядело бесплатным, полный прогон опроверг.

Вывод: убирать причину - порог `max(30, min(0.45*peak, 55))`, трассировать по уровню 0.5 (marching squares).

## Трассировка по уровню альфы вместо внутренних пикселей границы

- Снос всей цепочки на `alpha == thresh`: `CORNER_KEEP_DEG` настроен на лестницу и не ловит углы, Cross теряет луч (IoU 0.918 -> 0.480).
- Там же, где силуэт цел: тёмная шапка на апексе Arrow, хотя `rim_layers` вдвое лучше (Arrow_Down 0.745 -> 0.322).
- Снос только неугловых прогонов после классификации, с зоной покоя: IoU падает у 11 из 16 (-0.023), `rim_layers` вразнобой.

Вывод: выигрыш по `rim_layers` держался на скруглении углов; все три варианта закрыты (NEXT.md 28.2, 28.3).

## Перестройка граней поверх ободка кромки

- вариант `_facet_split` со статистикой по `ed > 0.35` поверх всей зоны острия: внутреннее стекло затирает ободок, `tip_contrast` Arrow 0.129 -> 0.083.
- Подбор перцентиля: не лечит.

Вывод: ободок этой стадии не отдавать (`_FACET_KEEP_RIM`, NEXT.md 30.3).

## Структурные грани на Arrow_Down и UpArrow

- Перцентиль 25/20/15 x keep 0/0.25/0.4 на Arrow_Down: лучший `tip_contrast` 0.0845 против авторского 0.0879.
- То же на UpArrow: `tip_contrast` 0.048 -> 0.041 при авторском 0.085.

Вывод: у этих двух дефект в самом ободке, а не в разделении поверхностей; на Arrow стадия работает (NEXT.md 30.3).

## `_tip_glass` before the size ladder: three placements, all worse (2026-08-20)

- Floor laid once at native, resampled: worse, 59.5% vs 50.9% at 0.15 units; apex 116.4 vs 133.3 at 32px.
- Canonical reference level, floor per size: worse, 52.9%; the per-size level is the rung's own, not drift.
- Inside `_up_alpha` before `_hold_coverage`: 50.6% vs 50.9%, but Arrow `scale_drift` 0.0034 -> 0.0072.
- Stage appended to `_up_alpha` tail: early return at `size == _LEVEL_REF` skips 128 (apex 54.8 vs 154.2).

Вывод: a floor filling a crisp mask belongs on the mask's grid; what varies along the ladder is coverage, and no alpha stage reaches it.

## Handwriting 3-6: три способа положить донорский цвет, два хуже (2026-08-21)

- Донор целиком вместо мастера: `delta_e` 3.55 -> 8.80, `fold_gap` 0.50 -> 4.38.
- Подгонка по четырём опорным точкам (`_landmarks`) вместо вторых моментов: `fold_gap` 3.75 против 1.50, код снят.
- Полоса отчуждения только для тёмной половины детали: `fold_wander` 0.93 против 0.20, светлая грань уводит гребень не хуже тёмной.
- Подмена цвета на мастере (512), а не на отгружаемом размере: `fold_wander` 0.33 против 0.20 даже без заимствования.

Вывод: работает разделение частот (низкие свои, высокие донорские, `delta_e` 3.82); подмена остаётся в `frame_image`, где её делал `_BROKEN_COLOUR`.

## Клин: гашение тела по поперечнику сечения (2026-08-21)

- модель `q = w/2r` с авторской `r`: закон уже соблюдают обе стороны, отличается только `r` (автор 1.32-1.34, у нас 1.0). Тело гасится до нашей кромки (121-128 при фоне 128), и остриё стирается: `tip_extreme_contrast` Arrow_Down 0.099 -> 0.039.

Вывод: сначала чинить уровень кромки, после этого механизм не нужен (NEXT.md 43, вариант E).

---

## `_LEVEL_SMOOTH` и `_LEVEL_CAP` не берут смещение уровня от переноса материала

- сузить `_LEVEL_SMOOTH` (4.5 -> 0.75) или поднять `_LEVEL_CAP` (12 -> 40): лестница плоская, dE[4] 4.57 -> 4.56. `_match_author_level` берёт разность от сырого мастера (`_master_rgb`), поэтому сдвиг от `_material_layer` в неё не попадает.

Вывод: адрес - перенос, а не стадия. Перенос починен (NEXT.md 48), `_LEVEL_SMOOTH`/`_LEVEL_CAP` не тронуты.

---

## Зонный temper: полная сила `_tip_relight` внутри его собственной полосы

- полная сила в зоне `along * lateral * mask`: внутреннее остриё смывается в заливку (тот же провал, что до `52f5e06`), `inner_tip` Arrow 0.750 -> 0.250, гейт FAIL (16). `s`/notch/rms при этом улучшаются.
- сужение по `taper_frac`: не помогает, внутреннее остриё дальше 5 LU.
- штатный `edge = 0.12`: смыв тот же, `s` 0.400. Смывают полномочия, а не ширина пандуса.

Вывод: к `temper = 1` по одному `t` не возвращаться. Открыто окно по `n` (зазор до гребня 3.1-3.5 LU) или модель с отдельной внутренней гранью, проверять парой: профиль + `--inner`.

---

## Изотропный низкочастотный фильтр как способ расширить складку

- вариант `_fold_broaden` (гауссово размытие 0.50 LU по полосе +-3 LU): `s` выходит авторским 0.600, но корпус размякает в градиент, грань складки пропадает, зарубка стёрта. `fold_notch` Arrow 1.218 -> 0.196 при пороге 0.40, гейт FAIL (4).

Вывод: разделение broad/structure работает, нужна направленная операция вдоль нормали и только у перехода, вне окрестности кадр не меняется. Кроп смотреть до таблиц.

## Насыщенность красного у NO по отдельности (2026-08-22)

- отдельный множитель цвета или покрытия кольца: ошибки гасят друг друга в композите, поэтому поодиночке хуже (цвет 7.653, покрытие 7.749 против 6.413 без правки). Вместе 5.768.

Вывод: alpha и цвет кольца ведёт один владелец (`_no_ring`), включаются атомарно.

## Складка и полоса на кромке: перенос радиального профиля закрыт полностью (2026-08-29)

- ветка (а), перенос вдоль излома `_fold_transfer`: общий потолок не подходит одновременно UpArrow (`fold_gap` 2.75 -> 0.50) и Arrow/Hand (`fold_step` 4.20 -> 15.9); код выключен, `_FOLD_XFER = set()` (NEXT.md 25)
- ветка (б), `_rim_transfer` на выходе `_master_raw` (`art/ai512`, `tools/ai512_xfer.py`): `rim_layers` хуже почти на всех кадрах, Help 0.644 -> 0.835, кромка толще, серый мазок у «?» (NEXT.md 58)

Вывод: `_rim_transfer` откалиброван под композит в конце пайплайна, поэтому постобработка закрыта; остаётся только вход Real-ESRGAN (`tools/upscale512.py`), это отдельный эпик и только по решению владельца.

## Заполнение поперечника у остриёв SizeAll не поднимает `tip_profile` до 0.9 (2026-08-30)

- кандидат 1, радиальный вес от угла (`_edge_distance_at`, `rim=1` в `_bevel_shading`): `tip_profile` 0.693 -> 0.819
- кандидат 2, вес по сечению `|q| <= h(s)`: у вершины `h(s) -> 0`, результат равен базе; с `|q| <= RIM_W` 0.756

Вывод: оба ниже 0.9, маршрут 2 закрыт (NEXT.md 59); менять форму затухания без смены модели `_bevel_shading` бесполезно.

## Затухание бевела у остриёв (маршрут 3) выравнивает перекос, опуская обе стороны (2026-08-30)

- затухание бевела у остриёв: перекос SizeNS 21.2 -> 2.4, но правильное остриё тоже темнеет, 140.2 -> 120.8 (у автора ~151); `tip_profile` SizeNS 0.97 -> 0.69, SizeAll 0.69 -> 0.50; `tip_extreme_contrast` SizeWE 0.106 -> 0.087

Вывод: маршрут 3 закрыт, код удалён; `SYM_PULL` в `trace.py` ждёт затенения острия по силуэту, и способа включить его нет.

## `_fold_restep` на NO: касательная грани цепляет соседний круг (2026-08-30)

- гипотеза «прибор занижает широкие переходы»: tanh через `foldfit.measure` расходится на 0.4%, причём в другую сторону
- restep без защиты: `fold_step` 0.439 -> 0.387 (порог 0.45); касательную загрязняет материал знака у конца хорды на кадрах 2-3, а не круг (`_ring_fit` None на кадрах 0-3)
- keep-out по цветности только по знаку автора: `fold_step` 0.438, зато `fold_notch` 0.875 -> 0.202, `fold_s_wide` 1.722 -> 2.778 и бусы на нашем контуре знака

Вывод: решено 2026-09-24 (NEXT.md 93): `_fold_profile_from_author` перед restep и keep-out по объединению знаков `_sign_owned`.

## Выключить `_fold_restep` ради зарубки: закрыт как регрессия (2026-09-01)

- выключить стадию (Hand): зарубка вернулась (0.302 -> 0.621), но с ней и пиксельная кромка AI-мастера: `fold_unres` 0.000 -> 0.200 при пороге 0.10.

Вывод: notch-долг - цена `_fold_restep`; не отключать стадию ни на одном курсоре без кандидата, который держит ширину; единственный адрес - notch-член внутри стадии, он открыт.

## Повторный `_fold_restep` после lightanim: закрыт на проверке идемпотентности (2026-08-30)

- второй `_fold_restep` на каноне без света: фит не держит собственный выход, `s` Hand 0.600 -> 0.900 (соседнее деление `S_GRID`).

Вывод: не повторять, пока фит `_fold_restep` не устойчив к повторному применению.

## Точечное исключение `(Handwriting, 5)` из `_edge_shadow_declutter` (2026-08-30)

- вариант `_EDGE_SHADOW_EXCEPT = {("Handwriting", 5)}`: `fold_curv` 2.000 -> 0.775, но `fold_s_conv` 1.600 -> 2.400, FAIL при пороге 1.6 (шаг `S_GRID` на 128).

Вывод: не пробовать без криволинейного `_fold_keepout` по форме черты (задевает `_edge_comb`, владелец отложил).

## Глобальный `_RESTEP_REACH=6.0` (2026-08-30)

- вариант `_RESTEP_REACH` 4.0 -> 6.0 глобально: Help `fold_unres` 0.190 -> 0.000, но три новых FAIL, в том числе `Handwriting fold_s_conv` 1.600 -> 1.846 при пороге 1.6.
- переснять baseline под регрессии: отклонено владельцем.
- вариант `_RESTEP_REACH` только для Help: не пробовался, вне контракта.

Вывод: Help и Handwriting[5] тянут один параметр в разные стороны; не возвращаться без пер-курсорной геометрии стадии.

## `_fold_restep` один раз после света, канон без restep (2026-08-30)

- канон без restep, свет, `_fold_restep` один раз (oracle): `AppStarting fold_s_conv` 6.044 при пороге 1.6; заодно Wait `fold_unres` 0.25 -> 0.30, контроль Hand `fold_s_conv` 1.00 -> 1.505.

Вывод: обе перестановки отклонены из-за дискретности `S_GRID`; остаток AppStarting/Wait не адресован, порядок стадий без нового кандидата не трогать.

## Полупрозрачная кромка пяти стрелок: срез, выравнивание полосы мастера, уровень по стороне (2026-09-19)

- срез юбки (G) по AI-альфе: убивает полупрозрачное лезвие, отклонён владельцем.
- выравнивание полосы мастера (R): переходы у углов рисуют наплывы (видно на 256).
- перерисовка после `_hold_coverage`: `scale_drift` 0.006 -> 0.160 до 96.
- полоса полной ширины до острия: `tip_sheen` AppStarting 31.1 -> 26.9 (FAIL); лечит `_BLADE_TAPER`.
- уровень по стороне (2/4 LU): лесенка 32px вернулась, `delta_e` Arrow 3.28 против 3.17.

Вывод: `_even_blade` на нативной карте; рост `delta_e` на 0.15..0.23 - цена ровной кромки.

## Рваная обводка на 48/64: box везде и отсечка Lanczos (2026-09-19)

Причина: Lanczos 512 -> 64 звенит на обводке в 2 px (`_master_rgb`), альфа совпадает (0.004). Принято: цвет мастера ниже `_MASTER_BOX_BELOW` (128) уменьшается по площади.

- Бисект стадий на Wait 64: ни одна не снижает ошибку кромки.
- Box на всех размерах: на 256 `tip_extreme_contrast` Arrow 0.222 -> 0.148, `fold_notch` NO 0.898 -> 0.348.
- Lanczos с отсечкой по диапазону исходника: кромка 4.94 -> 4.91, остриё Arrow 0.222 -> 0.170.
- Веса итоговой альфой вместо `m_a`: всего 0.05 к box.
- HAMMING 3.19 против box 3.08, BILINEAR/BICUBIC 4.01/4.30.

Вывод: отрезки - звон внутри диапазона цветов, а не выброс.

## Тёмная обводка на 32-96: сдвиг порога и нормировка поля (2026-09-20)

Причина: `_rim_transfer` проверяет луч в аппаратных пикселях, на 32 `keep.sum() < 8`, стадия молчит. Принято: поле на `_RIM_XFER_REF` (512), по площади ниже `_RIM_XFER_MIN` (128) у `_RIM_XFER_BORROW` - Arrow, Help, AppStarting.

- NO вместе со всеми: кадэнс морфа 0.2017 -> 0.2029 при храповике 0.2024.
- Порог 256: `fold_unres` NO 0.200 -> 0.333.
- Опора 256 вместо 512: AppStarting 64 4.65 против 3.61.
- Нормировка поля по уменьшенному покрытию: сдвиг 0.01.
- Выключить стадию ниже 128: 48-96 хуже.

## Пятна на тёмном ободке анимаций: темп по старому свету, KT4 (2026-09-23)

Причина: `lightanim._lit` гасит в 1 + dy/y раз, на тёмном ободке упор в `_DIM_FLOOR`. Принято: `_dim_ref`, y^0.25 * y_n^0.75 (`_DIM_SHARE` = 0.75), темп с тем же правилом; `fold_rms` AppStarting 42.99 -> 35.69. Храповик не пропускают:

- `tip_sheen` AppStarting 30.77 -> 29.05, Hand 32.74 -> 30.95 (-5.5% при допуске 5%). Размах в диске у острия включал мигание пятен. У автора 10.65, остаётся в 2.7 раза больше; застывшее остриё, от которого метрика стережёт, даёт 0.07.
- `inner_tip` Wait 0.167 -> 0.000 на 512. Провал на фазах 4-6 есть уже у HEAD: ключ рендера на фазе 5 держит разделитель на 12 станциях из 12, продукт - на 2-3. Разделитель заливает прибывающий свет (сложение размытого поля), Lγ меньше гасит тёмный разделитель и добивает до нуля. Глазами кадры HEAD и Lγ на фазе 5 не различаются. Это открытый дефект модели света, а не этой правки.
- `fold_unident` Hand 0.55 -> 0.65: максимум по 27 кадрам. На HEAD он от кадра к кадру ходит 0.25-0.55, шаг прибора 0.05, пики у Lγ на кадрах 11 и 14.

Закрыты:

- Темп по старому свету: `cadence` Wait 1.061 -> 1.141.
- KT4 вместе с Lγ: на углах до 20 уровней против 64-77, цена - шесть подмен стадий; не встроен.

## Чёрная шапка на остриё хвоста: ограничитель звона света (2026-09-23)

Причина: звон `periodic_at` через девять ключей, `_LIGHT_GAIN` 2.0 и `_DIM_FLOOR` делают пятно.

- Своё усиление уходящего света (0.725, 0.85): упор в пол, 10 -> 15.
- Поле в пределах двух ключей везде: живость AppStarting 0.857.
- Интерполяция в логарифме: живость AppStarting 0.884.
- Пол из ключей рендера: Hand `tip_sheen` -21%.
- Степень во всём диске: Hand `tip_sheen` 30.95 -> 26.98.
- Без усиления уходящего света в диске: `tip_sheen` Wait -14.7%.
- Степень по всему курсору: живость Hand 0.844; взята 2026-10-01 (NEXT.md 121).

Закрыто 2026-09-24 (NEXT.md 97): ограничитель в диске 1.0-1.75 LU (`_field_at`) + `_point_dim`, живость AppStarting 0.907.

## NO[5] `delta_e`: цвет, шаблоны кольца и перечёркивания, авторская альфа (2026-09-24)

Кадр 5 5.54 при цели 5.0 (NEXT.md 94); оракул с его альфой 3.88, с его цветом 2.91.

- Шаблон кольца на 4-6: кадр 5 6.00-6.67, у автора кольцо некруглое.
- Шаблон перечёркивания: кадр 5 5.59.
- Цвет знака `_RING_RGB` или по кадру: 5.38 и 5.30, chroma-match 5.40 (NEXT.md 70).
- Его альфа в зоне знака через Lanczos: 4.71, ореол на белом, отклонено глазами.

Вывод: не пробовать без нового мастера кадров 4-6 или некруглой модели знака.

## Разделитель Wait на фазах 4-8: доля приходящего света (2026-09-24)

Причина: приходящий свет размыт на 2.75 LU и добавляется целиком, уходящий берёт долю через `_dim_ref`; ободок оранжевый от `_LIGHT_GAIN` 2.0.

- Та же доля для приходящего света: живость Wait 0.69.
- Только тонкие тёмные линии: живость Wait 0.846.
- Свет по краям канона (направленный фильтр): `temporal_fold` AppStarting 1.238 при цели 1.16.

Вывод: со стороны модели света адреса нет; не пробовать без способа отделить линию от блика, который не шевелит складку.

## Стамеска на остриях: чем сводить ободок в точку (2026-09-24)

Принято `_point_converge` (NEXT.md 98): rho(r) = r + 2.5 (1 - r/8)^2.

- Радиальное rho = T r (`_BLADE_TAPER` = 3): углы сохраняются, вложенная вершина на 512 почти в 1 от точки.
- Отображение кадра вместе со светом: темп AppStarting 1.035 -> 1.136.
- R1 = 0.7 / sin(theta/2): 1.33-1.51, короче смыкания 2.0-2.75.
- R1 = 2.0: скачок по биссектрисе 23-46 уровней (UpArrow, Arrow_Down).
- Охват 5-6 LU: живость AppStarting 0.888-0.894 при пороге 0.9.

Вывод: двигать стекло, не свет; падение `tip_sheen` (AppStarting 29.05 -> 14.88) - не спад.

## Стамеска у семейства стрелок: чем отличить остриё (2026-09-24)

Принят порог угла на сглаженном контуре в 1.5 LU (NEXT.md 99): острия 50-75 градусов, плечи 87-90.

- Охрана по маске: ключ 6 Handwriting не чинит.
- Маска по всему отрезку чтения: ключ 6 без изменений, гнётся сама полоса.
- Диск не шире половины пути до соседнего угла: ключ 6 без изменений.
- Прямизна рёбер: у хороших остриёв 0.51-0.69, у плохих 0.56-1.59, не разделяет.
- Сводить только при скачке `tip_nest`: угол ключа 6 читает 112, но там складка.

Вывод: угол снимать близко к точке, на 3 LU вершина ключа 3 уже 61.

## Трещина у "?" Help: где кончается складка (2026-09-24)

- Порог силы края: режет станции у острия Arrow_Down, UpArrow, AppStarting (-4..-98 при медиане 250-620).
- Якорь на сильнейшей станции, обрыв на смене знака: на прогнанном кадре сильнейшей становится станция 89 на "?".
- Обрыв в обе стороны от якоря: на 128 Handwriting 1 теряет стадию почти на всей складке.
- Хорда Help до другой точки: `_fold_chord` читают foldfit, анализатор и трекер.

Вывод: держится прогон одного знака с наибольшей суммой |g|.

## Ровная полоса кромки: что не сработало (2026-09-25)

`_even_band` (NEXT.md 103).

- Без охраны выемки: двойные линии и штрихи; гашение у выемки 1-3 LU их снимает.
- Без охраны выпуклых углов: `tip_profile` Arrow_Down 1.966 -> 1.631.
- Зона острия из v8: `inner_tip` Arrow 0.417 при гейте 0.5.
- Окно среднего 1.0-2.0 LU: `inner_tip` 5/12, провал разделителя 15-36 -> 5-7.
- Вес линии только для тёмного контура (порог 10): серые не доходят; держит порог 4, потолок 10.
- Своя яркость со сглаживанием 0.5 LU: `delta_e` AppStarting 5.031 > 5.0.

Вывод: обёртку-кандидат сверять со свежим процессом (`tip_nest` Arrow 10.3 против 3.67).

## Пятнистые серые клинья: что не сработало (2026-09-25)

`_bevel_colour` (NEXT.md 104).

- Гладкая подгонка цвета по клину: на 256 `delta_e` IBeam 5.87.
- Остаток после фаски с нормалью фаски в базисе: 7 FAIL, `tip_profile` SizeNESW 0.742.
- Пятна у острых углов в базисе: `tip_profile` Cross 0.077.
- Подгонка карты альфы: заливает дырку SizeAll.
- Сигма вдоль дуги 2 LU: `delta_e` IBeam 5.44.
- Поле без дырки SizeAll: лучи у кольца волнистые.
- Вход выравнивания на 64-256 px: на 96-128 клинья крючками.

## Полоса кромки для Help и Handwriting (2026-09-25)

- Help: `fold_curv` 0.300 -> 0.975; причина в хорде, с хордой Arrow до крючка (NEXT.md 108) взята, 109.
- Handwriting: кадры морфа (`_MATERIAL_BASIS`) двоят линию у выемки, `fold_s_conv` 1.5 -> 7.2; на кадрах мастера взята, NEXT.md 112.

## Горб кромки Help: неполные варианты (2026-09-25)

К NEXT.md 108 взяты три шага вместе.

- Только ровное лезвие: горб у правого острия на 256 и 512 остаётся (`delta_e` +0.28).
- Контур Arrow со своей хордой Help: `fold_s_wide` 1.5 -> 4.17; фит неустойчив, складка в 1.5-2 LU от хорды.
- Хорда Arrow до выемки (19.5, 19.0): `_fold_restep` дорисовывает 72.6 уровня в "?".
- То же без прижатия контура: `inner_tip` 0.667 -> 0.417.

## Нитки у вершины NO (2026-09-26)

Кадры 0-3 NO (указатель Hand): тёмная полоса по верхней кромке, две нитки слева. Гейт по NO.

- вариант `_tip_relight` со ступенью Hand 0.5: `inner_tip` 0.667 -> 0.333; гасит разделитель клина.
- вариант `_even_band` на всех кадрах: цвет кольца на кромке указателя, красный штрих на кадре 10.
- вариант `_even_band` на кадрах 0-3: на 256 кадр 0 теряет разделитель, `inner_tip` 0.667 -> 0.500.

## Ободок под светом и кончик крыла (2026-10-01)

К NEXT.md 122.

- Шаг сохранения суммы в `_point_along` (ван Циттерт): бусины, `point along` 5.88-7.09 при цели 5.0.
- Зажим звона по цветности: двигал соседние пиксели до 68 уровней.
- Усиление 1 в полосе ободка вместо `_LIGHT_GAIN`: размах ободка на 32 ниже автора.
- Доля прихода света на всех размерах: живость AppStarting на 256 0.77 при цели 0.9.
- Доля прихода у самих остриёв (`_POINT_UNIT`, 1-1.75 LU): стороны уходили на 44 уровня под ключи.

Вывод: доля прихода только ниже 128, у остриёв 3-4.5 LU.
