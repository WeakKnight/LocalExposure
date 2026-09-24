# Mobile performance

The mobile default is `guided-fused-reconstruction`: quarter-resolution residual
Fusion, a fused small pyramid tail, and local reconstruction of the three finest
levels. All pyramid levels remain included. Log-luminance/guide and EV/guide use
RG16F; Guided horizontal coefficient sums use half storage, with FP32 moments,
variance and final accumulation. At 1080p, production dispatches fall from 14 to 12.
Small images fall back to separate reconstruction when the required levels are
unavailable. The viewer remains the independent reference; `guided-direct-tail`
preserves the previous mobile default and `lossless` selects the original algorithm.

## Current results

1080p, R11G11B10 HDR to RGBA8 sRGB, foreground graphics HDR producer and postprocess
in one submission, 45 FPS. Measured on **Adreno 830**, process-local driver 512.842.6:

| Path | Complete chain | Local Exposure increment |
|---|---:|---:|
| Previous default | 4.127 ms | 1.685 ms |
| Current default | 4.030 ms | 1.588 ms |

Two retained long repeats measured **1.5882 / 1.5885 ms**, meeting the 1.59 ms
target; all six round medians remained below 1.59 ms. Local Exposure improved
**5.8%** against the matched control. Each repeat sampled 1,800 frames per path.
Four desktop HDR scenes differ by at most two sRGB8 codes from the previous
default, and all four same-phone reference gates pass.
These are single-device results, not Snapdragon 8 Gen 1 measurements.
[Measurements, quality limits and rejected experiments](baselines/goal159.json).

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
