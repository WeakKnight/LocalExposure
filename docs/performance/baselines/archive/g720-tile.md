# Mali shader baseline

Target: **Immortalis-G720**. Compiler: **Mali Offline Compiler v2026.5.0 (Build 922df8)**.

All nine compute entries compiled successfully. These are offline estimates, not measured GPU time.
Cycle columns are the compiler’s total instruction-cycle estimates; do not sum them across pipelines or multiply them into frame milliseconds.
Runtime branches and loops are retained. Inspect raw JSON shortest/longest paths, variants and warnings.

| Entry / variant | Work regs | Occupancy % | FP16 arithmetic % | Spill bytes | Arithmetic | Load/store | Texture | Bound |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| reduce_source / Main | 32 | 100 | 0 | 0 | 0.806 | 2.000 | 0.500 | load_store |
| fit_coefficients / Main | 56 | 50 | 2 | 0 | 1.994 | 2.000 | 3.875 | texture |
| average_coefficients / Main | 30 | 100 | 0 | 0 | 0.969 | 20.000 | 0.375 | load_store |
| apply_exposure / Main | 26 | 100 | 0 | 0 | 0.672 | 6.000 | 0.375 | load_store |
| setup_weights / Main | 13 | 100 | 0 | 0 | 1.562 | 4.000 | 0.125 | load_store |
| downsample / Main | 21 | 100 | 0 | 0 | 0.211 | 2.000 | 0.500 | load_store |
| reconstruct / Main | 12 | 100 | 0 | 0 | 0.234 | 2.000 | 0.500 | load_store |
| convert_exposure / Main | 12 | 100 | 0 | 0 | 0.734 | 2.000 | 0.375 | load_store |
| compute_main / Main | 10 | 100 | 21 | 0 | 0.859 | 6.000 | 0.375 | load_store |

Workload: [1920, 1080], Fusion [480, 270], 9 levels, 32 dispatches.
Logical texture payload: 85.28 MiB; inverse LUT: 2 KiB.
The payload includes viewer base/final outputs; it is not measured bandwidth or physical allocation.
Calibration and static-image caching are excluded. Exported SPIR-V and raw malioc reports are under outputs/mobile/mali/.
