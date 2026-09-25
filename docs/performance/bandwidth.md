# Bandwidth accounting

Report Local Exposure's **incremental** traffic over ordinary tonemapping,
including reduction, pyramids, reconstruction, Guided intermediates and extra
apply reads. Shared HDR input/output work is not automatically an incremental cost.

For the current mobile path at 1920x1080:

| Metric | Estimate |
|---|---:|
| Incremental texture-sweep payload | 16.71 MB/frame |
| At 30 FPS | 0.501 GB/s |
| At 45 FPS | 0.752 GB/s |

Use R11G11B10 HDR input and RGBA8 sRGB output. Average GB/s is bytes/frame times
FPS divided by 1e9. Packing residuals and weights slightly increases the sweep
estimate from 16.66 to 16.71 MB/frame. Direct 5×5 Guided fitting keeps this sweep
unchanged, but repeats more cached input reads. The expanded logical-access
estimate is 98.88 MB/frame (4.449 GB/s at 45 FPS), including reconstruction halos
and every direct fit sample, up from 3.946 GB/s before the Guided change.
Cache reuse determines how much reaches DRAM; no physical-bandwidth or power
improvement is claimed.

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
[Current raw accounting](baselines/current.json).
