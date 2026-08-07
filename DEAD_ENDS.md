# Dead ends

Approaches tried and rolled back, with what they actually did. Read before
trying anything: `tools/loop.py diagnose` skips a step whose name is already
here, which is the only thing stopping a run from spending its third iteration
rediscovering `_fold_still`.

The first 36 entries are the record from PLAN.md section 5, carried over so the
loop can see them. Everything after that is written by `loop.py rollback`.

Written in English to match the code these names live in.

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
