# Implementation Notes

Start with the core files below. Tests and profiling tools are kept outside the main reading path.

| Read in order | Purpose |
| --- | --- |
| [tone_mapper.py](../tone_mapper.py) | Pipeline orchestration, textures, and pass ordering |
| [shaders/pyramid.slang](../shaders/pyramid.slang) | Three exposures, weights, and downsampling |
| [shaders/fusion.slang](../shaders/fusion.slang) | Laplacian fusion, reconstruction, and exposure conversion |
| [shaders/guided.slang](../shaders/guided.slang) | Low-resolution guidance and full-resolution application |
| [zcurve.py](../zcurve.py) / [shaders/zcurve.slang](../shaders/zcurve.slang) | Curve fitting and inverse LUT |
| [main.py](../main.py) | Interactive viewer and command-line entry point |

Supporting material: [documentation](README.md), [tests](../tests/README.md), and [developer tools](../tools/README.md). Profiling is optional; it is not needed to run the viewer.

The Android benchmark compiles five independent stage files in `shaders/compact/`. Each file declares its own inputs, outputs, constants and shared memory; there is no umbrella shader or shared resource declaration file. The files above remain the independent viewer reference.

| Stage | Responsibility |
| --- | --- |
| [initialize.slang](../shaders/compact/initialize.slang) | HDR reduction, three exposures and weights |
| [pyramid.slang](../shaders/compact/pyramid.slang) | Residual and weight downsampling |
| [tail.slang](../shaders/compact/tail.slang) | Small pyramid tail in one workgroup |
| [reconstruct.slang](../shaders/compact/reconstruct.slang) | Residual reconstruction and inverse exposure |
| [guided.slang](../shaders/compact/guided.slang) | Guided fitting and coefficient averaging |

The host maps entry points directly to stage files in [variants.py](../tools/profiling/android/variants.py). Production keeps only two compile-time choices: unsigned input gathering and packed-half versus FP32 Guided coefficients. Public benchmark presets are the optimized default, its FP32-coefficient control, and the independent unfused `lossless` reference. Historical macro combinations live only in the frozen test fixture; they are not production options.


`HDR → Three-exposure lightness and weights → Multiscale pyramids → Weighted Laplacian blending and coarse-to-fine reconstruction → Local exposure multiplier → HDR × Exposure → ACES → sRGB`

`shaders/pyramid.slang` generates lightness and weights. `shaders/fusion.slang` handles blending, reconstruction, and inverse exposure conversion. The implementation uses UE Fusion-style four-tap downsampling and exp2 weights. It extracts scalar luminance and uses a monotone Z curve fitted to the current tone operator's neutral response (ACES Filmic by default). This is not a full reproduction of UE FilmToneMap.

```powershell
.\.venv\Scripts\python.exe tests/test_pyramid.py          # Numerical regression tests
.\.venv\Scripts\python.exe tools/render_examples.py  # Regenerate README comparisons
```

## Quarter-Resolution Fusion

By default, Fusion and inverse exposure conversion run at **1/4 width x 1/4 height** (1/16 as many pixels). A 4096x2048 input uses a 1024x512 working image. The UI's **Fusion resolution** selector switches between the guided version and the full-resolution reference; `--fusion-scale 1` selects the reference from the command line.

`shaders/guided.slang` downsamples linear HDR and log-luminance guidance separately, fits local `EV = a * guide + b` models in 5x5 low-resolution windows, averages the coefficients, and evaluates them with full-resolution guidance. Regularization is 0.04 EV squared, and the resulting local EV is limited to [-12, 12]. Only exposure application and the real tone mapper run at full resolution.

This is an approximation: averaging HDR before nonlinear tone mapping and omitting the finest Fusion bands can change fine detail and strong highlights. Guided upsampling reduces edge bleed but cannot recover information already lost during reduction. The lower working pixel count is not a measured 16x frame-time speedup; full-resolution output and guided-filter passes still have a cost.

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

