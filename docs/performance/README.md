# Mobile performance

The mobile default is `guided-fused-reconstruction`: quarter-resolution residual
Fusion, a fused small pyramid tail, and local reconstruction of the three finest
levels. All pyramid levels remain included. Log-luminance/guide and EV/guide use
RG16F; Guided horizontal coefficient sums use half storage, with FP32 moments,
variance and final accumulation. Guided uses 256 threads per 16x16 output tile;
its horizontal sums reuse dead moment storage after the existing barrier. This
reduces shared storage from 12,160 to 10,880 bytes without additional rounding or
synchronization. Two-row Gather reads plus point reads share texture queries
while preserving the 5x5 filter support. At 1080p, the production graph has 12 dispatches.
Residual reconstruction uses the stored normalized weight pair directly, without
correcting small UNORM pair-sum drift at each level. Initial weight normalization
and the complete pyramid are retained.
HDR reduction and exposure initialization use 4x8-thread groups with unchanged
sampling and arithmetic.
Small images fall back to separate reconstruction when the required levels are
unavailable. The viewer remains the independent reference; `guided-direct-tail`
preserves the previous mobile default and `lossless` selects the original algorithm.

## Current results

1080p, R11G11B10 HDR to RGBA8 sRGB, foreground graphics HDR producer and postprocess
in one submission, 45 FPS. Measured on **Adreno 830**, process-local driver 512.842.6:

| Path | Complete chain | Local Exposure increment |
|---|---:|---:|
| Previous default | 3.964 ms | 1.522 ms |
| Current default | 3.755 ms | 1.313 ms |

Two long repeats measured **1.3135 / 1.3116 ms**, about **13.8%** faster than the
1.5222 ms interleaved control. The **1.48 ms target is met**. Each repeat sampled
1,800 frames per path; all six per-round increments also remain below the target.
Four phone captures pass the independent image gates and match the previous
default byte-for-byte. README reference/optimized/error images are current.
Separately timestamped diagnostics locate the gain in HDR initialization
(0.627 to 0.417 ms); shared final application remains approximately 2.131 ms.
These diagnostics are not additive headline timings. Results apply to this
device/driver, not measured Snapdragon 8 Gen 1 timings.
An extended 1080p random-HDR stress test at +4 EV exceeds the maximum-error gate
(17 display codes) in the retained control as well as the screened arithmetic
candidate. Representative phone captures still pass; this extreme synthetic
case remains a quality limitation.
[Measurements and rejected candidates](baselines/goal148.json);
[previous 1.59 ms milestone](baselines/goal159.json).

Estimated incremental texture traffic is **16.62 MB/frame**, or **0.748 GB/s at
45 FPS**. This includes Fusion intermediates; it is not measured DRAM traffic.
See [bandwidth accounting](bandwidth.md).

## Optimization priorities

Focus on Guided, then HDR reduction/exposure setup and pyramid work. Compare
Fusion against matched tonemapping and check complete-chain time too. Exclude
visualization; do not count shared tonemapping savings as Local Exposure gains.

Tile memory is experimental: the tested placement improved the complete chain
by only about 0.048 ms and also changed baseline timing. The observed setup-pass
reduction is not an isolated, proven tile-memory benefit.

Default sigma 0.2 / ±1.2 EV and the tested ±3 EV sweep pass. Validation of this
revision is limited to that range. The previous default already failed a 513x289
moving-edge gate at ±6 EV. Narrow weights (sigma 0.05 / ±3 EV) also have a known
RG16F limitation; RG32F fixed that older case. Do not generalize these image checks
to every parameter or scene.

## Tools

- [Android benchmark](android.md): phone execution and image validation.
- Adreno offline: `python tools/profiling/mobile_profile.py --require-aoc` (defaults to A730; provide `--aoc PATH` if needed).
- Mali offline: `./tools/profiling/install_mali.ps1`, then `python tools/profiling/mali_profile.py`.

Offline projections help choose experiments; they do not establish phone time.
[Experiment archive](archive/README.md) contains supporting investigations and
[driver setup](archive/experiments/custom-driver.md).
