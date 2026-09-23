# Developer tools

These are optional; launch the application with `run.ps1` from the repository root.

| Tool | Purpose |
| --- | --- |
| `render_examples.py` | Regenerate the README comparison images |
| `profiling/mobile_profile.py` | Export SPIR-V and run AOC; defaults to Adreno 730 |
| `profiling/mali_profile.py` | Run Mali Offline Compiler; defaults to Immortalis-G720 |
| `profiling/install_mali.ps1` | Download and extract the pinned Arm toolchain |
| `profiling/android/` | Deploy the production Vulkan benchmark and measure an attached phone; see the [workflow](../docs/performance/android.md) |
| `profiling/android/activity.py` | Foreground graphics-produced HDR, joint submissions and sustained AB/BA timing |
| `profiling/android/quality_sweep.py` | Same-backend spatial and temporal stress; presets live in `variants.py` |
| `experiments/ten_rounds.py` | Replay historical optimization candidates; not part of the application |

Run from the repository root, for example:

```powershell
.\.venv\Scripts\python.exe tools/profiling/mobile_profile.py --require-aoc
```

See the [profiling guide](../docs/performance/README.md) for setup and interpretation. Generated files live in `outputs/`; downloaded compilers live in `.tools/`. Both directories are ignored by Git. Historical experiments temporarily substitute shader source and restore it after each candidate; they do not apply optimizations automatically.
