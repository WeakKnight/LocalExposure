# Wave operation experiments

Neither candidate replaces `gather-reduction`. Measurements below are on the
NX789J / SM8750 / **Adreno 830**, not Snapdragon 8 Gen 1. A730 results are
offline compiler checks only.

## Results

1080p, quarter-resolution Fusion, R11G11B10 HDR input, RGBA8 sRGB output,
45 FPS. Foreground NativeActivity, graphics HDR producer and postprocess in
one submission. Each configuration has three alternating Fusion/baseline
rounds, 45 warmup frames and 180 measured frames per block (540 per path).
Presentation and visualization are excluded from the timestamps.

| Candidate | Producer + Fusion + tonemap | Producer + tonemap | Increment | Decision |
|---|---:|---:|---:|---|
| Retained Gather control | 4.612 ms | 2.500 ms | 2.112 ms | Keep |
| Four-lane Wave reduction | 4.932 ms | 2.512 ms | 2.419 ms | Reject as an optimization |
| Guided horizontal shuffle | — | — | — | Failed phone quality gate; foreground measurement skipped |

The Wave reduction increment is about 15% worse in this screen. These are
short, sequential device runs, not frequency-locked or sustained-game results.
The foreground output matches each candidate's headless output byte for byte.
Nominal texture sweep traffic is unchanged: these substitutions target local
communication and execution, not fewer input/output textures. No DRAM-counter
bandwidth measurement was made.

## What was tried

**Reduction:** four consecutive lanes each Gather one 2x2 quad, exchange two
FP32 sums (luminance and log luminance), and let one lane evaluate the three
exposures and write the result. This preserves the full 4x4 footprint. A runtime
check verifies lane ordering and active-lane grouping; odd image sizes and
incompatible mappings use the original sampled reduction. The opt-in
`wave-reduction` preset requires subgroup vote, ballot and shuffle support;
the fallback is for mapping/dimensions, not devices without subgroup features.

It passed same-phone Veranda quality checks (0.224-code RMSE, maximum 8 codes
against the independent unfused reference). Desktop HDR ramps, colored edges,
noise, checkerboards and motion passed at 512x288, 513x289 and 17x9. Worst
temporal differential was 2 codes. This is not bitwise equivalence or validation
of every parameter setting. Four-lane cooperation lowers per-lane register use,
but only one in four lanes performs the nonlinear exposure setup; its scheduling
and exchange overhead did not pay off in the measured complete chain.

**Guided:** exchange horizontal moment and coefficient values through lane
shuffles while preserving the original 5x5 supports, FP32 moment sums and
vertical shared-memory stages. Three forms were tested: looped, unrolled with
predicated writes, and expression selection instead of the inner branch.
Desktop tests passed, but all three produced non-finite averaged coefficients
on the phone. Final-image RMSE was 13.86, 13.35 and 14.89 codes respectively.
The failure is unresolved; these results do not establish a driver bug. The
failed implementation and presets were removed from the runnable production
source and saved in the patch below. Combining it with Wave reduction was
therefore not measured on the phone.

## Compiler checks and follow-up

AOC 7.0.15 / A730 reported zero scratch for both initial candidates. The initial
Guided candidate increased static instruction count from 523 to 2,123 and reduced
estimated occupancy from 75% to 50%. Reduction register footprint fell from 13
to 5, but that did not predict a whole-chain speedup. Static counts include
fallback paths and are not dynamic operation counts or phone timings.

A next attempt should redesign the Guided lane/row layout and establish
cross-device shuffle correctness in a small isolated kernel before integrating
it. This experiment does not rule out a better Wave-based algorithm; it rejects
these direct substitutions. The default production graph remains unchanged.

## Evidence and reproduction

- [Portable measurements and validation](../baselines/wave-operations.json)
- [Archived experimental patch](wave-operations.patch), based on commit
  `b0561c8b038db0ac6f97df1922f44caa28601fe9`. Apply only to a clean checkout of
  that commit when investigating the failed Guided experiment.
- Raw bundles, images, timestamps, telemetry and compiler output:
  `outputs/android/wave/` (ignored by Git).

The live reduction experiment can be reproduced with:

```powershell
python -m tools.profiling.android.benchmark --variant wave-reduction --source-format r11g11b10_float --output-format rgba8_srgb --fps 45 --out outputs/android/wave-repro
python -m tools.profiling.android.activity outputs/android/wave-repro/bundle --out outputs/android/wave-repro-joint --hdr-producer --joint-submission --frames 180 --warmup 45 --rounds 3 --fps 45
```

Use `gather-reduction` in a separate output directory for the matched control.
Only the foreground measurements above support the game-context comparison.
