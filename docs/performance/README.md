# Mobile performance

The default is `guided-packed-coefficients`. The independent viewer reference
and `guided-coefficient-layout` (FP32 fitted-coefficient control) remain available.

## Current measurement

**Adreno 830 / NX789J, process-local Qualcomm 512.842.6**, 1920×1080 at 45 FPS,
R11G11B10 HDR → RGBA8 sRGB. The same graphics HDR producer and tone mapper run
in both paths. Visualization, presentation, calibration and uploads are excluded.
Each sustained run samples 1,800 frames per path, with 60 warmup frames per block.

| Sustained run order | Complete chain | Local Exposure increment |
|---|---:|---:|
| Previous Guided, first | 3.5955 ms | 1.1519 ms |
| Direct 5×5 Guided, 64 threads | 3.5341 ms | **1.0912 ms** |
| Previous Guided, second | 3.5941 ms | 1.1525 ms |
| Integrated default verification | 3.5347 ms | **1.0922 ms** |

The **1.1 ms median-increment target is met** by the integrated default, about
0.061 ms faster than the previous path. This is not a per-frame guarantee or a
measurement of another GPU. Separate pass diagnostics are not an additive frame
budget. [Raw records and source hashes](baselines/current.json).

## Retained implementation

- Fusion runs at quarter width and height; all pyramid levels contribute.
- Initialization shares log-domain curve work. Finite unsigned R11G11B10 skips
  redundant negative clamps; other formats retain clamping.
- Residuals and centered weights share RGBA16F mips 0–2 and RGBA32F coarse mips.
- Small tail and fine reconstruction passes are fused; 1080p has 12 dispatches.
- Guided retains full 5×5 fitting and 5×5 coefficient averaging. Each 8×8 workgroup
  produces a 16×16 output tile using 64 threads and 2,880 bytes of shared storage,
  down from 256 threads and 9,600 bytes. Direct fits replace the intermediate
  row-moment buffer and one publication barrier.
- Moments and averaging accumulate in FP32. Fitted coefficients and horizontal
  averaging sums retain their half rounding; the FP32 fitted-coefficient control
  remains independent. No exposure-value shortcuts or shared-tonemap savings.

The [five stage files](../implementation.md) declare their own resources. Compiler
reflection supplies bindings and uniform offsets. Frozen-graph regressions retain
fixed image-quality gates; the optimized pipeline is not bitwise-equivalent to
the full reference.

## Quality and bandwidth

All 64 tests and the regenerated four-scene/four-preset matrix pass. Veranda strong
peaks at **10 sRGB8 codes** (21 pixels above 4, none above 12). The integrated phone
image gate peaks at 8; its output matches the validated candidate. Tiny/odd/signed
inputs and synthetic HDR edges/motion pass; worst temporal differential is 2 codes
for both coefficient presets. The README comparison sheets and worst crops have
been regenerated and inspected.

Estimated incremental texture-sweep traffic is **16.71 MB/frame / 0.752 GB/s at
45 FPS**. Direct fits preserve this sweep but repeat more input reads: expanded
logical-access accounting rises from 3.946 to **4.449 GB/s**. Cache reuse is not
assumed by that model. Neither model measures DRAM bandwidth or power.
[Accounting](bandwidth.md) · [Precision](../precision.md) · [Images](../image-comparison.md).

These checks are not universal error guarantees. Extreme weights/brackets, future
curve changes and other GPUs need separate validation. Same-phone all-asset
coverage is narrower than the desktop matrix.

## Reproduce and rejected directions

- [Android benchmark](android.md): matched foreground timing and optional driver setup.
- [Developer tools](../../tools/README.md): image regeneration and offline compilers.
- [Raw records](baselines/README.md): timing, quality and driver provenance.

The 3×3 Guided shortcut was rejected by image gates (Veranda strong peak 206);
restoring 5×5 in the same implementation restores quality. Larger direct-fit
workgroups lose the gain: 128 threads screen at 1.101 ms, 256 at 1.150 ms.
Integer HDR views/manual decoding, extra pass fusion, half fetches, shared-memory
padding and wave-sharing trials did not improve the matched chain. Details are
recorded in the baseline JSON; reproducible experimental bundles and raw samples
remain under `outputs/goal110/`. They are not production options.
