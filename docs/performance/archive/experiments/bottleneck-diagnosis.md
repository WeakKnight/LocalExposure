# Production bottleneck diagnosis

The first priorities are **Guided reconstruction and reduction/exposure setup**.
The full-resolution apply pass is expensive in absolute terms, but ordinary
tonemapping costs almost the same in the matched replay experiment. Its entire
duration must not be counted as Local Exposure overhead.

## Method

NX789J / Adreno 830, process-local Qualcomm 512.842.6, retained gather-reduction,
1920x1080, R11G11B10 HDR input and RGBA8 sRGB output. Ordinary memory, no tile
placement. Foreground graphics HDR producer and postprocess share one submission;
visualization and presentation are excluded. Each run uses two alternating
rounds, 40 warmup frames and 120 measured frames per block (240 samples/path).

`replay_probe.py` repeats a production pass immediately after itself with the
normal inter-pass memory barrier. Inputs and shader binaries are unchanged;
the pass overwrites the same output with the same values. The apply-pair probe
repeats both production apply and baseline tonemapping in their respective paths.
All completed runs produce byte-identical final images against the retained
phone control. These bundles are diagnostic workloads, not production variants.

Replay measures a marginal dispatch under warm-cache conditions, including an
extra barrier. It is not an exact additive decomposition of the original frame,
nor does its cost equal an achievable optimization saving. Frequency is not
locked. A final control brackets the candidates to check drift.

See [portable measurements](../../baselines/bottleneck-diagnosis.json) for complete
chain timings, per-block medians, diagnostics and source/result hashes.

| Run order | Producer + Fusion + tonemap ms | Producer + baseline ms | Difference ms |
|---|---:|---:|---:|
| Control | 4.5239 | 2.4425 | 2.0814 |
| Guided twice | 5.3687 | 2.4412 | 2.9275 |
| Reduction/setup twice | 5.1626 | 2.4426 | 2.7200 |
| Apply and baseline each twice | 6.6538 | 4.5748 | 2.0790 |
| Control repeat | 4.5203 | 2.4425 | 2.0778 |

The two controls differ by 0.0037 ms in complete-chain median. Against their
mean, replay adds 0.8466 ms for Guided and 0.6405 ms for setup. Paired apply
adds 2.1317 ms to Fusion and 2.1323 ms to baseline; their -0.0006 ms difference
is effectively unresolved, not an exposure-related speedup.

## Interpretation

- Replaying Guided adds about 0.85 ms to the complete chain.
- Replaying reduction + three-exposure setup adds about 0.64 ms.
- Replaying production apply adds about 2.13 ms, but replaying plain tonemapping
  also adds about 2.13 ms. No positive incremental apply cost is resolved here;
  this does not mean the extra exposure math is free under all workloads.
- Separate instrumented control timings put pyramid downsampling at about
  0.28 ms, pyramid reconstruction at 0.19 ms and EV conversion at 0.19 ms.
  Those values include instrumentation effects and must not be summed with
  replay deltas as a precise budget.

This supports prioritizing the low-resolution filters over further placement-only
changes or optimizing the full-resolution tonemapper on behalf of Local Exposure.

## What limits Guided internally?

The retained shader uses a 16x16 output tile, a 24x24 input tile and 20x20
coefficient tile. It has four group synchronization points and four shared arrays
totalling 18,048 bytes per group. Input halo loading requests 576 float2 values
for 256 outputs before considering cache reuse between groups. The moment and
coefficient filters repeatedly read overlapping shared windows.

The existing **Adreno 730 offline** compilation of the exact same Guided SPIR-V
reports 523 static instructions, zero scratch, 75% projected fiber occupancy,
and 34.8%/58.2% exposed short/long latency-sync cycles. These percentages are
compiler projections, not measured Adreno 830 counters, are not additive, and
do not identify which hardware resource causes every wait. They support examining
dependency chains, shared-memory access and synchronization; they do not prove
a pure ALU or DRAM bandwidth bottleneck. The earlier tile-residency experiment
reduced diagnostic Guided time by only about 0.023 ms, also suggesting that
external intermediate residency alone does not address most of its cost.

The current Perfetto source list does not expose `gpu.counters`; GPU clock sysfs
reads return permission denied to ADB shell. No measured DRAM traffic, cache-hit,
stall, or shader-occupancy counters are claimed. Internal compute/shared-memory/
synchronization attribution remains open. Next targeted experiments should vary
window reuse and thread-to-output mapping, with matched whole-chain timing and
the existing quality gate, rather than assume that adding half or tile memory
automatically addresses the limiting resource.

## Tooling correction and reproduction

The first apply-pair attempt exposed an old runner assumption that exactly one
baseline pass existed. Diagnostic readback then waited for an unwritten query.
That incomplete attempt is excluded. The runner now counts production passes
explicitly and allocates sufficient query slots for either path. Removing the
baseline graphics producer from the activity pass list does not decrement the
production count. The completed paired replay exercises this fix.

```console
python -m tools.profiling.android.replay_probe PATH_TO_VALIDATED_BUNDLE --stage reconstruct_guided --out outputs/android/probe-bundle
python -m tools.profiling.android.activity outputs/android/probe-bundle --out outputs/android/probe-run --custom-driver .tools/mobile/drivers/842.6 --hdr-producer --joint-submission --frames 120 --warmup 40 --rounds 2
```

Other stage choices are `reduce_setup`, `apply_exposure_production`, and
`apply_pair`. Use the original bundle for bracketing controls. Preserve the
actual phone/driver identity; these timings are not Snapdragon 8 Gen 1 results.
