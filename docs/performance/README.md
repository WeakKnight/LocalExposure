# Mobile performance

The mobile default is `guided-direct-moments`: quarter-resolution Fusion with a
residual pyramid, precomputed EV, horizontal/vertical Guided-window reuse and
direct texture moments (three workgroup barriers instead of four). The desktop
viewer remains the independent reference. `gather-reduction` preserves the previous
mobile control; `guided-vertical2-t256` preserves the 2.019 ms starting point,
and `lossless` selects the original algorithm.

## Current results

1080p, R11G11B10 HDR to RGBA8 sRGB, foreground graphics HDR producer and postprocess
in one submission, 45 FPS. Measured on **Adreno 830**, process-local driver 512.842.6:

| Path | Complete chain | Local Exposure increment |
|---|---:|---:|
| Previous default (matched repeat) | 4.464 ms | 2.022 ms |
| Current default | 4.229 ms | 1.787 ms |

The repeat improved Local Exposure by **11.6%**, meeting the 1.8 ms target.
Desktop differences across four HDR scenes are at most one sRGB8 code. These are single-device results,
not Snapdragon 8 Gen 1 timings or a guarantee for every scene.
[Measurement and quality record](baselines/goal180.json).

Estimated incremental texture traffic is **19.18 MB/frame**, or **0.863 GB/s at
45 FPS**. This includes Fusion intermediates; it is not measured DRAM traffic.
See [bandwidth accounting](bandwidth.md).

## Optimization priorities

Focus on Guided, then HDR reduction/exposure setup and pyramid work. Compare
Fusion against matched tonemapping and check complete-chain time too. Exclude
visualization; do not count shared tonemapping savings as Local Exposure gains.

Tile memory is experimental: the tested placement improved the complete chain
by only about 0.048 ms and also changed baseline timing. The observed setup-pass
reduction is not an isolated, proven tile-memory benefit.

RG16F residual quality is validated for the default sigma 0.2. Narrower weights
(sigma 0.05 with +/-3 EV) failed a moving-edge quality gate; RG32F residuals fixed
that case. Do not generalize default-setting validation to all parameters.

## Tools

- [Android benchmark](android.md): phone execution and image validation.
- Adreno offline: `python tools/profiling/mobile_profile.py --require-aoc` (defaults to A730; provide `--aoc PATH` if needed).
- Mali offline: `./tools/profiling/install_mali.ps1`, then `python tools/profiling/mali_profile.py`.

Offline projections help choose experiments; they do not establish phone time.
[Experiment archive](archive/README.md) contains supporting investigations and
[driver setup](archive/experiments/custom-driver.md).
