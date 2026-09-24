# Tile-memory residency experiment

This opt-in experiment uses the process-local Qualcomm 512.842.6 driver on
NX789J / Adreno 830. Shader code, formats, dimensions, filter supports and
exposure parameters are unchanged. Production defaults remain ordinary memory.

## Results

1080p / 45 FPS, retained gather-reduction, same 512.842.6 driver, foreground
graphics HDR producer plus joint submission. Each row has 3 alternating rounds,
60 warmup and 300 measured frames per block: 900 samples per path.

| Run order / placement | Producer + Fusion + tonemap ms | Producer + baseline ms | Difference ms |
|---|---:|---:|---:|
| 1. Ordinary memory | 4.5253 | 2.4424 | 2.0829 |
| 2. guide_ev + averaged | 4.4777 | 2.5786 | 1.8990 |
| 3. averaged only | 4.5135 | 2.5796 | 1.9339 |
| 4. Ordinary memory repeat | 4.5266 | 2.4417 | 2.0849 |

The guided placement saves approximately **0.048–0.049 ms (1.1%) of complete
chain time** against the bracketing controls. Do not call the 0.184–0.186 ms
reduction in the difference an equivalent speedup: baseline itself regressed
by approximately 0.137 ms in the tile-enabled runs, despite no explicit tile
binding in its command buffer. The repeat returned to the original baseline.
The causal split between feature enablement, allocation, and driver state after
tile commands remains unisolated. This is a small opt-in experimental result,
not a demonstrated large production or power improvement.

Diagnostic guided-pass timestamps changed from 0.8530 to 0.8304 ms and final
apply from 2.1212 to 2.1092 ms. These separately instrumented values are only
localization clues; headline results use whole-chain timestamps.

All long-run final images were byte-identical to their existing phone control.
Additional foreground guided-placement checks on abandoned_tiled_room,
qwantani_patio and sundowner_deck were also byte-identical (four scenes total
including veranda). These short scene checks are quality checks, not performance
measurements. Tile intermediates themselves were not directly read back.
See the [machine-readable results](../baselines/tile-memory-runtime.json).
An initial transfer-usage attempt was rejected and is excluded from timings.
The standard system-loader binary also compiled; 8 benchmark/traffic tests passed.

## Implementation

`activity --tile-memory guided` places `guide_ev` (RG32F) and `averaged` (RG16F)
in one tile allocation, without aliasing. `--tile-memory averaged` places only
the latter in tile memory. Both require the single-queue graphics HDR producer
and joint submission workflow. No persistent input, LUT, final output or
backbuffer is allocated in tile memory.

Image support is queried before creation. Tile requirements determine offsets,
alignment and allocation size; the heap capacity and compatible memory types
are checked. Actual guided allocation: 1,658,880 bytes, with guide_ev occupying
1,105,920 bytes at offset 0 and averaged occupying 552,960 bytes at offset
1,105,920. Both have 12,288-byte alignment. Ordinary allocations explicitly
exclude the tile heap.

The tile range is bound after the graphics HDR producer, before Fusion, and
persists through final tonemapping within the same command buffer/submission.
Baseline and presentation command buffers do not bind tile memory. Every tile
texel is rewritten each Fusion execution; no tile contents cross submissions.

The first attempt requested transfer source/destination usage and received zero
tile requirements for guide_ev. The working images use sampled + storage + tile
usage only. Initialization omits tile clears, and post-submit debug dumps omit
tile resources. Validation compares the final ordinary-memory image exactly;
it does not claim direct intermediate tile readback. Debug readback is outside
all timing, so skipping it is not credited as an optimization.

The tiled pyramid itself is not migrated in this experiment. Multi-mip images
are outside the extension's guaranteed image configuration, and would need
additional format support checks or separate images per pyramid level.

## Reproduce

After the [custom driver setup](custom-driver.md), use an existing validated
gather-reduction bundle and fresh output directories:

```console
python -m tools.profiling.android.activity outputs/android/guided-batch/gather-reduction-phone-retry/bundle --custom-driver .tools/mobile/drivers/842.6 --hdr-producer --joint-submission --frames 300 --warmup 60 --rounds 3 --tile-memory guided --out outputs/android/tile-memory/new-guided
```

Omit `--tile-memory` for the same-driver control. Use `--tile-memory averaged`
for the smaller allocation. Results record the driver, resource requirements,
timings and exact final-image equality. Keep the phone unlocked and foreground.

## Bandwidth interpretation

The algorithm still performs the same texture accesses. In the existing sweep
model, reads and writes of these two resources sum to 3,110,400 bytes/frame
(0.140 GB/s at 45 FPS, 0.093 GB/s at 30 FPS). These accesses are candidates to
move on-chip, **not measured DRAM savings**. Ordinary-memory caches already
absorb some of them; reserving tile capacity can also alter other rendering
costs. No thermal or power improvement is claimed.

The entire algorithm's nominal traffic remains 19,177,620 bytes/frame; residency
changes where accesses are served, not the shader's requested bytes.
