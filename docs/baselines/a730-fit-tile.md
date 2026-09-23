# Mobile shader baseline

Target: **a730**. Status: **aoc-complete**.

Portable SPIR-V code statistics are not Adreno ISA counts, cycles, occupancy or GPU timing.
Uniform branches and loops remain in the modules; sites are not per-pixel execution counts.

Source/display: [1920, 1080]; Fusion: [480, 270]; 9 levels.
Fresh-frame dispatches: 32. Logical texture payload: 85.28 MiB.

| Entry | SPV bytes | FP16 sites | FP32 sites | Sample/read/write sites | Loop sites |
|---|---:|---:|---:|---|---:|
| reduce_source | 2960 | 0 | 11 | 1/0/1 | 2 |
| fit_coefficients | 4668 | 3 | 22 | 0/2/1 | 3 |
| average_coefficients | 3232 | 0 | 2 | 0/1/1 | 3 |
| apply_exposure | 4176 | 0 | 34 | 1/2/3 | 0 |
| setup_weights | 4980 | 0 | 49 | 0/1/2 | 0 |
| downsample | 2404 | 0 | 14 | 4/0/1 | 0 |
| reconstruct | 3392 | 0 | 11 | 2/2/1 | 0 |
| convert_exposure | 4572 | 0 | 34 | 1/2/1 | 0 |
| compute_main | 4656 | 9 | 17 | 3/0/3 | 0 |

## Adreno offline estimates

| Entry | Main instructions | Register footprint | Scratch bytes | ALU fiber occupancy % |
|---|---:|---:|---:|---:|
| reduce_source | 183.0 | 7.0 | 0.0 | 100.0 |
| fit_coefficients | 578.0 | 9.0 | 0.0 | 100.0 |
| average_coefficients | 333.0 | 5.0 | 0.0 | 100.0 |
| apply_exposure | 198.0 | 4.0 | 0.0 | 100.0 |
| setup_weights | 281.0 | 3.0 | 0.0 | 100.0 |
| downsample | 101.0 | 5.0 | 0.0 | 100.0 |
| reconstruct | 89.0 | 4.0 | 0.0 | 100.0 |
| convert_exposure | 202.0 | 2.0 | 0.0 | 100.0 |
| compute_main | 259.0 | 2.0 | 0.0 | 100.0 |

Preamble is reported separately in JSON. Register/occupancy definitions differ from Mali; do not compare their numerical values directly.

Adreno estimates and raw command logs are in report.json and each pass directory.
AOC metrics are null when unavailable; even successful AOC analysis does not measure frame time.
Calibration is initialization-only and excluded. Static-image viewer caching is excluded.
