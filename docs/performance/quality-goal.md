# Full-resolution quality goal

The retained default is `fine-residual-lookup`. Acceptance is **<1% native pixels with max RGB sRGB8 error ≥12 in every one of 4 scenes × 4 presets**, with Local Exposure incremental GPU time no more than 20% above the previous 0.9602 ms baseline (limit 1.1522 ms). No thresholds or preview scales were relaxed to count fewer red pixels.

## Integrated result

- Desktop D3D12 / RTX 5080: **16/16 pass**, worst red area **0.02175%** (Abandoned Tiled Room, strong-balanced). Both paths read identical 1920×1080 R11G11B10 HDR and share calibration; the independent reference runs full-resolution Fusion without Guided. See the [complete matrix](../images/parameter-matrix/README.md).
- Adreno 830 / NX789J, process-local Qualcomm **512.842.6**, 1080p / 45 FPS: **0.8514 ms LE increment / 3.2983 ms complete chain**, 1,800 frames/path, 60 warmup frames/block. Fresh retained Guided control: **0.9625 ms / 3.4083 ms**. This is about 11.5% less incremental time, comfortably inside the +20% limit.
- Matched graphics-produced R11G11B10 HDR → RGBA8 sRGB, joint submission. Both paths include the same HDR producer and tone mapper; presentation, visualization, uploads and calibration are outside timing. Results are not measurements of Adreno 730/750 or a complete game.
- Foreground output is **byte-identical to the new headless candidate output**. Same-phone independent full-resolution reference, Veranda/default: **0.000193%** red, RMSE **0.36085**, max **15** codes. That reference validation used the system Vulkan loader; foreground used the process-local driver. Full 16-case image coverage is desktop, not 16 phone captures.
- Modeled incremental texture sweeps: **0.7563 GB/s at 45 FPS**. This is not measured DRAM bandwidth; the two forward tables are charged as bound inputs, with no hardware cache-counter claim.

The earlier strict gate (RMSE ≤0.75, P99 ≤3, max ≤12, pixels >4 ≤0.1%) still passes only **2/16**. Its metrics and `legacy_accepted` remain in the manifests. The accepted goal is the explicitly requested red-area criterion, not universal pixel equivalence.

## What changed

The old path averaged HDR before nonlinear exposure/weight evaluation, reconstructed inverse exposure at low resolution, and fitted Guided coefficients. The new path evaluates exposure and weights on four bilinear source samples before averaging, retains the compact residual pyramid, then restores a fine residual and inverts lightness at full resolution. No Guided dispatch is needed.

Two 2048-entry RGBA32F forward tables use log2 luminance [-40,40] (64 KiB total). The existing inverse remains 1024-entry R16F. Tables are cached until curve/bracket/sigma changes; their rebuild cost is outside runtime timing. Source evaluation retains the calibrated 65535 bound. See [stage layout](../implementation.md).

## Known limits

- This correction approximates missing fine pyramid bands. Synthetic independent random HDR pixels still produce **10.8–19.9%** red area.
- A newly added 513×289 discontinuous colored edge at −2 EV produces **1.95%** red area and max **79** codes. It remains an explicit expected failure in `tests/test_fine_residual.py`; the same edge at 0/+2 EV passes. Do not infer universal edge acceptance from asset metrics.
- The earlier moving-edge/ramp sweep has zero red pixels and temporal differential peak four codes. It is not an animation/temporal guarantee.
- All 81 small-dimension/parameter cases remain finite, but extreme hard edges at 3×2 and 65×1 can fail the red-area criterion (up to 20 codes).
- The full-resolution reference shares curve calibration and some half storage; it is an independent spatial algorithm, not all-FP32 ground truth. Shared model errors are outside this comparison.

## Reproduction and evidence

```powershell
python tools/render_comparison.py
python tools/validate_asset_matrix.py
python -m unittest discover -s tests
```

Export using `python -m tools.profiling.android.benchmark --variant fine-residual-lookup --source-format r11g11b10_float --output-format rgba8_srgb` (see [benchmark instructions](android.md)); full-resolution reference work runs separately after timing.

Ignored local evidence under `outputs/quality-goal/`:

| Evidence | Directory/file |
| --- | --- |
| Starting 16-case errors and target | `baseline.json` |
| Integrated same-phone independent reference | `integrated-verified/bundle`, `integrated-verified/validation.json` |
| Integrated foreground short/sustained runs | `integrated-phone-screen`, `integrated-phone-sustained` |
| Fresh retained Guided sustained control | `retained-control-sustained` |
| Spatial and small-size limits | `nonlinear4-spatial.json`, `nonlinear4-small.json` |
| Published full-size desktop triples | `../quality/parameter-matrix` |

The first integrated headless command completed rendering and reference validation but its report step initially failed on obsolete inverse-LUT traffic accounting. Traffic accounting was fixed; a fresh complete run in `integrated-verified` passed normally, with candidate and full-reference bytes identical to the first run. Headless timings are diagnostic only. The sustained foreground run completed normally with exact output agreement.

Rejected experiments: analytic fine correction cost 1.766 ms; sixteen-sample nonlinear initialization cost 2.133 ms. A faster lookup-only correction with averaged-HDR initialization reached 0.740 ms but retained larger edge errors. Four-sample nonlinear initialization was selected for the measured quality/performance balance.
