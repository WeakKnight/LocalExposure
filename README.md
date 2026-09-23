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
| `--levels` | 16 | Maximum pyramid levels, capped by the shorter working-image dimension |
| `--fusion-scale` | 4 | Resolution divisor per axis: 4 for guided quarter resolution, 1 for full reference |

## Implementation

`HDR → Three-exposure lightness and weights → Multiscale pyramids → Weighted Laplacian blending and coarse-to-fine reconstruction → Local exposure multiplier → HDR × Exposure → ACES → sRGB`

`shaders/pyramid.slang` generates lightness and weights. `shaders/fusion.slang` handles blending, reconstruction, and numerical exposure inversion. The implementation uses UE Fusion-style four-tap downsampling and exp2 weights. It derives luminance from an RGB LUT proxy of the current tone operator (ACES Filmic by default), and is not a full reproduction of UE FilmToneMap.

```powershell
.\.venv\Scripts\python.exe test_pyramid.py          # Numerical regression tests
.\.venv\Scripts\python.exe docs/render_examples.py  # Regenerate README comparisons
```

## Quarter-Resolution Fusion

By default, Fusion and the 10-step exposure search run at **1/4 width x 1/4 height** (1/16 as many pixels). A 4096x2048 input uses a 1024x512 working image. The UI's **Fusion resolution** selector switches between the guided version and the full-resolution reference; `--fusion-scale 1` selects the reference from the command line.

`shaders/guided.slang` downsamples linear HDR and log-luminance guidance separately, fits local `EV = a * guide + b` models in 5x5 low-resolution windows, averages the coefficients, and evaluates them with full-resolution guidance. Regularization is 0.04 EV squared, and the resulting local EV is limited to [-12, 12]. Only exposure application and the real tone mapper run at full resolution.

This is an approximation: averaging HDR before nonlinear tone mapping and omitting the finest Fusion bands can change fine detail and strong highlights. Guided upsampling reduces edge bleed but cannot recover information already lost during reduction. The lower working pixel count is not a measured 16x frame-time speedup; full-resolution output and guided-filter passes still have a cost.

```powershell
.\.venv\Scripts\python.exe -m unittest test_guided test_lut test_pyramid
```

## Log-Input 3D LUT Proxy

Fusion uses a GPU-baked **16-cubed RGB10A2_UNORM LUT** (16 KiB). Each HDR RGB channel is encoded as `log2(1 + x/k) / log2(1 + M/k)`, with `k = 1/64` and `M = 65535`. Log spacing concentrates samples in shadows and midtones while preserving black. The LUT stores **display-linear RGB** with 10 bits per channel (alpha is unused), so its output needs no log decoding. LUT baking and lookup arithmetic remain float32.

The LUT is rebuilt on startup and **F5**, using `shaders/tone_operator.slang`. Three-exposure lightness and scalar exposure search use the same trilinear lookup; the original comparison and final image use the real operator. Inputs outside [0, 65535] clamp to the LUT boundary; lookup never falls back to the real operator. No curve fitting or SciPy dependency is required.

The adapter must return finite linear Rec.709 SDR RGB in [0, 1]. Validation checks the real operator and ideal trilinear LUT on 25 color rays for nonmonotone luminance responses before accepting a new LUT; a failed reload retains the previous shaders and LUT. Hardware-filter rounding is recorded separately (maximum downward luminance step about 0.0000392 on the current validation set). This sampled check is not a proof of monotonicity for arbitrary operators. Spatial or temporal tone mapping cannot be represented by this fixed RGB LUT.

```powershell
.\.venv\Scripts\python.exe lut_proxy.py   # Bake and validate independently
.\.venv\Scripts\python.exe test_lut.py    # LUT, channel coupling, bounds, reload tests
```

Open `outputs/lut/report.html` for validation errors. `validation.json` and `samples.npz` contain metrics and measured responses. The report tool also accepts `--size 33` or `--size 129` to compare precision; the viewer uses 16 cubed. On the current ACES validation set, maximum RGB error is approximately **0.02424**, and RGB RMSE is **0.00715**. Exposure is still one scalar multiplier shared by RGB, solved with 10 LUT-based bisection iterations within +/-12 EV.

Precision: final/base colors use RGBA16F. The search interval, guided-filter per-sample products, and sRGB multiply/add operations use native half arithmetic. Sensitive Fusion calculations and guided accumulation/solving remain float. See the [precision review](docs/precision.md) for error measurements and rejected candidates.

## References

- [Bart Wronski — Exposure Fusion: local tonemapping for real-time rendering](https://bartwronski.com/2022/02/28/exposure-fusion-local-tonemapping-for-real-time-rendering/): synthetic exposures, multiscale fusion, and applications in real-time rendering.
- [kbmajeed / exposure_fusion](https://github.com/kbmajeed/exposure_fusion): a reference implementation of Mertens et al.'s Exposure Fusion method, including weights and pyramid blending.
- **Unreal Engine source:** `Engine/Shaders/Private/PostProcessLocalExposure.usf`, used to compare Fusion parameter semantics and downsampling (requires access to the engine source).
- [Krzysztof Narkowicz — ACES Filmic Tone Mapping Curve](https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/): the filmic curve approximation used in this project.
- [SlangPy documentation](https://slangpy.shader-slang.org/en/latest/): GPU compute, resources, and window APIs.

Example HDRIs are from Poly Haven under CC0: [Sundowner Deck / Dario Barresi](https://polyhaven.com/a/sundowner_deck) and [Veranda / Greg Zaal](https://polyhaven.com/a/veranda).
