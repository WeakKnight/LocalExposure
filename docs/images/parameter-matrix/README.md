# Asset and parameter validation

Same desktop backend, not phone captures. Independent unfused full pyramid reference; reference uses full-resolution Fusion without Guided; optimized uses quarter-width/height Fusion with full-resolution fine-residual correction. Shared calibration.

Result: 16/16 cases pass the red-area goal (native max RGB error ≥12 occupies <1%).

Backend: Metal, Apple M4 Pro. 1920×1080 R11G11B10 input, sigma 0.2.

Contrast Scale uses the viewer mapping: bracket magnitude = 6 × (1 − scale) EV.

| Scene | Preset | Global EV | Highlight / Shadow | RMSE | P99 | Max | Red area (%) | Goal |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| abandoned_tiled_room_4k | default | +0 | 0.8 / 0.8 | 0.3719 | 1 | 13 | 0.00005 | PASS |
| abandoned_tiled_room_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.5949 | 2 | 22 | 0.00921 | PASS |
| abandoned_tiled_room_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.6203 | 2 | 28 | 0.01509 | PASS |
| abandoned_tiled_room_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.7730 | 2 | 31 | 0.02079 | PASS |
| qwantani_patio_4k | default | +0 | 0.8 / 0.8 | 0.4142 | 1 | 7 | 0.00000 | PASS |
| qwantani_patio_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.6730 | 2 | 14 | 0.00096 | PASS |
| qwantani_patio_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.6293 | 2 | 17 | 0.00183 | PASS |
| qwantani_patio_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.7106 | 2 | 14 | 0.00178 | PASS |
| sundowner_deck_4k | default | +0 | 0.8 / 0.8 | 0.4358 | 2 | 11 | 0.00000 | PASS |
| sundowner_deck_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.7518 | 3 | 21 | 0.00767 | PASS |
| sundowner_deck_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.6999 | 3 | 31 | 0.00313 | PASS |
| sundowner_deck_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.8540 | 3 | 23 | 0.00207 | PASS |
| veranda_4k | default | +0 | 0.8 / 0.8 | 0.3445 | 1 | 9 | 0.00000 | PASS |
| veranda_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.5642 | 2 | 18 | 0.00289 | PASS |
| veranda_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.5748 | 2 | 59 | 0.00448 | PASS |
| veranda_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.7102 | 3 | 17 | 0.00299 | PASS |

Errors are sRGB8 code values. Goal: red area <1% per case (max-channel error ≥12). The earlier strict RMSE/P99/max gate remains in manifest.json as legacy_accepted. Numerical gates supplement visual inspection; this is not an exhaustive parameter sweep.

Each overview row shows reference / optimized / absolute error. The error scale is shared across all cases. Worst-pixel crops and source hashes are indexed in [manifest.json](manifest.json). Full-resolution triples are generated locally in `outputs/quality/parameter-matrix`.

## abandoned_tiled_room_4k

![Comparison](abandoned_tiled_room_4k.png)

## qwantani_patio_4k

![Comparison](qwantani_patio_4k.png)

## sundowner_deck_4k

![Comparison](sundowner_deck_4k.png)

## veranda_4k

![Comparison](veranda_4k.png)

Regenerate: `python tools/validate_asset_matrix.py`; check freshness: `python tools/validate_asset_matrix.py --check`. All cases run even when a numerical gate fails; the final exit code is nonzero if any case fails.
