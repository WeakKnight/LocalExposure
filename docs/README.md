# Documentation

For the algorithm and examples, start with the [project README](../README.md).

- [Implementation notes](implementation.md): pipeline, viewer controls, guided upsampling, and fitted inverse curve.
- [Precision](precision.md): where half is used and why sensitive operations stay float.
- [Mobile profiling](performance/README.md): optional AOC/Mali workflow and performance analysis.
- [Current mobile production optimization](performance/twohour-optimization.md): residual/Gather Fusion, image comparisons, foreground phone timings and A730 compiler checks.
- [Earlier Adreno 730 baseline](performance/baselines/a730-ten-rounds.md): viewer-derived offline analysis.
- [Earlier G720 cross-check](performance/baselines/g720-ten-rounds.md).
- [Guided window reuse](performance/experiments/guided-window-reuse.md): multi-output and sliding-window candidates, image checks and matched phone measurements.
- [Wave operation experiments](performance/experiments/wave-operations.md): rejected reduction timing and Guided shuffle portability findings.
- [Qualcomm tile memory](performance/experiments/tile-memory.md): phone capability probe and intermediate residency plan; current driver unsupported.
- [Process-local Adreno driver](performance/experiments/custom-driver.md): optional 842.6 loader, tile heap discovery and foreground rendering validation.
- [Tile-memory runtime experiment](performance/experiments/tile-memory-runtime.md): same-driver residency A/B, complete-chain timings and baseline side effect.
- [Production bottleneck diagnosis](performance/experiments/bottleneck-diagnosis.md): output-identical pass replays distinguish Local Exposure hotspots from shared tonemapping cost.
- [Dependency and synchronization review](performance/experiments/dependency-review.md): Guided work distribution, four necessary group barriers and the production pass dependency chain.
- [Guided vertical reuse](performance/experiments/guided-vertical-reuse.md): adjacent vertical windows and decoupled thread counts, with quality gates and phone timings.
- [Optimization experiments](performance/experiments/ten-rounds.md): accepted and rejected candidates.

`images/` contains the README comparisons. `performance/baselines/archive/` contains historical snapshots; they are reference records, not the current implementation. JSON files alongside reports are machine-readable analysis data.
