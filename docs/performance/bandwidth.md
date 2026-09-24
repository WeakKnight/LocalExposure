# Bandwidth accounting

Report Local Exposure's **incremental** traffic over ordinary tonemapping,
including reduction, pyramids, reconstruction, Guided intermediates and extra
apply reads. Shared HDR input/output work is not automatically an incremental cost.

For the current mobile path at 1920x1080:

| Metric | Estimate |
|---|---:|
| Incremental texture-sweep payload | 19.18 MB/frame |
| At 30 FPS | 0.575 GB/s |
| At 45 FPS | 0.863 GB/s |

Use R11G11B10 HDR input and RGBA8 sRGB output. Average GB/s is bytes/frame times
FPS divided by 1e9. Vertical Guided reuse changes shared-memory work, not this
texture-traffic model.

These estimates are **not measured DRAM bandwidth**. Caches, compression,
transaction size and tile residency change physical traffic. Dividing modeled
bytes by GPU milliseconds gives an effective rate, not a DRAM-counter result.

`tools/profiling/android/traffic.py` generates accounting from the benchmark
manifest. An independent streaming benchmark is available:

```console
python -m tools.profiling.android.bandwidth --out outputs/android/bandwidth
```

Its copy throughput characterizes that workload; it does not measure Local
Exposure's physical DRAM traffic or power consumption.
[Historical measurements](archive/bandwidth-history.md).
