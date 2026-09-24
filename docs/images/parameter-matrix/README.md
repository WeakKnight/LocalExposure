# Asset and parameter validation

Same desktop backend, not phone captures. Independent unfused full pyramid reference; both paths use quarter-width/height Fusion, Guided upsampling and shared calibration.

Result: 15/16 cases pass all fixed gates.

Backend: D3D12, NVIDIA GeForce RTX 5080. 1920×1080 R11G11B10 input, sigma 0.2.

Contrast Scale uses the viewer mapping: bracket magnitude = 6 × (1 − scale) EV.

| Scene | Preset | Global EV | Highlight / Shadow | RMSE | P99 | Max | Pixels >4 (%) | Gate |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| abandoned_tiled_room_4k | default | +0 | 0.8 / 0.8 | 0.2182 | 1 | 2 | 0.00000 | PASS |
| abandoned_tiled_room_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.2785 | 1 | 3 | 0.00000 | PASS |
| abandoned_tiled_room_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.1523 | 1 | 7 | 0.00231 | PASS |
| abandoned_tiled_room_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.2799 | 1 | 4 | 0.00000 | PASS |
| qwantani_patio_4k | default | +0 | 0.8 / 0.8 | 0.2025 | 1 | 3 | 0.00000 | PASS |
| qwantani_patio_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.2988 | 1 | 4 | 0.00000 | PASS |
| qwantani_patio_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.1622 | 1 | 4 | 0.00000 | PASS |
| qwantani_patio_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.2276 | 1 | 7 | 0.00024 | PASS |
| sundowner_deck_4k | default | +0 | 0.8 / 0.8 | 0.2191 | 1 | 3 | 0.00000 | PASS |
| sundowner_deck_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.2722 | 1 | 11 | 0.00034 | PASS |
| sundowner_deck_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.1738 | 1 | 6 | 0.00010 | PASS |
| sundowner_deck_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.2866 | 1 | 7 | 0.00043 | PASS |
| veranda_4k | default | +0 | 0.8 / 0.8 | 0.2192 | 1 | 3 | 0.00000 | PASS |
| veranda_4k | dark-shadow-lift | -2 | 0.9 / 0.5 | 0.2984 | 1 | 6 | 0.00053 | PASS |
| veranda_4k | bright-highlight-protection | +2 | 0.5 / 0.9 | 0.1367 | 1 | 4 | 0.00000 | PASS |
| veranda_4k | strong-balanced | +0 | 0.5 / 0.5 | 0.2672 | 1 | 13 | 0.00101 | FAIL |

Errors are sRGB8 code values. Fixed gates: RMSE ≤0.75, P99 ≤3, max ≤12, pixels >4 ≤0.1%. Numerical gates supplement visual inspection; this is not an exhaustive parameter sweep.

Each overview row shows reference / optimized / absolute error. The error scale is shared across all cases. Worst-pixel crops and source hashes are indexed in [manifest.json](manifest.json). Full-resolution triples are generated locally in `outputs/quality/parameter-matrix`.

Failed case: **veranda_4k / strong-balanced**. 2 pixels exceed 12 codes; 21 exceed 4. [Worst-pixel crop](veranda_4k-strong-balanced-worst.png) (reference / optimized / error). The failure is retained; thresholds are unchanged.

## abandoned_tiled_room_4k

![Comparison](abandoned_tiled_room_4k.png)

## qwantani_patio_4k

![Comparison](qwantani_patio_4k.png)

## sundowner_deck_4k

![Comparison](sundowner_deck_4k.png)

## veranda_4k

![Comparison](veranda_4k.png)

Regenerate: `python tools/validate_asset_matrix.py`; check freshness: `python tools/validate_asset_matrix.py --check`. All cases run even when a numerical gate fails; the final exit code is nonzero if any case fails.
