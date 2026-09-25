# Measurement records

- [Current mobile baseline](current.json): settings, matched timings, compiler projections and quality results.
- [Tested driver provenance](driver.json): download source, hashes and loader revision.

Original recorded paths are provenance, not runtime dependencies. The retained
historical bundle lives in `outputs/current/`; the latest direct-Guided acceptance
bundles, raw timing samples and phone captures live in `outputs/goal110/`.
Regenerate new runs with the [Android workflow](../android.md).
