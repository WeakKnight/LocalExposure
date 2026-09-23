# Mobile shader baseline

Target: **Adreno 750**. Status: **portable-only; AOC unavailable**.

Portable SPIR-V code statistics are not Adreno ISA counts, cycles, occupancy or GPU timing.
Uniform branches and loops remain in the modules; sites are not per-pixel execution counts.

Source/display: [1920, 1080]; Fusion: [480, 270]; 9 levels.
Fresh-frame dispatches: 32. Logical texture payload: 85.28 MiB.

| Entry | SPV bytes | FP16 sites | FP32 sites | Sample/read/write sites | Loop sites |
|---|---:|---:|---:|---|---:|
| reduce_source | 2596 | 0 | 11 | 1/0/1 | 2 |
| fit_coefficients | 3460 | 3 | 22 | 0/3/1 | 2 |
| average_coefficients | 2236 | 0 | 2 | 0/1/1 | 2 |
| apply_exposure | 4108 | 0 | 34 | 1/2/3 | 0 |
| setup_weights | 4980 | 0 | 49 | 0/1/2 | 0 |
| downsample | 2404 | 0 | 14 | 4/0/1 | 0 |
| reconstruct | 3392 | 0 | 11 | 2/2/1 | 0 |
| convert_exposure | 4572 | 0 | 34 | 1/2/1 | 0 |
| compute_main | 4656 | 9 | 17 | 3/0/3 | 0 |

Adreno measurements and raw command logs are in report.json and each pass directory.
AOC metrics are null when unavailable; even successful AOC analysis does not measure frame time.
Calibration is initialization-only and excluded. Static-image viewer caching is excluded.
