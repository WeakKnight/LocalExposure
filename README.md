# Fusion Local Exposure

**Reveal shadow detail while keeping bright regions under control.** A GPU local-exposure pipeline built with SlangPy and Slang, from an interactive reference to an optimized mobile implementation.

| Global exposure + ACES | Fusion local exposure + ACES |
| :---: | :---: |
| ![Deck before local exposure](docs/images/sundowner_deck-before.png) | ![Deck after local exposure](docs/images/sundowner_deck-after.png) |
| ![Veranda before local exposure](docs/images/veranda-before.png) | ![Veranda after local exposure](docs/images/veranda-after.png) |

Each pair uses the same HDR input, global exposure, and tone mapper. Examples use ±3 EV brackets to emphasize the effect; the default is ±1.2 EV.

## What we built

Exposure fusion supplies the foundation. Our work focuses on turning it into a practical **HDR exposure adjustment** with a small mobile runtime:

- **Fuse lightness, apply exposure to HDR.** Blend three synthetic exposures across a Laplacian pyramid, reconstruct the desired lightness, then recover a local exposure multiplier. The final RGB image passes through the real tone mapper.
- **Calibrate the brightness response.** Fit a monotone Z curve to the tone mapper's neutral response and bake its inverse into a **2 KiB, 1024-entry R16F LUT**. Exposure recovery takes one filtered lookup instead of an iterative search. This approximates neutral luminance, not arbitrary color interactions.
- **Do the heavy work on 1/16 of the pixels.** Fusion runs at quarter width and height. Guided upsampling uses full-resolution luminance to align exposure changes with image edges and reduce halos.
- **Store exposure differences, preserve the baseline.** The optimized mobile graph keeps the middle-exposure lightness in FP32 and stores two signed differences in RG16F. Compact intermediates, Gather reduction, and local reconstruction of three pyramid levels reduce memory traffic and synchronization.

## Keeping the optimized result faithful

**Full reference · Optimized default · Error**

Each scene covers four parameter presets, top to bottom: default, darker global exposure with stronger shadow lift, brighter global exposure with stronger highlight protection, and stronger balanced local exposure.

**Abandoned Tiled Room**

![Abandoned Tiled Room: four presets, reference, optimized result, and error](docs/images/parameter-matrix/abandoned_tiled_room_4k.png)

**Qwantani Patio**

![Qwantani Patio: four presets, reference, optimized result, and error](docs/images/parameter-matrix/qwantani_patio_4k.png)

**Sundowner Deck**

![Sundowner Deck: four presets, reference, optimized result, and error](docs/images/parameter-matrix/sundowner_deck_4k.png)

**Veranda**

![Veranda: four presets, reference, optimized result, and error](docs/images/parameter-matrix/veranda_4k.png)

Both paths use the same HDR input, complete pyramid, and quarter-width/height Fusion with Guided upsampling. The reference runs the independent, unfused pipeline. Error colors show the largest RGB difference in sRGB8 code values on a fixed 0–12 scale; black means identical. Previews preserve peak errors rather than averaging them away.

Desktop validation passes 15 of 16 cases. Veranda's stronger balanced preset has two pixels at 13 codes, exceeding the unchanged 12-code limit.

[All settings and error metrics](docs/images/parameter-matrix/README.md) · [Full-size images and regeneration](docs/image-comparison.md)

## Try it

Windows or macOS

**Windows** (D3D12 or Vulkan)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run.ps1 --view compare
```

**macOS**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --view compare
```

Switch HDR scenes, adjust exposure, and compare the result interactively. **F5** reloads shaders; **F2** saves an image.

The PC viewer is the independent reference implementation. The optimized mobile graph lives in [fusion_compact.slang](shaders/fusion_compact.slang) and runs through the [Android benchmark](docs/performance/android.md).

[Pipeline and calibration details](docs/implementation.md) · [Developer documentation](docs/README.md)

## References

- [Bart Wronski — Exposure Fusion: local tonemapping for real-time rendering](https://bartwronski.com/2022/02/28/exposure-fusion-local-tonemapping-for-real-time-rendering/)
- [Mertens-style exposure fusion reference implementation](https://github.com/kbmajeed/exposure_fusion)
- Unreal Engine's `PostProcessLocalExposure.usf` — Fusion parameter semantics and pyramid downsampling.
- [Krzysztof Narkowicz — ACES Filmic Tone Mapping Curve](https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/)
- [SlangPy](https://github.com/shader-slang/slangpy)

Example HDRIs: [Sundowner Deck / Dario Barresi](https://polyhaven.com/a/sundowner_deck) and [Veranda / Greg Zaal](https://polyhaven.com/a/veranda), via Poly Haven (CC0).
