# Android GPU benchmark

SlangPy prepares the EXR, fitted Z curve, R16F inverse LUT and desktop reference. A native Vulkan runner executes the **production** pipeline using SPIR-V compiled from the same repository shaders. Python stays on the host. No APK, root access, display surface or game-engine integration is required.

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

## Measurement contract

- Every frame recomputes reduction, weights, both pyramids, reconstruction, inverse exposure, guided fitting/averaging and final exposure application. Viewer caches are bypassed. At 1920×1080 this is **31 dispatches**, Fusion resolution 480×270 and nine pyramid levels.
- Production writes final linear SDR RGBA16F only. Comparison color, exposure-map writes, display/UI and presentation are excluded.
- Fusion totals include tone mapping. A matched baseline executes the same tone operator/output write without Local Exposure. The difference of medians is descriptive, not frequency-locked incremental cost.
- Whole-chain timestamps and per-pass diagnostics are separate runs. Diagnostic timestamps include the dispatch and dependency barrier and can serialize stages. Do **not** sum them as an uninstrumented frame total.
- Uploads, calibration, compilation, pipeline creation, command recording, ADB, CPU waits, reference execution and readback are outside GPU timestamp intervals. Resident resources and command buffers are reused; shader work is never skipped.
- Blocks alternate Fusion/baseline and baseline/Fusion across rounds. Raw samples, block summaries, median and P95 are retained. Battery/thermal snapshots are polled about every five seconds. Restricted frequency paths remain explicit telemetry errors; no clock is guessed or forced.
- Images use GENERAL layouts and explicit compute dependencies. This is a conservative standalone baseline; renderer integration can share resources and use different scheduling/layouts.

One static, resident EXR does not model animated-scene cache behavior, concurrent rendering, thermal equilibrium, sustained gameplay or maximum clocks.

## Validation

After the measured process exits, an **untimed separate process** runs the existing viewer application entry on the same phone. Debug textures exist only in that second process. Mip 0 of reduction, luminance, weights, reconstruction, exposure, coefficients, averaged coefficients and final color is read back. Acceptance requires finite output and bitwise same-phone agreement at these stages. This checks the production/debug separation; it is not an independent proof of the algorithm. Frozen shader and CPU reference tests remain in `tests/`.

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
