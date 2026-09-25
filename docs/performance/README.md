# Mobile performance

The default is `guided-packed-coefficients`. The independent viewer reference
and `guided-coefficient-layout` (FP32 fitted-coefficient control) remain available.

## Current measurement

**Adreno 830 / NX789J, process-local Qualcomm 512.842.6**, 1920×1080 at 45 FPS,
R11G11B10 HDR → RGBA8 sRGB. The same graphics HDR producer and tone mapper run
in both paths. Visualization, presentation, calibration and uploads are excluded.
Each run samples 1,800 frames per path, with 60 warmup frames per block.

| Sustained run order | Complete chain | Local Exposure increment |
|---|---:|---:|
| Optimized, first | 3.6369 ms | **1.1933 ms** |
| FP32 coefficient control | 3.6546 ms | 1.2112 ms |
| Optimized, second | 3.6371 ms | **1.1952 ms** |

The **1.2 ms median-increment target is met on this device/workload**. This is
not a per-frame guarantee or a measurement of another GPU. Separate pass
diagnostics are not an additive frame budget. [Raw record](baselines/current.json).

## Retained implementation

- Fusion runs at quarter width and height; all levels of that pyramid contribute.
- Initialization shares log-domain curve work and skips redundant negative clamps
  only for finite unsigned R11G11B10 inputs. Other formats retain clamping.
- Fine residual mips 0–2 use RG16F; coarse residuals use RG32F, weights RG16_UNORM.
- Small tail and fine reconstruction passes are fused; the 1080p graph has 12 dispatches.
- Guided uses 5×5 support and FP32 moments/accumulation. Each 16×16 output tile
  uses 256 threads, row Gather reuse and 9,600 bytes of shared storage.
- Fitted slope/intercept are rounded to half, explicitly packed into a 32-bit
  shared word, then unpacked before FP32 accumulation. Intercept rounding is an
  approximation. No exposure-value special cases or shared-tonemap savings are counted.

Estimated incremental texture traffic, including Fusion intermediates, is
**16.66 MB/frame / 0.750 GB/s at 45 FPS**. This is not measured DRAM bandwidth.
[Accounting](bandwidth.md) · [Precision](../precision.md).

The independent stage files retain the dispatch sequence and resource formats.
Frozen-graph GPU regressions compare final pixels and Guided coefficients exactly.
Resource bindings and uniform offsets come from each stage's compiler reflection.
This is structural validation, not a new phone timing measurement.
See the [stage map](../implementation.md).

## Quality and limits

The desktop four-scene/four-preset matrix passes 16/16; Veranda strong peaks at
5 sRGB8 codes. Phone default peaks for room / patio / deck / Veranda are
4 / 2 / 4 / 5. Strong Veranda peaks at **14**, meeting the requested ≤16 criterion;
the original 12-code gate remains unchanged and is exceeded by **two pixels**.

Odd/thin sizes, HDR edges and motion are covered by tests. Synthetic checks at
513×289 and 1080p include global EV −4/0/+4 and ±3 EV brackets; temporal worst
is 2 codes. The packed implementation is not bitwise-equivalent to the FP32
control. Narrow weights, extreme brackets and arbitrary future curve changes
are not covered by a universal error guarantee; revalidate them independently.
[Reference / optimized / error images](../image-comparison.md).

## Reproduce

- [Android benchmark](android.md): matched foreground timing and optional driver setup.
- [Developer tools](../../tools/README.md): image regeneration and offline compilers.
- [Raw records](baselines/README.md): measured timings, quality and driver provenance.

Optimize LE's matched increment and check complete-chain time. Offline compiler
projections guide experiments; they do not establish phone performance.
