# UE 5.8 Local Exposure ports

`ue_local_exposure.py` and `shaders/unreal/` implement the two Local Exposure methods from the supplied UE 5.8 checkout. Bart's independent `ToneMapper`, calibration and mobile optimized graph remain available. The viewer's Algorithm selector switches among Bart, UE Fusion and UE Bilateral Grid.

```sh
.venv/bin/python main.py --method ue-fusion --view compare
.venv/bin/python main.py --method ue-bilateral --view compare
.venv/bin/python main.py --method ue-bilateral --ue-profile mobile --headless --output outputs/ue-mobile.png
.venv/bin/python main.py --method ue-fusion --ue-storage fp32 --headless --output outputs/ue-fp32.png
```

On Windows use `.venv\Scripts\python.exe`. Device selection uses SlangPy's automatic backend or `--device metal`, `d3d12`, `vulkan`. Metal is validated locally; the new UE paths have not been executed on Windows/Vulkan hardware in this run.

## Source correspondence

Audit root: `/Users/litianyu/Perforce/hermitli_litianyudeMacBook-Pro_PBR`, `Engine/Build/Build.version` reports 5.8.0. [Source hashes](unreal-source-audit.json) identify the examined files; engine files are not included in this repository. These ports reproduce the algorithm and selected default render graph, not a bitwise Unreal frame capture.

| UE source, relative to Engine | Port |
| --- | --- |
| `Shaders/Private/PostProcessLocalExposure.usf` | Fusion setup/blending and log setup |
| `Shaders/Private/PostProcessHistogram.usf` | 64×64-tile, 32-slice bilateral grid; packed integer histogram |
| `Shaders/Private/PostProcessHistogramCommon.ush` | Eye luminance, histogram mapping, base/detail/threshold exposure and Fusion inverse |
| `Shaders/Private/TonemapCommon.ush` | Scalar neutral-axis film response and fixed inverse fit |
| `Shaders/Private/PostProcessDownsample.usf` | One-bilinear low-quality and four-bilinear high-quality reductions |
| `Shaders/Private/FilterPixelShader.usf` | Paired bilinear Gaussian samples, mirror addressing |
| `Source/Runtime/Renderer/Private/PostProcess/PostProcessLocalExposure.cpp` | Formats, ceil pyramid dimensions, level cap, graph and parameters |
| `Source/Runtime/Renderer/Private/PostProcess/PostProcessHistogram.cpp` | Tile dispatch and grid extent |
| `Source/Runtime/Renderer/Private/PostProcess/PostProcessEyeAdaptation.cpp` | Luminance method and exposure conventions |
| `Source/Runtime/Renderer/Private/PostProcess/PostProcessing.cpp` | Desktop scene reduction inputs |
| `Source/Runtime/Renderer/Private/PostProcess/PostProcessWeightedSampleSum.cpp` | Gaussian radius, tap pairing, fast horizontal half-width blur |
| `Source/Runtime/Engine/Private/Scene.cpp` | Film and Local Exposure setting defaults |
| `Source/Runtime/Apple/MetalRHI/Private/MetalRHI.cpp` | Native PF_FloatRGB mapping |

## Fusion

Fusion starts at full resolution. It evaluates exposed luminance through UE's neutral film response followed by square root. Highlight/shadow scales map to brackets of `6 × (1 − scale)` stops. Gaussian well-exposedness weights use target 0.5 and fixed sigma 0.2 with `exp2`, then normalize. Each exposure/weight level uses four bilinear samples; dimensions round up independently, with at most `floor(log2(shorter side)) + 1` levels (default cap 16).

Coarse-to-fine reconstruction blends the weighted Laplacian lightness. Exposure recovery uses UE's fixed two-branch inverse film fit after squaring the reconstructed response, divided by exposed luminance. It intentionally keeps UE's upper-only pre-square clamp, fixed inverse constants when film settings change, and absence of a bracket-zero identity shortcut. This differs from Bart's calibrated Z curve/inverse LUT and bounded EV recovery.

Native storage uses R11G11B10 for exposures, weights **and reconstructed lightness**, matching the audited Metal PF_FloatRGB mapping. Reconstruction can lose signed residuals and precision. The FP32 control uses RGBA32F throughout these intermediates to show that storage effect; it is not the native UE default. Neutral-axis film math is evaluated in FP32, rather than reproducing every UE `half` operation or matrix rounding. Chroma/glow/color transforms have no mathematical contribution on a neutral axis; no full RGB UE FilmToneMap is implemented.

## Bilateral Grid

The grid covers 64×64 source tiles and 32 log-luminance slices. An 8×8 group gathers 16 complete 2×2 quads per thread. Partial quads at odd borders are omitted as in UE. Two adjacent slices receive fixed-point packed weight/moment contributions; the 16-bit packing, truncation and carry behavior are preserved. Histogram positions are clamped for bucket selection, while moment packing retains the original unclamped position. Out-of-range HDR is not silently repaired into a different histogram algorithm.

Trilinear slicing divides accumulated log luminance by weight. Empty slices fall back to the blurred log image. The base blends bilateral and Gaussian log luminance and adds global EV; middle grey, separate highlight/shadow thresholds, threshold strengths, contrast and detail strength then recover the multiplier. Strength 1 uses the finite limit of UE's infinite-width smoothstep ramp. There is no value-specific exposure-multiplier shortcut.

Desktop uses half-resolution scene color for grid construction and the 1/32 scene reduction for log setup. The first reduction is the default low-quality one-sample path; remaining reductions use high quality. Mobile uses full-resolution scene color for both. Native scene reductions use R11G11B10, grid RG32F, and log/blur R16F. The FP32 control uses RGBA32F scene reductions and R32F log/blur while preserving grid packing.

Gaussian taps reproduce the audited defaults `r.Filter.SizeScale=1`, `r.Filter.LoopMode=0`: radius from log-image **width** for both axes, maximum radius 31, paired discrete Gaussian weights, mirrored boundaries, horizontal half-width output when requested radius ≥7, then original-width vertical output. This is a compute implementation of the filter equations, rather than UE's raster filter machinery. Zero-radius underflow taps are assigned finite zero contribution; UE's possible `0/0` is not reproduced. Blend zero skips log/blur and supplies a cleared black fallback.

## Parameters and comparison conventions

The shared comparison preset uses highlight/shadow 0.8 to match this viewer; raw UE scene defaults are 1. Other defaults follow the audited source: detail 1, blurred blend 0.6, blur size 50%, thresholds 0, strengths 1, middle-grey bias 0; film slope 0.88, toe 0.55, shoulder 0.26, black clip 0, white clip 0.04. Use `main.py --help` for `--ue-*` overrides. Film configurations with singular match points are rejected. The tested parameter cases are described below, not an exhaustive guarantee for arbitrary extreme film settings.

Manual comparison supplies eye exposure `2^globalEV`, grey multiplier 1, exposure compensation settings/curve 1, and pre-exposure 1. `--ue-pre-exposure` divides incoming scene color; `--ue-grey-multiplier` and `--ue-middle-grey-bias` control bilateral middle grey. Log2 histogram bounds default to −8..4; extended EV100 project ranges must be converted explicitly. Luminance defaults to equal RGB weights, matching `r.AutoExposure.LuminanceMethod=0`; NTSC and working Rec.709 controls are available.

Automatic eye adaptation, history, exposure/contrast curves, lens calibration, working-color-space conversion, bloom interactions, viewport subrects and full UE tonemapping are outside this port. All algorithms apply recovered exposure to the same HDR input and then this repository's common ACES operator. Images therefore isolate Local Exposure behavior, rather than reproduce Unreal's complete post-processing output. Desktop scene reductions are recorded in the standalone chain even if an engine could share them with bloom.

## Validation

`python -m unittest tests.test_unreal_local_exposure` checks independent NumPy equations and pyramid stages for thin/tiny/odd dimensions up to 129×65, random HDR, black and colored hard edges, native storage, asymmetric brackets, EV ±2, film-toe branches, thresholds, detail strength, zero blend/empty grid, and pre-exposure invariance. Production output matches the diagnostic color output exactly in tested native cases. The NumPy reference does not call the runtime shaders or its Gaussian-tap builder.

On Apple M4 Pro, an independent 1021-sample ramp measures 8-bit linear interpolation fractions. The reference models that measured precision; FP32 CPU/GPU arithmetic can still straddle interpolation rounding ties. Stage bounds are 0.0001 stop for blurred log luminance and relative 0.05% for recovered multipliers, with tighter Fusion pyramid bounds and a separate packed-grid check. These are tested numerical tolerances, not an Unreal bitwise parity claim.

Four supplied HDR scenes and four exposure/contrast presets are rendered at 1080p, including native-versus-FP32 storage controls. [Image and GPU results](performance/unreal.md) preserve intentional algorithm differences. Existing Bart reference/optimized/error images are regenerated separately under their original quality gates.
