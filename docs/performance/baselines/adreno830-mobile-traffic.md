# Local Exposure incremental texture traffic

1920 x 1080, 45 FPS; 1/4 width/height guided Fusion.

| Production pass | Read sweep MB | Write MB | Sweep total MB | Expanded taps total MB |
|---|---:|---:|---:|---:|
| reduce_setup | 8.294400 | 3.628800 | 11.923200 | 36.806400 |
| pyramids_mip1 | 2.592000 | 0.648000 | 3.240000 | 11.016000 |
| pyramids_mip2 | 0.648000 | 0.160800 | 0.808800 | 2.733600 |
| pyramids_mip3 | 0.160800 | 0.039600 | 0.200400 | 0.673200 |
| pyramids_mip4 | 0.039600 | 0.009600 | 0.049200 | 0.163200 |
| pyramids_mip5 | 0.009600 | 0.002400 | 0.012000 | 0.040800 |
| pyramids_mip6 | 0.002400 | 0.000560 | 0.002960 | 0.009520 |
| pyramids_mip7 | 0.000560 | 0.000120 | 0.000680 | 0.002040 |
| pyramids_mip8 | 0.000120 | 0.000020 | 0.000140 | 0.000340 |
| reconstruct_mip8 | 0.000020 | 0.000004 | 0.000024 | 0.000024 |
| reconstruct_mip7 | 0.000140 | 0.000024 | 0.000164 | 0.000624 |
| reconstruct_mip6 | 0.000680 | 0.000112 | 0.000792 | 0.002912 |
| reconstruct_mip5 | 0.002960 | 0.000480 | 0.003440 | 0.012480 |
| reconstruct_mip4 | 0.012000 | 0.001920 | 0.013920 | 0.049920 |
| reconstruct_mip3 | 0.049200 | 0.007920 | 0.057120 | 0.205920 |
| reconstruct_mip2 | 0.200400 | 0.032160 | 0.232560 | 0.836160 |
| reconstruct_mip1 | 0.808800 | 0.129600 | 0.938400 | 3.369600 |
| reconstruct_guided | 4.278848 | 0.518400 | 4.797248 | 33.419520 |
| apply_exposure_production | 0.518400 | 0.000000 | 0.518400 | 33.177600 |

Incremental sweep model: **22.799448 MB/frame**, **1.025975 GB/s**.
Incremental expanded-tap model: **122.519860 MB/frame**, **5.513394 GB/s**.
Matched tonemap baseline (excluded above): 16.588800 MB/frame.

- Increment over matched tonemap: final source read and output write cancel; all other production passes remain.
- Sweep model charges every bound input mip once per pass, and every output once. Assumes within-pass reuse; ignores cross-pass reuse. Not a DRAM lower bound.
- Expanded model includes zero-weight/duplicate texel slots even for aligned reduction samples. It charges each issued load and four texels per bilinear 2D sample (two for 1D), including duplicate/clamped taps. Not a DRAM upper bound.
- Reduction uses 16 samples. Separate guided stages load 144 entries per 8x8 group; Fused reconstruction/guided uses (group width + 8) x (group height + 8) input entries and a two-pixel coefficient halo. Partial groups included; shared-memory accesses excluded.
- Whole stored texel bytes charged even for RGB/alpha-only reads. Inverse LUT assumed queried at every low-res pixel; actual branch can skip.
- No compression, cache-line transactions, write allocation, uniforms, instructions, metadata or unrelated GPU traffic modeled.
- Calibration, uploads, viewer/debug resources and presentation excluded.
