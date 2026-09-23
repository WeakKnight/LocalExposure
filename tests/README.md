# Regression tests

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

- `test_pyramid`, `test_guided`, `test_zcurve`, `test_precision`: algorithm and numerical coverage (GPU required).
- `test_reduction`, `test_average`, `test_fit`, `test_rounds`: bitwise checks against frozen pre-optimization shaders (GPU required).
- `test_mobile_profile`, `test_mali_profile`: offline-report parsing and workflow checks.
- `test_compact`, `test_residual_fusion`: fused GPU/reference parity and an independent algebraic check of residual pyramid reconstruction.
- `test_android_benchmark`, `test_android_traffic`, `test_quality`: production measurement separation, bandwidth accounting and fixed image-quality gates.

Approximate mobile candidates also use the [same-phone image and desktop temporal stress workflow](../docs/performance/android.md#foreground-graphics-context-measurement). Passing unit tests alone does not establish phone performance or perceptual quality.

Run one module with `python -m unittest tests.test_guided`. `fixtures/` holds reference shaders and a recorded compiler report, used only by tests and historical experiments. These shaders are not part of the runtime pipeline.
