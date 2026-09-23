# Local Exposure incremental texture traffic

1920 x 1080, 45 FPS; quarter-width/height guided Fusion.

| Production pass | Read sweep MB | Write MB | Sweep total MB | Expanded taps total MB |
|---|---:|---:|---:|---:|
| reduce_setup | 8.294400 | 4.147200 | 12.441600 | 37.324800 |
| pyramids_mip1 | 3.110400 | 0.777600 | 3.888000 | 13.219200 |
| pyramids_mip2 | 0.777600 | 0.192960 | 0.970560 | 3.280320 |
| pyramids_mip3 | 0.192960 | 0.047520 | 0.240480 | 0.807840 |
| pyramids_mip4 | 0.047520 | 0.011520 | 0.059040 | 0.195840 |
| pyramids_mip5 | 0.011520 | 0.002880 | 0.014400 | 0.048960 |
| pyramids_mip6 | 0.002880 | 0.000672 | 0.003552 | 0.011424 |
| pyramids_mip7 | 0.000672 | 0.000144 | 0.000816 | 0.002448 |
| pyramids_mip8 | 0.000144 | 0.000024 | 0.000168 | 0.000408 |
| reconstruct_mip8 | 0.000024 | 0.000004 | 0.000028 | 0.000028 |
| reconstruct_mip7 | 0.000164 | 0.000024 | 0.000188 | 0.000648 |
| reconstruct_mip6 | 0.000792 | 0.000112 | 0.000904 | 0.003024 |
| reconstruct_mip5 | 0.003440 | 0.000480 | 0.003920 | 0.012960 |
| reconstruct_mip4 | 0.013920 | 0.001920 | 0.015840 | 0.051840 |
| reconstruct_mip3 | 0.057120 | 0.007920 | 0.065040 | 0.213840 |
| reconstruct_mip2 | 0.232560 | 0.032160 | 0.264720 | 0.868320 |
| reconstruct_mip1 | 0.938400 | 0.129600 | 1.068000 | 3.499200 |
| reconstruct_guided | 4.797248 | 1.036800 | 5.834048 | 35.112960 |
| apply_exposure_production | 1.036800 | 0.000000 | 1.036800 | 66.355200 |

Incremental sweep model: **25.908104 MB/frame**, **1.165865 GB/s**.
Incremental expanded-tap model: **161.009260 MB/frame**, **7.245417 GB/s**.
Matched tonemap baseline (excluded above): 16.588800 MB/frame.

- Increment over matched tonemap: final source read and output write cancel; all other production passes remain.
- Sweep model charges every bound input mip once per pass, and every output once. Assumes within-pass reuse; ignores cross-pass reuse. Not a DRAM lower bound.
- Expanded model includes zero-weight/duplicate texel slots even for aligned reduction samples. It charges each issued load and four texels per bilinear 2D sample (two for 1D), including duplicate/clamped taps. Not a DRAM upper bound.
- Reduction uses 16 samples. Separate guided stages load 144 entries per 8x8 group; Fused reconstruction/guided uses (group width + 8) x (group height + 8) input entries and a two-pixel coefficient halo. Partial groups included; shared-memory accesses excluded.
- Whole stored texel bytes charged even for RGB/alpha-only reads. Inverse LUT assumed queried at every low-res pixel; actual branch can skip.
- No compression, cache-line transactions, write allocation, uniforms, instructions, metadata or unrelated GPU traffic modeled.
- Calibration, uploads, viewer/debug resources and presentation excluded.
