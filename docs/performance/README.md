# Mobile performance

The default is `guided-packed-coefficients`. The independent viewer reference
and `guided-coefficient-layout` (FP32 fitted-coefficient control) remain available.

## Current measurement

**Adreno 830 / NX789J, process-local Qualcomm 512.842.6**, 1920×1080 at 45 FPS,
R11G11B10 HDR → RGBA8 sRGB. The same graphics HDR producer and tone mapper run
in both paths. Visualization, presentation, calibration and uploads are excluded.
Each sustained run samples 1,800 frames per path, with 60 warmup frames per block.

| Sustained run | Complete chain | Local Exposure increment |
|---|---:|---:|
| Previous direct 5×5, one fit per task | 3.5347 ms | 1.0922 ms |
| Four adjacent fits per task, candidate | 3.4519 ms | 1.0086 ms |
| Batched direct-fit integrated verification | 3.4511 ms | 1.0090 ms |
| Batched direct-fit fresh control | 3.4517 ms | 1.0086 ms |
| Uniform inverse-LUT query, previous | 3.4437 ms | 1.0010 ms |
| Fresh pre-average-batching control | 3.4438 ms | 1.0010 ms |
| Four adjacent coefficient averages, previous | 3.4331 ms | 0.9909 ms |
| Fresh centered-moment control | 3.4343 ms | 0.9922 ms |
| Raw FP32 moments, previous | 3.4242 ms | 0.9826 ms |
| Fresh 8×8 layout control | 3.4249 ms | 0.9824 ms |
| Guided 64×1 layout, previous | 3.4117 ms | 0.9683 ms |
| Fresh 64×1 control | 3.4125 ms | 0.9698 ms |
| Interior four-fit windows, candidate | 3.4016 ms | 0.9598 ms |
| Interior four-fit windows, repeat after control, retained | 3.4022 ms | **0.9602 ms** |

Register reuse across four vertically adjacent fits saves about 0.083 ms.
Uniform inverse-LUT queries save another approximately 0.008 ms. Reusing eight
shared inputs across four adjacent coefficient averages saves another 0.010 ms
against a fresh sustained control. Averaging retains each five-item sum order
and the same half rounding; shader-level shared reads fall from 2,880 to 1,152
per output tile. External texture traffic is unchanged. The eight active
integrated shaders match the sustained candidate byte for byte.
Raw FP32 moments remove per-input centering in the optimized coefficient path,
saving another 0.0096 ms against fresh control. Its 0.9826 ms sustained result
belongs to the previous layout. FP32 control statistics remain centered.
The retained 64×1 layout saves 0.0141 ms incremental and 0.0132 ms complete-chain
against fresh 8×8 control. It keeps 64 threads, the same 16×16 output tile,
arithmetic and workgroup barriers; no subgroup extension is enabled in production.
Interior four-fit batches then sum fixed row windows; only batches touching the
top/bottom clamp keep the offset cases. Sampling, summation order and half rounding
are unchanged, and phone output is byte-identical. Against a fresh sustained control
it saves about 0.010 ms incremental and complete-chain; the three-round increments
(0.9588–0.9605 ms over two candidate runs, 0.9691–0.9705 ms control) do not overlap.
The eight active integrated shaders match the sustained candidate byte for byte.
Integrated foreground validation screens at 0.9587 ms (3.4017 ms chain) with exact
phone output; use the sustained **0.9602 ms** repeat as the current baseline.
The **0.9 ms goal
is still open**. These are median increments, not per-frame guarantees or results
for other GPUs. Separate pass diagnostics are not an additive frame budget.
[Raw records and source hashes](baselines/current.json).

## Retained implementation

- Fusion runs at quarter width and height; all pyramid levels contribute.
- Initialization shares log-domain curve work. Finite unsigned R11G11B10 skips
  redundant negative clamps; other formats retain clamping.
- Residuals and centered weights share RGBA16F mips 0–2 and RGBA32F coarse mips.
- Small tail and fine reconstruction passes are fused; 1080p has 12 dispatches.
- Guided retains full 5×5 fitting and 5×5 coefficient averaging. Each 64×1 workgroup
  produces a 16×16 output tile using 64 threads and 2,880 bytes of shared storage,
  down from 256 threads and 9,600 bytes. Direct fits replace the intermediate
  row-moment buffer and one publication barrier. Four fits share eight input
  rows in registers: 4,000 fitting reads per tile instead of 10,000, with the
  original five-row summation order. Interior batches use fixed row windows;
  clamped-border batches keep explicit offset cases.
- Moments and averaging accumulate in FP32. Fitted coefficients and horizontal
  averaging sums retain their half rounding; the FP32 fitted-coefficient control
  remains independent. No exposure-value shortcuts or shared-tonemap savings.

The [five stage files](../implementation.md) declare their own resources. Compiler
reflection supplies bindings and uniform offsets. Frozen-graph regressions retain
fixed image-quality gates; the optimized pipeline is not bitwise-equivalent to
the full reference.

## Quality and bandwidth

All 65 tests and the regenerated four-scene/four-preset matrix pass. Veranda strong
peaks at **10 sRGB8 codes** (21 pixels above 4, none above 12). The integrated phone
image gate peaks at 8; its output matches the validated candidate. Tiny/odd/signed
inputs and synthetic HDR edges/motion pass; worst temporal differential is 2 codes
for both coefficient presets. The README comparison sheets and worst crops have
been regenerated and inspected.

Estimated incremental texture-sweep traffic is **16.71 MB/frame / 0.752 GB/s at
45 FPS**. Batched direct fits preserve this sweep and reduce expanded
logical-access accounting from 4.449 to **3.893 GB/s**. Cache reuse is not
assumed by that model. Neither model measures DRAM bandwidth or power.
[Accounting](bandwidth.md) · [Precision](../precision.md) · [Images](../image-comparison.md).

These checks are not universal error guarantees. Extreme weights/brackets, future
curve changes and other GPUs need separate validation. Same-phone all-asset
coverage is narrower than the desktop matrix.

## Reproduce and rejected directions

Interior four-fit Guided windows are now retained (see above). Validation:
exact packed/FP32 coefficient parity over seven sizes, 16 scene/preset gates,
140 extreme final-image checks, and odd-size temporal error of two codes. It is
unrelated to the earlier static-interior indexing screen, which was measured on
an older Guided implementation
(`outputs/goal090/guided-interior-fit-results.json`).

Screens on the retained interior-window build (control 0.9587 ms, 240 frames/path,
same phone/workload) found no further gain. Guided loads through a nearest
clamp-to-edge sampler with constant texel offsets keep exact phone output but
regress to 1.0387 ms (AOC: 22 registers, 12% occupancy). Folding mip4/mip3
reconstruction into fused EV recovery removes two dispatches but gives 0.9998 ms;
removing its mip2 shared phase by inline taps gives 0.9880 ms. Both change output
and lower projected EV occupancy from 50% to 31%/37%; neither was quality-validated.
Foreground diagnostics attribute about 0.19 ms to the seven small coarse passes,
each only 3–9 µs in back-to-back headless runs; these intervals are not an additive
budget (`outputs/goal090/dispatch-fold-results.json`).

Doubling guideEV storage from RG16F to RG32F screens at 0.9940 ms against
0.9663 ms for a fresh retained control; complete chains are 3.4365/3.4093 ms.
All SPIR-V binaries and benchmark output bytes match. This suggests format/cache
sensitivity, not measured DRAM bandwidth or a prediction of savings from further
compression. Sequential 240-frame/path screens on the same Adreno 830/842.6
workload; no default change (`outputs/goal090/guide-bandwidth-results.json`).

Linear image tiling is supported for the tested intermediates but gives no useful
screen gain: guideEV alone gives0.9654ms; compact,baseline,guideEV and averaged
together give0.9672ms. Both phone outputs match; all shader binaries and common
HDR/final-image tiling stay unchanged. Exact usage/extent support is queried,
including linear filtering for averaged coefficients. Temporary runner changes
restored; no general-size followup. Same phone/workload,240frames/path
(`outputs/goal090/linear-tiling-results.json`).

Forcing initialization2x2Gather loops to remain loops screens at0.9669ms;
forcing unroll gives0.9658ms. Both benchmark outputs match. AOC looped code drops
from13 to7registers and raises projected occupancy21%to40%, with zero scratch,
but no useful runtime gain is established. Not retained; no full quality sweep.
Same phone/workload,240frames/path (`outputs/goal090/initialize-gather-loop-results.json`).

Consolidating initialization4x8/32-thread microtiles preserves phone output but
regresses: eight microtiles in a 256-thread16x16 output group give 1.2024 ms; two
stacked microtiles in a64-thread4x16 group give 1.2180 ms. AOC projects13 registers
and no scratch, with18%/21% occupancy. Both rejected; no full quality followup.
Same phone/workload,240frames/path (`outputs/goal090/initialize-microtiles-results.json`).

Fine reconstruction with an 8x8 output tile screens at 0.9877 ms with an 8x8
thread group and 0.9882 ms with 64x1, remapped to the same output pixels. Both
benchmark phone outputs match. The 8x8-layout matrix passes 16/16, peak 11 codes.
Shared halos shrink to 6x6/5x5, but boundary work repeats more often. Both AOC
projections report six registers, 50% occupancy and zero scratch. Rejected;
no odd/tiny/temporal followup. Same phone/workload, 240 frames/path
(`outputs/goal090/reconstruct-tile8-results.json`).

Fine reconstruction with a 32x32 output tile screens at 0.9777 ms with 256
threads, 0.9859 ms with 512; both benchmark phone outputs match. The 256-thread
matrix passes 16/16, peak 11 codes. Shared mip1/mip2 halos are 18x18/11x11,
reducing overlap while increasing per-thread outputs. AOC projects 7/5 registers,
40%/59% occupancy and no scratch. Rejected; no odd/tiny/temporal followup.
Same phone/workload, 240 frames/path (`outputs/goal090/reconstruct-tile32-results.json`).

A rational inverse-LUT warp (k=0.9, same 1,024 R16F nodes and fitted curve) gives
0.9680 ms incremental, no useful gain. The 16-case matrix passes, peak 11 codes;
phone differs by at most 1 code in 52,973 channels. However, a CPU ideal-filter
roundtrip sweep reaches 14.62 EV error across 1e-8..65,535: passing scene gates does
not establish inverse-tail accuracy. Rejected without changing calibration;
no full edge/temporal followup. Same phone/workload, 240 frames/path
(`outputs/goal090/rational-warp-results.json`).

Per-batch guide centering followed by half differences/squares/cross products
and FP32 accumulation passes 16/16 matrix cases (peak 11 codes), but regresses
to 1.0097 ms incremental (3.4511 ms chain). Phone differs from retained by at
most 1 code in 14,433 channels. AOC projects 14 registers, 18% occupancy and no
scratch. Rejected before odd/temporal/extreme checks. Same phone/workload,
240 frames/path (`outputs/goal090/guided-local-half-products-results.json`).

Packing initialization log/guide and FP32 baseline into one RGBA32F texture
regresses to 1.0660 ms incremental (3.5090 ms chain). It removes one independent
write/read but adds an estimated 2.074 MB/frame of logical sweep traffic. Explicit
half rounding is not bitwise identical to retained image storage: phone differs
by at most 1 code in 266,025 channels. Rejected before full quality validation.
Same phone/workload, 240 frames/path (`outputs/goal090/packed-float4-input-results.json`).

Combining the 28x28 Guided tile, scaled moments and two weight exponents gives
0.9663 ms incremental (3.4091 ms chain), without demonstrated additive benefit.
The 16-case matrix passes, peak 11 codes; phone differs from retained by at most
1 code in 9,109 channels. Not retained; the copied retained-headless mismatch is
expected for this approximation. No combined odd/temporal/extreme followup.
Same phone/workload, 240 frames/path (`outputs/goal090/guided-tile28-combined-results.json`).

Tiles with one four-fit batch per thread give 0.9639 ms in a short 28x28/256
screen, but sustained results are 0.9675 ms versus fresh control
0.9698 ms (1,800 frames/path); no useful repeatable gain established. The
28x28 matrix and 140 extreme final-image gates pass. Larger tiles regress:
60x60/1,024 threads gives 3.4748 ms and 28x60/512 gives 1.0579 ms. All phone
outputs match. AOC projects 80 bytes scratch for 60x60, none for the other two;
shared storage is 7,680/31,744/15,360 bytes. None retained; no temporal followup.
Same phone/workload; larger variants use 240 frames/path
(`outputs/goal090/guided-full-fit-tiles-results.json`).

Low-resolution MRT initialization (same three output formats/arithmetic, exact4x
Gather) regresses to 1.2956 ms incremental. A compute control with the same added
color-attachment usage flags gives 0.9660 ms; flags alone do not explain the
regression. Both benchmark outputs match. Common graphics producer and tonemap
remain unchanged. Rejected before general-size/quality implementation; temporary
MRT runner changes restored. Same phone/workload, 240 frames/path
(`outputs/goal090/initialize-mrt-results.json`).

Wave-shared horizontal moments regress to 1.4502 ms incremental despite reducing
Guided source reads from 4,000 to 768 per tile. The 256-thread group uses required
full 64-lane subgroups, FP32 moments and 9,280 bytes of shared storage; benchmark
phone output matches. AOC projects six registers, 25% occupancy and no scratch.
Rejected before desktop/odd/temporal checks; no cross-device subgroup mapping
claim. Same phone/workload, 240 frames/path
(`outputs/goal090/guided-wave-horizontal-results.json`).

Guided storage-image reads in place of sampled-image point loads screen at
0.9697 ms with float2 and 0.9881 ms with half2 declarations, unchanged RG16F
storage. Both benchmark outputs match; float2 matrix passes 16/16, peak 11 codes.
AOC uses memory reads and projects 24/15 registers, 12%/18% occupancy, zero scratch.
Neither is retained; no odd/temporal followup. Same phone/workload, 240 frames/path
(`outputs/goal090/guided-storage-read-results.json`).

Allocating only used reconstruction mips3..5 screens at 0.9669 ms as a tight
60x33 three-level image, or 0.9674 ms as three separate images. Both benchmark
outputs match; shaders and sampled dimensions are unchanged. Neither establishes
a useful timing gain. The 680,300-byte texel-capacity reduction is not a measured
allocation reduction or per-frame bandwidth saving. Not retained; general-size
host adaptation was not pursued. Same phone/workload, 240 frames/path
(`outputs/goal090/reconstructed-allocation-results.json`).

Revisiting Gather in the current raw-moment/64x1/batched-average Guided path gives
0.9682 ms with float texture declarations and 0.9693 ms with native half; no
useful screen gain. Each four-fit batch uses 16 channel Gathers plus eight point
loads instead of 40 point loads. Both benchmark phone outputs match; the float
variant matrix passes 16/16, peak 11 codes. Both AOC projections report 15 registers,
18% occupancy and zero scratch. Not retained; no odd/temporal followup. Same
phone/workload, 240 frames/path (`outputs/goal090/guided-raw-gather-results.json`).

A smaller 16x8 Guided output tile screens at 0.9913 ms with 64 threads and
1.1118 ms with 32 threads. Shared storage falls to 1,728 bytes, but fitting
reads rise to 4,800 per 256 output pixels versus 4,000 retained. Both benchmark
phone outputs match; the 64-thread matrix passes 16/16, peak 11 codes. AOC projects
12/14 registers, 25%/18% occupancy, zero scratch. Rejected; no odd/temporal followup.
Same phone/workload, 240 frames/path (`outputs/goal090/guided-tile16x8-results.json`).

Per-output/per-mip image barriers for LE intermediate compute passes screen at
0.9680 ms incremental (3.4103 ms chain), with exact benchmark phone output.
Compute execution scopes and read/write access masks remain unchanged; common
HDR producer and tonemap publications keep global memory barriers. No useful gain;
the temporary runner changes were restored. This is not a synchronization-layer
validation claim. Same phone/workload, 240 frames/path
(`outputs/goal090/output-image-barriers-results.json`).

Keeping Guided covariance/variance scaled by 25 gives only a 0.0022 ms sustained
screen difference, insufficient to establish a useful repeatable gain:
0.9684 ms incremental versus fresh control 0.9706 ms, complete chains
3.4102/3.4136 ms (1,800 frames/path, same phone/workload).
The 16-case desktop matrix and 140 extreme final-image gates pass. Phone differs
from retained by at most 1 code in 9,109 channels; sustained output matches its
screen. Candidate runs report a copied retained-headless mismatch, expected for
this rounding change; independent candidate headless and temporal validation were
not pursued after the timing rejection. Not retained; AOC projects 14 registers,
18% occupancy and zero scratch
(`outputs/goal090/guided-scaled-moments-results.json`).

Fine reconstruction read scheduling gives no gain: native half point reads for
fine residual/weights and log/guide screen at 0.9705 ms; prefetching fine inputs
before the shared coarse reconstruction screens at 1.0019 ms. Both benchmark
phone outputs match. AOC projects 6/8 registers, 50%/37% occupancy and no scratch,
respectively. Neither is retained. Same phone/workload, 240 frames/path; full
quality sweep skipped after timing rejection
(`outputs/goal090/reconstruct-read-scheduling-results.json`).

Evaluating only two non-unit stabilized weight exponents screens at 0.9662 ms
versus a fresh 0.9677 ms control (complete chains 3.4095/3.4104 ms); this does not
establish a useful gain. Both phone outputs match. AOC main instructions increase
652 to 706 while complex FP32 instructions decrease 42 to 40; both project
13 registers and 21% occupancy. Not retained. Same phone/workload, 240 frames/path
(`outputs/goal090/initialize-two-weight-exp-results.json`).

Native half2 Guided shared storage gives no retained gain: converting fitted
coefficients and rounded horizontal averages screens at 0.9826 ms incremental;
converting only the rounded averages gives 0.9682 ms, effectively the retained
level. Complete chains are 3.4250/3.4101 ms; both benchmark phone outputs match.
AOC projects 14 registers, 18% occupancy and zero scratch for both. Same phone,
driver and workload as above, 240 frames/path. No full quality sweep after the
negative screen (`outputs/goal090/guided-nativehalf-storage-results.json`).

Shared horizontal FP32 Guided moments reduce fitting texture reads from 4,000
to 2,400 per tile, but screen at 1.1311 ms incremental (3.5735 ms complete chain).
Overlaying rounded averaging rows into the freed moment storage gives 1.1326 ms;
512 threads give 1.1365 ms. All three benchmark phone outputs match the retained
headless image. The latter two AOC projections report zero scratch and 25%/50%
occupancy, respectively; these projections do not imply runtime gains. Rejected
before full matrix/odd/temporal validation; production is unchanged. Same device,
driver and workload as above, 240 frames/path
(`outputs/goal090/guided-shared-horizontal-results.json`).

Initialization 32-thread shape screens give 1.2583 ms at 8x4, 0.9664 ms at
2x16 and 0.9664 ms at 1x32. All benchmark phone outputs match; none establishes
a useful gain over the retained 4x8. AOC projects the same 13 registers,
21% occupancy and zero scratch for 8x4 and 2x16 despite their timing difference.
Same phone/workload, 240 frames/path; no full quality sweep after screening
(`outputs/goal090/initialize-shapes32-results.json`).

Initialization 64-thread screens also regress: 8×8 gives 1.2687 ms and 16×4
1.3132 ms incremental, versus a fresh 4×8 control at 0.9798 ms (240 frames/path,
same device/workload above). Phone outputs match; complete chains regress too.
The 16×4 offline projection reports zero scratch, so spilling is not a sufficient
explanation. Neither is retained (`outputs/goal090/initialize-group64-results.json`).
The reverse 4×4 / 16-thread screen also regresses to 1.2026 ms. Removing the
odd-size fallback for an exact-4×-only initialization probe gives 0.9791 ms,
but no complete-chain gain against that fresh control; not retained. Both phone
outputs match (`outputs/goal090/initialize-small-specialized-results.json`).
Initialization group reordering likewise gives no retained gain: four-row bands
screen at 1.0062 ms; adjacent 2×2 group transposition at 0.9789 ms, with its
complete chain slightly slower than control. Both phone outputs match; the
transposition is bijective across 1,225 odd/tiny group grids. Offline projections
report no scratch (`outputs/goal090/initialize-order-results.json`).
Explicit multiply-add in Guided moments and covariance also shows no established
gain: two screens of identical SPIR-V give 0.9775 / 0.9787 ms, with complete-chain
times effectively unchanged from fresh control. Portable `mad` passes 16/16 image
cases; `fma` fails the desktop D3D overload. Not retained; no sustained claim
(`outputs/goal090/explicit-mad-results.json`).
Raw-moment 4×2 and transposed 2×4 fitting blocks reduce fitting reads from 4,000
to 2,400 per tile, but screen at 1.0061 / 1.0280 ms. Both pass the 16-case desktop
matrix; transposition changes summation order and phone output is not bitwise
equal. Offline footprints rise to 17 registers / 15% projected occupancy, without
scratch. Neither is retained (`outputs/goal090/raw-rectangle-results.json`).
Reducing that rectangle to 32 threads worsens the screen to 1.0684 ms; reducing
the original vertical batch from four to two fits gives 1.0242 ms despite an
offline footprint of 12 registers / 20% occupancy. Both pass 16 image cases and
match phone output. Smaller batches increase fitting reads to 6,000 per tile;
neither tradeoff wins (`outputs/goal090/guided-register-tradeoff-results.json`).
Half2 coefficient-average accumulation passes 16/16 image cases, but screens at
0.9880 ms (chain 3.4303 ms), with unchanged 14-register offline footprint. Phone
output changes by at most one code; no benefit justifies the added rounding.
Not retained; extreme-coefficient qualification was not pursued
(`outputs/goal090/half-averages-results.json`).
Packing the RG16F log/guide pair and FP32 baseline into one RG32_UINT image
keeps eight bytes/pixel and removes a separate store, but screens at 0.9980 ms
(chain 3.4392 ms). Explicit packing is not bitwise equal to prior phone output
(peak one code); the rounding source remains unqualified. Rejected before full
image validation (`outputs/goal090/packed-init-results.json`). The harness now
accepts explicit `linear_filter: false` for point-loaded integer resources;
existing resources retain their filtering-capability check.
Explicit subgroup-size investigation found that Slang `WaveSize(32)` exports
identical SPIR-V here. A real Vulkan pipeline request for 32 is rejected by the
device's queried 64–64 range; explicit 64 runs correctly at 0.9788 ms with exact
phone output, showing no established gain over control. Opt-in harness support
is documented in the Android procedure (`outputs/goal090/subgroup-size-results.json`).
Dropping the final coarse level fails all 16 image cases (peak 252 codes), so it
was not timed on phone. Retaining every level but directly loading singleton
1×1 samples passes all cases and matches phone output; its 0.9806 ms screen
shows no gain over fresh control. Neither is retained
(`outputs/goal090/tail-coarsest-results.json`).
Full-resolution coefficient reuse replaces 64 bilinear samples per 8×8 group
with 16 point loads and manual interpolation. Shared-memory reuse screens at
0.9817 ms; required-64 subgroup broadcasts regress to 1.2904 ms. Both differ
from retained phone output by at most one code. Baseline SPIR-V is unchanged;
neither candidate is retained or fully image-qualified
(`outputs/goal090/apply-coefficient-reuse-results.json`).
Guided 64×1 layout was isolated using a sustained full-subgroup
control is 0.9717 ms, versus 0.9709 ms with subgroup-scoped barriers, indicating
little benefit from barrier narrowing itself. Ordinary-barrier source exports
identical SPIR-V to that layout control, passes 16 image cases, and screens at
0.9660 ms with exact phone output and default device features. The fresh sustained
default-feature A/B and integration checks passed; the layout is retained above.
Subgroup-scoped barriers are not retained
(`outputs/goal090/guided-layout64-results.json`).
The same layout idea did not establish gains elsewhere on that retained base:
fine reconstruction at 256×1 screens at 0.9662 ms, and tail reconstruction at
128×1 at 0.9694 ms, versus the integrated control screen of 0.9661 ms. Each passes
16 image cases and matches phone output. Neither is retained
(`outputs/goal090/other-stage-layout-results.json`).
Flattening initialization to 32×1 while preserving its original 4×8 image tile
screens at 0.9656 ms, with no established gain. Flattening pyramid downsampling
to 64×1 while preserving its 4×16 tile regresses to 0.9774 ms. Both pass 16 image
cases and match phone output; neither is retained
(`outputs/goal090/fixedtile-layout-results.json`).
Guided 24×24 output tiles with 64×1 threads reduce modeled fitting loads from
2,040,000 to 1,881,600 at 1080p, but shared storage rises from 2,880 to 5,824 bytes.
The screen regresses to 0.9991 ms despite 16 passing image cases and exact phone
output. Offline projected occupancy falls to 10%, without scratch. Not retained
(`outputs/goal090/tile24-results.json`).
The intermediate 20×20 tile also regresses (1.0051 ms). Reusing coefficient
storage for row sums lowers the 24×24 tile's shared allocation to 3,136 bytes
and restores 18% projected occupancy, but the added publication barrier leaves
its screen at 0.9810 ms, still slower than retained 16×16. Both pass 16 image
cases and match phone output; neither is retained
(`outputs/goal090/tile-size-overlay-results.json`).
Adaptive constant-EV skipping is not retained. Range gates of 1/64, 1/16 and
1/8 EV pass all 16 desktop image cases, but scanning the 24×24 support at runtime
screens at 1.4435 ms (1/64) and 1.3026 ms (1/8). Generating 8×8 min/max metadata
inside EV reconstruction reduces the latter to 1.0231 ms, still slower than the
then-retained 0.9683 ms; its complete chain is 3.4657 ms. This metadata covers 28.24%
of tiles in the captured phone workload and occupies 8,160 bytes. The metadata
candidate differs from retained phone output by at most 4 codes; independent
matrix/temporal qualification was not run after its performance rejection.
Explicit full-64 subgroup reduction of the upstream ranges screens at 1.0374 ms;
also distributing Guided metadata reads across the wave gives 1.0629 ms. Both
match the metadata control image exactly but regress complete-chain time; neither
is retained. These are 240-frame/path screens on the device/workload above, not sustained
acceptance or general skip-rate guarantees (`outputs/goal090/adaptive-guided-results.json`).

Guide-load representation screens also regress against fresh control (0.9667 ms):
packing RG16F bits into R32_UINT gives 0.9906 ms, and native half2 texture reads
with FP32 moments give 0.9893 ms. Both phone outputs match retained exactly;
native half passes all 16 desktop cases. AOC still projects 14 registers, 18%
occupancy and no scratch. Payload size is unchanged; neither is retained
(`outputs/goal090/guide-load-results.json`).

Moving the complete tail boundary from mip 5 to mip 4 removes two dispatches,
but screens at 0.9769 ms (128 threads) or 0.9712 ms (256 threads). Both phone
images differ from retained by at most one code; the 128-thread desktop matrix
passes 16/16. Shrinking the original tail arrays from 683 to 171 elements gives
0.9676 ms, exact phone output and 16/16 desktop passes, with no established gain
over fresh control (0.9667 ms). None is retained
(`outputs/goal090/tail-boundary-results.json`).

Current raw-moment Guided with 128 threads screens at 0.9787 ms (12 registers,
25% AOC occupancy); five fits per task reduce fitting reads to 3,600/tile but
regress to 1.0324 ms (13 registers, 18%). Both have zero projected scratch,
exact phone output and 16/16 desktop passes. Neither is retained
(`outputs/goal090/guided-task-balance-results.json`).

Keeping Guided covariance/division in FP32 until slope storage screens at
0.9659 ms; delaying slope rounding until after intercept evaluation gives
0.9652 ms. Both pass 16/16 desktop cases with unchanged AOC register/occupancy
footprints (14 / 18%, no scratch). These small screen differences do not establish
a sustained gain; neither is retained (`outputs/goal090/guided-fp32-fit-results.json`).

A 1,024-node R32F forward lightness LUT screens at 0.9696 ms. Precomputing the
complete three-exposure residual/weight setup into RGBA32F + R32F LUTs gives
0.9672 ms. Both pass 16/16 desktop cases and differ from retained phone output
by at most one code, but neither establishes a timing gain. LUT generation is
outside these intervals; curve/bracket/sigma changes require rebuilding dependent
tables. Extreme-range and temporal checks were not pursued; neither is retained
(`outputs/goal090/setup-lut-results.json`).

Fresh output-identical replay diagnostics against a 0.9688 ms control add
0.3098 ms for another initialization and 0.2180 ms for another Guided pass.
Repeating both final apply and its matched Tonemap baseline changes the increment
by only 0.0002 ms. These are warm-cache marginal costs including extra barriers,
not additive per-pass times. A 32×8 Guided output tile screens at 0.9690 ms,
with exact phone output and 16/16 desktop passes; no gain, not retained
(`outputs/goal090/current-replay-results.json`).

Combining the setup LUT with 128 initialization threads regresses to 1.3322 ms,
with output identical to its 32-thread LUT control. Four full-subgroup lanes per
4×4 HDR output reduce AOC registers to 7 and project 40% occupancy without scratch,
but regress to 1.3853 ms with exact retained phone output. Neither is retained;
these offline resource reductions do not predict runtime gains
(`outputs/goal090/initialize-cooperation-results.json`).

Fusing fine reconstruction/EV with Guided (32×16 output, 40×24 halo) screens at
1.5519 ms. Reusing shared storage across lifetimes cuts 10,980 to 6,720 bytes and
improves this to 1.2779 ms; 128 and 256 threads reach 1.1573 and 1.0724 ms.
All four phone outputs match retained exactly; the initial desktop matrix passes
16/16. None beats the separate passes. AOC reports no scratch, with projected
occupancy rising from 6% to 25%; halo reconstruction and shared-input costs remain.
A larger 32×32 tile regresses to 1.1157 ms at 256 threads and 1.1690 ms at
512 threads; its 256-thread desktop matrix passes 16/16. Native half2 shared
EV/row storage on the smaller 32×16/256 variant gives 1.1462 ms. All three phone
outputs remain exact, but none is retained (`outputs/goal090/ev-guided-results.json`).

Eight-sample guide-log reduction (retaining the full 16-sample HDR mean through
bilinear averaging of the other quads) fails 16/16 desktop cases, peaking at
187 sRGB8 codes. Inspection shows concentrated foliage/window-frame edge errors.
Rejected before phone timing; guide subsampling is not a qualified approximation
(`outputs/goal090/guide8-results.json`).

Four integer RGB gathers through an R32_UINT alias of graphics-produced R11G11B10
are rejected. Explicit view-format lists and removing extended usage do not
restore performance. Corrected target-only alias runs give 1.2827 ms / 4.0636 ms
increment / complete chain with the original shader, and 1.3046 / 4.0824 ms with
integer gathers; ordinary-image fresh control gives 0.9658 / 3.4086 ms. Outputs
are exact and all finite 10/11-bit CPU decode patterns pass. Earlier probes also
propagated alias fields into the immutable producer input; the harness now strips
those fields there. All 65 tests pass. Optional alias configuration remains
strictly diagnostic, not a default (`outputs/goal090/packed-gather-results.json`).

A fused pyramid mip-1/2/3 pass removes two dispatches but screens at 1.1262 ms
(complete chain 3.5685 ms). It preserves per-level half/float storage and uses
software bilinear for shared intermediates. All 16 desktop cases pass, but phone
output differs from retained by up to 20 codes; this is not an independent
phone-reference error measure. With no timing gain, the candidate is rejected
before odd/tiny/temporal qualification. Tightening halos to 26×26 / 11×11 with
512 threads gives 1.1315 ms; using half4 shared storage with FP32 interpolation
and 256 threads improves to 1.0371 ms, still slower than default. Both pass
16/16 desktop cases and match the initial fused phone image exactly. A CPU
footprint sweep checks 1,021 axis sizes without out-of-bounds taps; it does not
replace GPU odd/tiny testing. An 8×8 coarse tile / 512-thread half-storage variant
reduces overlap but regresses to 1.0772 ms. It passes 16/16 desktop cases, while
phone output differs from the initial fused candidate by up to 20 codes; no
independent phone-reference/temporal qualification was pursued. Not retained
(`outputs/goal090/pyramid-three-results.json`).

Unconditional interpolation of alternate Guided coefficient columns fails the
16-case desktop gate. Fitting odd columns when neighboring coefficient responses
differ by more than 1/32 or 1/8 EV passes all 16 cases, but screens at 1.0212 and
1.0231 ms respectively. Branches, another publication barrier and fallback fits
offset the reduced fit work; neither is retained. The endpoint-response gate is
not a mathematical interpolation-error bound (`outputs/goal090/adaptive-columns-results.json`).

- [Android benchmark](android.md): matched foreground timing and optional driver setup.
- [Developer tools](../../tools/README.md): image regeneration and offline compilers.
- [Raw records](baselines/README.md): timing, quality and driver provenance.

The 3×3 Guided shortcut was rejected by image gates (Veranda strong peak 206);
restoring 5×5 in the same implementation restores quality. Larger direct-fit
workgroups lose the gain: 128 threads screen at 1.101 ms, 256 at 1.150 ms.
Integer HDR views/manual decoding, extra pass fusion, half fetches, shared-memory
padding and wave-sharing trials did not improve the matched chain. Details are
recorded in the baseline JSON; reproducible experimental bundles and raw samples
remain under `outputs/goal110/`. They are not production options.

The current batch-size and scheduling screens are recorded under `outputs/goal090/`.
Larger batches, shared input tiles, smaller output tiles and 128-thread groups did
not beat the retained four-fit, 64-thread implementation.

Locally centering both guide and exposure enabled half row statistics and passed
all 16 desktop scene/preset numerical gates, but phone screens measured 1.033 ms
increment (3.474 ms complete chain). Eight-fit batching also measured 1.033 ms
(3.475 ms chain). Both were rejected; neither is a retained quality/performance
result. Raw screens: `outputs/goal090/dual-centered-half-results.json`.

Initialization precision screens reached 1.006 ms with native half Gather
(phone output identical to control) and 1.005 ms with half weight arithmetic
(numerically different; not quality-validated). Neither short screen establishes
a material gain. AOC projects the same register footprint and occupancy for
native half Gather as the control. Neither was adopted; records are in
`outputs/goal090/initialization-precision-results.json`.

Keeping 5x5 fitting but reducing coefficient averaging to 3x3 failed all 16
scene/preset gates; it is not a viable quality-preserving shortcut. An independent
exposure-recovery scheduling candidate samples the inverse LUT unconditionally
and selects boundary/identity results afterward. It passed the 16-case matrix
with unchanged comparison PNGs and odd-size HDR edge/temporal checks. A sustained
phone run measured 1.0010 ms increment / 3.4437 ms chain with unchanged phone output
(`outputs/goal090/recon-unconditional-lut-sustained`). A fresh control measured
1.0086 ms / 3.4517 ms. This change is now retained; the 0.9 ms goal remains open.
Splitting Guided into global fits and coefficient averaging removed repeated halo
fits but screened slower at 1.0423 ms / 3.4858 ms, so it was not adopted
(`outputs/goal090/global-fits-foreground`).
Replacing its 25-point coefficient average with nine bilinear samples passed all
16 desktop numerical gates but still screened at 1.0361 ms / 3.4782 ms. Using one
fit per thread instead of four raised the increment to 1.0969 ms despite better
AOC-projected occupancy. These split variants remain rejected; raw records and
compiler projections are in `outputs/goal090/global-guided-results.json`.
Precomputing FP32 guide/exposure moments in exposure recovery also regressed:
filtered reads screened at 1.6531 ms increment and point reads at 1.3304 ms.
The filtered variant passed all 16 desktop gates, but AOC projected higher register
footprints (27 filtered, 17 point versus 15 retained Guided), with no spills.
Neither was adopted; `outputs/goal090/precomputed-moments-results.json` preserves
the measurements and their limits.
Stride-two Guided coefficient fitting/interpolation failed the scene matrix.
Wave64 sharing of overlapping downsample reads screened at 1.0247 ms increment
(two-dimensional sharing) and 1.0051 ms (horizontal sharing); neither beat the
retained path. Desktop wave fallback validation does not establish phone wave64
quality. Rejected records: `outputs/goal090/sparse-wave-results.json`.
Selective tile-memory screens also remain rejected. Guide-only residency measured
3.5618 ms chain / 0.9838 ms increment; compact/base-lightness residency measured
3.5291 ms / 0.9504 ms. Both outputs matched control, but both chains were slower.
Enabling the feature without allocating tile images already measured 3.5800 ms
chain / 2.5790 ms baseline / 1.0010 ms increment. Thus residency helps within that
enabled-feature configuration, but does not overcome its shared-path regression;
the driver cause is unproven. The luminance-mip tile selection failed image limits.
Records: `outputs/goal090/tile-residency-results.json`.
Quartic and quadratic log-mantissa approximations, restricted to initialization's
guide calculation, both passed the 16-case desktop matrix. Short phone screens
were 0.9977 ms and 0.9997 ms increment respectively, insufficient to establish a
material gain over the retained path. Neither approximation was adopted; numeric
fit limits and raw results are in `outputs/goal090/guide-log-approximation-results.json`.
Full-resolution guide-log approximation also failed to establish a gain. Removing
the apply pass's uniform Guided-mode branch screened at 0.9960 ms but sustained
1.0012 ms, matching the retained path rather than improving it; all 16 desktop
gates passed and phone output was identical. Neither was adopted
(`outputs/goal090/apply-stage-results.json`). A 12x12 Guided output tile with a
power-of-two coefficient region also screened slower (3.4571 ms complete chain),
despite a lower AOC register projection; see `outputs/goal090/tile12-results.json`.
Compiler-path screens changed only six Local Exposure entries: Slang via GLSL
measured 1.0012 ms increment, and SPIR-V optimization/loop unrolling measured
0.9991 ms. Phone output stayed identical; neither established a material gain.
The compiler workflow remains unchanged. Compatibility details and projections:
`outputs/goal090/compiler-path-results.json`.
Horizontal fit batching passed the scene matrix but did not establish a gain.
Static interior-window indexing passed exact coefficient tests and the scene
matrix; its sustained 0.9970 ms increment is only about 0.004 ms below the retained
run on that older implementation; the current interior-window form is retained
after repeat sustained runs (see above). Combining the old form with Gather
reads screened slower at 1.0126 ms despite identical output. Records:
`outputs/goal090/guided-window-layout-results.json`.
Revisiting shared input with native half2 storage plus four-fit reuse remained
slower (1.2510 ms increment). Removing redundant post-load clamping and padding
the shared row pitch measured 1.2607 ms. Both passed exact coefficient/phone-output
checks, but AOC still projected footprint 20 versus 15 for retained Guided, with
no spills. Neither was adopted: `outputs/goal090/shared-input-revisit-results.json`.

Normalizing four guide products into FP32 exponents and mantissas reduces their
four log2 calls to one without changing the geometric-mean formula. The 16-case
desktop matrix passed, but the 240-frame/path phone screen measured 0.9976 ms
increment / 3.4397 ms chain, insufficient to establish a gain over 1.0010 ms.
Numerical output differs from the copied control; candidate-specific headless
parity was not established. Not adopted; details in
`outputs/goal090/exponent-product-results.json`.

Guided task/window screens: column-major task assignment preserves exact
coefficients but regresses to 1.0394 ms. Sliding FP32 row sums retain full 5x5
support and pass all 16 scene/preset and odd-size edge/temporal gates. Its
1,800-frame/path sustained increment is 0.9959 ms /
3.4382 ms chain, without an established material gain.
Neither is adopted. Candidate-specific phone headless parity remains unverified
for the numerical sliding variant. Records: `outputs/goal090/guided-task-window-results.json`.

Fine reconstruction screens also retain the original implementation. Integer
interpolation coordinates for exact 2:1 dimensions passed all 16 image gates but
screened at 1.0051 ms increment. A 64-thread group producing the same 16x16 tile
matched the retained phone output but screened at 1.0146 ms. Its AOC a830 projection
is seven registers, 40% occupancy and zero scratch; that projection did not
translate into faster runtime. Records: `outputs/goal090/fine-reconstruction-results.json`.

Expanding horizontal coefficient-average reuse beyond four outputs regressed:
eight outputs screened at 1.0025 ms and sixteen at 1.0547 ms, versus retained
0.9909 ms. Both preserve exact desktop coefficients and phone output. AOC a830
projects 14 registers, 18% occupancy and zero scratch for both; reduced shared
reads alone are insufficient. Neither adopted; records in
`outputs/goal090/average-batch-size-results.json`.

Shared-layout screens preserve exact desktop coefficients and phone output:
transposing both arrays with pitch 21 regresses to 1.2008 ms; padding only the
horizontal-average rows to pitch 17 screens at 0.9904 ms, no established gain
against 0.9909 ms retained. Neither adopted. No bank-conflict counters were
measured; records: `outputs/goal090/shared-layout-results.json`.

Skipping sample-coordinate clamps in fully interior Guided tiles preserves exact
coefficients and phone output, but a per-read uniform branch screens at 1.2168 ms.
Hoisting it outside the eight-row loop improves that candidate to 1.0263 ms,
still slower than retained 0.9909 ms. Both rejected; AOC projects zero scratch,
not a measured explanation of the regression. Records:
`outputs/goal090/interior-load-results.json`.

Wave exchange between Guided fits and horizontal averaging removes one shared
array and one publication barrier but screens at 1.0965 ms. Skipping padding
column reads regresses further to 1.1623 ms. Both preserve exact tested desktop
coefficients and phone output; neither adopted. Prototypes assume wave32/64 and
have no portable fallback. Records: `outputs/goal090/wave-fit-average-results.json`.

Three weighted bilinear samples per Guided row preserve first moments but lose
within-pair variance/covariance. Both the raw approximation and a linear-gradient
second-moment correction fail all 16 image gates (worst peaks 214/216 sRGB8 codes;
Veranda strong 113/103). Neither was phone-timed or adopted. Records:
`outputs/goal090/linear-moment-results.json`.

Balanced FP32 five-item sums in Guided moments pass all 16 image gates and both
coefficient variants' odd HDR edge/temporal checks (worst temporal delta 2 codes),
but screen at 1.0226 ms increment / 3.4651 ms chain. Rejected; changed numerical
output was compared with the copied retained control, not a candidate-specific
headless result. Records: `outputs/goal090/balanced-statistics-results.json`.

Taller Guided tiles reduce halo duplication but do not improve the retained
chain: 16x32 screens at 0.9949 ms and 16x24 at 1.0039 ms. Both pass all 16 image
gates. Shared storage is 5,184/4,032 bytes; AOC a830 projects 12%/15% occupancy
with zero scratch, versus retained 18%. Neither adopted; candidate-specific
headless parity not established. Records: `outputs/goal090/vertical-tile-results.json`.

A bijective four-row-band Guided tile order preserves exact tested desktop
coefficients and phone output but screens at 1.0348 ms, slower than retained.
It adds no tiles and changes no sampling; cache behavior was not measured with
counters. Not adopted; `outputs/goal090/band4-order-results.json`.

Attribution refresh: the retained screen remains 0.9897 ms incremental. Raw
per-pass intervals are initialization 0.3086, Guided 0.2318 and fine reconstruction
0.1568 ms. Diagnostic-only removal of all setup curve/weight arithmetic changes
the first interval to 0.2909 ms; replacing 4x4 integration with one point gives
0.3010 ms. These invalid-output probes are not optimizations. `runner.cpp` starts
pass queries at TOP_OF_PIPE after recording the graphics prefix; outstanding
prefix work can contaminate the first pass interval. Do not label 0.3086 ms as
pure initialization shader time. Next attribution work must separate prefix
completion; matched whole-chain timing remains authoritative. Records:
`outputs/goal090/hotspot-attribution-results.json`.

Follow-up attribution does not support the preceding-prefix timing hypothesis:
compute-stage start queries measure initialization at 0.3078 ms, explicit
diagnostic-only execution draining at 0.3092 ms, versus 0.3086 ms original.
Even an invalid-output no-HDR-read/no-curve kernel measures 0.2862 ms. Shader ALU
is not an adequate explanation; write, dispatch, synchronization and instrumentation
costs remain unresolved. Production timing and shaders are unchanged. Records:
`outputs/goal090/timestamp-attribution-results.json`. See also the
[Vulkan timestamp semantics](https://docs.vulkan.org/refpages/latest/refpages/source/vkCmdWriteTimestamp.html).

Initialization attribution: reducing the diagnostic from three constant UAV
writes to one leaves 0.2854 ms (three writes: 0.2862 ms), so write volume alone
does not explain the interval. A real 16x16 / 256-thread initialization candidate
passes all 16 image gates and matches phone output, but regresses the increment
to 1.3203 ms. Rejected; retained 4x8 groups unchanged. Records:
`outputs/goal090/initialization-dispatch-results.json`.

Skipping initialization dispatch only in diagnostic recording leaves a 0.0026 ms
interval; normal whole-chain recording remains complete. This rules out a large
empty timestamp/barrier floor in that probe. The three-constant-write kernel
changes from 0.2862 ms at 32 threads to 0.2258 ms at 256 threads, but the full
256-thread shader previously regressed. Group count and byte volume alone do
not explain the behavior. Diagnostic-only results, no retained changes:
`outputs/goal090/dispatch-attribution-results.json`.

Keeping 32 initialization threads while reshaping them to 32x1 or 16x2 screens
at 0.9880/0.9893 ms, respectively. Tested phone output is identical, but these
small short-screen differences do not establish a material gain. Both remain
experimental; retained 4x8 geometry unchanged. Records:
`outputs/goal090/initialization-shape-results.json`.

Native half pyramid fetches with FP32 sums and half fetches/sums both pass the
16-case image matrix. Phone screens are 0.9892/0.9874 ms, insufficient to establish
a gain over 0.9909 ms. These also quantize coarse FP32 texture samples; broader
edge/temporal validation and candidate-specific headless parity remain unverified.
Neither adopted; `outputs/goal090/pyramid-half-results.json`.

Combining the small numerical candidates (exponent-product guide, 32x1 init,
half pyramid sums, sliding Guided sums with retained batched averaging) passes
all 16 image gates and odd edge/temporal tests but regresses to 1.0070 ms / 3.4482 ms
chain. Individual short-screen differences did not add; no changes adopted.
Candidate-specific headless parity remains unverified. Records:
`outputs/goal090/combined-small-results.json`.

Register reuse of pyramid samples across 2x2 outputs (9 queries instead of 16
on exact 2:1 levels) passes all 16 image gates but screens at 1.0868 ms. Horizontal
pairs (6 instead of 8 queries) also pass, but screen at 1.0304 ms. Both slower
than retained; no adoption. Numerical candidates were compared with copied
control output, not candidate-specific headless validation. Records:
`outputs/goal090/pyramid-register-reuse-results.json`.

Compiler mode checks: explicit fast floating-point mode produces identical
binaries for all six Local Exposure entries. Minimum Slang frontend optimization
changes binaries but screens at 0.9884 ms with identical tested phone output;
no established gain over retained. Shared apply/baseline binaries are unchanged
in both probes. Not adopted; `outputs/goal090/compiler-mode-results.json`.

Looping four initialization pixels per thread (4x8 threads covering 4x32 outputs)
keeps tested phone output identical but screens at 0.9921 ms, without improvement.
AOC a830 projects 15 registers, 18% occupancy and no scratch. Not adopted;
`outputs/goal090/initialize-loop-four-results.json`.

Canceling common lightness normalization inside the inverse-logit ratio passes
all 16 image gates but screens at 0.9898 ms, no established gain over retained.
Same LUT and endpoint handling; FP32 rounding changes. Not adopted; records:
`outputs/goal090/inverse-normalization-results.json`.

Mixed row-moment storage also fails the quality gate: keeping first moments in
FP32 but storing both second moments in half passes 15/16 cases (Sundowner strong
peak 21). Keeping the cross moment in FP32 and quantizing only the square moment
still peaks at 20 in that case. Neither phone-timed or adopted; records:
`outputs/goal090/mixed-moment-precision-results.json`. Quantizing only the cross
moment passes 16/16, but screens at 0.9921 ms and is also not adopted; AOC a830
projects 14 registers (was 15), unchanged 18% occupancy, zero scratch.

Direct EV-recovery/Guided fusion dependency audit: radius-two fitting followed
by radius-two averaging needs radius-four EV support. At 480x270, straightforward
16x16 tiling would evaluate 293,760 EV inputs versus 129,600 separate (2.27x).
32x32 tiling reduces that to 1.67x but uses about 16.2 KB for separate staging,
coefficient and row arrays. Removing guide_ev saves 1.037 MB/frame of modeled
texture sweep (0.0467 GB/s at 45 FPS), not measured DRAM. This is a dependency
and storage model, not a tested fused kernel or lower bound; boundary/lifetime
optimizations could change it. It argues against prioritizing naive fusion.
`outputs/goal090/ev-guided-fusion-cost.json` records dimensions and assumptions.

A 32-thread tail screen was rejected: 1.083 ms increment (1.052 ms with smaller
shared arrays), with substantial phone output errors despite desktop parity.
The unchanged control remained exact at 0.990 ms; device-only discrepancy cause
is unresolved. Linear indexing restores exact phone output, but screens at 1.014 ms
with 32 threads and 0.991 ms with 128: neither improves the retained path.
Details: `outputs/goal090/tail32-results.json`.


Analytically evaluating the exposure curve as reciprocal square root passes all
16 matrix cases, but screens at 0.9893 ms with no established gain. Phone differences
from retained output are at most one code; the candidate was not adopted.
Details: `outputs/goal090/reciprocal-curve-results.json`.

Reusing coefficient shared storage for horizontal averages reduces default LDS
from 2,880 to 1,600 bytes, but adds a barrier and screens at 1.021 ms increment.
Desktop and phone outputs remain exact; the candidate was rejected. Offline
occupancy stays at 18%. Details: `outputs/goal090/shared-overlay-results.json`.

Fixed 16x16 Guided output tiles with 32 and 96 threads retain exact desktop/phone
output but screen at 1.033 and 1.094 ms increment, respectively. Both are rejected;
64 threads remain retained. Details: `outputs/goal090/guided-group-size-results.json`.

A 2x2 fit block reduces fitting reads from 4,000 to 3,600 per tile. Array and
streaming accumulations pass 16 image cases but screen at 0.988 and 0.992 ms,
without established gains. Coefficient parity is not exact on random desktop
inputs; neither is adopted. Details: `outputs/goal090/square-fit-results.json`.

A 4x2 fit block lowers fitting reads to 2,400 per tile but screens at 1.018 ms.
Explicit accumulators eliminate its 144-byte offline scratch allocation, yet
screen at 1.019 ms. Both are rejected; matrix checks pass and benchmark phone
outputs match. Details: `outputs/goal090/rectangle-fit-results.json`.

Four bilinear HDR reduction samples with log-of-mean guide fail 16/16
image cases (peak 132 codes), and temporal stress reaches 29–30 codes.
Rejected before phone timing. Details: `outputs/goal090/four-bilinear-results.json`.

Splitting inverse-logit log2(a/b) into two independent logarithms passes 16 image
cases but screens at 0.9898 ms, without established improvement. Not adopted.
Details: `outputs/goal090/split-logit-results.json`.

A 32x16 fine-reconstruction tile passes 16 image cases and odd-size/temporal
stress, with exact benchmark phone output, but screens at 0.9954 ms increment.
No gain; retain 16x16. Details: `outputs/goal090/reconstruct-tile32-results.json`.

Native half2 coefficient sampling in final exposure application passes 16 image
cases and preserves the benchmark phone output, but screens at 0.9898 ms without
established gain. Baseline SPIR-V is unchanged; not adopted. Details:
`outputs/goal090/apply-half-sampled-results.json`.

Pyramid groups 8x4 and 16x8 preserve exact output across 14 desktop size/format
cases and the phone benchmark, but screen at 0.9913 and 1.0042 ms. Neither is
adopted. Details: `outputs/goal090/pyramid-shape-results.json`.

Raw FP32 Guided moments are now retained. Extended synthetic checks expose up to
0.0297 EV internal difference, but 140 production-shader final-image cases peak
at one sRGB8 code, including +/-16 EV shifts to reveal clipped errors. Independent
phone readback, integrated foreground output and sustained candidate SPIR-V agree.
This validates the tested ACES workloads, not arbitrary tone operators.
Details: `outputs/goal090/uncentered-results.json`.

Half per-sample luminance in the R11G11B10 gather path passes 16 image cases and
spatial/temporal tests, but screens at 0.9854 ms against the 0.9826 ms retained
baseline. No gain; not adopted. Details: `outputs/goal090/half-luma-results.json`.

Combining raw moments with 2x2 fit reuse passes 16 image cases and preserves
benchmark phone output, but screens at 0.9832 ms versus 0.9826 ms retained.
Offline occupancy improves to 20% without runtime gain; not adopted. Details:
`outputs/goal090/raw-square-results.json`.
