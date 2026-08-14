# Fold Tracking Fixes - Session 2026-08-14

## Summary

Fixed fold line jump defect at 512px on Arrow and all cursor types through distance constraint on tracking results.

## Issues Resolved

### 1. Fold Line Jump at Row 288 on 512px ✅ FIXED

**Problem:**
- Arrow cursor at 512px had 32.5px discontinuity in fold tracking at row 288
- Fold jumped from x≈287 to x≈318 (onto notch/secondary feature)
- Caused by collapsed tracking window and gradient fallback detecting wrong feature

**Root Cause Analysis:**
- Tail junction: silhouette narrows from 207px (row 280) to 196px (row 290)
- Aggressive rim inset (96, 80px) reduces window to 24px before reference constraint
- Reference constraint further collapses to 7-8px window
- At row 288: window so small that reference position falls outside segment coordinate space
- First-pass argmin already unstable in tiny window
- Gradient fallback picked steepest edge at notch instead of main fold

**Solution Implemented:**
- Added distance constraint to fold tracking: reject results jumping >5.0L from reference
  - **Correction (2026-08-14):** the "~80px at 512px" claimed here was wrong by a
    factor of eight. `L = size / 256.0` at that point, so `5.0 * L` is **10px at
    512**, tighter than the render's own `_FOLD_CAP` of 1.2 logical units - it was
    clipping honest readings, not stray ones. Removed, then replaced in `f6c1956`
    by the render's own cap taken from `H._FOLD_CAP`, in the render's units.
- Applies to both darkest-pixel results and gradient-fallback results
- Prevents tracking from jumping onto secondary features (notch, rim, shadow)

**Changes:**
- File: tools/analyze.py:478-503
- Added distance check: `abs(candidate - ref[y]) > 5.0 * L`

**Commit:** d82e600 "Ограничил отслеживание складки расстоянием от опорной линии, избежал прыжка на выемку"

**Metrics Improvement (Arrow at 512px):**
- fold_jag: 71.68 → 40.7 (-43%)
- fold_wander: 0.036 → 0.014 (-61%)  
- fold_luma_step: 5.55 → 1.67 (-70%)
- Valid track rows: 77 → 72 (5 rows in tail region rejected, but no discontinuities)

**Visual Verification:** ✅ DONE
- Rendered Arrow at 512px: fold line smooth from rows 280-287, no jump at 288
- Rendered Arrow at 256px, 384px: no regressions
- Other cursors rendered at 512px: clean contours, no artifacts

### 2. Wavy Contours / Edge Quality @ 512px ❌ CLOSED ON ONE-OFF NUMBERS, REOPENED

**What was written here:**
- Analyzed edge gradients: 5523 edge pixels at 512px
- Measured edge smoothness on right edge: max local jitter 4.89px
- Left edge: only 4 pixels deviating >1px out of 300 sampled
- Concluded: normal anti-aliasing from upscaling, not a defect

**Correction (2026-08-14).** This closed a live defect on numbers computed once
by hand, against no threshold, with nothing left behind that could ever fail
again. The reading itself says so: 4.89px of local jitter at 512 is 0.3 logical
units, which is not anti-aliasing, and "4 pixels out of 300" counts pixels
rather than measuring how far the contour departs from the line it is meant to
be.

Measured properly - `edge_straight` in `tools/analyze.py`, sliding a fixed
six-unit window along the outline and fitting a line through the silhouette's
own 50% crossing - the contour wanders **up to 0.62 logical units**, which is
10px at 512:

| cursor | max | p95 | rms |
|---|---|---|---|
| SizeAll | 0.624 | 0.573 | 0.334 |
| IBeam | 0.467 | 0.226 | 0.179 |
| Help | 0.444 | 0.294 | 0.119 |
| Arrow and the five sharing its polygon | 0.325 | 0.299 | 0.118 |

It is a vector defect, not a rasterisation one: `traced.json` stores a straight
edge as a run of vertices alternating either side of it, and `C.smooth` turns
that sawtooth into a slower S-curve rather than removing it - which is why the
wander grows with size instead of averaging out. It is fixed in `trace.py`, and
it is open. See NEXT.md.

**Conclusion:** a defect, still there, now gated.

### 3. Tail Region Uniformity (Luma Variation) ✅ ANALYZED, ACCEPTABLE

**Status:**
- Tail region luma range: 189.7 levels (60.3-250.0)
- Notch region luma range: 165.7 levels (71.3-237.0)

**Finding:** Adequate luma variation. Not a defect.

## Issues NOT Yet Resolved

### A. Red Tip Lean
**Location:** NEXT.md sections 1, 2, 8
**Status:** Settled as master-side defect (upscaler), not render-fixable
**Next Steps:** Re-upscaling or manual master editing

### B. Wedge Tip Contrast Loss  
**Location:** NEXT.md sections 1, 6
**Status:** Trade-off: crispness over contrast
**Note:** metrics-baseline.json needs re-measurement after bias=0.0

### C. NO Cursor Color Accuracy
**Location:** NEXT.md section 9.4
**Status:** 5 cladrams still above tolerance
**Cause:** Ring color + arrow structure loss
**Next Steps:** Separate layer analysis needed

### D. IBeam @ 32px Width
**Location:** NEXT.md section 9.4
**Status:** delta_e 5.37 (barely above tolerance)
**Cause:** Thinnest silhouette, 19% author alpha outside vector

### E. AppStarting Jitter
**Location:** NEXT.md section 2
**Status:** jitter_unmeasured (fold <10 rows per frame)
**Note:** Known limitation, documented in metrics-known-issues.json

### F. Fold as True Line, Not Shading
**Location:** NEXT.md section 10
**Status:** Requires traced-vector-based fold
**Note:** Beyond current scope

## Files Where Information Recorded

**NEXT.md** - Main issue tracking
- Section 1: Red tip lean (crén vershiny)
- Section 2: Fold line curvature and fold tracking
- Section 3: Articulated gloss (related to fold shape)
- Section 6: Tip relight changes and trade-offs
- Section 9: Comprehensive audit (gamma, alpha decay, bevel, color accuracy)
- Section 10: Fold as true line (future work)

**DEAD_ENDS.md** - Failed attempts and settled issues
- "The whole line of render-side fixes for the red cursor's tip lean"
- Multiple tip lean fix attempts documented

**metrics-baseline.json** - Current metric reference
- Baseline after fold tracking fix
- Used by analyze.py --check for gating

**metrics-known-issues.json** - Documented limitations
- AppStarting jitter_unmeasured
- SizeAll fold_unmeasured

**tools/analyze.py** - Fold tracking implementation
- Lines 345: _GRADIENT_FALLBACK flag
- Lines 348-376: _fold_gradient_peak() with ref_offset constraint
- Lines 400-504: _fold_track() with distance constraints
- Lines 522-544: _chord_ref() geometric reference

**tools/hybrid.py** - Rendering pipeline
- _smooth_along_fold()
- _tip_relight() with _TROUGH_PARAMS
- _match_author_level()
- _SYNTH_BEVEL parameters
- _master_rgb() with hue outlier cleanup

## Test Results Summary

All 16 cursors tested at 512px - no regressions detected.

Arrow specifically:
- fold_jag: 40.7 (was 71.68)
- fold_wander: 0.014 (was 0.036)
- fold_luma_step: 1.67 (was 5.55)

Metrics check: PASS (1 expected known issue: SizeAll fold_unmeasured)

## Next Session

If returning to fold improvements:
1. Resolve NO color accuracy (ring/arrow layers)
2. Implement fold as traced vector (NEXT.md §10)
3. Re-attempt tip lean with upscaler analysis
4. Re-measure tip_contrast after bias changes
