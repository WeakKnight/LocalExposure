# Adreno 830: first device benchmark

Follow-up: [controlled tonemap diagnosis](../tonemap-diagnosis.md) found nearly equal copy/tonemap costs and strong pacing sensitivity. The original numbers below remain valid for their stated paced setup; they are not fixed or peak GPU throughput.

Measured on the attached **NX789J / SM8750 / Adreno (TM) 830**, Android 15. **This is not an 8 Gen 1 / Adreno 730 result.** [Workflow](../android.md) · [Raw samples, source hashes and validation](adreno830-device.json).

Input: `veranda_4k.exr`, resized to 1920×1080 RGBA32F before upload. Fusion is 480×270 with nine pyramid levels and 31 production dispatches. Global EV 0, contrast scales 0.8 (±1.2 EV brackets), sigma 0.2, fitted Z curve and 1024-entry R16F inverse LUT. No viewer work is measured.

Three alternating Fusion/baseline rounds, 60 warmup and 120 measured frames per block, nominal 16 ms submission interval. GPU timestamp period 52.0833 ns. USB charging; stock clocks/power policy. GPU frequency access was denied, so these results do not establish full-clock throughput. Raw battery/thermal snapshots are retained locally in `outputs/android/adreno830-1080p-baseline/telemetry.jsonl`.

| Whole-chain measurement | Median | P95 | Samples |
|---|---:|---:|---:|
| Fusion + final tone mapping | 3.3032 ms | 3.3302 ms | 360 |
| Tone mapping alone | 0.9664 ms | 0.9809 ms | 360 |

The difference of medians is **2.3368 ms**, descriptive only: the two workloads can trigger different DVFS states. The current input is static and resident; every iteration still recomputes the entire chain.

Largest separately instrumented passes:

| Diagnostic pass | Median |
|---|---:|
| `reduce_source` | 1.6087 ms |
| `apply_exposure_production` (includes tone mapping) | 0.9912 ms |
| `setup_weights` | 0.1161 ms |
| `average_coefficients` | 0.1041 ms |
| `fit_coefficients` | 0.1032 ms |

Reduction is the largest measured individual pass on this device/workload. These diagnostics include barriers and timestamp serialization; do not sum them as the production total or interpret the entire apply pass as Local Exposure overhead.

## Numerical checks

**Same-phone production versus viewer-reference: bitwise PASS** for mip 0 of all eight readback stages. The reference executes in a separate process after timing, so its debug resources never enter the measured process. A 321×181 phone smoke run also passes, covering odd dimensions and partial workgroups. All 35 desktop tests pass, including frozen-shader regressions and a production-entry test allowing at most one FP16 step on desktop.

**Desktop portability check: WARNING.** Final color RMSE is 0.0001443, maximum absolute error 0.0268555. Low-resolution exposure maximum deviation is 0.53682 EV (RMSE 0.006163 EV). Thresholds are retained unchanged; this is not labelled cross-device numerical equivalence.

Inspection found that desktop reduced RGB matches an exact 4×4 box mean for this aligned input, while phone reduced RGB differs (RMSE 0.0007099; maximum 0.04857 in HDR units). This is consistent with vendor sampling differences, though it does not isolate a particular driver implementation detail. The largest exposure discrepancies occur where reconstructed lightness lies near the inverse curve's white endpoint: roughly 1e-4 lightness changes can cause large EV changes. This portability sensitivity remains open; the benchmark does not modify the algorithm to hide it.

Compiler identity, input/shader hashes, calibration, raw timestamp arrays and per-stage errors are in the JSON sidecar. Local full artifacts are under `outputs/android/adreno830-1080p-baseline/`. There is no sustained-gameplay, maximum-clock, or Adreno 730 performance claim.
