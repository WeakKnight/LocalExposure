# Asset and parameter validation

Same desktop backend, not phone captures. Independent unfused full pyramid reference; reference uses full-resolution Fusion without Guided; optimized uses quarter-width/height Fusion with full-resolution fine-residual correction. Shared calibration.

Result: 16/16 cases pass the red-area goal (native max RGB error ≥12 occupies <1%).

Backend: Metal, Apple M4 Pro. 1920×1080 R11G11B10 input, sigma 0.2.

Contrast Scale uses the viewer mapping: bracket magnitude = 6 × (1 − scale) EV.

| Scene | Preset | Global EV | Highlight / Shadow | RMSE | P99 | Max | Red area (%) | Goal |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| abandoned_tiled_room_4k | default | +0 | 0.8 / 0.8 | 0.3764 | 1 | 15 | 0.00005 | PASS |
| abandoned_tiled_room_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.6012 | 2 | 18 | 0.00950 | PASS |
| abandoned_tiled_room_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.6291 | 2 | 30 | 0.01654 | PASS |
| abandoned_tiled_room_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.7817 | 2 | 33 | 0.02170 | PASS |
| qwantani_patio_4k | default | +0 | 0.8 / 0.8 | 0.4111 | 1 | 8 | 0.00000 | PASS |
| qwantani_patio_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.6650 | 2 | 15 | 0.00125 | PASS |
| qwantani_patio_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.6220 | 2 | 19 | 0.00313 | PASS |
| qwantani_patio_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.7059 | 2 | 14 | 0.00212 | PASS |
| sundowner_deck_4k | default | +0 | 0.8 / 0.8 | 0.4405 | 2 | 13 | 0.00010 | PASS |
| sundowner_deck_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.7562 | 3 | 20 | 0.00781 | PASS |
| sundowner_deck_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.7125 | 3 | 27 | 0.00502 | PASS |
| sundowner_deck_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.8665 | 3 | 26 | 0.00318 | PASS |
| veranda_4k | default | +0 | 0.8 / 0.8 | 0.3372 | 1 | 15 | 0.00019 | PASS |
| veranda_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.5316 | 2 | 16 | 0.00135 | PASS |
| veranda_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.5752 | 2 | 33 | 0.00670 | PASS |
| veranda_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.6919 | 3 | 32 | 0.00265 | PASS |

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
