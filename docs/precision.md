# Precision

Precision follows the stage's numerical range. The readable viewer reference and
optimized mobile graph are independent; their storage choices differ deliberately.

| Stage | Precision and reason |
|---|---|
| HDR reduction and exposure application | FP32: input reaches 65535 and sums/exposure can exceed half range. |
| Fitted Z curve and inverse lookup | FP32 arithmetic; 1024-entry R16F LUT stores log luminance. Coordinates and exp2 remain float. |
| Reference Fusion pyramids/reconstruction | FP32: small residuals and inversion near the shoulder are sensitive to error. |
| Mobile residual pyramid | Residuals in RGBA16F xy at mips 0–2, RGBA32F above; FP32 reconstruction. Coarse precision protects strong highlights. |
| Mobile weights | Centered weights (weight − 0.5) share pyramid zw; decode with +0.5. Normalization and filtering arithmetic remain float. |
| Exposure and guide storage | Reference exposure R16F; mobile log-luminance/guide and EV/guide RG16F. Exposure limits are ±12 EV. |
| Guided fit | Subtraction, moments and variance remain FP32 on the mobile path; regularized slope division uses half. |
| Mobile fitted coefficients | Two half values packed into one shared uint; unpack to FP32 for averaging. Intercept quantization is approximate. |
| Guided horizontal sums / final coefficients | Half storage, with FP32 accumulation and evaluation. The independent reference keeps its own coefficient path. |
| Coordinates | FP32 to preserve texel positions at large resolutions. |
| Tone-mapped output | Half color storage; the real tone operator's arithmetic remains float. |

The neutral-response proxy does not reproduce arbitrary chromatic behavior.
Near-flat tone responses can amplify small pyramid errors; lower storage size
alone is not evidence of acceptable quality or faster execution.

Validation includes black/HDR endpoints, odd/thin sizes, edges, motion and four
HDR assets at several exposure/contrast settings. The inverse LUT's regression
budget is 0.02 EV. These are tested cases, not universal error bounds.

See [current phone results and limitations](performance/README.md),
[image comparisons](image-comparison.md), and [regression tests](../tests/README.md).
