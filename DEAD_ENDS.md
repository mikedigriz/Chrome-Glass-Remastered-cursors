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

## Shipped, then measured out (2026-08-07)

Both of these were in the pipeline, not in a branch. They are here because the
loop has to know not to reach for them again.

- `_tip_pinch` Colour near every sharp corner taken to a flat edge colour. Closed the cross-section onto nothing: the seam beside Arrow's tail corners lifted from black to 69 while the lit core fell from 255 to 229, both sliding to the same flat value. Contrast on a background fell 0.325 to 0.207 and 0.347 to 0.267 at the two tail corners, and the point it was added for did not move at all. Same idea as `_tip_pinch_flat` (PLAN.md 10), shipped instead of rejected.
- `_straighten_fold` Fold warped onto a chord fitted per frame. Cost the point 0.367 to 0.266 of contrast, and was itself a source of the jitter it was aimed at, because the correction was refitted every frame: removing it moved fold smoothness on every interpolated cursor at once (Hand 1.141 to 0.962, Wait 1.215 to 1.047, AppStarting 1.241 to 1.091) and brought every fold about two logical units closer to its point. Mechanism of PLAN.md 3.
- `still_tip_r_6` The shading frozen to the cycle mean over six logical units around every sharp corner. Added at 4.0, widened to 6.0 to cover what `_tip_pinch` read its edge colour from, and left behind when the pinch went. At that radius the sweep did not reach the points at all: the cycle's swing two units from Wait's apex measured 0.07 luma levels against the author's 10.65, so the tips were dead while every smoothness metric read them as perfect - a still image is smooth. What it was bought for, the point beating as the sweep crosses the narrow wedge, turns out to be smaller than the author's own once measured (0.11 against 0.25 at the apex). Now 1.75, set by matching his swing rather than by eye, and guarded by `tip_sheen`.

## Written, measured, not shipped

- `_smooth_along_fold` Averaging the crease down its own length, along the chord's direction, with a corner exclusion. Not dead end 3: the direction comes from the outline, so it cannot chase the jitter, and it never moves the line. It works on what it aims at - section roughness falls below where it was before any of this (Arrow 98.8 to 41.7, UpArrow 71.9 to 64.4, Wait 70.7 to 58.7). It is off because it costs a few per cent of both things that were actually asked for, every time: Arrow_Down's point contrast 0.208 to 0.199, UpArrow's 0.157 to 0.149, Wait's sheen smoothness 1.047 to 1.165. Widening the exclusion to 7.5 logical units bought all of Arrow's contrast back and none of theirs. Left in hybrid.py, unwired, with the numbers: the trade is a decision, not a discovery.

## The red tip: three ways it cannot be fixed (2026-08-08)

The defect, measured across Wait's point: the master's dark rim does not narrow
as the wedge narrows. The author's rim is 0.20 logical units wide 1.5 units back
from the apex and 1.10 at four units back; the master's is 0.90 and 1.20 over
the same span. Four units back the two agree. At the point the master's rim is
four times too wide, leaving 0.20 units of lit glass out of 1.48 and pushing it
onto one flank - which is what reads as the orange stopping short and sitting
off to the right.

The reason nothing below worked is one number. The brightest pixel of the
section, read off the colour master before any of our stages, is 53 luma at 1.5
units back, 117 at two, 151 at three and 218 at six. Our alpha there is 190-205
and the shipped frame matches the master to the level. The net painted the tip
as ink. There is no lit glass at the point to move, sharpen or re-centre.

- `tip_relief_from_bevel` Flat edge colour plus the analytic bevel, in the pinch's place. The bevel is mean-removed over the whole mask, so near a thin wedge its rim term dominates and the point went darker still: contrast 0.207 to 0.183 on Arrow, 0.144 to 0.080 on UpArrow.
- `_taper_tip_rim` Fetch the colour from depth d*2 and place it at depth d, narrowing the rim while leaving the outline itself untouched (the displacement vanishes at the edge, so it cannot eat the author's own outline the way PLAN.md 18 and 19 did). It barely moved the rim - 1.12 to 1.08 at 2.5 units, nothing at 1.5 - because the whole wedge is dark there and the fetch lands on a medial axis that is itself inside the rim. Cost contrast anyway: 0.328 to 0.281.
- `_author_tip` The last 2.5 units of each point taken from the author's own colour, the way Handwriting's middle frames are. It does narrow the rim (0.90 to 0.56 at 1.5 units), and it costs 48 per cent of the point's contrast: 0.328 to 0.172 on Arrow, 0.208 to 0.123 on Arrow_Down. His colour is 32 pixels, and a point is the smallest feature in the drawing.

What is left is the route that already works elsewhere: draw the shading at the
points analytically, as `_SYNTH_BEVEL` does for the seven geometric cursors,
where tip_convergence measures 0.00. That is not a correction, it is the stage 5
fork in PLAN.md - flatter glass, and a change of look for the whole set.

## Re-running the upscale: measured, and it is not the fix (2026-08-08)

Both weights files were fetched and run against the same input, and the wedge's
section at the point compared with the author's:

- `RealESRGAN_x4plus_anime_6B` (what ships) sharpest step across the section 102 luma at 2.5 units back from Wait's apex.
- `RealESRGAN_x4plus` (general, num_block=23) the same structure, marginally softer: 79. Correlation with the author's own profile 0.64 against 0.63. It also carries the chroma noise this repo already rejected it for.

Neither model is the problem, and neither is the x4 pass: the bright ribbon is
already in `src/ai` at 128px, so it comes from the 32-to-128 upscale, and
regenerating that would move `traced.json` and every silhouette with it.

More to the point, the premise was wrong. The author's own native 32px art has
the same structure - at his y=5 the row reads 29, 112, 120, 66, 38, 23: a narrow
bright core with dark shoulders, and a 91-level step between two adjacent pixels.
The "smooth gradient" it was being compared against was his frame stretched with
Lanczos, which turns that step into a ramp. That comparison is invalid for the
same reason `morph_iou_vs_lanczos` (PLAN.md 34) was, and `orig_frame`'s own
docstring says so.

Judged at his resolution instead, the remaster sits 5.3 luma levels from him on
average - which is where the real defect turned out to be, and it is fixed in
`_match_author_at_tips` rather than in the upscale.

- `_match_author_at_tips` The author's level restored at the points as a low-frequency correction: his 32px frame minus ours downsampled to it, carried back up and applied inside a disc around each traced corner. By construction it cannot invent or soften detail, and frozen to frame 0 it costs nothing temporally. It works on what it aims at - the one-sided gap along the inner flank drops from 44 luma levels to 28 - and it improves four cursors' point contrast (Arrow_Down 0.208 to 0.250, UpArrow 0.157 to 0.192, Hand 0.108 to 0.182). It is off because of Wait, the cursor it was written for: matching the author there costs 44 per cent of the point's contrast, 0.170 to 0.095. Capping the correction at 10 levels keeps Wait at 0.146 but then the gap it exists to close only goes 44 to 40, which is nothing. There is no setting in between, because on Wait the two are one axis: his tip is darker than ours, so matching him is darkening, and darkening a tip is exactly what lowers its contrast on a dark background. That is a choice between faithful and crisp, not a defect with a fix, so it is the owner's to make and not a thing to ship quietly. Two collateral failures it caused on the way are worth keeping: fitted per frame it flickered (fold smoothness 0.974 to 1.009 on Wait), and applied to the synthetic-bevel cursors it subtracted their analytic relief, since there the render already is the author's colour (SizeNS point contrast 0.079 to 0.040, below the author's own).

## A hole in the gate, found by the above

`tip_contrast` and `tip_sheen` have a floor, not a ceiling, and every other
check here only consults the baseline once a value has already missed its
threshold. So Wait losing 44 per cent of its point contrast passed silently:
0.095 still clears the author's 0.066. Both are now ratcheted against the
baseline whatever they read, with five per cent of slack. Verified by replaying
the exact number the gate let through.

## The line that slides right (2026-08-08)

The complaint, and it is real: on Wait the dividing line runs from the upper
point downward and drifts right. Four measurements were tried before one held.
The dark seam's own path, the left edge of the lit region, and the seam's
position as a fraction of the wedge all gave different and mutually
contradictory numbers - the first because the tracked span was a third of the
line, the second because it caught the silhouette's edge, the third because the
tracker went bimodal again. None of them should have been trusted, and the first
of them was reported before it was checked.

What holds: the boundary of the lit sheet, read as a fraction of each row's
interior with the rim excluded, against the author's own at 32px. He puts it at
0.20, 0.17, 0.24, 0.25, 0.25, 0.28 going down from y=8 to y=13. The remaster has
it at 0.97, 0.99, 0.86, 0.72, 0.66, 0.38. The lit sheet is squeezed into a strip
along the top edge near the point and only opens out further down, and that is
the slant the eye reads as the line sliding right. Consistent on Arrow, Hand and
UpArrow, which share the silhouette.

- `_match_author_level` The author's levels restored across the whole glass, not just at the points: his 32px frame minus ours downsampled to it, capped at 12 levels, smoothed by 1.2 logical units on the way back up, frozen per cycle, skipped where the colour is already his. It fixes what it aims at - the shift's middle rows go from +0.62 to +0.21 on Hand and +0.47 to +0.31 on Arrow - and it improves the colour of every cursor it touches (Arrow's Delta-E 2.70 to 2.34, UpArrow's 3.84 to 2.99, Wait's 4.06 to 3.59) while leaving the points alone (Arrow 0.328 to 0.327, UpArrow 0.157 to 0.179). It is off for two reasons. Wait loses 16 per cent of its point contrast, which is the same unavoidable trade as everywhere else here: his tip is darker than ours. And the crease metrics regress on five cursors - fold curvature 0.21 to 1.95 on Wait, brightness step along the crease 3.5 to 10.2 on AppStarting. That second one could not be pinned down: the seam is 80 luma levels deep and the correction is 12, which cannot move a minimum that deep, and on frame 0 the curvature reads 0.11 to 0.23 rather than 1.95 - so the regression comes from frames and sizes where the tracker loses the seam, not from a line that bent. Repairing the tracker in order to clear a number that blocks a change of mine is not a thing to do, so the change stays off and the choice is the owner's.

**Now on.** The owner asked for the shifted line to be beaten and allowed the
drawing to be departed from where something has to be drawn in. Both objections
above were dealt with rather than waived. The point contrast is no longer traded:
`_draw_tip` builds the apex from the distance field, so Wait's tip does not
depend on the correction at all. The crease regression was the smoothing being
too short - the bilinear lattice from the author's 32 pixels still had a tail at
1.2 logical units for the tracker to walk. At 3.0 the curvature is back at
baseline everywhere and the brightness step is better than baseline on Help
(12.3 against 16.1) and UpArrow (7.8 against 10.0).

Two knobs were tried and rejected with numbers: lowering `_LEVEL_CAP` to 8, 5 or
3 does not touch the step and costs colour (Arrow 2.62 to 2.83), and skipping the
morphs makes them worse, not better (Handwriting 35.2 to 36.5, its Delta-E 6.39
to 6.63).

What is still paid: Handwriting's brightness step along the crease, 21 to 35.
Neither stage explains it alone - 21 with both off, 44 with the levels only, 36
with the drawn tip only - so it is their interaction, and no knob removes it.
Named as a regression, not filed as noise.

- `_tip_beat` as a scalar. The drawn tip needs the frame's own beat carried in or
it goes dead (the sweep's swing at the apex falls from the author's 10.6 levels
to 5.3). Carrying it as one average level for the whole disc makes the disc pump:
temporal_fold 1.027/1.053/1.091 on Wait, Hand and AppStarting against
0.972/1.016/0.990 with the tip left alone. Carried as the field it is, it costs
nothing.

- `want` read off the live frame. The drawn wedge's amplitude was taken from the
glass behind the point in the frame being rendered, which multiplies a shape that
never moves by a number that pulses: temporal_fold 1.149 on Wait against 0.972
untouched. Frozen to the cycle mean it reads 0.963, below baseline.

- Narrowing the whole band toward the point so the built divider reaches the
  apex. The colour of each sheet is sampled at the band's own edge, so a band
  squeezed into the narrow wedge samples the crease itself and smears its
  darkness across the glass as a dark whisker. Clamping the *sampling* distance
  alone, with the band, the crossover and the core left at full width, is the
  version that works - it is what removed the grey blot the far sample dragged
  in off the outer bevel.

- Wiping the leftover sculpted crease above where the rebuild starts, to kill
  the burr on the inner tip. The burr was never the leftover: it was the built
  straight line crossing the real crease where the real one bows outside a
  2.5-unit band. Widening the band to 4.0 removes it outright. The wipe stays in
  place because it does smooth the junction, but it is not what fixed this, and
  at 2, 4 and 7 units of smoothing the burr did not move at all.

- Allowing the drawn point to sit above the colour it replaces. Meant to keep
  the relief while cutting the bloom; measured, the allowance costs the point
  instead - UpArrow 0.170 at zero, 0.141 at ten levels, 0.112 at twenty. The
  clamp was never eating relief, it darkens the point, and a darker point reads
  harder against every background.

- Reading the fold metrics off a baseline recorded on a different size ladder.
  Not a code fault and not a render regression: --ratchet without --full records
  32/64/128/256 while --check --full measures 32..512, and scale_drift alone
  differs 0.1337 against 0.1409 between the two. It presents as every one of the
  sixteen cursors regressing by the same amount at once, which is the tell. The
  render is deterministic - two runs agree to the last digit.

- Clamping the drawn point per pixel so it can never sit above the colour it
  replaces. It was added against a white bloom at the apex, and it did hide it -
  but the bloom's real cause was the drawn disc's own edge landing across the
  point, which _DRAW_TIP_FEATHER at 3.0 fixed properly. Left in afterwards the
  clamp darkens whichever flank the drawn wedge is brighter on, and on an arrow
  that is always the left one, so the lit core at the tip slid from the author's
  4.70 to 5.63 - the tip visibly leaning right, which is exactly what the owner
  reported. Removing it reads 4.62 and doubles Wait's point contrast, 0.078 to
  0.169. Shaving only the top of the excess (98th percentile) keeps the bloom
  guard without the lean.

- Smoothing the drawn tip's base to fight the jitter that removing that clamp
  exposed. It goes the wrong way: Hand's fold jitter is 1.088 at no smoothing,
  1.141 at 0.6 and 1.146 at 1.2. The base is not what varies frame to frame.

- Freezing the peak-shave threshold over a sheen cycle. Measured first, and the
  measurement killed it: the threshold sits around 145 levels on Wait and 77 on
  Hand, high enough that the shave touches almost nothing, so its per-frame
  travel cannot be what moves the picture.

**Standing rule, learned three times over.** Any quantity fitted to the frame
being rendered becomes a jitter source, even when the picture looks unchanged:
`want` read off the live frame (temporal 1.149 against 0.972), `_tip_beat`
carried as one scalar for the disc (1.027/1.053/1.091 against 0.972/1.016/0.990),
and the fold offsets fitted per frame, which is what retired _straighten_fold in
the first place. Check any new constant for frame dependence before looking
anywhere else.

- **`_draw_tip`, the whole stage.** Shipped for a while and defended through four
  rounds of tuning because tip_contrast rose with it. It rose because the stage
  made the point *brighter* than its surroundings, and contrast against a
  background is what that metric measures - so the number went up while the eye
  saw a bloom, then a glint, then a tip that looked bent toward the bright spot.
  Every complaint about the points traced back to it.

  The measurement that should have been made first: what level does the point
  actually want? The author's own 32px frame puts Wait's apex at 14 and 24 luma
  on the two top rows. The master alone gives 49 and 48. With the tip drawn it
  reads 56 and 49 - brighter than the uncorrected master, i.e. the stage was
  fighting the level correction rather than helping it. Removing it leaves 37
  and 36, and the jitter that had been traded against tip sharpness (Hand 1.088)
  comes back on its own to 1.017.

  Lesson worth more than the stage: when a metric rewards a change the eye keeps
  rejecting, check what the metric is made of before defending the change again.

- Raising `_LEVEL_CAP` to reach the tip. The cap was never the limit: 12 to 90
  moves Wait's apex from 61 to 58. Nor is the smoothing of the sharp term (0.5
  to 0.05 moves 37 to 36), nor the coverage gates, which pass at 0.35..0.79
  there. What is left is the resolution of the reference itself - the correction
  is fitted on the author's 32px grid and cannot be sharper than one of his
  pixels.

- **Treating the author's 32px tip level as a target.** His apex reads 14 luma
  where the remaster reads 71, and three separate stages were built to close
  that gap - a drawn tip, a no-brighten clamp, a sharp local level match. Each
  one lowered the number (71 to 56 to 37) and each one was rejected on sight by
  the owner, who had already called the un-corrected 71 version "almost
  perfect". At sixteen times the scale a dark apex in his art is a shortage of
  pixels, not a decision to reproduce. His frames stay the reference for
  position and shape; they are not a reference for the level at a point.

- **The whole line of render-side fixes for the red cursor's tip lean.** Five
  rounds, five rejections. Every one had a mechanism and numbers behind it and
  every one made something else worse in the eye. The lean is in the master -
  the upscale sculpts the apex - and correcting a master defect by painting over
  it downstream has now failed enough times to count as settled. If it is worth
  another attempt, it is at the upscale, not in hybrid.py.

## Tempering `_match_author_level`, and `_LEVEL_CAP` as a tip knob (2026-08-12)

- **Tempering `_match_author_level` along with the other two.** The three stages
  were halved together because they were isolated together, not because they
  cost the same. Measured separately: at 1.0 this one takes the wedges from
  sixteen gate failures to fourteen (`fold_jag` leaves Arrow/Hand/Arrow_Down,
  AppStarting's `fold_luma_step` 9.03 -> 6.63), and it moves the tail corner the
  owner reported by 0.06 and 0.07 levels on average - against the 6.15 levels
  tempering all three bought back there. It was paying the fold's bill for a
  corner it does not touch. Reverted to full strength; `relight` and `sat` stay
  at 0.5, they are the two that actually reach the corner.

- **`_LEVEL_CAP` as a way to reach the apex.** The apex sits 30-odd levels
  brighter than the author's and the cap is 12, so raising it looks like the
  obvious lever. It is not: the correction is blurred over `_LEVEL_SMOOTH` (4.5
  logical units) and the measured disc is 1.5, so what lands at the apex is its
  neighbours, not the apex. 12 -> 24 -> 36 pulls UpArrow up (0.049, 0.054,
  0.057) and pushes Hand down the whole way (0.062, 0.053, 0.045), and at 36 it
  opens a new `tip_contrast` failure on Wait. Whole-glass corrections cannot
  address a point defect. (It is a real point defect all the same - see the
  correction below.)

- **`_tip_relight`'s lateral confinement, its `taper_frac`, and
  `_edge_shadow_declutter` as suspects for the apex contrast.** All three were
  introduced in the same commit as the temper and all three were checked by
  isolation. Lateral reach to infinity and `_edge_shadow_declutter` off each
  move `tip_contrast` by less than 0.005 on every wedge; `taper` 5.0 -> 0 gets
  Hand from 0.062 to 0.086 and UpArrow not at all. Swapping the whole of the old
  `_tip_relight` back in reaches 0.120 and 0.099. Resolved: on Hand it is
  `taper_frac` and the `_band_level` anchor together (0.062 -> 0.086 -> 0.121
  reverting them one line at a time); on UpArrow it is none of the three - it is
  the trough -> step parameter swap that came with the crack fix, and raising
  the step's `diff` from 18 to 55 does not move it at all. Both causes are the
  price of another accepted fix, so there is no free recovery here.

  Method note: reverting `taper_frac` by setting `taper` near zero measures the
  wrong thing - `taper_frac` also scales `width` and `hw`, so the constant
  changes three places at once. Patch the one line.

- **Reading the apex `tip_contrast` failures as a stale ratchet.** They are not.
  `hybrid.py` from `02363b2` reproduces the recorded baseline exactly
  (0.215 / 0.165 / 0.220 / 0.061), so the drop is a real regression in
  `5a5f363`, and restoring it is not the rejected "match the author's dark
  apex" direction - the old values sit well above his. See NEXT.md item 15.

## The dark outline along the edge: three levers, all measured, all worse (2026-08-12)

Owner report: a dark line like an outline, a couple of millimetres thick, most
visible at large sizes. Real and localised - it sits 0.68 logical units in from
the traced edge, 0.2..0.8 units wide, down to 22..29 luma composited on grey.

**It is in the master, not in `hybrid.py`.** `src/ai512/cur__Arrow__0.png` reads
a darkest pixel of 1 with 0.42% of the cursor below 70 luma, before any stage in
this file runs; the shipped 512 render reads 22 and 0.50%. The pipeline lightens
it slightly. It shows only at large sizes because downsampling to 32 averages the
halo away - at 32 we read a darkest pixel of 100 against the author's 106, and
neither has anything below 70. Wait is the exception and must be left alone: its
darkness is the author's own (29 against his 29, 7.8% against his 7.4%).

- **`_EDGE_SHADOW_D_LO` 0.7 -> 0.2.** Removes the line nearly completely (Arrow
  342 dark pixels -> 0, Hand 102 -> 0). Gate 14 -> 16..17: Help picks up a
  `tip_contrast` failure of its own (0.159 -> 0.125) and its engraved groove
  opens (`fold_gap` 0.125 -> 0.375), AppStarting's `fold_luma_step` doubles,
  Hand's `fold_jag` 45 -> 69. The 0.7 floor is what keeps the max filter off the
  edge; the line sitting at 0.68 is a two-hundredth of a unit outside the band
  written to remove it, and closing that gap costs the band's whole purpose.
- **The master unsharp's `dark` 0.45 -> 0.** Shaves about a third (Arrow darkest
  22 -> 31, share 0.50% -> 0.32%) and nothing at 0.25. Gate 14 -> **28**: Help's
  `fold_gap` 0.125 -> 4.750, Handwriting's `fold_luma_step` 5.3 -> 18.2, Wait
  gains `jitter_unmeasured`. The darkening half of the overshoot is what holds
  every fold line and engraved detail together - attenuating it dissolves the
  drawing. This is the same knob the `_master_raw` call already sets to 0.45 on
  purpose; 0.45 is not a leftover, it is the setting.
- **Regenerating the upscale.** Already settled above (2026-08-08): both weight
  files give the same structure, the artefact enters at the 32-to-128 stage, and
  redoing that moves `traced.json` and every silhouette with it.

Left alone. Every downstream lever pays more in fold and engraving than it buys
at the edge, which is the same conclusion this file already reached for the tip
lean - a master defect does not have a downstream fix.

## `density_%`: three anchors for the alpha level, all worse (2026-08-12)

The standing block nobody had touched - sixteen cursors of sixteen over the 2.0
tolerance, worst Cross 6.16%. Diagnosed, not fixed.

**The drift is made by the correction, not by the alpha.** Measured over the
metric's own region, `_up_alpha_raw` is already scale-consistent: Arrow 0.10%,
SizeNESW 0.57%, IBeam 0.66%, Cross 1.47%, all inside tolerance. The scalar level
correction in `_up_alpha` takes Arrow from 0.10% to 2.50%. It holds the
mask-weighted mean, and the mask's soft edge carries a share of that mean that
collapses with size - a large fraction at 32, a sliver at 384 - so holding the
whole-mask mean forces the interior up at the small end.

- **Anchoring on solid pixels (`m > 250`) instead of the whole mask.** Helps the
  thick cursors (Arrow 2.50% -> 1.20%, Help 2.29% -> 1.55%) and hurts the thin
  ones (SizeNESW 3.20% -> 5.36%, Cross 6.16% -> 7.03%), because at 32px the
  threshold only picks a thin cursor's brightest core - the anchor region itself
  becomes size-dependent. This is the trap `_density_points` documents, walked
  into from the other side.
- **Anchoring on a region fixed once in logical units at `_LEVEL_REF`.** Worse
  everywhere: worst 6.16% -> 7.38%, every cursor up.
- **Dropping the correction altogether.** Density worst 6.16% -> 3.91%, still
  over tolerance, and `scale_drift` worst 0.068 -> 0.172, through its own 0.10
  threshold. So the correction is still earning its keep on coverage even after
  the `_deburr` fix removed the other source.

The two metrics are one axis under a scalar: coverage is held by moving the
level, and moving the level is what density measures. Per rule 7 in NEXT.md a
scalar cannot fix a distribution - if this is worth another pass it needs a
per-pixel correction in the manner of `_THIN_LEAN`, not another anchor.

## Wait's split apex: two more render-side attempts (2026-08-13)

NEXT.md item 7 settles this as a master defect - the network invented a crease
at an apex where the author's own 32px art has one smooth peak. Two levers that
did not exist when that entry was written were tried against it, and neither
touches it.

- **Putting the three sheen cursors back on the trough.** `_TROUGH_PARAMS` was
  written to flatten this band ("they carry no fold here at all"), and
  `5a5f363` swapped them to a `diff` step that paints one, so restoring the
  trough looked like the obvious undo. Rendered side by side at 512 on grey, the
  bright sliver and the dark band beside it are identical under both. It also
  costs UpArrow's fold badly (`fold_luma_step` 13 -> 19, `fold_jag` 78 -> 98).

- **Releasing `_fold_keepout` near the apex so `_edge_shadow_declutter` can
  reach the crack.** Principled on paper: the keepout holds the max filter off
  ±0.8 units around the chord, the crack sits there, and per NEXT.md item 1 the
  three sheen cursors carry no real fold near the apex to protect. Ramping the
  keepout in from t=0 over t=0.25 and t=0.45 changes the render by nothing the
  eye can find.

  The measurement says why. Cross-sections at t=0.10/0.15/0.20 read one
  continuous bright core (91..147 luma) flanked by darker facets on both sides -
  there is no narrow dark line *across* the wedge for a max filter to bridge.
  The two "petals" are separated along the wedge, not across it, and
  `_edge_shadow_declutter` is keyed to distance from the outline, so it cannot
  address that shape at all.

- **`taper` as the seam between the painted apex facet and the master's body.**
  Third attempt at Wait's split, from the cross-section finding that the two
  petals are divided along the wedge rather than across it: `_tip_relight` ramps
  in over `taper` logical units from the point, so a mismatch where its
  influence ends would read as exactly that seam, and the boundary would then
  move with the constant. Rendered at taper 2.0, 5.0 and 9.0 the bright sliver
  and the dark band beside it do not move at all. The division is in the master,
  as item 7 says; three render-side levers have now missed it.

- **`_tip_realign` (2026-08-13), a fourth lever, on UpArrow rather than Wait.**
  `_tip_realign` (NEXT.md 23.5) fixes a *lateral offset* - the master's fold
  runs parallel to the chord, shifted sideways, and sliding it back onto the
  chord before `_tip_relight` reads it removes the ghost second line on
  Arrow/Hand/Arrow_Down/Wait/AppStarting. UpArrow was measured at only 0.05
  units of that offset - next to nothing - and stayed a closed loop after the
  fix. Cross-sections at t=0.12/0.16 explain why: 113, 42, 194, 149, 20, 88 -
  a genuine bright core with dark flanks on *both* sides, the same "two
  petals" shape as Wait's, not a single line sitting in the wrong place.
  Sliding a shape sideways cannot fix a shape that is wrong to begin with.
  Same root cause as this entry, same verdict: baked into `src/ai512`, out of
  render code's reach.

- **Regenerating `src/ai512` with a different fill of the transparent zone
  (2026-08-13), to un-flatten UpArrow's apex.** The best remaining theory after
  four render-side misses: `upscale_lib.bleed_extend` inpaints the transparent
  margin with TELEA before the RGB-only net sees it, and a soft inpainted
  gradient wrapped around a sharp point is exactly the thing that would make a
  network round it off. Reran the 128 -> 512 pass on UpArrow's own base three
  ways: the shipped TELEA inpaint, a nearest-visible-pixel clamp (so the
  wedge's own colour runs straight past its point instead of dissolving into an
  average of both flanks), and no fill at all.

  All three come out the same. Cross-section maxima down the chord, stations
  0.25..2.5 logical units from the point: TELEA `112 113 114 115 117 118 120
  121 235`, nearest `113 114 115 116 117 118 120 121 237`, raw `116 116 118 118
  120 121 122 122 238`. Two levels apart, same flat slab, same cliff. Side by
  side at 5x the three crops are indistinguishable. It is how the net reads
  this wedge, not what surrounds it - and the same net, fed Arrow_Down's
  near-identical 128 base (`110 111 113 116 114 150 153 210`), keeps the ramp
  (`107 108 109 113 140 190 216`). Only the hue differs between them.

- **Blending the 128px base back into the master around the point
  (2026-08-13).** The ramp the net dropped is still in its own input, so
  reading the master back toward `_base128` in a disc around the traced point
  looked like recovering data rather than inventing it - and near the point the
  master is a flat slab, so there is no network detail to lose. It does restore
  the ramp on paper (`144 150 146 172 193 199 204` against `146 145 144 203`),
  and it looks worse: the 128 base upsampled is soft, and what arrives is the
  lit facet dissolving into a glow around the point instead of converging. Blur
  is on the owner's own reject list. `_tip_advance` (NEXT.md 23.6) reaches the
  same station by resampling the master's own pixels, which keeps the edge.

- **Scaling the master about the traced point to advance the lit facet
  (`_tip_advance`, 2026-08-13).** The fifth lever on UpArrow, and the one whose
  geometry was actually right: the wedge is a cone with its apex on the traced
  point, so a radial scale about that point maps each flank onto itself and
  moves only what lies along the axis. It does what it says - the facet's step
  goes from 2.25 logical units to 1.67, where the healthy wedges start theirs,
  the profile takes the right shape, and no other cursor changes by a level.

  It also drags the master's dark rim in with the facet. A radial contraction
  compresses tangentially by the same factor, so the rim arrives at the point
  narrower, denser and darker, sitting on both flanks of the lit facet as a
  hard shadow that was not there before (max darkening 43 levels; on a signed
  difference map the red line hugs the blue region on both sides). The owner
  saw it on the first crop. Same trade as `_draw_tip` and
  `_match_author_at_tips`: one defect removed, another drawn.

  `tip_contrast` objected too (0.049 -> 0.032 against a 0.046 floor, and
  1.15/1.20/1.25 give 0.041/0.040/0.045, so no factor clears it), but that is
  not what decided it - the shadow is.

- **Three narrower shapes for the tail notch (2026-08-13).** All three were
  tried before `_notch_from_author` settled on a plain deviation cap over a
  disc, and each looked like it should cost less.

  *A keep-out strip along the chord* - cap the deviation only where the crease
  has already left the chord, so the part the fold tracker reads is untouched.
  It does keep every tracker row (Wait `fold_gap` stays 0.875, AppStarting keeps
  its size), and the hook is still plainly there on the crop: it starts inside
  the strip, at s = -0.20 by t = 0.93, and only reaches -0.90 by t = 0.97.
  Worse, correcting right up against a protected strip puts a step at the
  boundary - AppStarting `fold_luma_step` 10.97 -> 25.37, UpArrow 30.3 -> 46.1.

  *Capping only the positive deviation* - the thing the eye picks out first is
  a bright rim curling along the top edge of the tail spike, so pull down only
  what the render made brighter than the author. It changes almost nothing: at
  cap 25 every fold number is the baseline to three decimals except UpArrow's
  jag, and the crop still has the curl. The rim is within 25 levels of his own
  paint - it is not a level error, it is an edge in the wrong place.

  *Adding back the difference blurred at 0.7-1.0 logical units* - move the
  local mean toward the author while leaving every high frequency the render
  has, so the crease keeps its gradient and only its position shifts. A
  displaced edge makes a dipole in the difference, and a blur that wide cancels
  it: at sigma 1.0 / cap 25 nothing moves at all, at 0.7 / 10 the numbers move
  a little and the crop is unchanged.

- Two ways of re-weighting `_up_alpha`'s level normaliser (2026-08-13), both
  aimed at `density_%`, which misses its 2.0 target on all sixteen cursors.
  Printing the ladder makes it one defect rather than sixteen: 32 sits +1.7 to
  +4.7 per cent above the cursor's own mean and 64 upward is a gentle 1 per cent
  decline. The normaliser holds the *mask-weighted* mean equal across the ladder
  and the mask's antialiased rim is one device pixel wide - a whole logical unit
  at 32, a sixteenth at 512 - so at 32 the rim carries a large share of the
  weight and the scalar pushes the interior up to compensate. `density` measures
  the interior.

  *Weighting on solid pixels only* (mask at 255, full mask as fallback below 16
  solid pixels). Right in principle, and it overcorrects where it matters: a
  thin cursor's solid interior at 32 is a handful of unrepresentative pixels.
  The wedges improve slightly (2.50 -> 2.12) and the thin ones collapse -
  SizeAll 3.55 -> 18.07, SizeNS 2.51 -> 10.32, SizeWE 2.66 -> 10.06, IBeam
  4.98 -> 7.37.

  *Switching the normaliser off altogether.* This is the one worth knowing
  about, because it works on the metric it was aimed at and fails on the other
  side of the same trade. `density_%` collapses - Arrow 2.50 -> 0.10, Help
  2.29 -> 0.09, Cross 6.16 -> 1.47, IBeam 4.98 -> 0.66, twelve of sixteen under
  target - and `scale_drift` goes from 0.011..0.068 to 0.124..0.172 against a
  threshold of 0.10, so all sixteen fail it instead. That is the normaliser's
  own docstring measured from the other end: it trades 0.15 logical units of
  coverage drift for 2..4 per cent of interior level. Coverage drift is the
  cursor changing size with the size it is drawn at, which the eye sees;
  2.5 per cent of interior opacity, on an eroded interior, it does not.

  So the sixteen `density_%` debts are one deliberate trade, not sixteen
  defects, and the 2.0 target is unreachable while `scale_drift` is held under
  0.10. Whether they should be reclassified from debt to accepted is a
  bookkeeping call for the owner, not a rendering fix.

## Медиана по дуге не отделяет полосу от складки, потому что полосы нет

Замысел: паразитная тёмная полоса идёт **вдоль** контура на постоянной
глубине, а складка его **пересекает**, значит в координатах (длина дуги,
нормаль) они разделяются медианой по дуге, и тогда `_fold_keepout` со всем его
побочным ущербом (до 22.7% подавленного дефекта на Help, у острия и у выемки)
становится не нужен. Дальше - минимальная поправка, убирающая внутренние
минимумы профиля: `min(накопленный максимум слева, справа)`.

Собрано целиком (`_rim_monotone`, станции каждые 0.25 единицы, профиль 0..2.5
шагом 0.05, медиана по дуге ±3 единицы, сплат обратно по тем же лучам).
Результат: **ноль изменённых пикселей**, числа до процента совпали с рендером
вообще без стадии.

Причина не в реализации. Медиана по дуге срезает дипы **вместе** со складкой:
усреднённый профиль Arrow идёт 135 → 145 → 149 → 188 → 186 → 165 → 157 и
внутренних минимумов не имеет вовсе, заполнять нечего. То есть дипы стоят на
отдельных станциях, а не тянутся полосой на постоянной глубине - посылка
разделимости неверна.

Замер, из которого посылка выводилась («на Arrow 68 станций из 280 становятся
монотонными»), считал монотонность **после** медианы и сравнивал с сырым
профилем. Это не «полосу видно, складку нет», это «медиана сгладила и то и
другое». Отдельно ранее отвергнут и глобальный радиальный профиль: полоса
разной глубины на разных рёбрах, среднее по всем станциям её не видит.

Что при этом видно в профилях и осталось незакрытым: на клиньях гребень на
глубине ~1.0 стоит на 188-221 уровня против авторских ~150, а на части станций
там же провал до 59 с обрывом в 130 уровней на соседнем отсчёте. Дефект - не
только лишний тёмный слой, но и пересвеченный гребень рядом с ним. Автор
держит дип на 12 станциях из 248 (Arrow), мы - на 240 из 280.

`_edge_shadow_declutter` оставлен на месте: он единственный, кто эти 240
станций хоть сколько-то чинит (76% против 82% без него на Arrow, 67% против
80% на Hand, 69% против 84% на NO).

---

## Спрямление рёбер: хорда не отличает пилу от дуги

Проверено 2026-08-15 и **закрыто как отдельный подход**. Проход спрямления в
`trace.py` (`straighten_runs`) сажает вершины прогона на подогнанную
ортогональной регрессией прямую. Отбор прогонов только по допуску от хорды
(«вершина не дальше 2.5 eps») **портит верность оригиналу**, и вот почему.

У Cross, IBeam и SizeAll лучи в авторском 32px растре нарисованы **вогнутыми**.
Прямая поверх вогнутой руки ложится снаружи всех авторских пикселей, то есть
проход не убирает дрожание, а надувает силуэт. IoU нашего 32px против `src/orig`:

| курсор | база | только допуск хорды | с проверкой на дугу |
|---|---|---|---|
| Cross | 0.8898 | 0.8729 | 0.8898 |
| IBeam | 0.8261 | 0.8116 | 0.8261 |
| SizeAll | 0.8438 | 0.8359 | 0.8438 |

Проверка хорды спрашивает «насколько далеко вершина», но никогда «с какой
стороны». Разрез Дугласа-Пекера пополам не спасает: получаются две хорды, каждая
поверх своей половины дуги.

**Что не работает и проверено.** Мерить знакопеременность от **подогнанной**
прямой: TLS центрирует свои остатки по построению, и дуга балансирует вокруг
своей подгонки не хуже пилы - читается 1 для всего, ноль отвергнутых прогонов.

**Что работает.** Знакопеременность от **хорды** (`_balance`, порог
`STRAIGHT_BALANCE = 0.4`): пила кладёт одинаковую массу по обе стороны хорды,
дуга лежит целиком по одну сторону.

Цена признака: выигрыш по `edge_straight` rms ужимается с 0.156 → 0.130 до
0.156 → 0.147. Стрелочные курсоры (8 из 16) сохраняют почти всё, 0.118 → 0.106;
вогнутые остаются нетронутыми, как и должны.

**Инструмент.** Вопрос «спрямлять или нет» решается не `edge_straight`, а IoU
силуэта на 32 против `src/orig`: прямизна и верность автору здесь в прямом
противоречии, и одна метрика на это не отвечает. Второй, независимый от рендера
инструмент - расстояние от вершины до плотной цепочки границы 128px: до 2.5 eps
его максимум не сдвигается ни на одном курсоре, на 3.0 ломается.

## Симметрия: приколотый апекс и остриё, которое держит не силуэт

Усреднение контура с его же отражениями (`trace.symmetrize`) стоило
`tip_contrast` на SizeNS 0.037 -> 0.021 при поле 0.055. Напрашивалось объяснение
«апекс размазали»: апекс не трассированная вершина, а пересечение двух
подогнанных боковин, то есть уже самая точная точка контура, и усреднять её с
зеркалом можно только во вред.

**Не подтвердилось.** Приколол апексы (вносят вклад в чужое среднее, сами не
двигаются) - глазом стало **хуже** обоих вариантов: апекс остаётся на старом
косом месте, боковины выравниваются, и остриё уезжает с оси. `tip_contrast` при
этом не восстанавливается.

**Где потеря на самом деле.** Разложил композит на множители в круге 1.5
единицы вокруг острия SizeNS, притяжение 0.0 против 1.0:

| | альфа в точке | яркость | ширина поперёк биссектрисы 0.25/0.5/1.0/2.0 |
|---|---|---|---|
| 0.0 | 0.616 | 112.7 | 0.130 0.370 0.810 1.680 |
| 1.0 | 0.604 | 119.3 | 0.130 0.370 0.810 1.570 |

Геометрия стоит на месте: альфа, ширины клина и угол не двигаются. Уходит
**яркость** - 112.7 -> 119.3 при фоне 128, то есть тень под остриём вдвое
слабее. Тёмное ядро лежит в AI-мастере, оно к силуэту не привязано, и сдвиг
контура на 0.2 единицы выводит остриё из-под него. Это сцепка на стороне
рендера, вектором она не решается.

Поэтому SizeNS и SizeWE **меряются, но не правятся**: `analyze.SYMMETRY` шире
`trace.SYMMETRY` на эти два курсора. Свип притяжения 0.0/0.35/0.5/0.7/1.0:
SizeNS теряет остриё монотонно (0.037/0.030/0.028/0.025/0.021) и уже на 0.35 не
проходит; порога, где симметрия даётся даром, нет. На 0.5 обе оси SizeNS
садятся ровно на авторскую асимметрию (lr 27.9 против его 27.7, ud 4.5 против
4.2) - то есть цель плана достигается, но платится остриём.

Cross, SizeAll и IBeam ведут себя обратно: остриё там **растёт** с притяжением
(Cross 0.053 -> 0.058, SizeAll 0.043 -> 0.049), IBeam почти не двигается.

## Устаревший traced.json: фоновый прогон, который считался мёртвым

Коммит `449ecbb` положил `trace.py` с `STRAIGHT_BALANCE = 0.4` и `traced.json`,
собранный при `0.30`: свип, запущенный фоном и признанный мёртвым по пустому
`Get-Process python`, дописал файл уже после. Проверка «байт-в-байт с коммитом»
ничего не поймала - сравнивались выход свипа с самим собой.

Разошлись 10 курсоров из 16, 3-5 вершин на курсор, до 0.27 логической единицы.
`metrics-baseline.json` был снят поверх этого файла, поэтому в гейте потом
всплыли четыре «регрессии» на курсорах, которых симметрия не касается вовсе
(Arrow_Down, UpArrow, SizeWE).

**Проверка, которая ловит это.** Не сравнение файла с коммитом, а
воспроизведение: `git show HEAD:trace.py > _tmp.py && python _tmp.py` и диф
результата с `HEAD:traced.json`. Ровно то, что делает CI. Своё же значение
константы в диффе кода при этом выглядит правильным - смотреть надо на выход.

## Перенос формы кромки: три способа положить поправку обратно (2026-08-19)

Все три о том, как из посчитанных по лучам поправок собрать картинку. Механизм
один и тот же, числа - `rim_layers` на Arrow при базе 0.719.

- **Рассыпать по своим же лучам с нормировкой по весу**: 0.65. Работает, но лучи
  идут через 0.25 единицы, отсчёты по лучу через 0.125, и на 512 между ними
  остаются целые пиксели, которых не коснулся никто. Сырых провалов в сечении
  становится вдвое больше (Arrow_Down 458 -> 1184), сама гофра и есть слой.
- **То же, но с размытием числителя и знаменателя перед делением**, чтобы дырки
  заполнились интерполяцией: **0.80**, хуже, чем без переноса вовсе. Размытие
  идёт и по глубине - по единственной оси, о которой вся поправка.
- **Приколоть отсчёт на контуре к нулю** («контур стоит на месте»): на первый
  взгляд безобидно, на деле ставит обрыв в 16 уровней там, где мастер и
  аналитика расходятся сильнее всего - у самой кромки. Профиль после этого не
  меняет форму, а просто опускается полосой, и её края - два новых провала.

Живой способ - поле: пиксель берёт свою глубину из `_edge_distance_at` и секцию
ближайшей станции, интерполируя только по глубине.

## Перенос формы вдоль складки не мирится с переносом поперёк кромки (2026-08-19)

Развилка 1 из NEXT.md, раздел «Перенос формы кромки». Эталон яркости вдоль
излома строится так же, как поперёк кромки, и переносится за тот же проход.
Механизм рабочий: при потолке 18 уровней разрыв складки у UpArrow (`fold_gap`
2.75 / 2.00 / 2.92 на 128 / 256 / 384) сходится к 0.50 / 0.38 / 0.67 - лучше
базы. Той же поправкой `fold_luma_step` у Arrow идёт 4.2 -> 15.9, `fold_jag`
53.9 -> 86.3, у Hand то же самое. Потолок 6 и 3 гасят обе стороны сразу.

Причина не в величине: аналитика вдоль складки несёт собственную амплитуду, и
там, где мастер уже нарисовал линию верно, любая её доля - чистая порча. Код
оставлен в дереве выключенным (`_FOLD_XFER = set()`), с числами.

## Ближайшая станция как способ чтения поправки (2026-08-19)

Продолжение предыдущего раздела, найдено глазами, а не числом. Поле поправки,
взятое от **ближайшей** станции, разбивает стекло на ячейки Вороного: каждая
печатает свою секцию, границы ячеек - прямые, и на 512 при увеличении 4x
поправка видна плоскими фасетками с прямыми швами. Хуже всего у остриёв и в
узких местах, где ячейки расходятся веером.

`rim_layers` при этом **лучше** (Help 0.314 против 0.333 у смешанного варианта):
фасетка сама по себе монотонна вдоль луча, а метрика считает провалы вдоль луча.
Числу нечем это увидеть. Смесь по станциям с весом по дуге фасетки убирает.

Отдельно: у самой точки поправку надо гасить. Нормали соседних станций там
пересекаются, секции расходятся, и смесь печатает в острие тёмный клин.

## Равномерный вынос трассированного контура наружу

Контур измеримо вдавлен внутрь своего же источника на 0.14-0.24 логической
единицы (NEXT.md 28.1). Соблазн - вынести его наружу по нормали на константу и
забрать `delta_e` у NO и IBeam. Не работает: вдавливание неравномерное. На
`d=0.05` `delta_e` улучшается у тринадцати из шестнадцати, но IoU падает у
четырёх (NO -0.022, Cross -0.019, SizeNS -0.011, Handwriting -0.009) - у них
силуэт относительно автора и так не тонкий. Гейт валится.

Отдельно: проверять такое на четырёх курсорах бесполезно. На выборке
Arrow/Help/NO/IBeam `d=0.05` выглядел бесплатным - обе метрики росли у всех
четырёх. Полный прогон это опроверг.

Что осталось живым - не двигать вершины, а убрать причину: жёсткий порог
`max(30, min(0.45*peak, 55))` по мягкому краю. Трассировка по уровню 0.5
(marching squares) ставит вершину в геометрически верное место сама, без
константы.

## Трассировка по уровню альфы вместо внутренних пикселей границы

Каждая точка сырой цепочки сносится по нормали на уровень `alpha == thresh`.
Геометрически правильно (у Arrow средний снос 0.48 пикселя наружу, лестница
исчезает), но в лоб не работает по двум причинам.

Первая: углы классифицируются по той же цепочке, а `CORNER_KEEP_DEG` настроен на
лестницу. Гладкий контур не даёт резкого поворота в окне, флаг угла не ставится,
`straighten_runs` сливает прогоны через бывший угол. Cross теряет луч
(delta_e 4.03 -> 15.05, IoU 0.918 -> 0.480), SizeNESW тоже, у NO по кольцу
тёмный шов.

Вторая, важнее: даже там, где силуэт не пострадал (шесть однокомпонентных, IoU
-0.009), остриё Arrow становится темнее - на апексе тёмная шапка. При этом
`rim_layers` улучшается вдвое (Arrow_Down 0.745 -> 0.322, UpArrow 0.755 -> 0.377).
Метрика хвалит то, что глаз бракует, ровно как в разделах про подвыборки.

Третий вариант - снимать лестницу только с неугловых прогонов, после
классификации углов, с зоной покоя вокруг каждого флага - собран и замерен тоже.
Силуэты выживают (Cross снова с четырьмя лучами, delta_e 4.24), но IoU падает у
одиннадцати из шестнадцати, у однокомпонентных ровно на -0.023, а `rim_layers`
идёт вразнобой: IBeam и UpArrow лучше, Help и SizeNESW хуже. Вывод: выигрыш по
`rim_layers` во втором варианте держался на скруглении углов, а не на снятии
лестницы. Все три варианта закрыты (NEXT.md 28.2, 28.3).

## Перестройка граней поверх ободка кромки

Стадия структурных граней (`_facet_split`) собирала статистику двух поверхностей
по внутренности (`ed > 0.35`), а накладывала результат на всю зону острия. У
острия клин узкий, ободок занимает почти всю его ширину, и внутреннее стекло
затирало ободок - тот самый, который и несёт контраст острия против рабочего
стола. Итог: `tip_contrast` Arrow 0.129 -> 0.083, Arrow_Down 0.092 -> 0.060,
UpArrow 0.048 -> 0.027 при авторских 0.084 / 0.088 / 0.085. Лечится не подбором
перцентиля, а тем, что ободок вообще не отдают этой стадии (`_FACET_KEEP_RIM`,
NEXT.md 30.3).

## Структурные грани на Arrow_Down и UpArrow

Девять вариантов (перцентиль 25/20/15 на keep 0/0.25/0.4) замерены на обоих.
Ни один не окупается. Arrow_Down: лучший контраст граней у острия 1.72 при
телесном 2.72, и при этом `tip_contrast` 0.0845 против авторских 0.0879. UpArrow:
грани 0.93 -> 1.22 при телесном 1.33, `tip_contrast` 0.048 -> 0.041 при том, что
он и так вдвое ниже авторского 0.085. У этих двух дефект острия не в разделении
поверхностей, а в самом ободке. На Arrow та же стадия работает (NEXT.md 30.3).
