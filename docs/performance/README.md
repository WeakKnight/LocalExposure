# Mobile performance

The mobile default is `guided-vertical2-t256`: quarter-resolution Fusion with a
residual pyramid, precomputed EV and vertical Guided-window reuse. The desktop
viewer remains the independent reference. `gather-reduction` preserves the previous
mobile control; `lossless` selects the original algorithm.

## Current results

1080p, R11G11B10 HDR to RGBA8 sRGB, foreground graphics HDR producer and postprocess
in one submission, 45 FPS. Measured on **Adreno 830**, process-local driver 512.842.6:

| Path | Complete chain | Local Exposure increment |
|---|---:|---:|
| Previous control | 4.526 ms | 2.083 ms |
| Current default | 4.460 ms | 2.019 ms |

The repeat improved Local Exposure by **3.1%**. Four desktop HDR scenes and the
phone test image matched the control exactly. These are single-device results,
not Snapdragon 8 Gen 1 timings or a guarantee for every scene.
[Measurement record](baselines/guided-vertical-reuse.json).

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
