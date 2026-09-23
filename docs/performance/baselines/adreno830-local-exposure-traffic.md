# Local Exposure incremental texture traffic

1920 x 1080, 45 FPS; quarter-width/height guided Fusion.

| Production pass | Read sweep MB | Write MB | Sweep total MB | Expanded taps total MB |
|---|---:|---:|---:|---:|
| reduce_source | 8.294400 | 2.073600 | 10.368000 | 35.251200 |
| setup_weights | 2.073600 | 4.147200 | 6.220800 | 6.220800 |
| luminance_mip1 | 2.073600 | 0.518400 | 2.592000 | 8.812800 |
| luminance_mip2 | 0.518400 | 0.128640 | 0.647040 | 2.186880 |
| luminance_mip3 | 0.128640 | 0.031680 | 0.160320 | 0.538560 |
| luminance_mip4 | 0.031680 | 0.007680 | 0.039360 | 0.130560 |
| luminance_mip5 | 0.007680 | 0.001920 | 0.009600 | 0.032640 |
| luminance_mip6 | 0.001920 | 0.000448 | 0.002368 | 0.007616 |
| luminance_mip7 | 0.000448 | 0.000096 | 0.000544 | 0.001632 |
| luminance_mip8 | 0.000096 | 0.000016 | 0.000112 | 0.000272 |
| weights_mip1 | 2.073600 | 0.518400 | 2.592000 | 8.812800 |
| weights_mip2 | 0.518400 | 0.128640 | 0.647040 | 2.186880 |
| weights_mip3 | 0.128640 | 0.031680 | 0.160320 | 0.538560 |
| weights_mip4 | 0.031680 | 0.007680 | 0.039360 | 0.130560 |
| weights_mip5 | 0.007680 | 0.001920 | 0.009600 | 0.032640 |
| weights_mip6 | 0.001920 | 0.000448 | 0.002368 | 0.007616 |
| weights_mip7 | 0.000448 | 0.000096 | 0.000544 | 0.001632 |
| weights_mip8 | 0.000096 | 0.000016 | 0.000112 | 0.000272 |
| reconstruct_mip8 | 0.000032 | 0.000004 | 0.000036 | 0.000036 |
| reconstruct_mip7 | 0.000212 | 0.000024 | 0.000236 | 0.000696 |
| reconstruct_mip6 | 0.001016 | 0.000112 | 0.001128 | 0.003248 |
| reconstruct_mip5 | 0.004400 | 0.000480 | 0.004880 | 0.013920 |
| reconstruct_mip4 | 0.017760 | 0.001920 | 0.019680 | 0.055680 |
| reconstruct_mip3 | 0.072960 | 0.007920 | 0.080880 | 0.229680 |
| reconstruct_mip2 | 0.296880 | 0.032160 | 0.329040 | 0.932640 |
| reconstruct_mip1 | 1.197600 | 0.129600 | 1.327200 | 3.758400 |
| reconstruct_mip0 | 4.795200 | 0.518400 | 5.313600 | 15.033600 |
| convert_exposure | 2.594048 | 0.259200 | 2.853248 | 3.369600 |
| fit_coefficients | 2.332800 | 1.036800 | 3.369600 | 6.324480 |
| average_coefficients | 1.036800 | 1.036800 | 2.073600 | 3.386880 |
| apply_exposure_production | 1.036800 | 0.000000 | 1.036800 | 66.355200 |

Incremental sweep model: **39.901416 MB/frame**, **1.795564 GB/s**.
Incremental expanded-tap model: **164.357980 MB/frame**, **7.396109 GB/s**.
Matched tonemap baseline (excluded above): 16.588800 MB/frame.

- Increment over matched tonemap: final source read and output write cancel; all other production passes remain.
- Sweep model charges every bound input mip once per pass, and every output once. Assumes within-pass reuse; ignores cross-pass reuse. Not a DRAM lower bound.
- Expanded model includes zero-weight/duplicate texel slots even for aligned reduction samples. It charges each issued load and four texels per bilinear 2D sample (two for 1D), including duplicate/clamped taps. Not a DRAM upper bound.
- Reduction uses 16 samples; guided tiles load 144 entries per 8x8 group, including partial groups. Shared-memory accesses excluded.
- Whole stored texel bytes charged even for RGB/alpha-only reads. Inverse LUT assumed queried at every low-res pixel; actual branch can skip.
- No compression, cache-line transactions, write allocation, uniforms, instructions, metadata or unrelated GPU traffic modeled.
- Calibration, uploads, viewer/debug resources and presentation excluded.
