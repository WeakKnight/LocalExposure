# Mobile bandwidth accounting

Measured on NX789J / SM8750 / **Adreno 830**, not Snapdragon 8 Gen 1. The production workload includes quarter-width, quarter-height Fusion and guided upsampling; visualization is excluded.

## Game-format tonemap payload

At 1920 × 1080, R11G11B10 input and RGBA8 sRGB output each occupy four bytes per pixel:

| Logical payload | MB/frame | Average GB/s at 45 FPS |
|---|---:|---:|
| HDR input read | 8.2944 | 0.373248 |
| SDR output write | 8.2944 | 0.373248 |
| Total | **16.5888** | **0.746496** |

Decimal units: bytes/frame = width × height × (4 + 4); average GB/s = bytes/frame × FPS / 1e9. This describes one tonemap source read and destination write. Fusion adds reduction, pyramids, reconstruction, exposure, guided coefficients and their reads/writes. This table is **not total Fusion traffic** or measured DRAM traffic; caches, compression and attachment handling affect physical traffic.

The native benchmark now supports a real offscreen `VK_FORMAT_R8G8B8A8_SRGB` color attachment with hardware sRGB conversion. Attachment storage is included; swapchain acquisition/presentation is excluded. This avoids treating a linear floating-point storage image as a backbuffer.

The recorded 45 FPS paced run measured 4.9920 ms median for the full guided chain and 0.8142 ms for baseline tonemap (360 samples each). Baseline effective logical throughput is 20.37 GB/s during its GPU interval. It is distinct from the 0.7465 GB/s nominal average across a second at 45 FPS.

These graphics-path timings are substantially higher than the earlier compute-output measurements. Input/output formats, pipeline type and stock power behavior differ, so this is not evidence of an algorithm regression or a format-only bandwidth cost. Narrowing the compute/graphics barriers did not remove the gap; its cause remains unresolved.

All captured same-phone stages, including final sRGB8 output, were bitwise equal to the viewer reference. The separate desktop portability check still warns (final maximum error 0.019608, RMSE 0.000625). See the [game-format snapshot](../baselines/adreno830-game-formats.json) for samples, validation, tool metadata and graph.

## Local Exposure incremental traffic

The increment subtracts the matched tonemap baseline: its HDR read and final color write cancel. The extra HDR read in reduction remains, as do all Fusion and guided-filter intermediate accesses.

For the current 1080p graph, a **per-pass texture sweep model** gives:

| Stage | Incremental MB/frame |
|---|---:|
| HDR reduction | 10.3680 |
| Three-exposure lightness and weights | 6.2208 |
| Both downsample pyramids | 6.9027 |
| Weighted Laplacian reconstruction | 7.0767 |
| Inverse exposure conversion, including LUT | 2.8532 |
| Guided coefficient fitting | 3.3696 |
| Coefficient averaging | 2.0736 |
| Extra coefficient read during tonemap | 1.0368 |
| **Local Exposure increment** | **39.9014** |

This model charges one full input-mip sweep per pass and each output write once: it assumes within-pass cache reuse but no cross-pass reuse. At **45 FPS the increment is 1.7956 GB/s**. Adding baseline tonemap gives **56.4902 MB/frame / 2.5421 GB/s** under this same model. These are neither hardware measurements nor guaranteed DRAM bounds.

A separate expanded-access model counts all shader loads, shared-tile halo loads, four texel slots per bilinear 2D lookup and two per inverse-LUT lookup, without texture-cache reuse. It gives 164.3580 MB/frame incremental, including zero-weight/duplicate slots for aligned sampling. This is useful for identifying reuse, not for predicting DRAM bandwidth. For example, final coefficient sampling expands to 66.3552 MB of texel slots but samples a 1.0368 MB image. Shared-memory window reads do not count as external texture traffic.

Formats are taken from the actual graph: reduced/lightness/weights RGBA32F, reconstruction R32F, exposure R16F, coefficients RG32F, inverse LUT R16F. Half arithmetic does not reduce these storage sizes. The conditional inverse lookup is conservatively charged; resource padding, cache-line transfers and compression are not modeled.

The [complete per-pass ledger](../baselines/adreno830-local-exposure-traffic.md) includes exact mip sizes, both models and assumptions. New benchmark runs generate `local-exposure-traffic.md` and embed the ledger in `summary.json`. To recalculate an existing graph without rerunning the GPU:

```powershell
.\.venv\Scripts\python.exe -m tools.profiling.android.traffic outputs/android/r11-srgb45-scoped/bundle/manifest.json --fps 45 --out outputs/android/traffic
```

The [fused production candidate](fusion-compaction.md) reduces this same sweep model to **25.9081 MB/frame / 1.1659 GB/s**, with matched phone timing and lossless validation recorded separately.

## Independent streaming benchmark

Three disjoint source/destination buffer pairs, deterministic hashed input, compute and transfer copies in alternating ABBA blocks. Each block uses 48 warmups and 96 timed samples; submission is unpaced. Every destination is fully checked after each block, outside timing.

| Working set MiB | Compute read + write GB/s | Transfer read + write GB/s |
|---:|---:|---:|
| 6 | 68.48 | 59.23 |
| 48 | 55.50 | 53.51 |
| 192 | 68.91 | 65.65 |
| 768 | 67.64 | 63.84 |

All copies passed validation. Effective bandwidth counts source reads **plus** destination writes; copy throughput counting only bytes copied is half these numbers. Larger working sets reduce cache residency but do not establish cold caches or pure DRAM throughput. Buffer copies also differ from texture sampling and render-target writes. These results cannot be substituted for Fusion's physical traffic or a hardware peak-bandwidth specification.

The device did not expose the Vulkan performance-query extension used to access performance counters. No physical DRAM counter was measured. See the [streaming snapshot](../baselines/adreno830-bandwidth.json) for per-block statistics and tool hashes, and [the workflow](../android.md#game-formats-and-bandwidth) for commands.
