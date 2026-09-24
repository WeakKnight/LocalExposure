# Ten lossless optimization experiments for Adreno 730

These are ten tested candidates, **not ten proven speedups**. Two changes are retained; eight were rejected, deferred or reverted. No phone timings have been collected. Each candidate starts from the same frozen pre-experiment shaders, so its result is not confused with earlier candidates. Retained changes were then combined and validated again.

Toolchain: Slang 2026.12, SPIR-V 1.3, AOC 7.0.15 / E17.52.07.00, `a730`. The previous baseline is [a730-fit-tile](../../baselines/archive/a730-fit-tile.md); the combined result is [a730-ten-rounds](../../baselines/a730-ten-rounds.md). [Machine-readable per-round results](ten-rounds-results.json) preserve AOC sections, including preamble and performance projections.

| Round | Candidate | Main instructions, before -> candidate | Decision |
|---|---|---:|---|
| 1 | Flatten guided fit's 5x5 loop into one 25-tap loop | 578 -> 586 | Reject: more instructions, same registers |
| 2 | Flatten coefficient averaging's 5x5 loop | 333 -> 333 | Reject: no benefit |
| 3 | Explicit half2 packing of guided-fit products | 578 -> 578 | Reject: compiler already handles it equivalently |
| 4 | Pad guided-fit shared row pitch from 12 to 13 | 578 -> 576 | Retain: small static code reduction, unchanged registers/spills/loop count |
| 5 | Pad averaging shared row pitch from 12 to 13 | 333 -> 345 | Reject: more instructions |
| 6 | Two-dimensional cooperative loading for guided fit | 578 -> 478 | Defer: compiler leaves a loop; static reduction cannot establish lower executed cost |
| 7 | Two-dimensional cooperative loading for averaging | 333 -> 231 | Defer: register footprint 5 -> 4, but retained loop and worse long-latency projection; needs device timing |
| 8 | Hoist reduction's vertical UV outside its inner loop | 183 -> 183 | Reject: compiler already produces the same result |
| 9 | Sample only the visible image in compare view | 259 -> 279 | Retain: removes the unused final-image sample in the baseline region, at the cost of flow control |
| 10 | Reuse baseline tonemapping when exposure equals exactly 1 | 198 -> 201 | Reverted: user rejected exposure-specific specialization; retain the uniform operator path |

Rounds 6 and 7 were also checked with explicit unroll hints; AOC still retained one loop and reported the same instruction counts. The original load scheme remains in the final shader. No summation was split into separable passes, no arithmetic precision was reduced, and no approximate reciprocal/logarithm was introduced.

## Retained changes and limits

The fit tile still contains the same 12x12 values, now stored with row pitch 13. Shared allocation increases from 1152 to 1248 bytes per group. A730 register footprint stays 9, scratch stays zero and occupancy stays 100%. Two fewer instruction sites are a modest compile-time result, not proof of a runtime speedup. G720 arithmetic-cycle estimates rise slightly (2.041 -> 2.086), with unchanged registers and spills.

Compare view previously sampled the final image before replacing that value with the baseline image on the left. It now selects a branch and samples only the required image. Source-level filtered reads fall from two to one in the baseline region; normal Fusion view still samples one image. This increases static branch code and requires real GPU timing to quantify the benefit.

The identity-exposure fast path from round 10 was reverted at the user’s request. Exposure application always evaluates the operator for baseline and exposed color, without an equality branch. Future optimization should avoid such value-specific fast paths.

In the combined A730 report, all nine passes still have **zero scratch and 100% ALU fiber occupancy**. Static instruction counts increase in display while dropping slightly in fit; exposure application returns to 198 instructions on A730. It would be incorrect to advertise this batch as a reduction in total static instruction count.

## Validation and reproduction

Every candidate passed `tests.test_fit`, `tests.test_average`, `tests.test_reduction` and `tests.test_rounds`. The first three compare intermediate outputs bitwise against frozen shaders. The pipeline test compares source reduction, low/full exposure, coefficients, averaged coefficients, baseline/final colors and displayed pixels against pre-batch shaders, covering odd/tiny dimensions, HDR extremes, zero/nonzero exposure brackets, full/quarter Fusion, all three view modes and letterboxing. The merged result passed the complete **33-test suite**.

This is local desktop GPU equivalence evidence, not a universal cross-driver guarantee. Adreno and Mali backends compiled successfully, but neither was run on a phone.

```powershell
# Re-run the ten independent candidates; temporarily substitutes shader source,
# restoring it after each candidate. Do not edit shaders during this experiment.
.\.venv\Scripts\python.exe tools/experiments/ten_rounds.py 1 10

# Analyze the retained implementation.
.\.venv\Scripts\python.exe tools/profiling/mobile_profile.py --require-aoc --out outputs/mobile/a730-ten-rounds
.\.venv\Scripts\python.exe tools/profiling/mali_profile.py --out outputs/mobile/g720-ten-rounds
```

Experiment sources, raw compiler logs and per-candidate test logs are under `outputs/optimization10/`. The recipe and frozen reference shaders are retained in the repository. The experiment does not automatically select or merge candidates.
