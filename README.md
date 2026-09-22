# Local Exposure

A three-exposure Fusion Local Exposure experiment built with **SlangPy + Slang**. It blends brightness across multiple scales, converts the result into local exposure, and applies it to the original HDR image before ACES Filmic tone mapping.

## Results

Each pair uses the same HDR image, global exposure, and ACES curve. Left: global exposure only. Right: local exposure enabled. Click an image to view it at full size.

| Global Exposure + ACES | Fusion Local Exposure + ACES |
| :---: | :---: |
| ![Sundowner Deck: global exposure only](docs/images/sundowner_deck-before.png) | ![Sundowner Deck: local exposure enabled](docs/images/sundowner_deck-after.png) |
| ![Veranda: global exposure only](docs/images/veranda-before.png) | ![Veranda: local exposure enabled](docs/images/veranda-after.png) |

Top: shadow detail in the deck roof and floor. Bottom: brightness changes in the veranda ceiling and brick walls.

**Example settings:** Highlight and Shadow Contrast Scale are both **0.5** (exposure offsets of ±3 EV), with Sigma = 0.2. Global exposure is −2 EV for the top pair and −1 EV for the bottom pair. These examples use a stronger adjustment than the application default of **0.8** to make the effect easier to see.

## Quick Start

Windows · Python 3.12 · GPU with D3D12 / Vulkan support.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run.ps1
```

Reproduce the deck example:

```powershell
.\run.ps1 --image Assets/sundowner_deck_4k.exr --exposure -2 --highlight-contrast 0.5 --shadow-contrast 0.5 --view compare
```

The View menu offers **Fusion Result / Original Comparison / Local Exposure EV**. Switch images and adjust exposure and weights interactively. **F5** reloads shaders, **F2** exports a PNG, and **Esc** exits.

| Parameter | Default | Description |
| --- | --- | --- |
| `--exposure` | 0 | Global exposure in EV |
| `--highlight-contrast` / `--shadow-contrast` | 0.8 / 0.8 | Each exposure offset has magnitude `6 × (1 − Scale)` EV; 1 means no offset |
| `--sigma` | 0.2 | Exposure weight width; smaller values make exposure selection more selective |
| `--levels` | 16 | Maximum pyramid levels, capped by the shorter image dimension |

## Implementation

`HDR → Three-exposure lightness and weights → Multiscale pyramids → Weighted Laplacian blending and coarse-to-fine reconstruction → Local exposure multiplier → HDR × Exposure → ACES → sRGB`

`shaders/pyramid.slang` generates lightness and weights. `shaders/fusion.slang` handles blending, reconstruction, and numerical exposure inversion. The implementation uses UE Fusion-style four-tap downsampling and exp2 weights. It currently derives luminance from an RGB ACES approximation and is not a full reproduction of UE FilmToneMap.

```powershell
.\.venv\Scripts\python.exe test_pyramid.py          # Numerical regression tests
.\.venv\Scripts\python.exe docs/render_examples.py  # Regenerate README comparisons
```

## References

- [Bart Wronski — Exposure Fusion: local tonemapping for real-time rendering](https://bartwronski.com/2022/02/28/exposure-fusion-local-tonemapping-for-real-time-rendering/): synthetic exposures, multiscale fusion, and applications in real-time rendering.
- [kbmajeed / exposure_fusion](https://github.com/kbmajeed/exposure_fusion): a reference implementation of Mertens et al.'s Exposure Fusion method, including weights and pyramid blending.
- **Unreal Engine source:** `Engine/Shaders/Private/PostProcessLocalExposure.usf`, used to compare Fusion parameter semantics and downsampling (requires access to the engine source).
- [Krzysztof Narkowicz — ACES Filmic Tone Mapping Curve](https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/): the filmic curve approximation used in this project.
- [SlangPy documentation](https://slangpy.shader-slang.org/en/latest/): GPU compute, resources, and window APIs.

Example HDRIs are from Poly Haven under CC0: [Sundowner Deck / Dario Barresi](https://polyhaven.com/a/sundowner_deck) and [Veranda / Greg Zaal](https://polyhaven.com/a/veranda).
