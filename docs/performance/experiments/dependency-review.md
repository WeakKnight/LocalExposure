# Data dependencies and synchronization review

Scope: the retained `gather-reduction` mobile graph, quarter-resolution Fusion,
precomputed EV and separable Guided filtering. This is a source/SPIR-V review,
not a new performance measurement. Shared tonemapping and presentation are not
Local Exposure optimization targets.

## Findings, in priority order

### 1. Guided work distribution leaves uneven work before each barrier

`shaders/fusion_compact.slang:509-651` assigns linear tasks in strides of 256
threads. The four producer stages have different tile sizes:

| Producer | Tasks | Loop rounds | Active threads in last round | Logical active slots |
|---|---:|---:|---:|---:|
| Load guide/EV into shared memory | 576 | 3 | 64/256 | 75% |
| Horizontal moments | 480 | 2 | 224/256 | 93.75% |
| Fit coefficients from vertical moments | 400 | 2 | 144/256 | 78.125% |
| Horizontal coefficient averaging | 320 | 2 | 64/256 | 62.5% |

These fractions describe source-level task distribution, not measured ALU
utilization or occupancy. Threads with fewer tasks reach synchronization sooner;
completion depends on the remaining threads. Expensive covariance/variance and
division work is on the critical path before the third barrier. Register-ready
independent work and sharing overlapping windows may shorten these phases.

Priority experiment: decouple thread-group size from output tile size and reuse
vertical as well as horizontal windows. Keep filter supports, clamp behavior,
tile anchor and FP32 moment precision. More outputs per thread may increase
register pressure or serialize too much work; measure rather than assume a win.
The previous batch2 experiment is promising but not a universal improvement;
batch4, padding and separate-moment passes should not be repeated unchanged.

### 2. All four Guided barriers protect real cross-thread reads

| Barrier line | Published shared data | Consumer |
|---|---|---|
| 519 | `fusedInputs` | Neighbor samples and common anchor for horizontal moments |
| 573 | `rowMoments` | Five vertically neighboring rows for coefficient fitting |
| 615 | `fusedCoefficients` | Five horizontally neighboring coefficients |
| 651 | `rowCoefficients` | Five vertically neighboring sums for final output |

The exact production SPIR-V contains four `OpControlBarrier` instructions with
workgroup execution/memory scope and AcquireRelease + WorkgroupMemory semantics.
They are not device-wide barriers. No obvious redundant internal barrier was
found in this layout. Removing a rendezvous, or replacing it with a memory fence
without thread synchronization, is unsafe. Neighbor data can belong to another
subgroup; a Wave intrinsic is not a drop-in replacement.

The out-of-bounds return at line 652 is correctly after the final barrier.
Moving it to the start would remove participating threads that populate halos
and would make group synchronization nonuniform for edge groups.

The A730 offline report's 13 barrier/fence instructions and exposed latency-sync
percentages do not mean 13 source barriers or that four rendezvous account for
58.2% of phone time. Compiler-inserted memory/dependency waits also matter.

### 3. The pass graph is a genuine serial dependency chain

Manifest subresource review finds a read-after-write dependency on **all 19
adjacent edges between the 20 production passes**:

`setup -> downsample mip1..8 -> reconstruct mip8..1 -> EV -> Guided -> apply`.

Downsampling reads the previous luminance/weight mip. Reconstruction reads the
previous reconstructed coarser mip. EV reads reconstruction; Guided reads EV;
apply reads averaged coefficients. See the [resource/mip edge list](../baselines/dependency-review.json).
Separate mips are distinct subresources, but each next dispatch explicitly reads
the mip just written. Simply dropping every other barrier is not correct.

Small pyramid passes have little work to hide dispatch/dependency latency.
Reducing their number requires an algorithm/scheduling change such as a fused
tail with correct cross-group coordination, not just deleting synchronization.
Filter footprints, odd dimensions and per-level quantization must be preserved
or separately validated.

### 4. Vulkan scopes are conservative, but narrowing them has limited proof

`runner.cpp:135` uses COMPUTE_SHADER -> COMPUTE_SHADER, shader-write ->
shader-read|shader-write between compute passes. The stage scope is already
compute-specific. For the retained non-aliasing, single-execution graph, most
inter-pass hazards are RAW, making destination shader-write a potential
specialization to audit. The generic helper also supports repeated writes and
other graphs, so deleting that flag globally would be unjustified.

A per-image barrier is not inherently faster than a global memory barrier and
does not by itself allow dependent compute stages to overlap. Khronos explicitly
uses global barriers for this pattern and recommends them in many such cases:
[synchronization examples](https://docs.vulkan.org/guide/latest/synchronization_examples.html).

`record()` also emits a compute barrier after the last pass. There is no later
compute consumer within that chain; the activity separately establishes the
compute-write -> transfer-read dependency for presentation. This terminal barrier
is a candidate for narrowly scoped cleanup, after checking other runner clients
and later submissions. It is shared by baseline and Fusion, so its absolute
saving must not be credited as a Local Exposure-specific gain.

### 5. Setup has dependency latency without workgroup synchronization

`reduce_setup_gather` has no shared-memory or group barrier. Its critical path
is RGB Gather -> luminance -> log accumulation -> exposure curve -> normalized
weights -> stores. The three exposure results and some Gather work offer
instruction-level parallelism; restructuring accumulators or batching inputs can
increase independent work but may increase registers and change rounding.
Removing group synchronization cannot improve this pass because none exists.

## Decision

Keep existing synchronization while testing changes to Guided's work ownership
and overlapping-window reuse first. Second, inspect setup's Gather/SFU/arithmetic
dependency scheduling. Treat pyramid fusion as a separate experiment. Do not
spend the first optimization round replacing all global barriers or changing
shared tonemapping.

No correctness race was found in the inspected retained intra-frame chain.
This is not certification of every optional variant, cross-queue configuration
or overlapping-frame integration. The foreground joint benchmark has no CPU
fence between its production passes; its end-of-submit fence and presentation
queue-idle are harness pacing, not per-pass Local Exposure GPU waits.

No shader or runtime behavior changed in this review. Hardware counter attribution
of shared-memory stalls versus arithmetic latency is still unavailable; follow-up
experiments must report matched incremental and complete-chain GPU times and
pass the existing image-quality gates.
