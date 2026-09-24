# Android benchmark

SlangPy prepares images and calibration on the host. A native Vulkan runner
executes the production shaders on Android. The tooling currently supports
Windows hosts and arm64 Android devices with the required Vulkan/FP16 features.
Connect an authorized USB-debugging device and keep it unlocked for foreground runs.

## Run

From the repository root with the project Python environment active:

```console
python -m tools.profiling.android.benchmark --bootstrap --fps 45 --out outputs/android/mobile
python -m tools.profiling.android.activity outputs/android/mobile/bundle --bootstrap --hdr-producer --joint-submission --fps 45 --warmup 60 --frames 600 --rounds 3 --out outputs/android/mobile-foreground
```

The first command installs local tool dependencies, builds the current default
bundle and validates against the same-phone reference. The second measures a
real graphics-produced HDR input. **Use the foreground result for game-performance
comparisons**, not the preliminary headless timing.

Defaults are 1920x1080, `guided-packed-coefficients`, R11G11B10 input and RGBA8 sRGB output.
The retained compute output encodes sRGB explicitly through a compatible UNORM
storage view. Final blit/presentation is outside the reported GPU interval.

Use `--variant guided-coefficient-layout` or `--variant lossless` on the first command for
controls. Other useful options are `--image Assets/another.exr`, `--ev`,
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

## Optional process-local Adreno driver

The current recorded results use Qualcomm 512.842.6 loaded only in the benchmark
process through libadrenotools. This does not replace the phone's system driver.
System-driver results are a separate configuration. The community package and
exact hashes/loader revision are recorded in [driver provenance](baselines/driver.json).
Downloaded tools/drivers stay under ignored `.tools/` and are not redistributed.

With the Android bootstrap complete, build the pinned loader once on Windows:

```powershell
git clone --recursive https://github.com/bylaws/libadrenotools.git .tools/mobile/libadrenotools
git -C .tools/mobile/libadrenotools checkout 8fae8ce254dfc1344527e05301e43f37dea2df80
git -C .tools/mobile/libadrenotools submodule update --init --recursive
python -m pip install cmake==4.4.3 ninja==1.13.2
$repo = (Get-Location).Path
.venv/Scripts/cmake.exe -S .tools/mobile/libadrenotools -B .tools/mobile/libadrenotools-build -G Ninja "-DCMAKE_MAKE_PROGRAM=$repo/.venv/Scripts/ninja.exe" "-DCMAKE_TOOLCHAIN_FILE=$repo/.tools/mobile/android/android-ndk-r30/build/cmake/android.toolchain.cmake" -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-29 -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"
.venv/Scripts/cmake.exe --build .tools/mobile/libadrenotools-build
```

Extract the recorded driver package to `.tools/mobile/drivers/842.6`, then add
`--custom-driver .tools/mobile/drivers/842.6` to the foreground command. Check
`metadata.json` for the actual loaded driver and retain the headless/foreground
image-equality check; a mismatch invalidates that comparison. Omit the option to
build a system-driver activity. Other applications are unaffected.

For a controlled A/B comparison, prepare fresh bundles for the default and
`guided-coefficient-layout`, then run default/control/default with identical
formats, driver, pacing, warmup and frame counts. Each foreground invocation
also measures its matched no-LE baseline. Existing bundles are immutable;
rebuild to pick up shader or default changes.
