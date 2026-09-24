# Process-local Adreno driver experiment

On the NX789J / Adreno 830 after its Android 16 update, libadrenotools successfully
loaded Qualcomm **512.842.6** inside the probe and foreground benchmark. No root,
system partition change, global driver setting or clock override was used.

| Capability | System driver | Process-local candidate |
|---|---|---|
| Driver | 512.800.40 | 512.842.6 |
| Device Vulkan API | 1.3.284 | 1.4.295 |
| Tile memory extension | absent | present |
| tileMemoryHeap feature | unavailable | true |
| Tile heap | absent | 8,355,840 bytes (7.96875 MiB) |
| queueSubmitBoundary | unavailable | false: submission-batch scope |

The community driver package is **not an official Qualcomm installer**. Its
metadata says extracted from GameHub, author StevenMX, Android API minimum 35.
It was downloaded from [AdrenoToolsDrivers v842.6](https://github.com/K11MCH1/AdrenoToolsDrivers/releases/tag/v842.6).
The [portable result](../../baselines/custom-driver-8426.json) records its URL, archive
SHA-256, every driver-library hash, libadrenotools commit and actual queried driver.
The binaries stay under ignored `.tools/`; they are not redistributed in this repo.

## Validation

- Capability probe loaded 512.842.6 and found a tile heap and enabled feature.
- Foreground `gather-reduction` at 1080p / 45 FPS, with the real graphics HDR
  producer and joint submission, completed 10 warmup + 30 measured frames per
  path. The activity itself reported 512.842.6, ruling out silent system fallback.
- Final output was byte-identical to the existing same-phone headless control.
- Fusion plus common producer median: 4.502 ms; baseline plus producer: 2.435 ms;
  increment: 2.067 ms. This short smoke run is **not a sustained performance
  comparison against the old driver**.
- An initial attempt received a window-destroy event before sampling and was
  rejected as interrupted. The retry completed normally.
- A fresh system probe afterwards still reported 512.800.40 with no tile heap.

This driver-loading experiment did not allocate resources in tile memory. A subsequent
[residency experiment](tile-memory-runtime.md) does. This experiment establishes driver
loading and basic rendering compatibility, not tile-memory correctness or savings.
Broader scenes and sustained validation remain necessary for production use.

## Reproduce

Use the existing Android NDK and APK packaging dependencies. Build the pinned
[libadrenotools](https://github.com/bylaws/libadrenotools) checkout with its submodule:

```powershell
git clone --recursive https://github.com/bylaws/libadrenotools.git .tools/mobile/libadrenotools
git -C .tools/mobile/libadrenotools checkout 8fae8ce254dfc1344527e05301e43f37dea2df80
git -C .tools/mobile/libadrenotools submodule update --init --recursive
python -m pip install cmake==4.4.3 ninja==1.13.2
$repo = (Get-Location).Path
.venv/Scripts/cmake.exe -S .tools/mobile/libadrenotools -B .tools/mobile/libadrenotools-build -G Ninja "-DCMAKE_MAKE_PROGRAM=$repo/.venv/Scripts/ninja.exe" "-DCMAKE_TOOLCHAIN_FILE=$repo/.tools/mobile/android/android-ndk-r30/build/cmake/android.toolchain.cmake" -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-29 -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"
.venv/Scripts/cmake.exe --build .tools/mobile/libadrenotools-build
```

Extract the recorded driver archive into `.tools/mobile/drivers/842.6`. Then:

```console
python -m tools.profiling.android.tile_memory --api max --surface --custom-driver .tools/mobile/drivers/842.6 --out outputs/android/tile-memory/new-custom-probe
python -m tools.profiling.android.activity outputs/android/guided-batch/gather-reduction-phone-retry/bundle --custom-driver .tools/mobile/drivers/842.6 --hdr-producer --joint-submission --frames 30 --warmup 10 --rounds 1 --out outputs/android/tile-memory/new-custom-activity
```

Use fresh output directories and an existing validated bundle. Keep the phone
unlocked and the activity foreground. Omit `--custom-driver` to rebuild the
activity with the system loader. The installed custom benchmark continues using
its bundled driver until replaced by a normal benchmark APK; other apps are unaffected.

The custom build routes every Vulkan function used by runner/activity, including
WSI, through the isolated loader; it is not linked against the system Vulkan API.
Hooks are packaged as extracted native libraries and the driver is extracted into
app-private files. The shell capability probe uses its own temporary directory.
Shader arithmetic, resource formats, timing scope and quality gates are unchanged.
