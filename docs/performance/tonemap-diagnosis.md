# Why did the 1080p tonemap take 0.97 ms?

The measured cost is dominated by the current image-access workload and is sensitive to submission pacing. It is **not evidence that the ACES rational curve costs 0.97 ms**. These findings are for the attached NX789J / Adreno 830, not Adreno 730.

All tests below use the real `tonemap_baseline` SPIR-V, 1920×1080, default EV 0 and RGBA16F output. Diagnostic controls keep the same Vulkan runner, timestamp boundaries, resource sizes and 8×8 groups. Copy preserves input fetch, exposure multiplication, conversion and output write but removes tone mapping. Fill only writes a constant. Empty executes the same group grid without image operations. Readbacks verify the controls actually produce their expected outputs.

| Input storage / pacing | Tonemap median | Copy median |
|---|---:|---:|
| RGBA32F / nominal 16 ms interval | 0.9672 ms | 0.9607 ms |
| RGBA32F / unpaced | 0.6451 ms | 0.6401 ms |
| RGBA16F / nominal 16 ms interval | 0.4755 ms | 0.4695 ms |
| RGBA16F / unpaced | 0.3843 ms | 0.3851 ms |

Removing ACES barely changes the matched pass. Narrowing input storage changes it substantially. The latter is **diagnostic only**, changes input precision, and has not been applied to the production pipeline. In particular, RGBA16F cannot retain the existing 65535 domain endpoint exactly.

The production baseline reads RGBA32F (16 bytes/pixel) and writes RGBA16F (8 bytes/pixel): **49.7664 MB of nominal texel payload per 1080p pass**, before accounting for caches, compression, transactions and other implementation details. Dividing payload by 0.9672 ms gives about **51.5 GB/s effective payload throughput**; this is not a measured DRAM counter or the GPU's bandwidth specification. RGBA16F input lowers nominal payload to 33.1776 MB, but the observed improvement is not strictly proportional to bytes, so do not reduce the explanation to a simple DRAM-bandwidth formula. Format-specific access behavior and power state remain relevant.

## Pacing and power state

An independent full-pipeline rerun with 180 warmup frames/block, 240 samples/block, three rounds and **no inter-frame sleep** measured:

| Whole chain | Median | P95 |
|---|---:|---:|
| Fusion + tone mapping | 2.2778 ms | 2.2880 ms |
| Tone mapping alone | 0.6424 ms | 0.6458 ms |

The original paced run measured 3.3032 / 0.9664 ms. The shaders and input are unchanged and same-phone validation passes. Different idle/load patterns materially affect results. A power/clock-state explanation is consistent with this, but GPU frequency sysfs access is denied: **a particular GPU clock or a frequency-locked maximum-performance result is not established**.

Even `--interval-ms 0` retains CPU submit/fence/query gaps. Baseline blocks paired with very light controls sometimes move between approximately 0.64 and 0.97 ms; aggregate medians alone can conceal this. Keep raw block samples and compare matched pacing/load histories. The unpaced value is not guaranteed peak performance.

## Workgroup and timestamp controls

| Empty-shader dispatch | Median |
|---|---:|
| 1920×1080 threads, 8×8 groups (32,400 groups), unpaced | 0.3741 ms |
| 960×540 threads rounded to 8×8 groups (8,160 groups), unpaced | 0.0958 ms |
| One 8×8 group, unpaced | 0.0022 ms |
| 1920×1080 threads, 16×16 groups (8,160 groups), unpaced | 0.1148 ms |

The empty kernel's SPIR-V body contains only `OpReturn`. The overhead scales strongly with dispatched work, so it is not a fixed 0.97 ms ADB/CPU/API cost. However, this empty-dispatch time must **not** be subtracted from tonemap or added to a bandwidth estimate: scheduling and execution overlap.

Changing the actual tonemap to 16×16 groups in a separate diagnostic shader leaves its RGBA32F-input median near **0.6438 ms** (copy 0.6420 ms), despite the smaller empty-dispatch cost. Its output is bitwise identical to the 8×8 control on this scene. Thus group-count reduction alone does not address the main cost of the current full-precision input path. Production group sizes are unchanged.

The runner now records CPU submit/wait/query wall time separately as a timestamp sanity check. In the one-group-control test, tonemap blocks measure roughly **0.645 ms GPU** versus **1.25–1.37 ms CPU**; no sample has GPU duration larger than the corresponding enclosing CPU interval. GPU conversion uses the device-reported 52.083332 ns timestamp period and its 48 valid bits. ADB, readback and the 16 ms host pacing sleep are outside the timestamp interval. The exported baseline contains one image fetch, the curve arithmetic and one image write, with no Fusion or viewer loop.

## Independent timer audit

The concern that an empty kernel should be very fast was checked separately, without assuming the existing timer is correct. The reusable audit distinguishes **zero dispatch** from dispatching 32,400 empty workgroups. It also enables `VK_EXT_calibrated_timestamps` in a separate audit process to compare the device clock with Android's `CLOCK_MONOTONIC_RAW` domain. Normal benchmark runs do not enable this extension.

The official [calibrated timestamp specification](https://docs.vulkan.org/refpages/latest/refpages/source/VkTimeDomainKHR.html) defines the device domain as the same domain and units used by command-buffer timestamp queries. Two independent ~600 ms clock comparisons measured GPU/CPU elapsed-time ratios **0.9999993718** and **1.0000001493**, with reported calibration deviations no greater than 1042 ns. All captured query ticks lay within the surrounding calibrated device-time boundaries. This rules out a large unit/frequency-conversion error in these captures; CPU submit/wait duration also encloses the GPU interval.

| Normal-mode audit | GPU median |
|---|---:|
| Two timestamp writes, no dispatch | 1.875 µs |
| Barrier only | 1.927 µs |
| One empty workgroup | 2.161 µs |
| 8,160 empty workgroups | 95.833 µs |
| 32,400 empty workgroups | 374.167 µs |
| Same 32,400 groups, without the trailing barrier | 374.062 µs |
| 16 repetitions of the 32,400-group empty dispatch | 5.96990 ms |

The 16-repeat duration is 15.955× the single duration. The large-grid cost is present with or without the trailing dependency barrier, whereas the true empty interval is only microseconds. Thus the evidence does **not** support a fixed 0.38 ms timer error. It supports actual cost associated with dispatching a large number of workgroups on this device/driver. It does not identify the precise hardware/driver scheduling mechanism.

A 16-dispatch tone batch measured 9.30469 ms total (~0.5815 ms per dispatch), versus 0.9662 ms for single submissions in that audit sequence. This further demonstrates sensitivity to batching, idle gaps and resource reuse; it is not an interchangeable replacement for the original paced number.

Raw normal/calibrated samples, clock pairs, query ticks, checks and tool hashes are in [the timer audit snapshot](baselines/adreno830-timer-audit.json). Local artifacts: `outputs/android/timer-audit-repro/`. The checks verify these captures, not every possible driver or profiler situation.

## Reproduce

First create a normal [benchmark bundle](android.md), then:

```powershell
# Continuous-load production rerun.
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --interval-ms 0 --warmup 180 --frames 240 --rounds 3 --out outputs/android/unpaced

# Copy, fill and empty controls, paced and unpaced. Use a fresh output directory.
.\.venv\Scripts\python.exe -m tools.profiling.android.diagnose --bundle outputs/android/baseline/bundle --out outputs/android/controls --frames 120 --warmup 90

# Storage-format diagnosis only; does not modify core shaders.
.\.venv\Scripts\python.exe -m tools.profiling.android.diagnose --bundle outputs/android/baseline/bundle --out outputs/android/half-controls --probes copy_probe --half-source

# Group shape and minimum-dispatch controls.
.\.venv\Scripts\python.exe -m tools.profiling.android.diagnose --bundle outputs/android/baseline/bundle --out outputs/android/groups16 --probes copy_probe empty_probe --intervals 0 --group-size 16 16
.\.venv\Scripts\python.exe -m tools.profiling.android.diagnose --bundle outputs/android/baseline/bundle --out outputs/android/onegroup --probes empty_probe --intervals 0 --empty-dimensions 1 1

# Zero dispatch, repeat scaling, CPU enclosure and independent clock calibration.
.\.venv\Scripts\python.exe -m tools.profiling.android.timer_audit --bundle outputs/android/onegroup/empty_probe-0ms --out outputs/android/timer-audit
```

Evidence snapshot: [diagnostic results and raw samples](baselines/adreno830-tonemap-diagnosis.json). Local complete artifacts are in `outputs/android/tonemap-controls`, `tonemap-half-controls`, `tonemap-empty-onegroup`, `tonemap-empty-quartergroups`, `tonemap-groups16` and `adreno830-unpaced-diagnosis`. No production precision, format, shader arithmetic or group-size optimization is claimed here.
