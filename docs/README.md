# Documentation

For the algorithm and examples, start with the [project README](../README.md).

- [Implementation notes](implementation.md): pipeline, viewer controls, guided upsampling, and fitted inverse curve.
- [Precision](precision.md): where half is used and why sensitive operations stay float.
- [Mobile profiling](performance/README.md): optional AOC/Mali workflow and performance analysis.
- [Current mobile production optimization](performance/twohour-optimization.md): residual/Gather Fusion, image comparisons, foreground phone timings and A730 compiler checks.
- [Earlier Adreno 730 baseline](performance/baselines/a730-ten-rounds.md): viewer-derived offline analysis.
- [Earlier G720 cross-check](performance/baselines/g720-ten-rounds.md).
- [Optimization experiments](performance/experiments/ten-rounds.md): accepted and rejected candidates.

`images/` contains the README comparisons. `performance/baselines/archive/` contains historical snapshots; they are reference records, not the current implementation. JSON files alongside reports are machine-readable analysis data.
