# Current Local Exposure algorithm performance

2026-10-08. Apple M4 Pro, Metal, macOS 26.3, SlangPy 0.43.1. Driver bundled with the OS; no separate driver revision queried. GPU timestamps use MTLCommandBuffer GPUStartTime/GPUEndTime, not CPU wall-clock timing.

## Workload and interpretation

- Four HDR EXRs: abandoned tiled room, Qwantani patio, Sundowner deck and Veranda. All resized identically to 1920×1080 or 3840×2160, packed once to R11G11B10 outside timing. These are static EXR workloads, not graphics-produced game HDR, Unreal engine frame captures or phone measurements.
- Global EV 0, Highlight Contrast 0.5, Shadow Contrast 0.8, sigma 0.2, 16-level cap, equal-RGB luminance. Bart UE-film mode uses the analytic curve/fixed inverse, no curve LUT. Bilateral uses its independent base/detail semantics at the same contrast controls; these are not quality-matched outputs.
- Shared final ACES and RGBA16F linear-SDR output. Baseline is the same source → global exposure → ACES → output, without Local Exposure. UE desktop reduction work is included, even if an engine could share it with other effects.
- Compilation/allocation/readback checks precede eight warmup rounds. Then 60 rounds per workload, random interleaving of the baseline and seven algorithms. All processing passes recompute every sample; no cached output, GUI, visualization, diagnostic writes or final display/presentation in timing.
- Complete chain is measured directly as a whole command buffer. Local Exposure increment is the median of each round’s algorithm time minus that round’s common baseline. Do not subtract independently summarized medians to reconstruct it.
- Aggregate tables take the median of four per-scene medians. Full per-scene P10/P90, samples, round orders, settings and source hashes are in the [raw report](baselines/current-algorithms.json). No measured bandwidth or offline compiler projection is reported.

## Aggregate GPU time

| Algorithm | 1080p LE increment ms | 1080p complete chain ms | 4K LE increment ms | 4K complete chain ms |
| --- | ---: | ---: | ---: | ---: |
| Bart fine residual / UE film ALU | 0.0917 | 0.2002 | 0.2780 | 0.7001 |
| Bart fine residual / Z LUT | 0.0949 | 0.2035 | 0.2985 | 0.7213 |
| Bart full reference / UE film ALU | 1.3623 | 1.4710 | 5.3167 | 5.7477 |
| UE Fusion / native | 0.4807 | 0.5897 | 1.6683 | 2.0917 |
| UE Fusion / FP32 | 1.5479 | 1.6579 | 6.0269 | 6.4700 |
| UE Bilateral Grid / native | 0.0880 | 0.1967 | 0.2756 | 0.6975 |
| UE Bilateral Grid / FP32 | 0.1440 | 0.2523 | 0.6306 | 1.0526 |

Baseline aggregate complete-chain time: 0.1087 ms at 1080p and 0.4215 ms at 4K. Shared tone-mapping performance is not counted as Local Exposure savings.

Bart fine residual with UE-film ALU and UE native Bilateral Grid are effectively in the same performance range here: approximately 0.20 ms complete chain at 1080p and 0.70 ms at 4K. Their small ordering difference should not be generalized into a meaningful winner. The optimized Bart graph retains a full-resolution fine correction but performs its pyramid on 1/16 of the input pixels. UE Fusion processes its pyramids at full resolution.

The UE Fusion native and FP32 variants preserve different intermediate formats. Prior image experiments show appreciable native-format darkening on this Metal path, so native timing is not a same-quality substitute for FP32. Conversely, Bilateral is a different algorithm and is not a same-quality substitution for Fusion. The full Bart reference is a diagnostic control, not the optimized default.

The earlier analytic-film measurements used RGBA32F HDR input. This run uses R11G11B10 HDR input for every algorithm. The absolute times must not be compared as a code speedup: texture size/filtering/cache costs differ. No runtime shaders were changed in this performance task.

## Per-scene medians

| Resolution / scene | Algorithm | Chain ms | Chain P10–P90 ms | LE increment ms |
| --- | --- | ---: | --- | ---: |
| 1920×1080 / abandoned_tiled_room_4k | Bart fine residual / UE film ALU | 0.2027 | 0.1953–0.2092 | 0.0941 |
| 1920×1080 / abandoned_tiled_room_4k | Bart fine residual / Z LUT | 0.2035 | 0.1999–0.2105 | 0.0948 |
| 1920×1080 / abandoned_tiled_room_4k | Bart full reference / UE film ALU | 1.4684 | 1.4510–1.4890 | 1.3595 |
| 1920×1080 / abandoned_tiled_room_4k | UE Fusion / native | 0.5907 | 0.5793–0.5994 | 0.4815 |
| 1920×1080 / abandoned_tiled_room_4k | UE Fusion / FP32 | 1.6562 | 1.6458–1.7001 | 1.5469 |
| 1920×1080 / abandoned_tiled_room_4k | UE Bilateral Grid / native | 0.1973 | 0.1931–0.2057 | 0.0883 |
| 1920×1080 / abandoned_tiled_room_4k | UE Bilateral Grid / FP32 | 0.2526 | 0.2469–0.2610 | 0.1445 |
| 1920×1080 / qwantani_patio_4k | Bart fine residual / UE film ALU | 0.1986 | 0.1955–0.2064 | 0.0897 |
| 1920×1080 / qwantani_patio_4k | Bart fine residual / Z LUT | 0.2035 | 0.1990–0.2099 | 0.0950 |
| 1920×1080 / qwantani_patio_4k | Bart full reference / UE film ALU | 1.4696 | 1.4497–1.5437 | 1.3615 |
| 1920×1080 / qwantani_patio_4k | UE Fusion / native | 0.5906 | 0.5794–0.5968 | 0.4823 |
| 1920×1080 / qwantani_patio_4k | UE Fusion / FP32 | 1.6590 | 1.6488–1.7012 | 1.5489 |
| 1920×1080 / qwantani_patio_4k | UE Bilateral Grid / native | 0.1963 | 0.1932–0.2009 | 0.0876 |
| 1920×1080 / qwantani_patio_4k | UE Bilateral Grid / FP32 | 0.2519 | 0.2466–0.2573 | 0.1435 |
| 1920×1080 / sundowner_deck_4k | Bart fine residual / UE film ALU | 0.1999 | 0.1957–0.2058 | 0.0911 |
| 1920×1080 / sundowner_deck_4k | Bart fine residual / Z LUT | 0.2050 | 0.1992–0.2091 | 0.0958 |
| 1920×1080 / sundowner_deck_4k | Bart full reference / UE film ALU | 1.4738 | 1.4636–1.5729 | 1.3648 |
| 1920×1080 / sundowner_deck_4k | UE Fusion / native | 0.5889 | 0.5797–0.6025 | 0.4798 |
| 1920×1080 / sundowner_deck_4k | UE Fusion / FP32 | 1.6575 | 1.6391–1.6767 | 1.5478 |
| 1920×1080 / sundowner_deck_4k | UE Bilateral Grid / native | 0.1967 | 0.1942–0.2015 | 0.0880 |
| 1920×1080 / sundowner_deck_4k | UE Bilateral Grid / FP32 | 0.2516 | 0.2466–0.2600 | 0.1430 |
| 1920×1080 / veranda_4k | Bart fine residual / UE film ALU | 0.2005 | 0.1968–0.2076 | 0.0922 |
| 1920×1080 / veranda_4k | Bart fine residual / Z LUT | 0.2030 | 0.1982–0.2066 | 0.0942 |
| 1920×1080 / veranda_4k | Bart full reference / UE film ALU | 1.4725 | 1.4634–1.5966 | 1.3632 |
| 1920×1080 / veranda_4k | UE Fusion / native | 0.5878 | 0.5790–0.5953 | 0.4782 |
| 1920×1080 / veranda_4k | UE Fusion / FP32 | 1.6583 | 1.6457–1.6818 | 1.5480 |
| 1920×1080 / veranda_4k | UE Bilateral Grid / native | 0.1967 | 0.1938–0.2002 | 0.0880 |
| 1920×1080 / veranda_4k | UE Bilateral Grid / FP32 | 0.2536 | 0.2466–0.2601 | 0.1446 |
| 3840×2160 / abandoned_tiled_room_4k | Bart fine residual / UE film ALU | 0.6971 | 0.6931–0.7021 | 0.2755 |
| 3840×2160 / abandoned_tiled_room_4k | Bart fine residual / Z LUT | 0.7224 | 0.7158–0.7350 | 0.3013 |
| 3840×2160 / abandoned_tiled_room_4k | Bart full reference / UE film ALU | 5.7599 | 5.6706–6.0206 | 5.3189 |
| 3840×2160 / abandoned_tiled_room_4k | UE Fusion / native | 2.0917 | 2.0786–2.2178 | 1.6689 |
| 3840×2160 / abandoned_tiled_room_4k | UE Fusion / FP32 | 6.4647 | 6.3547–6.7726 | 6.0249 |
| 3840×2160 / abandoned_tiled_room_4k | UE Bilateral Grid / native | 0.6973 | 0.6897–0.7096 | 0.2754 |
| 3840×2160 / abandoned_tiled_room_4k | UE Bilateral Grid / FP32 | 1.0561 | 1.0461–1.0719 | 0.6340 |
| 3840×2160 / qwantani_patio_4k | Bart fine residual / UE film ALU | 0.7007 | 0.6968–0.7145 | 0.2799 |
| 3840×2160 / qwantani_patio_4k | Bart fine residual / Z LUT | 0.7202 | 0.7126–0.7293 | 0.2976 |
| 3840×2160 / qwantani_patio_4k | Bart full reference / UE film ALU | 5.7002 | 5.6592–5.9213 | 5.2701 |
| 3840×2160 / qwantani_patio_4k | UE Fusion / native | 2.0917 | 2.0755–2.2388 | 1.6674 |
| 3840×2160 / qwantani_patio_4k | UE Fusion / FP32 | 6.4156 | 6.3502–6.7032 | 5.9723 |
| 3840×2160 / qwantani_patio_4k | UE Bilateral Grid / native | 0.7002 | 0.6907–0.7103 | 0.2781 |
| 3840×2160 / qwantani_patio_4k | UE Bilateral Grid / FP32 | 1.0516 | 1.0447–1.1594 | 0.6300 |
| 3840×2160 / sundowner_deck_4k | Bart fine residual / UE film ALU | 0.7004 | 0.6939–0.7319 | 0.2787 |
| 3840×2160 / sundowner_deck_4k | Bart fine residual / Z LUT | 0.7193 | 0.7133–0.7334 | 0.2973 |
| 3840×2160 / sundowner_deck_4k | Bart full reference / UE film ALU | 5.7626 | 5.6670–6.0370 | 5.3330 |
| 3840×2160 / sundowner_deck_4k | UE Fusion / native | 2.0953 | 2.0775–2.2596 | 1.6715 |
| 3840×2160 / sundowner_deck_4k | UE Fusion / FP32 | 6.4753 | 6.3688–6.7376 | 6.0289 |
| 3840×2160 / sundowner_deck_4k | UE Bilateral Grid / native | 0.6978 | 0.6882–0.7102 | 0.2758 |
| 3840×2160 / sundowner_deck_4k | UE Bilateral Grid / FP32 | 1.0520 | 1.0412–1.1136 | 0.6294 |
| 3840×2160 / veranda_4k | Bart fine residual / UE film ALU | 0.6999 | 0.6938–0.7070 | 0.2773 |
| 3840×2160 / veranda_4k | Bart fine residual / Z LUT | 0.7226 | 0.7150–0.7363 | 0.2995 |
| 3840×2160 / veranda_4k | Bart full reference / UE film ALU | 5.7356 | 5.6721–5.9865 | 5.3145 |
| 3840×2160 / veranda_4k | UE Fusion / native | 2.0916 | 2.0784–2.1377 | 1.6677 |
| 3840×2160 / veranda_4k | UE Fusion / FP32 | 6.4867 | 6.3653–6.6707 | 6.0671 |
| 3840×2160 / veranda_4k | UE Bilateral Grid / native | 0.6965 | 0.6902–0.7136 | 0.2745 |
| 3840×2160 / veranda_4k | UE Bilateral Grid / FP32 | 1.0533 | 1.0447–1.0842 | 0.6313 |

## Reproduce

```sh
python tools/profiling/benchmark_current_algorithms.py
```

All eight workloads produced finite outputs for every algorithm before timing. Shader quality/regression coverage is unchanged from [the equal-RGB validation](equal-rgb-luminance.md).
