# Regression tests

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

- `test_pyramid`, `test_guided`, `test_zcurve`, `test_precision`: algorithm and numerical coverage (GPU required).
- `test_reduction`, `test_average`, `test_fit`, `test_rounds`: bitwise checks against frozen pre-optimization shaders (GPU required).
- `test_mobile_profile`, `test_mali_profile`: offline-report parsing and workflow checks.
- `test_guided_batch`: short-window reuse versus the unchanged Guided kernel, including FP32 coefficient readback and nearly constant guides.
- `test_compact_production`: exact output and Guided-coefficient parity against the frozen optimized graph, with packed/FP32 controls, signed/unsigned input, tiny/odd sizes and varied exposures.
- `test_compact`, `test_residual_fusion`: fused GPU/reference parity and an independent algebraic check of residual pyramid reconstruction.
- `test_android_benchmark`, `test_android_traffic`, `test_quality`: production measurement separation, bandwidth accounting and fixed image-quality gates.
- `test_mixed_residual`, `test_tail_grid`: mixed-format mip bindings/traffic and exact tail traversal/storage parity, including odd and thin sizes.
- `test_log_initialization`: log-domain exposure initialization at black, HDR limits, odd dimensions and asymmetric exposure brackets.
- `test_unsigned_gather`: signed source textures retain per-sample clamping; unsigned initialization parity is covered by `test_log_initialization`.
- `test_guided_coefficient_layout`: exact Guided coefficient parity across physical row pitches, including flat guides, edges and thin/odd sizes.
- `test_guided_interior`: exact coefficient parity for interior/border tiles, thin and odd images, and nearly constant guides, in both FP32 and packed-half modes.

Approximate mobile candidates also use the [same-phone image and desktop temporal stress workflow](../docs/performance/android.md#foreground-graphics-context-measurement). Passing unit tests alone does not establish phone performance or perceptual quality.

Run one module with `python -m unittest tests.test_guided`. `fixtures/` holds reference shaders and a recorded compiler report, used only by tests and historical experiments. These shaders are not part of the runtime pipeline.
