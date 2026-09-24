# Guided short-window reuse

This experiment follows the [GPU filtering research](gpu-filtering-research.md).
It tests the multi-output and sliding-window ideas without Wave intrinsics.
The production default remains `gather-reduction`.

## Implementation

`GUIDED_BATCH=2/4` assigns each participating thread two/four adjacent horizontal
intermediate outputs in both Guided stages. It loads overlapping inputs into
register arrays once, forms FP32 moments once per cached sample, and reuses them
for neighboring windows. `GUIDED_SLIDING=1` additionally updates each sum by
subtracting the departing value and adding the entering value.

The final output tile remains 16x16 with 256 threads. This first experiment
batches the horizontal intermediate windows; it does not yet decouple final
output-tile size from thread-group size or redesign the vertical stages. Both
5x5 supports, tile anchor, texture formats, shared arrays, four synchronization
points, and full-resolution output backend remain unchanged. The nominal
incremental sweep traffic therefore remains 0.863 GB/s at 1080p/45 FPS; this is
not measured DRAM bandwidth.

The baseline arithmetic remains compiled when `GUIDED_BATCH=1`. All seven
production/control SPIR-V entrypoints in the retained control were byte-identical
to the earlier Wave experiment's control bundle.

## First phone screen

NX789J / SM8750 / **Adreno 830**. 1080p, R11G11B10 HDR to RGBA8 sRGB, quarter
resolution Fusion, default bracket +/-1.2 EV and sigma 0.2. NativeActivity with
graphics HDR producer and postprocess in one submission, 45 FPS; visualization
and presentation excluded. Three alternating rounds, 45 warmup and 180 measured
frames per block: 540 samples per Fusion/baseline path.

| Variant | Producer + Fusion + tonemap | Producer + tonemap | Increment |
|---|---:|---:|---:|
| `gather-reduction` | 4.593 ms | 2.526 ms | 2.067 ms |
| `guided-batch2` | 4.573 ms | 2.526 ms | 2.048 ms |
| `guided-batch4` | 4.724 ms | 2.507 ms | 2.217 ms |
| `guided-sliding4` | 4.682 ms | 2.596 ms | 2.086 ms |

Batch4 is slower. Sliding4 does not improve complete-chain time, and its larger
baseline makes subtraction look more favorable than the total. Batch2's initial
~0.019 ms difference requires repetition; this screen alone is not a reliable
speedup claim. These runs are not frequency-locked gameplay measurements.

The first headless control attempt completed GPU execution but lost ADB during
readback. It is excluded. The ADB service was restarted, the connection returned,
and all reported phone screens completed with numerical validation. The transport
failure's root cause was not determined.

## Longer reverse-order repeat and decision

The candidate ran first and the control second, reversing their initial order.
Each used three alternating rounds, 60 warmup frames and 600 measured frames
per block (1,800 samples per path).

| Variant | Producer + Fusion + tonemap | Producer + tonemap | Increment |
|---|---:|---:|---:|
| `guided-batch2` | 4.572 ms | 2.512 ms | 2.060 ms |
| `gather-reduction` | 4.652 ms | 2.510 ms | 2.142 ms |

The repeat's incremental reduction is 0.081 ms (3.8%); total interval decreases
by 0.080 ms. Per-round increments were 2.030/2.091/2.054 ms for batch2 and
2.102/2.138/2.166 ms for control. Both screens favor batch2, but the first screen
improved only 0.019 ms. Sequential device runs and variable frequency/thermal
state prevent treating 3.8% as a guaranteed gain.

**Decision:** retain `guided-batch2` as a promising opt-in candidate. Do not
replace the production default until broader matched phone scenes confirm the
benefit. Batch4 and sliding4 remain research presets, not accepted optimizations.
Bandwidth is unchanged and the 1.5 ms target remains unmet. A further redesign
could amortize vertical windows or decouple output tiles from thread counts;
those changes were not implemented in this round.

[Portable compiler, validation and timing records](../../baselines/guided-window-reuse.json)

## Validation

- Desktop synthetic HDR and motion checks passed for all three candidates at
  512x288, 513x289 and 17x9. Maximum temporal differential against the independent
  unfused reference was 2 codes (1 for the tiny case).
- Four 1080p HDR scenes compared directly against `gather-reduction`: maximum
  difference 1 sRGB8 code, RMSE below 0.0047 codes. These are desktop results.
- The Veranda phone batch2/batch4 outputs were byte-identical to the retained
  phone control. Sliding4 differed slightly. All three passed the fixed
  independent same-phone reference gate, with RMSE approximately 0.224 codes
  and maximum 8 codes; all checked intermediate outputs were finite.
- Foreground output matched each candidate's headless output byte for byte.
- Existing 47 regression tests passed. The additional `test_guided_batch` checks
  isolated FP32 coefficients with tiny/odd sizes, random and nearly constant
  guides, requiring evaluated exposure within 0.001 EV of the unchanged kernel.
- Random small-image direct comparisons at sigma 0.05 / +/-3 EV introduce no new
  final-code error in those samples. This does **not** remove the original
  residual-pyramid's known sharp-weight limitation.

## Adreno 730 offline check

AOC 7.0.15; these are compiler statistics, not Snapdragon 8 Gen 1 phone timings.

| Guided variant | Static instructions | Register footprint | Scratch | Occupancy estimate |
|---|---:|---:|---:|---:|
| Control | 523 | 10 | 0 | 75% |
| Batch2 | 618 | 8 | 0 | 75% |
| Batch4 | 720 | 8 | 0 | 75% |
| Sliding4 | 705 | 8 | 0 | 75% |

Reduced register footprint did not increase estimated occupancy. Static
instruction count is also not a dynamic per-pixel work measurement: candidates
compute different numbers of windows per participating thread.

## Reproduce

```powershell
python -m tools.profiling.android.quality_sweep --variants guided-batch2 guided-batch4 guided-sliding4 --game-format --out outputs/android/window-quality.json
python -m unittest tests.test_guided_batch
python -m tools.profiling.android.benchmark --variant guided-batch2 --source-format r11g11b10_float --output-format rgba8_srgb --fps 45 --out outputs/android/window-phone
python -m tools.profiling.android.activity outputs/android/window-phone/bundle --out outputs/android/window-joint --hdr-producer --joint-submission --frames 180 --warmup 45 --rounds 3 --fps 45
```

Use separate output directories for each candidate and the `gather-reduction`
control. Raw bundles, phone readbacks, timestamps, desktop stress reports and
compiler output are under `outputs/android/guided-batch/` (ignored by Git).
