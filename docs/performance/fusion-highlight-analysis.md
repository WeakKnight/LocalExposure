# Fusion highlight amplification probe

2026-10-07. Diagnostic quality experiment on the current viewer paths, Apple M4 Pro / Metal, macOS 26.3, SlangPy 0.43.1. No timing or bandwidth claim. UE results below refer to this repository's UE port, not a capture from Unreal Editor.

GPU workload: neutral RGB float arrays uploaded through `create_hdr_texture`; EV 0; highlight/shadow contrast 0.8 (both brackets 1.2 EV); sigma 0.2. Bart full reference and current fine-residual runtime; UE Fusion with FP32 storage to exclude packed-format quantization. Read diagnostic local-exposure textures after submission. Values are log2 of exposure multipliers, averaged over the region.

For uniform 32×32 patches, all three paths darken highlights. At luminance 4, full Bart / fine Bart / UE give −0.5376 / −0.5366 / −0.6391 EV. At luminance 8 they give −0.4705 / −0.4705 / −0.5522 EV.

For a 128×128 image with background RGB 0.02 and a 64×64 central square (indices [32:96,32:96]), the center [60:68,60:68] gives:

| Square luminance | Bart full | Bart fine residual | UE FP32 |
| --- | ---: | ---: | ---: |
| 2 | −0.1082 | −0.1089 | −0.3531 |
| 4 | +0.6670 | +0.6650 | −0.1651 |
| 8 | +12.0000 | +12.0000 | +0.1242 |
| 16 | +12.0000 | +12.0000 | −0.7777 |

This separates spatial reconstruction from a flat-patch response. The full reference already exhibits the problem. At luminance 4 its base fusion lightness is 0.985185 and reconstructed center is 0.991574. At luminance 8 these are 0.993481 and 1.002473, exceeding `zMaxLightness = 1.001614`. The Bart inverse then returns its endpoint 65535; the exposure multiplier hits its +12 EV cap. This is pre-tonemapping gain: the final clipped SDR pixel does not become 4096 times brighter.

Multiscale Laplacian reconstruction with spatially varying weights is not a pointwise convex combination of the three original exposures. It can overshoot. The nearly flat high-luminance forward curve makes inverse recovery very sensitive to a small positive lightness error. Fine residual preserves the finest detail but cannot remove this property inherited from the reference. Approximation can additionally change edges: for the luminance-4 square, top inner rim [32:36,48:80] gives +0.8257 EV full versus +1.1885 EV fine.

The UE inverse in `shaders/unreal/common.slang` clamps fused lightness to 1 before squaring and uses fixed film-inverse constants. Its maximum recovered luminance is approximately 9.332847, versus Bart's 65535 domain endpoint. This bounds highlight amplification much more tightly; it does not guarantee exposure ≤ 1 at every bright pixel (the luminance-8 probe is a counterexample). Forward-curve differences also change fusion weights and reconstruction, so the ceiling alone does not explain every pixel difference.

Potential correction should constrain reconstruction overshoot and stabilize the near-white inverse, with a defined highlight-preservation policy. Do not globally clamp exposure to ≤ 1, which would remove shadow lifting. These probes do not establish final thresholds, performance, scene-wide perceptual quality, or production UE behavior under other film settings. No shader was changed for this analysis.
