# Fusion bandwidth and pass compaction

The lossless production candidate reaches the **1.2 GB/s texture-sweep accounting target**, but **does not reach the 1.5 ms GPU increment target** on the connected Adreno 830. This is not an Adreno 730 phone measurement.

## Matched comparison

1920 × 1080, quarter-width/height guided Fusion, R11G11B10 input, RGBA8 sRGB attachment output, nominal 45 FPS. Both runs use identical input bytes, inverse LUT/calibration and final/baseline SPIR-V. Each workload has 60 warmups per block and 360 measured samples. Stock clocks; sequential runs, no frequency locking.

| Metric | Original | Fused candidate |
|---|---:|---:|
| Incremental texture-sweep MB/frame | 39.9014 | **25.9081** |
| Incremental texture-sweep GB/s at 45 FPS | 1.7956 | **1.1659** |
| Full guided chain median ms | 4.9937 | **4.2544** |
| Full guided chain P95 ms | 5.0117 | **4.2827** |
| Matched tonemap median ms | 0.6730 | 0.7597 |
| Difference of medians, ms | 4.3207 | **3.4947** |
| Compute dispatches, plus one final draw | 30 | **18** |

The full chain improves by about 14.8%. The increment improves descriptively by about 19.1%, but the baseline varies with stock power behavior. Older compute-output timing and this sRGB graphics-output timing are different contracts; an approximately 2 ms historical increment cannot replace the measured control above.

The sweep model charges each input mip once per pass and every output write. This assumes within-pass reuse and ignores cross-pass reuse. Its 35.1% reduction is **not a measured DRAM reduction**. Expanded texel-slot accounting falls only from 164.3580 to 161.0093 MB/frame: fusion eliminates stored intermediates while introducing halo recomputation. Cache behavior determines actual memory traffic. See the [candidate ledger](baselines/adreno830-fused-traffic.md) and [original ledger](baselines/adreno830-local-exposure-traffic.md).

## Changes

- Fuse HDR reduction and three-exposure setup. Keep only FP32 linear luminance and log guide in RG32F, rather than reduced RGBA32F color.
- Store all six useful lightness/weight channels in RGBA32F + RG32F. The lightness texture's former constant alpha holds the first weight; the second texture holds the other two. No mantissa bits are removed, and every channel retains the original filtering.
- Build both packed pyramids in one dispatch per level, preserving the four sample coordinates and addition order.
- Fuse finest weighted reconstruction, inverse exposure and both guided stages. A 16×16 output tile loads a 24×24 guide/exposure halo and computes a 20×20 coefficient halo in shared memory. Preserve the original half exposure/EV rounding and FP32 coefficient accumulation. No global finest-reconstruction, exposure or fitted-coefficient write is needed.

An initial 8×8 fused tile reduced stored traffic but did too much repeated halo work. Increasing it to 16×16 reduced the diagnosed fused-kernel median from about 1.84 to 1.39 ms; diagnostic pass timings are not additive production totals.

The largest remaining diagnostic costs are fused reconstruction/guided (~1.39 ms), full-resolution exposure/tonemap (~1.31 ms), and reduction/setup (~0.86 ms). Reaching 1.5 ms incremental GPU time needs further work; bandwidth accounting alone did not deliver that target.

## Validation and use

All 42 regression tests pass. The new test compares every packed pyramid mip and final averaged coefficients against the original graph on tiny, odd, partial-tile, high-dynamic-range and extreme-EV inputs. The current 1080p phone run is bitwise equal at all retained readbacks, including the final sRGB image. The phone reference executes the **entire original graph**, outside timing. Removed intermediate exposure/coefficient images are not separately checked in that run. The pre-existing desktop portability warning remains; no error threshold was widened.

Adreno 730 offline compilation reports **zero scratch usage** for all four final production kernels. This is a compiler check, not an 8 Gen 1 runtime result. Raw samples, validation, manifests and compiler records are archived in [the phone comparison](baselines/adreno830-fusion-compaction.json) and [the A730 compiler snapshot](baselines/adreno730-fusion-compaction.json).

```powershell
# Optimized production candidate; original graph remains the viewer/control.
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --fused-guided --source-format r11g11b10_float --output-format rgba8_srgb --fps 45 --out outputs/android/fused

# Matched original production control.
.\.venv\Scripts\python.exe -m tools.profiling.android.benchmark --source-format r11g11b10_float --output-format rgba8_srgb --fps 45 --out outputs/android/control
```

The implementation is `shaders/fusion_compact.slang`. `--compact` without `--fused-guided` retains separate guided stages for diagnosis; `--fused-guided` implies compact storage and the complete fused path. These options select production dataflow, not a visualization shortcut.
