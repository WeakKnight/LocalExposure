# Performance baselines

Current implementation snapshots:

- [Adreno 730](a730-ten-rounds.md): primary optimization target (Snapdragon 8 Gen 1).
- [Immortalis-G720](g720-ten-rounds.md): secondary architecture check.

[Adreno 750](a750-aoc.md) is an earlier reference target snapshot, not the latest shader revision. Each report has a JSON sidecar with compiler identity, source hashes and commands. Source hashes determine which revision was measured.

`archive/` contains older baselines, kept for reproducibility. Recorded commands and absolute paths in JSON describe the original run and are intentionally not rewritten during repository reorganization. Use the current [profiling guide](../README.md) for commands to run today.
