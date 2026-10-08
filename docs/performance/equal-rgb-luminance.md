# Equal-RGB luminance update

2026-10-08. Current Bart Z and analytic UE-film paths now use `(R+G+B)/3` on linear RGB in both setup and exposure recovery. Full-resolution reference and quarter-resolution fine residual agree on the metric. UE defaults already used equal RGB. Film parameters, inverse rules, brackets and final display ACES are unchanged.

The historical Guided host now loads frozen Rec.709 pyramid and conversion shaders from `tools/profiling/controls`; old compact/Guided benchmark controls retain their definitions. Neutral-axis Z calibration still measures the display response, not arbitrary colored input. This is a Fusion proxy change, not a change to the output color space.

## Validation

The targeted pyramid/Z/UE-film/fine-residual run passed 24 tests, with the existing one expected extreme-edge failure. Independent UE FP32 comparisons now use equal RGB. The equal-luminance color regression uses gray/red/green with identical arithmetic means.

Regenerated and inspected reference/optimized/error pictures: Z mode 16/16 cases passed the existing red-pixel gate; analytic UE mode 16/16 passed. This gate requires error ≥12 sRGB8 codes on <1% of pixels, not a per-pixel guarantee. Sparse errors and the known extreme synthetic-edge limit remain. See [Z matrix](../images/parameter-matrix/README.md) and [UE film matrix](../images/ue-film/manifest.json).

Native 4096×2048 Veranda, Highlight 0.524 / Shadow 0.8, analytic UE mode: RMSE 0.6007, P99 2, max 22 codes, red fraction 0.01299%. Inspection covered roof/sky boundaries, foliage, door and furniture edges.

## Current GPU measurements

Apple M4 Pro / Metal / macOS 26.3 / SlangPy 0.43.1; OS-bundled driver. Static RGBA32F EXR input, shared ACES, RGBA16F output. Eight warmups, 60 randomized interleaved rounds, GPU whole-command timestamps. Viewer was stopped for timing. Local Exposure increments subtract the matched global-only baseline. Debug/readback/display/compilation are excluded. This compares current curve modes, not an isolated before/after speed claim for coefficient replacement. No phone, game or bandwidth claim.

| Workload | Z chain ms | UE film chain ms | Z LE increment ms | UE LE increment ms |
| --- | ---: | ---: | ---: | ---: |
| abandoned_tiled_room_4k-1920x1080 | 0.3961 | 0.4070 | 0.1957 | 0.2061 |
| qwantani_patio_4k-1920x1080 | 0.3954 | 0.4060 | 0.1975 | 0.2081 |
| sundowner_deck_4k-1920x1080 | 0.3962 | 0.4066 | 0.1982 | 0.2092 |
| veranda_4k-1920x1080 | 0.3963 | 0.4035 | 0.1986 | 0.2055 |
| veranda_4k-4096x2048 | 1.4676 | 1.5193 | 0.6735 | 0.7245 |

Raw samples, workload settings and source hashes: [manifest](../images/ue-film/manifest.json). Earlier Rec.709 measurements are preserved separately in [ue-film-rec709.json](baselines/ue-film-rec709.json).

Full discovery: 89 tests; the same 11 failing subcases, 5 errors and 1 expected failure as the preceding baseline. Failure/error identifiers were compared exactly, with no additions. Existing failures are retained, not skipped. Log: `outputs/equal-rgb-full-tests.log`.
