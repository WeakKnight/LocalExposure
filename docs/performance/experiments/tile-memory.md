# Qualcomm tile memory: capability-gated experiment

**Update: process-local Qualcomm 512.842.6 loading succeeded on this phone.**
The system-driver limitation below still applies, but the optional custom-driver
path exposes the extension and passes a foreground rendering smoke test.
See [custom-driver validation](custom-driver.md).
The subsequent [runtime residency experiment](tile-memory-runtime.md) measures
actual intermediate placement in that heap.

The connected NX789J / Adreno 830 was queried directly on 2026-09-24. Its current
Vulkan driver does **not** advertise `VK_QCOM_tile_memory_heap`. Neither of its
two memory heaps has `VK_MEMORY_HEAP_TILE_MEMORY_BIT_QCOM`. Consequently no
tile-memory execution or timing comparison was possible. Production code is
unchanged; there is no claimed speedup or measured DRAM saving.

The device does advertise `VK_QCOM_tile_properties`; that extension does not
enable explicit tile-memory allocation. This result describes this installed
driver, not all Adreno 830 devices, and establishes nothing about Adreno 730.

[Raw capability record](../baselines/tile-memory-capabilities.json) includes the
firmware fingerprint, driver version, full extension list and heap flags.

### Instance / SDK cross-check

A second probe requested the loader's maximum API version (1.3.0) and enabled
`VK_KHR_surface` plus `VK_KHR_android_surface`. Its device extension list was
identical to the original 1.2 headless probe: tile memory remained absent.
The physical device reports Vulkan 1.3.284. The compiled NDK headers are revision
335 and already contain this extension's declarations. The extension requires
Vulkan 1.1 (or its equivalent extension dependencies), so the original 1.2
instance satisfies its core-version dependency.

Android's independent `adb shell cmd gpu vkjson` query also omitted the extension
and identified the same Qualcomm driver: build `0fd63a2c96`, `I5538b87673`, date
`05/02/25` (2025-05-02), compiler `E031.47.18.30`. This points to the installed
driver's exposed capabilities, not missing application SDK definitions. It does
not prove whether a newer driver can enable the feature on this GPU.

[Instance audit record](../baselines/tile-memory-instance-audit.json).

```console
python -m tools.profiling.android.tile_memory --api max --surface --out outputs/android/tile-memory/instance-recheck
```

## Reproduce

From the repository root, with an authorized Android device and the existing NDK:

```console
python -m tools.profiling.android.tile_memory --out outputs/android/tile-memory/new-probe
```

Use a fresh output directory. `--serial` selects a device. The probe queries
features/properties only if the extension is advertised. `eligible` requires
the extension, feature and heap; it does not promise support for every image.

## Why it fits this algorithm

Qualcomm's extension allows transient images and buffers to live in on-chip
memory across compute/render passes within a submission batch (or, if the
queried property permits it, a queue submit). Fusion intermediates are produced
and consumed within a frame and need no history, so their lifetime fits.

For the retained 1920 x 1080, quarter-width/height graph, logical texture storage is:

| Resource | Bytes, including allocated mips | Suggested priority |
|---|---:|---|
| guide_ev, RG32F | 1,036,800 | First: reconstructed EV and guide, consumed by Guided |
| averaged, RG16F | 518,400 | First: consumed during full-resolution apply |
| luminance residual pyramid, RG16F | 690,620 | Next: downward and upward pyramid reads |
| weights pyramid, RG16_UNORM | 690,620 | Next: downward and upward pyramid reads |
| reconstructed pyramid, R32F | 690,620 | Next: upward reconstruction |
| compact, RG32F | 1,036,800 | Later: source summary retained until EV reconstruction |
| base_lightness, R32F | 518,400 | Later: preserved middle-exposure lightness |
| Total | 5,182,260 | Before driver alignment/tiling; not peak live allocation |

Start with guide_ev plus averaged (1,555,200 logical bytes), leaving HDR source,
output and persistent inverse LUT in normal memory. Actual tile requirements
must come from `VkTileMemoryRequirementsQCOM`; zero size/alignment means the
resource cannot use the heap. Never size an allocation from the table alone.

## Next experiment when supported

1. Enable the feature and query tile requirements for selected images. Allocate
   one tile-memory object with aligned, non-overlapping bindings initially.
2. Bind it to the command buffer before producers, and preserve it until the last
   consumer. Keep the existing shader arithmetic and synchronization.
3. The current post-submit debug readback cannot recover tile contents. Copy
   validation intermediates to ordinary memory inside the producing submission,
   in a separate untimed validation run. Persistent LUT uploads must remain normal.
4. Validate against the ordinary-memory path, then use the matched foreground
   `activity --hdr-producer --joint-submission` workflow. Report total and
   incremental GPU times. Restrict the bound range/lifetime: reserving tile memory
   can reduce space available to graphics rendering and offset compute gains.
5. Only after a positive result, alias resources with disjoint lifetimes and
   expand pyramid residency. Preserve both moment and coefficient filter supports.

The 19.18 MB/frame nominal texture traffic does not disappear: the shader still
performs those accesses. Some accesses may move to on-chip memory. Do not subtract
the residency table from that traffic model or claim a physical DRAM saving
without counters. No bandwidth or thermal improvement has been measured here.

## References

- [Qualcomm: improving bandwidth with tile memory heap](https://www.qualcomm.com/developer/blog/2026/05/high-performance-memory-extension-optimize-memory)
- [Khronos extension proposal and allocation examples](https://docs.vulkan.org/features/latest/features/proposals/VK_QCOM_tile_memory_heap.html)
- [Vulkan extension reference](https://docs.vulkan.org/refpages/latest/refpages/source/VK_QCOM_tile_memory_heap.html)
