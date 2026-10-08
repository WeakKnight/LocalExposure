# Historical controls

`legacy_guided.py` and `guided.slang` freeze the former average-HDR / low-resolution
inversion / Guided viewer path. Application code does not import or compile them.
They remain exclusively for historical benchmarks, export controls and numerical
regressions, as required by the repository's independent-control policy.

Run the application with `FineResidualToneMapper` (default) or the full-resolution
`ToneMapper` reference. The latter rejects `fusion_scale=4`; there is no implicit
fallback to the old algorithm. See [the halo diagnosis](../../../docs/performance/viewer-halo.md).

The frozen `pyramid_rec709.slang` and `fusion_rec709.slang` retain the legacy
Rec.709 metric after current Bart switched to equal RGB on 2026-10-08.
