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
- **Store exposure differences, preserve the baseline.** The optimized mobile graph keeps the middle-exposure lightness in FP32 and stores two signed differences in RG16F, with compact weights, Gather reduction, and fused passes. Precision is spent where reconstruction needs it.

## Try it

Python 3.12 · Windows or macOS

**Windows** (D3D12 or Vulkan)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run.ps1 --view compare
```

**macOS**

```bash
python3.12 -m venv .venv
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
