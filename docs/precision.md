# Shader precision review

Precision is fixed per stage. Safe operations directly use `half`; there is no float/half switch or precision type alias.

| Stage | Decision | Reason |
| --- | --- | --- |
| Final/base tone-mapped color | Half shader resources and RGBA16F storage | Operator output is explicitly narrowed to half. Arithmetic inside the arbitrary operator remains float. Both full-resolution textures use half the previous storage. |
| HDR reduction, global/local exposure application | Float arithmetic and storage | 65535 already exceeds half's maximum finite value, 65504. Exposure and the 16-sample sum extend the range further. |
| Z-curve evaluation and inverse 1D LUT | Float arithmetic and R16F LUT | Coordinates and exp2 remain float; FP16 storage is validated with a 0.02 EV round-trip budget. The 1024-entry LUT (2 KiB) stores log2 luminance; no per-pixel search remains. |
| Lightness, Gaussian weights and both pyramids | Float arithmetic and storage | Small sigma magnifies errors; subsequent inversion can strongly amplify even small bounded weight errors. See rejected experiment below. |
| Laplacian and reconstruction | Float | Signed small differences and accumulation across levels; preserve zero-bracket identity. |
| Inversion target and luminance | Float | Flat/clipped tone responses are ill-conditioned. |
| Solved/local exposure multiplier | Half arithmetic value and R16F storage | The fixed 2^-12 through 2^12 range contains no half overflow or subnormals. Keep exp2 and HDR multiplication float; explicitly round the multiplier before use and storage. |
| Guided per-sample centered guide, EV, `g*g`, `g*e` | Half | Narrow after float guide subtraction and float log2. With guidance in [-20,16] and EV in [-12,12], these products fit comfortably in half. Validated against float GPU and double CPU references. |
| Guided regularized slope solve | Half covariance/denominator and division | Subtract moments and add regularization in float first, then narrow for half division. |
| Guided moment accumulation, intercept, coefficient storage/averaging and evaluation | Float | Accumulate 25 samples in float. Covariance subtracts nearly equal quantities; intercept construction and `a * guide + b` can also suffer cancellation. |
| Pixel/UV coordinates | Float | Preserve texel positions at 4K. |
| Display sampled RGB and sRGB multiply/add | Half | Final output is 8-bit UNORM. Keep pow evaluation/exponent float; display changes never feed Fusion. Dense ramps remain monotone and differ by at most one output code. |

At 4096x2048, the two color textures together decrease from 256 MiB to 128 MiB, excluding allocation overhead. R16F exposure maps save a further 17 MiB at quarter working resolution (16 MiB full-resolution map plus 1 MiB low-resolution map). This is a storage reduction, not a measured GPU-time improvement. HDR, LUT lookup and guided-filter accumulation remain FP32.

## Rejected half-weight experiment

RGBA16F weight mips with native half four-tap accumulation passed ordinary cases but failed a stress ramp covering 2^-20 through 2^16, colored pixels, +/-6 EV brackets and sigma 0.8. In quarter-resolution mode, a reconstructed high-lightness value crossed from slightly above 1 to slightly below 1. The inverse lookup changed from identity to roughly -10 EV, and guided application produced a maximum output RGB difference of about 0.284. An affine reformulation of the blend did not resolve this cross-level effect. Both experimental changes were reverted.

Using half weights safely would require a separate change to stabilize inversion near plateaus, with an explicit visual tradeoff. This precision change preserves current behavior instead.

## Second review: partial Guided Filter and display arithmetic

Keep the guide subtraction in float **before** casting its result to half. Quantizing the two absolute log-luminance values first would erase small local differences. Compute each `g*g` and `g*e` in half, then promote to float before accumulation. Coefficient textures remain RG32F; no formats or precision switches were added.

Compared with the first review's implementation, all four 4K assets at EV -1 and default Fusion settings showed maximum linear RGB change of 0.00048828125, maximum local EV change below 0.000874, and at most one display code difference at 1600x800. Synthetic ramps, tiny guide variations, hard edges and prescribed extreme exposure fields additionally exercise cases absent from the assets. An 80-case window experiment (including guide evaluation offsets of +/-8 stops) measured maximum EV error 0.009676 and linear RGB error 0.001264. These are measured bounds for those cases, not a guarantee for every image or arbitrary tone operator.

Quantizing averaged `a,b` to half was also tried and rejected: the preliminary ramp tests already reached 0.021385 EV error, exceeding half of the exposure search's final interval (0.01171875 EV). Retaining only the per-sample half products avoids that coefficient cancellation error.

Experiment metrics, comparison images and native DXIL dumps are in `outputs/precision-round2/`. DXIL confirms native half multiplies for both guided products, float accumulation, and half multiply/add operations in the sRGB path. No phone performance claim is implied.

## Third review: exposure maps and regularized division

Both exposure maps now use R16F, with `half` SRV/UAV types. Compute exp2 in float and explicitly round its result to half, then use that same multiplier for the HDR operation and the diagnostic exposure map. All 1,024 possible search results fit in normal half range; their maximum additional EV error is below 0.00071 EV. Zero-bracket identity remains exact. The real arbitrary tone operator is unchanged.

Guided covariance subtraction and variance regularization remain float; the resulting covariance, denominator and slope division use half. The denominator is at least 0.04. Promote the slope to float when constructing the intercept, and retain RG32F coefficient storage and float final evaluation. This differs from storing both `a,b` in half, which was rejected in round two.

Color UAVs and display SRVs now explicitly use `half4` too. This makes conversion to half explicit before a typed store, rather than depending on float-to-RGBA16F store rounding.

Compared with round two, the four 4K assets (global EV -1, default Fusion settings) showed maximum EV change below 0.002048, maximum linear RGB change 0.0009765625, and at most one display code change. Colored ramps with sigma 0.02/0.2/0.8, +/-6 EV brackets, odd dimensions and both resolutions reached 0.008735 EV maximum difference, also with at most one display code change. These measurements do not establish a universal error bound. Outputs are in `outputs/precision-round3/`. DXIL confirms `fdiv ... half` and `textureStore.f16`.

## Current verification

```powershell
.venv/Scripts/python.exe -m unittest tests.test_pyramid tests.test_guided tests.test_zcurve tests.test_precision
```

The current pipeline uses a fitted scalar Z curve and inverse 1D LUT. The 20 tests cover four-parameter fitting, monotonicity, dense GPU forward/inverse checks, custom operators, domain endpoints, atomic reload, CPU pyramid/guided references, odd/tiny images, zero-bracket identity, and dense display ramps. Guided EV error against the CPU regression is limited to 0.012 EV in the stress test. Half exposure maps retain the normal finite range [2^-12,2^12].

Earlier rounds above describe measured precision changes to the **previous RGB-proxy pipeline**, including its now-removed ten-step search. Those image deltas are historical results, not quality claims for the new luminance proxy. Retained half operations remain covered by current tests. Mobile compiler output and timing require measurement on a target phone.
