# Reference and optimized images

The optional [analytic UE film mode](performance/ue-film-analytic.md) has its own
[reference / fine-residual / error matrix](images/ue-film/manifest.json), including
four HDR scenes, four presets and the native-resolution Veranda edge case.
Its errors are measured against the independent full-resolution **same-curve** reference,
not against the calibrated Z curve or the complete UE renderer.

The separate [Bart / UE 5.8 comparison](performance/unreal.md) shows the standalone Fusion and Bilateral Grid ports, including native-storage versus FP32 error controls. Differences between these algorithms are intentional; Bart is not a ground-truth image for UE.

The viewer defaults to this same fine-residual graph. Both generators also require exact linear-output equality between the viewer runtime and the optimized profiling control; a stale or incorrectly wired viewer fails regeneration.

These images compare the independent `ToneMapper` reference with the current
`DEFAULT_VARIANT` from the mobile profiling workflow. They run on the **same desktop
backend**, not on a phone. The reference now runs Fusion at the full 1920×1080 input resolution, with all
pyramid levels and no Guided upsampling. The optimized path runs at quarter width
and height with full-resolution fine-residual correction. The reference is not all-FP32 storage or ground truth.

| Scene | Full-resolution Fusion | Optimized default | Absolute error |
| --- | --- | --- | --- |
| Sundowner Deck | [1920×1080 PNG](images/comparison/sundowner_deck-reference.png) | [1920×1080 PNG](images/comparison/sundowner_deck-optimized.png) | [Heatmap](images/comparison/sundowner_deck-error.png) |
| Veranda | [1920×1080 PNG](images/comparison/veranda-reference.png) | [1920×1080 PNG](images/comparison/veranda-optimized.png) | [Heatmap](images/comparison/veranda-error.png) |

## Matched settings

- HDR panoramas resized to 1920×1080 using bilinear filtering, then packed into R11G11B10_FLOAT. Both paths read the same packed texture.
- Both current Bart curve modes use equal RGB weights, `(R + G + B) / 3`, in setup and exposure recovery.
- Global exposure 0 EV, brackets ±1.2 EV, weight sigma 0.2, ACES output. Reference Fusion scale is 1; optimized Fusion scale is 4 with fine-residual correction. Both share the same fitted Z curve and inverse LUT.
- Final linear RGB converted identically to sRGB8. Metrics are measured at full output resolution, before preview resizing.
- Heatmaps show maximum absolute RGB-channel error per pixel: black = 0, blue = 1, cyan = 3, yellow = 6, red = 12 or above. The README heatmap uses the maximum error in each 3×3 block to keep sparse errors visible; full-size heatmaps have no pooling.

The [generated manifest](images/comparison/manifest.json) records the actual backend,
optimized preset, numerical metrics, and SHA-256 hashes of inputs, code and images.
These errors include the low-resolution approximation, not just optimization
rounding. Shared curve/model defects can still be invisible. Large differences
are retained, with red meaning 12 codes **or more**, not a maximum error of 12.
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
with the change. The generator follows `DEFAULT_VARIANT` and rejects non-finite renders. Finite
quality failures are saved in full before it returns a nonzero exit code; thresholds
follow the current red-area goal (<1% native pixels at ≥12 codes). Older strict gates remain recorded as `legacy_accepted`. `--check` requires no GPU, checks source/settings and artifact hashes,
and also returns nonzero when the recorded quality gates fail. Fresh artifacts do
not imply passing image quality. GPU/backend differences can affect rounding;
regeneration records the backend that produced the images.

The separate `tools/render_examples.py` maintains the introductory global-vs-local
examples, which deliberately use stronger ±3 EV brackets.
