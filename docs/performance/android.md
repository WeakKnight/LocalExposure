# Android GPU benchmark

SlangPy prepares the EXR, fitted Z curve, R16F inverse LUT and desktop reference. A native Vulkan runner executes the **production** pipeline using SPIR-V compiled from the same repository shaders. Python stays on the host. The headless runner needs no APK or display surface. For game-oriented timing, use the foreground NativeActivity workflow below; neither workflow requires root.

## Run

From the repository root, with an authorized USB-debugging connection:

```powershell
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --bootstrap
```

The first run installs official Platform Tools, pinned NDK r30, Slang 2026.12 and the header-only nlohmann/json 3.12.0 dependency under `.tools/mobile/`. NDK and JSON archives are checksum-verified. Platform Tools uses Google's rolling download; its version and executable SHA256 are recorded. Nothing is added to PATH. Currently supports Windows hosts and arm64 Android devices with Vulkan 1.2, FP16 arithmetic, required storage-image formats and compute timestamps.

```powershell
# 1080p: 60 warmup frames per block, 120 samples per block, 3 alternating rounds.
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --out outputs/android/baseline

# Partial workgroups and odd-size mip chains.
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --width 321 --height 181 --warmup 2 --frames 5 --rounds 1 --interval-ms 0

# Longer run; inspect thermal drift instead of assuming steady clocks.
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --warmup 120 --frames 1200 --rounds 3
```

Use `--serial SERIAL` for multiple phones, `--adb PATH` for another ADB installation, and `--image Assets/another.exr --ev 0` to change input. The EXR is bilinearly resized **before upload**; requested dimensions describe actual shader work, not viewer window size. Default pacing is a nominal 16 ms submission interval; `--interval-ms 0` is a different, unpaced throughput workload. Do not run concurrent instances: the tool owns `/data/local/tmp/local-exposure-benchmark`.

## Game formats and bandwidth

```powershell
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --source-format r11g11b10_float --output-format rgba8_srgb --fps 45 --out outputs/android/game-formats
.\.venv\Scripts\python.exe -m tools.profiling.android.bandwidth --out outputs/android/bandwidth
```

`--fps` and `--interval-ms` are mutually exclusive. Legacy format defaults remain unchanged for reproducibility. The game-format path uses packed R11G11B10 input and a real RGBA8 sRGB color attachment. A fullscreen fragment shader outputs linear color; hardware encodes sRGB. Attachment storage is included, while swapchain acquisition and presentation are excluded. This path requires a graphics-capable queue.

At 1080p this path runs 30 compute dispatches and one draw. Same-phone validation keeps core stages bitwise and allows at most one UNORM code difference for final sRGB8 output against the viewer compute output resolved into an sRGB attachment. The recorded run is bitwise identical even at the final output. Desktop thresholds remain unchanged.

See [bandwidth results and accounting](bandwidth.md) for effective throughput versus nominal traffic.

## Fused production candidate

Add `--fused-guided` to the game-format command to use the lossless production candidate. At 1080p it uses 18 compute dispatches and one draw instead of 30 dispatches and one draw. The original graph remains the default control and the viewer reference. `--compact` alone retains separate guided fitting/averaging for diagnostics.

This candidate keeps FP32 luminance/guide and pyramid values, removes constant alpha storage, combines the two downsample chains per level, and fuses finest reconstruction, inverse exposure, guided fitting and averaging in a 16x16 output tile. It does not change the exposure curve or use an exposure-equals-one shortcut. The reference process executes the entire original graph; it does not reuse the optimized intermediate values. Removed exposure/coefficient images are not read back or included in validation; retained averaged coefficients and final output are checked against the original graph. Desktop all-mip and edge-tile regression tests provide additional coverage.

See [the optimization results](fusion-compaction.md) for bandwidth assumptions, timing comparisons and unmet targets.

## Approximate mobile candidate

The latest [two-hour optimization](twohour-optimization.md) uses `--variant gather-reduction`: a residual pyramid, precomputed low-resolution EV, separable guided moments and full 4x4 source integration with texture gathers. The original control remains independent. The older `half-aux-compute` results below are historical.

The [goal-mode experiments](mobile-goal.md) retain `--variant half-aux-compute`: full reduction and guided windows, half auxiliary weights/averaged coefficients, and explicit sRGB compute output through a compatible storage view. Four compute-only 1080p HDR scenes measured 0.586-0.613 ms incremental GPU time and 1.026 GB/s incremental texture-sweep traffic on Adreno 830. A subsequent foreground graphics-context audit measured approximately 2.81 ms incremental for the same candidate: the earlier compute-only times do not establish game performance. See the linked report for quality images, the matched compute control and swapchain integration constraints. These times do not apply to the earlier fragment-output path.

Approximate presets generate `comparison.png`, `worst-crop.png` and explicit quality metrics; a failed image gate makes the command fail. `reduction4`, `radius1` and `mobile` are rejected experiments, kept only for reproducibility. The default lossless validation remains unchanged.

## Foreground graphics-context measurement

Headless compute-only timing is not sufficient on the attached phone: a preceding graphics draw changes subsequent compute timings substantially. Use this matched setup for new game-performance claims:

```powershell
# Independent same-phone image reference and production SPIR-V bundle.
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --variant gather-reduction --image Assets/veranda_4k.exr --source-format r11g11b10_float --output-format rgba8_srgb --fps 45 --out outputs/android/mobile-candidate

# Real graphics HDR producer, guided Fusion or matched tonemap, blit and present.
.\.venv\Scripts\python.exe -m tools.profiling.android.activity outputs/android/mobile-candidate/bundle --bootstrap --hdr-producer --joint-submission --frames 180 --warmup 60 --rounds 3 --fps 45 --out outputs/android/mobile-foreground

# Sustained alternating Fusion/baseline blocks, about eight minutes plus setup.
.\.venv\Scripts\python.exe -m tools.profiling.android.activity outputs/android/mobile-candidate/bundle --hdr-producer --joint-submission --frames 2700 --warmup 120 --rounds 4 --fps 45 --out outputs/android/mobile-sustained
```

`--bootstrap` installs pinned Android build tools 35.0.1, platform 35 and Zulu JRE 17 beneath `.tools/`, with SHA256 verification. It builds and installs the local debug package `org.localexposure.benchmark`. Keep its foreground activity visible; interruption invalidates a run. `--serial` selects a phone. Do not run another phone benchmark concurrently.

Every frame, `--hdr-producer` draws the resident input into the actual R11G11B10 source attachment. With `--joint-submission`, GPU timestamps include the common HDR producer plus Local Exposure + tonemap, or the same producer plus matched tonemap. Their difference is the incremental result; blit/presentation are outside both intervals. There is no CPU fence wait between the producer and postprocess. Omit `--joint-submission` for the separate-submission diagnostic: its core timestamps exclude the producer, which has a separate measured interval. Never compare the two modes' total times directly. Joint mode's raw `context_gpu_ms` zeros are placeholders, not measurements of zero producer cost.

Both modes record CPU full-frame work time and use a real RGBA8 sRGB surface, but the compute result is blitted to the swapchain: this does **not** validate direct storage writes to a swapchain image. It is a synthetic graphics workload with a static source, not a complete game.

`activity-result.json` retains every sample and AB/BA block, `summary.json` reports complete-chain and baseline statistics, `metadata.json` records the bundle/library hashes and settings, and `telemetry.jsonl` captures battery/thermal state. The final readback must exactly match the corresponding headless candidate. Inspect block drift and both total and incremental times; subtracting an inefficient baseline can misleadingly improve the increment.

Optional `--no-graphics-context`, `--separate-queue`, `--dedicated-compute` and `--graphics-draws` switches are context diagnostics. Keep their results separate from the default HDR-producer contract.

Desktop spatial/temporal stress screening is complementary:

```powershell
.\.venv\Scripts\python.exe -m tools.profiling.android.quality_sweep --variants gather-reduction --game-format --width 512 --height 288 --out outputs/android/stress-even.json
.\.venv\Scripts\python.exe -m tools.profiling.android.quality_sweep --variants gather-reduction --game-format --out outputs/android/stress-odd.json
```

The command fails on a fixed spatial image gate or non-finite intermediates. It also reports frame-difference errors for moving edges and changing exposure; these are desktop comparisons, not phone animation captures.

## Measurement contract

- Every frame recomputes reduction, weights, both pyramids, reconstruction, inverse exposure, guided fitting/averaging and final exposure application. Viewer caches are bypassed. At 1920×1080 the default compute-output path uses **31 dispatches**, Fusion resolution 480×270 and nine pyramid levels.
- The default path writes final linear SDR RGBA16F only; the game-format path writes RGBA8 sRGB. Comparison color, exposure-map writes, display/UI and presentation are excluded.
- Fusion totals include tone mapping. A matched baseline executes the same tone operator/output write without Local Exposure. The difference of medians is descriptive, not frequency-locked incremental cost.
- Whole-chain timestamps and per-pass diagnostics are separate runs. Diagnostic timestamps include the dispatch and dependency barrier and can serialize stages. Do **not** sum them as an uninstrumented frame total.
- Uploads, calibration, compilation, pipeline creation, command recording, ADB, CPU waits, reference execution and readback are outside GPU timestamp intervals. Resident resources and command buffers are reused; shader work is never skipped.
- Blocks alternate Fusion/baseline and baseline/Fusion across rounds. Raw samples, block summaries, median and P95 are retained. Battery/thermal snapshots are polled about every five seconds. Restricted frequency paths remain explicit telemetry errors; no clock is guessed or forced.
- Images use GENERAL layouts and explicit compute/graphics dependencies. This is a conservative standalone baseline; renderer integration can share resources and use different scheduling/layouts.

One static, resident EXR does not model animated-scene cache behavior, concurrent rendering, thermal equilibrium, sustained gameplay or maximum clocks.

The initial 0.97 ms tonemap measurement is pacing-sensitive and nearly matched by a pure copy. See the [controlled diagnosis](tonemap-diagnosis.md): continuous submission measures about 0.64 ms with the same production formats. Record and match pacing before drawing conclusions about the tone operator. New runs also record CPU submit/wait/query time separately for timestamp sanity checks; it is not included in GPU milliseconds.

The diagnosis also includes a separate zero-dispatch and calibrated-clock audit. Zero dispatch measures approximately 2 µs, and GPU/CPU clock slopes agree within one part per million in the recorded run; the large-grid empty-shader duration must not be described as timer overhead.

## Validation

After the measured process exits, an **untimed separate process** runs the existing viewer application entry on the same phone. Debug textures exist only in that second process. Mip 0 of reduction, luminance, weights, reconstruction, exposure, coefficients, averaged coefficients and final color is read back. Acceptance requires finite output and bitwise same-phone agreement at these stages, with the sRGB8 final-output exception described above. This checks the production/debug separation; it is not an independent proof of the algorithm. Frozen shader and CPU reference tests remain in `tests/`.

Desktop SlangPy is a separate portability check with fixed thresholds and reported actual errors. `--require-desktop-match` turns its warning into a command failure. Cross-vendor sampling/transcendental differences can be amplified near the inverse curve's white endpoint. The Adreno 830 1080p run has such a warning; this remains an unresolved numerical concern, not a speedup or a reason to widen thresholds.

The shared shader refactor passes existing frozen-reference tests. A desktop production-entry test permits at most one FP16 representable step because removing debug outputs can change backend arithmetic scheduling; the measured full-size phone scene is bitwise identical. No exposure-value-specific fast path was added.

## Results and comparisons

New runs go under `outputs/android/`; completed directories cannot be overwritten.

| File | Contents |
|---|---|
| `report.md` | Totals, pass diagnostics, validation and limitations |
| `timings.json` | Every GPU sample, timestamp properties and detected GPU/driver |
| `summary.json` | Statistics and per-round summaries |
| `metadata.json` | Device/build, tool hashes/commands, Git revision/working-tree state |
| `telemetry.jsonl` | Battery/thermal snapshots and frequency-access failures |
| `validation.json` | Same-phone checks and separate desktop errors |
| `bundle/manifest.json` | Resource graph, input/shader hashes, calibration and compile commands |
| `bundle/*.reflection.json` | Slang reflection used for Vulkan binding/constant layout |
| `bundle/*.bin` | Input and reference/readback data |

For before/after tests, match phone, driver, input hash, dimensions, calibration, toolchain, warmup, pacing and thermal/power conditions. Check whole-chain and per-round samples before pass diagnostics. A different Adreno model requires a separate baseline; no automatic speedup verdict is issued.

The attached phone is **NX789J / SM8750 / Adreno 830**, not Adreno 730. See the [first measured snapshot](baselines/adreno830-device.md). Connecting an 8 Gen 1 phone uses the same workflow with its own device-labelled report.

## Upstream support and tools

guoxx's Android contributions include [slang-rhi #607](https://github.com/shader-slang/slang-rhi/pull/607) (Vulkan loader/surfaces), [slang-rhi #638](https://github.com/shader-slang/slang-rhi/pull/638) (Android build configuration), [Slang #9805](https://github.com/shader-slang/slang/pull/9805) (cross-compilation presets) and [SlangPy #701](https://github.com/shader-slang/slangpy/pull/701) (downstream SPIR-V disassembler configuration).

The inspected SlangPy main checkout did not provide a packaged Android Python deployment workflow. This tool therefore uses host SlangPy and native Android Vulkan; it does not claim to deploy SlangPy or slang-rhi on the phone.

Sources: [Platform Tools](https://developer.android.com/tools/releases/platform-tools), [NDK](https://developer.android.com/ndk/downloads), [Slang 2026.12](https://github.com/shader-slang/slang/releases/tag/v2026.12), [nlohmann/json 3.12.0](https://github.com/nlohmann/json/releases/tag/v3.12.0).
