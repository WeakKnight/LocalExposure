# Reference and optimized images

These images compare the independent `ToneMapper` reference with the current
`DEFAULT_VARIANT` from the mobile profiling workflow. They run on the **same desktop
backend**, not on a phone. “Full reference” means the complete unfused algorithm,
including all pyramid levels; it does not mean full-resolution Fusion or all-FP32 storage.

| Scene | Full reference | Optimized default | Absolute error |
| --- | --- | --- | --- |
| Sundowner Deck | [1920×1080 PNG](images/comparison/sundowner_deck-reference.png) | [1920×1080 PNG](images/comparison/sundowner_deck-optimized.png) | [Heatmap](images/comparison/sundowner_deck-error.png) |
| Veranda | [1920×1080 PNG](images/comparison/veranda-reference.png) | [1920×1080 PNG](images/comparison/veranda-optimized.png) | [Heatmap](images/comparison/veranda-error.png) |

## Matched settings

- HDR panoramas resized to 1920×1080 using bilinear filtering, then packed into R11G11B10_FLOAT. Both paths read the same packed texture.
- Global exposure 0 EV, brackets ±1.2 EV, weight sigma 0.2; Fusion at quarter width and height, Guided upsampling, ACES output. Both use the same fitted Z curve and inverse LUT.
- Final linear RGB converted identically to sRGB8. Metrics are measured at full output resolution, before preview resizing.
- Heatmaps show maximum absolute RGB-channel error per pixel: black = 0, blue = 1, cyan = 3, yellow = 6, red = 12 or above. The README heatmap uses the maximum error in each 3×3 block to keep sparse errors visible; full-size heatmaps have no pooling.

The [generated manifest](images/comparison/manifest.json) records the actual backend,
optimized preset, numerical metrics, and SHA-256 hashes of inputs, code and images.
Numerical gates supplement visual inspection; these two scenes do not replace the
HDR/edge/parameter stress checks used for optimization.

The [all-asset parameter matrix](images/parameter-matrix/README.md) adds three typical
presets to the default: −2 EV with stronger shadow lift, +2 EV with stronger highlight
protection, and symmetric 0.5 contrast scales. All four EXRs are tested at 1080p,
including asymmetric highlight/shadow settings. It records failures as well as passes.
Run `python tools/validate_asset_matrix.py` after optimization changes, then
`python tools/validate_asset_matrix.py --check` to verify freshness and gate status.

## Maintain the comparison

From the repository root, using the Python environment from the README:

```sh
python tools/render_comparison.py
python tools/render_comparison.py --check
```

Regenerate after changing the shaders, calibration, reference, or optimized default.
Inspect both comparison sheets and full-size details, then commit the PNGs and manifest
with the change. The generator always follows `DEFAULT_VARIANT` and rejects non-finite
renders or failed quality gates. `--check` requires no GPU and fails if source/settings
hashes or generated artifacts have changed. GPU/backend differences can affect rounding;
regeneration records the backend that produced the images.

The separate `tools/render_examples.py` maintains the introductory global-vs-local
examples, which deliberately use stronger ±3 EV brackets.
