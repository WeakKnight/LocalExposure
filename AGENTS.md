# Optimization scope

- Optimize the production Fusion Local Exposure runtime path, primarily for Snapdragon 8 Gen 1 / Adreno 730.
- Exclude visualization, debug outputs, comparison images, and viewer presentation from production cost and optimization benefit claims. Removing viewer-only work is not an algorithm optimization.
- The current `apply_exposure` entry mixes production exposure/tonemapping with viewer-only baseline-color and exposure-map outputs. Do not attribute the whole entry's cost to production. `compute_main` is viewer presentation and is excluded.
- Existing viewer-derived offline baselines are useful compiler records, but are not isolated production-path performance measurements. State this limitation when interpreting them.
- Preserve the established lossless requirement: maintain numerical behavior and validate against reference GPU outputs. Do not introduce value-specific fast paths such as reusing tonemapping only when exposure equals exactly one.
- Offline compiler statistics do not establish phone frame time or sustained performance. Validate performance claims with appropriate production-path measurements when available.
