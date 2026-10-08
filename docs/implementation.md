# Implementation Notes

Both current Bart curve policies use linear RGB arithmetic-mean luminance in setup
and final exposure recovery, matching UE's default metric. Z calibration still
measures the neutral-axis display response; final ACES and display colorimetry are
unchanged. Historical Guided controls retain their Rec.709 setup/conversion shaders.

`--fusion-curve ue-film` selects an optional analytic curve policy in both Bart hosts.
`ue_film_curve.py` supplies five film uniforms, without calibration or texture allocation.
`shaders/ue_film_curve.slang` uses the audited functions in `shaders/unreal/common.slang`;
the new full-reference and fine-residual initialize/apply entries evaluate them directly.
Shared pyramid/reconstruction stages and the independent UE renderer remain unchanged.
This reproduces the neutral film response, fixed approximate inverse and upper-only
pre-square limit, not Unreal's complete post-processing. See
[validation and limitations](performance/ue-film-analytic.md).

Start with the core files below. Tests and profiling tools are kept outside the main reading path.

| Read in order | Purpose |
| --- | --- |
| [fine_residual.py](../fine_residual.py) | Default optimized viewer host, textures and stage ordering |
| [tone_mapper.py](../tone_mapper.py) | Independent full-resolution reference |
| [shaders/pyramid.slang](../shaders/pyramid.slang) | Three exposures, weights, and downsampling |
| [shaders/fusion.slang](../shaders/fusion.slang) | Laplacian fusion, reconstruction, and exposure conversion |
| [shaders/reference_apply.slang](../shaders/reference_apply.slang) | Full-resolution reference exposure application |
| [zcurve.py](../zcurve.py) / [shaders/zcurve.slang](../shaders/zcurve.slang) | Curve fitting and inverse LUT |
| [main.py](../main.py) | Interactive viewer and command-line entry point |

Supporting material: [documentation](README.md), [tests](../tests/README.md), and [developer tools](../tools/README.md). Profiling is optional; it is not needed to run the viewer.

The default mobile variant is `fine-residual-lookup`. It uses five stages, each with its own resources; the viewer uses the same stage shaders through `FineResidualToneMapper`. Historical Guided controls are isolated under `tools/profiling/controls/` and cannot be selected in the application.

| Stage | Responsibility |
| --- | --- |
| [initialize.slang](../shaders/fine_residual/initialize.slang) | Four bilinear HDR samples; evaluate exposure lightness and weights before averaging |
| [pyramid.slang](../shaders/compact/pyramid.slang) | Packed residual and weight downsampling |
| [tail.slang](../shaders/compact/tail.slang) | Small pyramid tail in one workgroup |
| [reconstruct.slang](../shaders/fine_residual/reconstruct.slang) | Reconstruct a low-resolution lightness residual |
| [apply.slang](../shaders/fine_residual/apply.slang) | Restore fine residuals at full resolution, invert lightness, then apply the real tone mapper |

Two cached 2048-entry RGBA32F forward tables (64 KiB total) store weighted lightness, weights, exposure residuals and baseline. [fusion_lookup.py](../fusion_lookup.py) rebuilds them when curve, brackets or sigma change; global EV changes only lookup coordinates. The existing 1024-entry R16F inverse remains unchanged. Tables cover log2 luminance [-40,40]; input evaluation retains the calibrated 65535 limit.

At full resolution, the target is `weighted lightness + reconstructed low residual - dot(low exposure residuals, full-resolution weights)`. This approximates omitted fine pyramid bands. It avoids Guided coefficient fitting, but is not algebraically identical to the full pyramid. See [quality validation and limits](performance/quality-goal.md).

[variants.py](../tools/profiling/android/variants.py) selects the stage files. `guided-packed-coefficients`, its FP32-coefficient control and the independent unfused reference remain available.


`HDR → Three-exposure lightness and weights → Multiscale pyramids → Weighted Laplacian blending and coarse-to-fine reconstruction → Local exposure multiplier → HDR × Exposure → ACES → sRGB`

`shaders/pyramid.slang` generates lightness and weights. `shaders/fusion.slang` handles blending, reconstruction, and inverse exposure conversion. The implementation uses UE Fusion-style four-tap downsampling and exp2 weights. It extracts scalar luminance and uses a monotone Z curve fitted to the current tone operator's neutral response (ACES Filmic by default). This is not a full reproduction of UE FilmToneMap.

```powershell
.\.venv\Scripts\python.exe tests/test_pyramid.py          # Numerical regression tests
.\.venv\Scripts\python.exe tools/render_examples.py  # Regenerate README comparisons
```

## Quarter-Resolution Fusion

The default viewer runs Fusion at **1/4 width × 1/4 height**, restores missing fine residuals and inverts lightness at full resolution. A 4096×2048 source uses a 1024×512 pyramid. **Bart resolution** switches between **1/4 × 1/4 (fine residual)** and the independent **Full resolution reference**; `--fusion-scale 1` selects the latter on the command line.

The old average-HDR / low-resolution exposure inversion / Guided fitting path has been removed from application code. Its frozen host and shader live under `tools/profiling/controls/` solely for historical benchmarks and regressions. `ToneMapper` now accepts only full-resolution Fusion. The default host imports no profiling code.

Fine-residual correction approximates missing fine pyramid bands; it is not exact full-resolution Fusion. The lower pixel count is not a measured 16× frame-time speedup. See [the viewer halo diagnosis](performance/viewer-halo.md) for the screenshot reproduction, initialization ablation, native-resolution limits and matched GPU measurements.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_guided tests.test_zcurve tests.test_pyramid tests.test_precision
```

## Fitted Z Curve and Inverse 1D LUT

On startup and **F5**, the GPU samples `shaders/tone_operator.slang` on neutral RGB `(L,L,L)` over [0,65535]. SciPy fits all four parameters of:

`f(L) = L^contrast / (b * L^(contrast * shoulder) + c)`

The constraints `contrast,b,c > 0` and `0 < shoulder <= 1` guarantee monotonicity. Shoulder is optimized, not fixed. The fit minimizes perceptual lightness error. Fusion uses `F(L) = sqrt(f(L))` for all three exposures, reconstructs lightness `S`, and computes `exposure = F_inverse(S) / L`, limited to +/-12 EV. Matched targets preserve identity, including black and domain-clamped highlights. Final HDR RGB still goes through the real operator.

The inverse is baked once into a **1024-entry R16F 1D LUT (2 KiB)**. It stores log2 luminance with logit-spaced lightness coordinates to resolve shadows and the shoulder. A shader performs one filtered lookup and exp2; there is no runtime bisection or 3D LUT. CPU numerical inversion runs only during calibration. Inputs and reconstructed targets clamp to the fitted domain endpoints; the proxy itself is not clipped to 1, which would destroy invertibility.

This models **neutral luminance**, not arbitrary RGB hue/saturation interactions. The operator must be spatially independent, black-preserving, and return finite linear SDR RGB in [0,1] with a monotone neutral response. Invalid or poorly fitted operators fail calibration; failed F5 reloads preserve the previous working shaders and curve. Measured errors are sampled checks, not universal bounds.

Current ACES fit: contrast **1.52577**, shoulder **0.999449**, b **1.00612**, c **0.210214**. Independent samples give luminance RMSE **0.00463**, maximum luminance error **0.01867**, and maximum lightness error **0.01024**. GPU round-trip error over [1e-8,65535] is about **0.0156 EV** across 32,768 samples (regression budget: **0.02 EV**).

```powershell
.\.venv\Scripts\python.exe zcurve.py       # Write outputs/zcurve/report.json
.\.venv\Scripts\python.exe tests/test_zcurve.py  # Fit, inverse, operator, reload tests
```

Colors use RGBA16F and exposure maps use R16F. Guided sample products, regularized slope division, and display multiply/add operations use half. Curve evaluation, inverse lookup, sensitive Fusion calculations and guided accumulation/evaluation remain float. See the [precision review](precision.md).
