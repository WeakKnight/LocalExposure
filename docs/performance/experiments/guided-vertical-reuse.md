# Guided vertical-window reuse

This experiment follows the dependency review. Two adjacent vertical windows
load six shared rows instead of independently loading five each. Both vertical
moment reduction/coefficient fitting and final coefficient averaging use this
reuse. Horizontal work, FP32 moment sums, radius-two supports, tile anchor,
clamping, texture formats and all four group barriers remain unchanged.

Two variants keep the same 16x16 output tile:

- `guided-vertical2-t256`: 256 threads, vertical reuse only.
- `guided-vertical2-t128`: 128 threads, more work per thread; slower on the phone.

The thread-group dimensions and output-tile dimensions are separate. Android
dispatch-group counts and desktop dispatch extents both account for this.
Changing just `numthreads` without changing dispatch would be incorrect.

## Initial matched measurements

Adreno 830 / NX789J, process-local Qualcomm 512.842.6, ordinary memory. 1080p,
R11G11B10 input, RGBA8 sRGB output, 45 FPS, joint graphics HDR producer. Three
alternating rounds, 45 warmup and 180 measured frames per block (540/path).
Visualization and presentation are excluded.

| Run order | Full chain ms | Baseline ms | Local Exposure increment ms | Diagnostic Guided ms |
|---|---:|---:|---:|---:|
| 128 threads | 4.6336 | 2.4423 | 2.1912 | 0.9656 |
| 256 threads | 4.4625 | 2.4424 | 2.0201 | 0.7909 |
| Original control | 4.5189 | 2.4408 | 2.0781 | 0.8530 |

The 256-thread version improves the initial increment by 0.0580 ms (2.8%) and
the full chain by 0.0564 ms. Baseline is nearly unchanged, so this is not an
apparent improvement manufactured by slower tonemapping. The 128-thread version
regresses and is not recommended. Per-pass diagnostics are separate instrumented
measurements, not additive frame budgets.

## Longer repeat

The 256-thread candidate and original control were each repeated with three
rounds, 60 warmup and 300 measured frames/block (900 samples/path):

| Variant | Full chain ms | Baseline ms | Local Exposure increment ms |
|---|---:|---:|---:|
| Vertical reuse, 256 threads | 4.4605 | 2.4416 | 2.0189 |
| Original control | 4.5263 | 2.4430 | 2.0834 |

The repeat saves **0.0645 ms / 3.1% of Local Exposure increment**, with a
0.0658 ms complete-chain improvement. Both screens favor 256-thread reuse;
sequential runs and unlocked device frequency still limit generalization.
The 256-thread version is now the mobile benchmark default; 128 threads is
rejected for performance. Keep the previous gather-reduction preset unchanged
as the control. Broader phone scenes/devices remain useful follow-up validation. This is a small
improvement, not attainment of the 1.5 ms target.

## Compiler evidence and interpretation

Adreno 730 offline analysis (not 8 Gen 1 phone timings):

| Guided variant | Main static instructions | Register footprint | Scratch | Projected fiber occupancy |
|---|---:|---:|---:|---:|
| Original | 523 | 10 | 0 | 75% |
| Vertical reuse, 256 threads | 901 | 13 | 0 | 75% |
| Vertical reuse, 128 threads | 1039 | 14 | 0 | 37% |

Fewer source shared loads do not imply fewer compiled instructions. Boundary
handling, cached-window selection and register reuse add work. The 256-thread
candidate trades those costs for fewer repeated loads/dependencies; this was
favorable in the initial phone screen. Reducing thread count alone was not.
The occupancy projections are supporting evidence, not proof of the phone's
stall cause.

Nominal texture traffic remains 0.863 GB/s at 1080p/45 FPS. This experiment does
not reduce intermediate image sizes or claim measured DRAM savings. Shared
arrays remain 18,048 bytes/group, and the number of synchronization points is
unchanged.

## Validation and scope

- Independent Guided tests include 1x1, 17x9 and 65x33, random and near-constant
  guides, FP32 coefficient readback, and the previous horizontal candidates.
- Full-pipeline synthetic HDR/motion sweeps passed at 513x289 and 17x9 against
  the independent original algorithm. Worst temporal differential was 2 and 1
  sRGB8 codes respectively, including the retained approximation's existing error.
- Four 1080p HDR scenes compared directly with retained gather-reduction on
  desktop: final sRGB8 colors and stored Guided coefficients were identical for
  both candidates.
- Completed foreground phone outputs were byte-identical to the retained phone
  control. This is one phone scene, not a multi-scene phone timing claim.
- Nine Guided/benchmark/traffic tests passed. A fresh `prepare` smoke run checked
  the 128-thread reflection and 16x16 tile dispatch. Default Guided SPIR-V was
  byte-identical to the previous production control.

The mobile benchmark defaults to `guided-vertical2-t256`. The viewer remains the
independent reference; `gather-reduction` and `lossless` remain available as controls.
See [portable results](../baselines/guided-vertical-reuse.json) for repeat
measurements, exact shader hashes and the retained decision. Original parameter
limitations of RG16F residuals still apply.
