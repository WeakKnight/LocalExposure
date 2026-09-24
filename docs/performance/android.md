# Android benchmark

SlangPy prepares images and calibration on the host. A native Vulkan runner
executes the production shaders on Android. The tooling currently supports
Windows hosts and arm64 Android devices with the required Vulkan/FP16 features.
Connect an authorized USB-debugging device and keep it unlocked for foreground runs.

## Run

From the repository root with the project Python environment active:

```console
python -m tools.profiling.android.benchmark --bootstrap --fps 45 --out outputs/android/mobile
python -m tools.profiling.android.activity outputs/android/mobile/bundle --bootstrap --hdr-producer --joint-submission --fps 45 --warmup 60 --frames 300 --rounds 3 --out outputs/android/mobile-foreground
```

The first command installs local tool dependencies, builds the current default
bundle and validates against the same-phone reference. The second measures a
real graphics-produced HDR input. **Use the foreground result for game-performance
comparisons**, not the preliminary headless timing.

Defaults are 1920x1080, `guided-vertical2-t256`, R11G11B10 input and RGBA8 sRGB output.
The retained compute output encodes sRGB explicitly through a compatible UNORM
storage view. Final blit/presentation is outside the reported GPU interval.

Use `--variant gather-reduction` or `--variant lossless` on the first command for
controls. Other useful options are `--image assets/another.exr`, `--ev`,
`--width`, `--height` and `--serial`. Use fresh output directories and run only
one phone benchmark at a time. `--fps` and `--interval-ms` are mutually exclusive.

## Read the result

- `summary.json`: Fusion and baseline medians/P95, their difference and image equality.
- `activity-result.json`: individual samples, alternating blocks and separate pass diagnostics.
- `metadata.json`: device/tool provenance, settings and hashes.

Compare matched workloads, drivers, formats and pacing. Headline intervals include
the common HDR producer plus Fusion/tonemap or baseline tonemap. Inspect both
complete-chain time and the difference; a slower baseline can make subtraction
look better without an equivalent speedup. Per-pass diagnostic timings are not
an additive frame budget. A static resident image does not model sustained gameplay.

Image validation runs outside timing. Preserve fixed quality gates and report
cross-device differences rather than relaxing thresholds to accept a candidate.
Compilation, calibration, uploads and readback are also outside GPU timing.

For optional process-local drivers and tile memory, see the
[driver setup](archive/experiments/custom-driver.md). Existing bundles are immutable
workloads: rebuild a bundle to pick up shader or default changes.
