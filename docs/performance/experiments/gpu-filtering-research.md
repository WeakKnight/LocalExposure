# GPU filtering implementation research

Research following the Wave experiments. These are candidate designs, not
measured improvements. No production shaders were changed by this research.

## Sources and transferable ideas

| Implementation inspected | Actual technique | Application to Local Exposure |
|---|---|---|
| [NVIDIA CUDA separable convolution, v12.5](https://github.com/NVIDIA/cuda-samples/blob/v12.5/Samples/2_Concepts_and_Techniques/convolutionSeparable/convolutionSeparable.cu) | Eight results per thread, cooperative main/halo loads, shared-memory reuse; column storage includes padding. | Decouple output-tile dimensions from thread-group dimensions. Test two/four outputs per thread without increasing the group to 1024 threads. |
| [NVIDIA CUDA box filter, v12.5](https://github.com/NVIDIA/cuda-samples/blob/v12.5/Samples/2_Concepts_and_Techniques/boxFilter/boxFilter_kernel.cu) | Sliding sums add the entering sample and subtract the leaving sample. The source also explains the row-access coalescing limitation. | Use short register windows within a tile for Guided moments and coefficient averaging, rather than assigning a whole image row to a thread. |
| [OpenCV CUDA column filter](https://github.com/opencv/opencv_contrib/blob/4.x/modules/cudafilters/src/cuda/column_filter.hpp) | Multiple patches per block, compile-time kernel size, shared halo, separate interior/border load paths. | Specialize the fixed radius-two production filter and amortize its halo across several outputs. |
| [NVIDIA nvpro_pyramid](https://github.com/nvpro-samples/vk_compute_mipmaps/blob/master/nvpro_pyramid/nvpro_pyramid.glsl) | Explicit small 2D lane teams, XOR shuffles, multi-level tiles; separate fast and general pipelines. | Learn the scheduling, not just the shuffle intrinsic. Try two adjacent pyramid levels before a full single-dispatch chain. |
| [AMD FidelityFX SPD](https://github.com/GPUOpen-Effects/FidelityFX-SPD/blob/master/ffx-spd/ffx_spd.h) | Remapped lane coordinates, early per-thread reductions, shared/Wave exchange, last-workgroup continuation for the tail. | Keep useful nonlinear setup work on every lane before reducing across lanes; avoid paying for four lanes when only one performs setup. |
| [Filament Gaussian coefficients](https://github.com/google/filament/blob/main/filament/src/PostProcessManager.cpp) and [shader](https://github.com/google/filament/blob/main/filament/src/materials/separableGaussianBlur.fs) | CPU combines adjacent weights into one linear-sampler tap; separable fragment passes and compile-time component specialization. | Consider hardware filtering only for linear intermediates, and measure complete pass/backend costs. |

## Proposed order of experiments

1. **Guided multi-output tile, shared-memory baseline first.** Keep both 5x5
   supports, the current tile anchor and FP32 accumulation. Assign two/four
   outputs per thread and reuse moments/window inputs. Four adjacent 5-tap
   windows contain eight distinct samples versus twenty independent sample
   visits. This is a local reuse opportunity, not a DRAM-traffic prediction.
2. **Short sliding sums.** Reinitialize at tile boundaries to limit accumulation
   drift. Check variance cancellation, odd sizes, motion and sharp weights.
   Mathematical equivalence does not imply bitwise equivalence.
3. **Explicit lane layout.** After the shared-memory version works, add a small
   subgroup-only test with known row/halo ownership. Keep exchanges in converged
   control flow and use queried subgroup capabilities. The previous phone
   non-finite result is unresolved; the references do not diagnose it.
4. **Two-level pyramid batching.** Preserve our actual four-bilinear-tap kernel,
   mip rounding and quantization. The existing failed tail experiment is not
   evidence that batching the larger levels cannot help, but limits optimism.

## Restrictions that matter here

- Standard SPD is a 2x2 reduction. Our `downsample_compact` uses four bilinear
  taps offset by +/- one input texel; at aligned 2:1 sizes it covers a 4x4
  footprint. Direct replacement changes the filter. SPD also documents omitted
  edge texels for odd dimensions. See [SPD technique and limitations](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/single-pass-downsampler/).
- nvpro's fast path requires subgroup shuffle support and subgroup size at least
  16; its source still carries a TODO about testing sizes other than 32. It is
  not evidence of Adreno performance or universal subgroup portability.
- Linear filtering cannot commute with moment construction: interpolating
  `g` and then squaring differs from interpolating `g*g`. The same applies to
  averaging luminance before `log`. A moments texture permits linear filtering
  but adds traffic; our previous separate-moment candidate did not improve the
  overall result. Do not repeat it unchanged.
- Shared-memory padding and larger tiles have already been tried locally. The
  new experiment is **more outputs per thread with reuse**, not merely another
  workgroup size or padding define.
- Retain the matched foreground graphics-producer benchmark, report both total
  and incremental GPU time, and validate output before accepting timing results.

CUDA references were read at the v12.5 tag; OpenCV, Filament, SPD and nvpro links
refer to their named moving branches as inspected on 2026-09-24. Their published
desktop speedups must not be relabeled as mobile speedups.
