# Mobile shader analysis

Latest work: [ten lossless optimization experiments](experiments/ten-rounds.md), with two retained changes and eight rejected/deferred/reverted candidates. Current snapshots: [Adreno 730](baselines/a730-ten-rounds.md) and [G720 cross-check](baselines/g720-ten-rounds.md). These are compile-time findings and source-work reductions, not measured phone speedups.

Primary optimization target: **Snapdragon 8 Gen 1 / Adreno 730**. The default CLI target is now `a730`; see [the A730 baseline](baselines/archive/a730-aoc.md). Run `python tools/profiling/mobile_profile.py --require-aoc` to regenerate it. Use `--arch a750` explicitly for the retained Adreno 750 reference. Cross-target baseline comparisons are rejected.

All nine A730 entries compile with zero scratch and 100% ALU fiber occupancy. Optimization candidates are the guided filter neighborhood reads and full-resolution exposure application; instruction counts alone do not establish frame-time ranking. AOC projects 56.3% exposed long-latency-sync cycles for `average_coefficients` and 56.4% texture-instruction cycles for `fit_coefficients`. These percentages are per-shader model outputs, not measured frame shares. Preserve sample/accumulation order and FP32-sensitive math during lossless optimization; continue validating against the original GPU results. Real sustained 8 Gen 1 performance still requires phone timestamps and thermal control.

Secondary target: **Immortalis-G720**, analyzed with **Mali Offline Compiler 2026.5.0 (922df8)**, driver model **r56p1-00rel0**, hardware revision **r0p0**. All nine runtime entries compile. See [the Mali baseline](baselines/archive/g720-mali.md).

Adreno 750 is now analyzed with **AOC 7.0.15**, compiler **E17.52.07.00**. See the [Adreno baseline](baselines/a750-aoc.md). All nine entries compile, report zero scratch memory and 100% ALU fiber occupancy. These vendor metrics have different definitions from Mali occupancy and register counts. The original portable-only baseline is retained for history.

## A730 optimization round 2: shared coefficient tile

Current results: [A730](baselines/archive/a730-tile.md), [G720 cross-check](baselines/archive/g720-tile.md). `average_coefficients` stages a 12x12 RG32F tile for each 8x8 output group, including its two-pixel halo. All lanes load clamped inputs and reach the barrier before out-of-bounds lanes return. Each valid pixel then adds the same 25 FP32 values in the original row-major order. There is no separable filter or reassociation of sums.

For a full group, source texture load requests fall from 64x25=1600 to 144 (91% fewer). This is an instruction-level request count, **not a 91% DRAM bandwidth reduction**, because texture caching already shares data. The change adds 1152 bytes of shared memory per group, 25 shared reads per output and one group barrier. Partial groups still stage the full tile, so tiny images can do more source loads than the original.

On A730, main instruction sites increase from 274 to 333, register footprint remains 5, scratch remains 0 and ALU fiber occupancy remains 100%. Projected exposed long-latency-sync cycles drop from 56.3% to 23.9%, while exposed short-latency-sync cycles rise from 1.1% to 14.0%. These percentages have different total-cycle denominators and do not prove a timing improvement. This is a source-read reduction candidate for the chosen A730 target; phone timing is still required.

The G720 cross-check is mixed: work registers fall from 32 to 30 with no spill and 100% occupancy, but load/store cycle estimates rise from 2 to 20 while texture estimates fall from 3.125 to 0.375. It is not established as a Mali performance improvement. Keep the prior baseline for comparisons.

`tests/test_average.py` compares the tiled pass with a frozen original shader on eight shapes, including partial groups, 1D/tiny images, 480x270 and 481x271. Signed wide-range and zero FP32 coefficient inputs produce bit-identical local GPU output. Guided/reduction/precision regressions also pass. Mobile-driver output and timing remain unmeasured.

To reproduce: `python tools/profiling/mobile_profile.py --require-aoc --out outputs/mobile/a730-tile`. The current baseline is `docs/performance/baselines/archive/a730-tile.json`; the previous A730 snapshot is retained.

## A730 optimization round 3: shared guided-fit inputs

Latest snapshots: [A730](baselines/archive/a730-fit-tile.md), [G720](baselines/archive/g720-fit-tile.md). `fit_coefficients` now stages a 12x12 `float2` tile containing the original FP32 log-luminance guide and the original half-rounded exposure EV. Every half value is exactly representable in the float shared component. Center subtraction stays FP32 before rounding to half; products, accumulation order, covariance subtraction and regularization are unchanged. The pair enables vector shared loads instead of separate scalar arrays.

For a complete 8x8 group, source texture requests fall from 3264 (64 center reads plus 2x25x64 neighbor reads) to 288; log2 evaluations fall from 1600 to 144. This adds 1152 bytes shared storage and one group barrier, plus shared reads for regression. These are source-operation counts, not measured memory traffic. Partial groups still stage the full tile. Out-of-bounds lanes return only after the cooperative load and barrier.

Compared with round 2, A730 main instructions fall **625 -> 578**; register footprint rises **6 -> 9**; scratch stays **0**, ALU fiber occupancy stays **100%**. Projected exposed long-latency-sync cycles move **26.8% -> 11.0%**, with exposed short-latency-sync cycles **1.3% -> 4.1%**. Percentages are not directly convertible to speedups. All other A730 pass metrics are unchanged.

G720 is again a tradeoff: work registers **56 -> 63**, occupancy remains **50%**, no spills, texture estimates **3.875 -> 0.750**, load/store estimates **2 -> 20**. This version targets A730 and does not establish a Mali speedup. Neither target has phone timing measurements.

`tests/test_fit.py` compares with a frozen pre-change shader on eight shapes and both wide-range and almost-flat guides, including exposure values across +/-12 EV and identity exposure. RG32F output is bit-identical on the local GPU in all 16 cases. All **32 tests** pass, including existing output/precision and previous optimization regressions. Use `--compare docs/performance/baselines/archive/a730-fit-tile.json` for subsequent A730 work. Earlier snapshots remain available.

## Mali setup (Windows)

```powershell
./tools/profiling/install_mali.ps1
.\.venv\Scripts\python.exe tools/profiling/mali_profile.py
.\.venv\Scripts\python.exe tools/profiling/mali_profile.py --compare docs/performance/baselines/archive/g720-mali.json --out outputs/mobile/mali-candidate
.\.venv\Scripts\python.exe -m unittest tests.test_mobile_profile tests.test_mali_profile
```

The installer script downloads the official Performance Studio 2026.5 MSI and verifies SHA256 `f47d3c3e2972cb45902ae746cca99d9d0eb3053cb8a993afa68d269a873e9859`, published in [Arm's manifest](https://artifacts.tools.arm.com/arm-performance-studio/metadata/manifest_v2.json). Administrative extraction keeps the tools under `.tools/mobile/arm-2026.5`; it does not install the suite or modify PATH. Download size is about 663 MiB. No Arm login is needed for this public artifact.

The analysis script defaults to Immortalis-G720; use `--core Mali-G720` or another target listed by `malioc --list` for a different GPU. It accepts `--malioc` or `MALIOC_PATH`, otherwise discovers the local extracted tool. First install pinned Slang with `tools/profiling/mobile_profile.py --download-tools` on a fresh checkout.

Each pass is exported directly from current Slang source and analyzed using Vulkan SPIR-V, compute stage, explicit entrypoint and detailed JSON output. Raw JSON, compiler logs, supported targets and GPU information are retained in `outputs/mobile/mali/`. Reports preserve every compiled variant, pipeline cycle estimates, registers, occupancy, spills, FP16 percentage, notes and warnings. Compiler EXE/DLL hashes include nested backend binaries. Comparison rejects different compilers, targets, configuration or driver models.

**Initial findings:** `reduce_source` uses 64 work registers, 50% occupancy and 12 bytes allocated to stack spills. `fit_coefficients` uses 56 registers, 50% occupancy and no spills. Other entries report 100% occupancy and no spills. FP16 arithmetic is 2% for guided fitting and 21% for display; the remaining entries report 0%. FP16 texture storage and conversion instructions do not imply FP16 arithmetic.

These are static compiler results, not measured phone performance. In particular, loop/branch behavior and memory latency prevent translating reported instruction cycles into milliseconds. Do not sum overlapping pipeline cycles or rank full-frame costs from per-shader cycle numbers alone. The baseline preserves the current shader code, including debug branches and both baseline/final color outputs.

### Lossless reduction optimization

The [spill-free baseline](baselines/archive/g720-no-spill.md) changes only the reduction outer loop bound from literal `4` to a uniform `reductionRows`, always bound to **4** by the host. It is not a user setting or specialization constant. Sampling locations, 16 samples, FP32 precision, row-major addition order and division by 16 remain unchanged. This prevents the constant-bound optimization that caused excessive register pressure in this compiler; unroll/loop hints alone did not help.

On the same G720 compiler/driver model, `reduce_source` falls from **64 to 32 work registers**, **50% to 100% occupancy**, and **12 to 0 allocated spill bytes**. All nine passes are now spill-free; other pass metrics are unchanged. Because the compiler now sees a runtime loop bound, the reduced cycle figures must **not** be interpreted as a proportional speedup: the compiler does not know the host always supplies four rows.

`python -m unittest tests.test_reduction tests.test_guided tests.test_precision` passes eight tests. The frozen original and updated reduction produce bit-identical RGBA32F output on the local GPU for seven shapes (including odd/tiny/1080p) and HDR values, zeros and clamped negatives. This establishes local GPU regression evidence, not a universal cross-driver bitwise guarantee; no Mali phone timing or output comparison has been performed. The original baseline remains available for comparison. To compare future changes against this version, use `--compare docs/performance/baselines/archive/g720-no-spill.json`.

## Reproduce

```powershell
.\.venv\Scripts\python.exe tools/profiling/mobile_profile.py --download-tools
.\.venv\Scripts\python.exe -m unittest tests.test_mobile_profile
```

The first command downloads official Slang 2026.12 (matching SlangPy's embedded compiler), verifies its pinned ZIP SHA256, and exports all nine runtime compute entries. It uses SPIR-V 1.3, `-O3`, preserved entry names, and Slang's default SPIR-V validation. Each pass has binary SPIR-V, readable assembly, exact commands, hashes and compiler logs under `outputs/mobile/a750/`. The exported modules analyze the current source; they are not captures of the SlangPy runtime driver binaries.

The workload is a fresh 1920x1080 frame with a same-sized display, Fusion scale 4, up to 16 levels, 8x8 groups, and the current guided filter. Odd dimensions use ceil division before the normal floor-sized mip chain. Calibration and the viewer's static-image cache are excluded. Runtime uniform branches are retained, including debug display and coarse reconstruction paths. Static instruction sites are counted once regardless of loop trip counts or vector width; FP counts include float arithmetic and extended math, not loads, comparisons or conversions.

Logical texture storage is a payload estimate, **not measured bandwidth or driver allocation**. It includes source, all pyramids, guided buffers, both base/final display colors, exposure maps, one RGBA8 display texture and the 2 KiB inverse LUT. It excludes alignment, swapchain and initialization resources. The current dual base/final tonemapping output is included; this is the viewer implementation, not a stripped production integration.

## Adreno Offline Compiler

```powershell
.\.venv\Scripts\python.exe tools/profiling/mobile_profile.py --aoc 'C:\path\aoc.exe' --require-aoc
# Alternatively set AOC_PATH to the executable path.
```

The adapter invokes `-api=Vulkan -arch=<target> -cs -entry_point_cs ENTRY FILE.spv -dump=all`, following the AOC integration in Unreal Engine's `ShaderCompilerCommon.cpp`. It preserves stdout/stderr, executable hash and commands. Numeric colon/equal-delimited statistics are retained, including repeated sections. An unsupported target, compilation failure or missing recognized instruction count fails the run; it never silently substitutes another GPU. This adapter has been validated against AOC 7.0.15 on all nine entries. Preamble, main shader and performance projection statistics are retained as separate sections. Check raw output and installed `OfflineCompiler.html` before interpreting the numbers.

Without AOC, hardware metrics are JSON null and reports explicitly say portable-only. `--require-aoc` returns nonzero after saving the portable results if AOC is absent. AOC statistics are static estimates and do not supply measured mobile milliseconds, energy or sustained performance.

Acquisition checked on 2026-09-23: the initial account received **Software Restricted**. After switching to the company account, the [official AOC product page](https://softwarecenter.qualcomm.com/catalog/item/Adreno_GPU_Offline_Compiler) became accessible and offered **7.0.15**, Windows/X86, **43.29 MB**, released **2026-09-14**. The downloaded ZIP was verified readable (45,390,524 bytes) and installed under `.tools/mobile/aoc-7.0.15/installed`. Its locally measured SHA256 is `ef1f41db8af8f2f8dd6804c0ae0e5fc1859a314d2c2f1e52fe6794eda2ebce66` (not a vendor-published checksum). The package is not committed. The script automatically discovers this installation; run `python tools/profiling/mobile_profile.py --arch a750 --require-aoc --out outputs/mobile/a750-aoc`. Raw output, commands, version and executable hash are retained.

## Track changes

```powershell
.\.venv\Scripts\python.exe tools/profiling/mobile_profile.py --compare docs/performance/baselines/archive/a730-aoc.json --out outputs/mobile/candidate
```

Comparison rejects changes in target/configuration/compiler/AOC identity and reports portable code-site deltas. Keep raw AOC output for hardware comparisons; repeated AOC sections are not summed automatically. Use these reports to locate candidates, then validate visual quality with the existing precision/guided/Z-curve tests. In particular, FP16 storage is not evidence of FP16 arithmetic, and fewer IR sites do not guarantee a faster shader.

For a measured baseline, deploy the same pipeline to the target phone and record GPU timestamp durations per pass after warm-up, driver/build versions, resolution, thermal state and median/p95 across repeated frames. Disable the static-frame cache and account for pass barriers and memory traffic. The desktop viewer's timing is not an Adreno measurement.

## References

- [Qualcomm Software Center](https://softwarecenter.qualcomm.com/)
- [Official download API workflow](https://api-docs.qualcomm.com/qualcomm-software-center/usage-guide)
- [Official account requirements](https://api-docs.qualcomm.com/qualcomm-software-center/getting-started)
- [Qualcomm's AOC overview](https://www.qualcomm.com/developer/blog/2025/08/optimize-performance-and-graphics-for-adreno-gpu-low-power-gaming)
- [Slang 2026.12 release](https://github.com/shader-slang/slang/releases/tag/v2026.12)
- Unreal Engine: `Engine/Source/Developer/ShaderCompilerCommon/Private/ShaderCompilerCommon.cpp`, `CompileShaderOffline_Adreno`.
