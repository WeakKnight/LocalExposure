# Shader precision review

Precision is fixed per stage. Safe operations directly use `half`; there is no float/half switch or precision type alias.

| Stage | Decision | Reason |
| --- | --- | --- |
| Exposure search `lo`, `hi`, `mid` | Native half arithmetic | All ten midpoints of the fixed [-12, 12] search are exactly representable. The final midpoint and `exp2` stay float. Recheck if the iteration count or bounds change. |
| Final/base tone-mapped color | Half shader resources and RGBA16F storage | Operator output is explicitly narrowed to half. Arithmetic inside the arbitrary operator remains float. Both full-resolution textures use half the previous storage. |
| HDR reduction, global/local exposure application | Float arithmetic and storage | 65535 already exceeds half's maximum finite value, 65504. Exposure and the 16-sample sum extend the range further. |
| LUT baking, encoding, coordinates and sampling results | Float | Log encoding, dark values and interpolation feed the inverse problem. LUT storage remains RGB10A2_UNORM. |
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
.venv/Scripts/python.exe -m unittest test_pyramid test_guided test_lut test_precision
```

The 21 tests include CPU numerical reference checks, mixed-precision guided filtering, all 1,023 possible ten-step search midpoints and 1,024 narrowed multipliers, odd/tiny images, black, 65535, global EV +/-16, zero-bracket identity, sharp weights, and both Fusion resolutions. New tests cover dense linear/dark/sRGB-junction ramps, every half value in [0,1], monotonic display output, and extreme guided windows against a double-precision CPU solve. Guided EV error is limited to half of the final search interval in that test. Color checks allow one FP16 ULP below 1; the current shader explicitly narrows color before storage.

During the original review, before removing the temporary FP32 comparison path, on all four repository 4K HDR assets at global EV -1, default brackets and quarter resolution: exposure fields were identical, maximum linear RGB error was 0.000488222, and the 1600x800 8-bit display differed by at most one code value. The original comparison images and metrics are in `outputs/precision/`.

The tested D3D12 DXIL contains `phi half`, `fadd ... half`, `fmul ... half` and explicit promotion before LUT evaluation; this is native half arithmetic, not merely renamed float variables. Mobile compiler output and timing still require measurement on the target phone.
