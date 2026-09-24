# Development guidelines

- Keep the core algorithm easy to follow. Put profiling tools, experiments and detailed reports in their existing subdirectories.
- Optimize Local Exposure's incremental GPU time and bandwidth against a matched baseline. Exclude visualization and debug work; do not count shared tonemapping improvements as Local Exposure gains. Check complete-chain time too.
- Preserve independent reference implementations and benchmark controls. Validate shader changes on representative HDR scenes, edges, odd dimensions and relevant parameter ranges. Approximation is acceptable when it does not noticeably harm quality; document its limits.
- Avoid value-specific shortcuts such as special-casing an exposure multiplier of exactly one.
- Distinguish measured GPU timings, offline compiler projections and estimated texture traffic. Identify the tested device, driver and workload; do not extrapolate results as measurements of other GPUs.
- For game-performance claims, use matched graphics-produced HDR workloads. Keep diagnostic per-pass timings separate from whole-chain measurements.
- Run checks appropriate to the change. Record experiment results and current limitations in the performance docs rather than this file.
- Keep the [reference/optimized/error images](docs/image-comparison.md) current when changing shaders, calibration or the optimized default; regenerate and inspect them before delivery.

See [documentation](docs/README.md) for implementation notes and [mobile profiling](docs/performance/README.md) for current defaults, benchmark procedures and results.
