"""Reproducible SPIR-V baseline and optional Adreno Offline Compiler adapter."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "2026.12"
ARCHIVE = f"slang-{VERSION}-windows-x86_64.zip"
URL = f"https://github.com/shader-slang/slang/releases/download/v{VERSION}/{ARCHIVE}"
SHA = "6a2f63174bac4edb994b196f18024c27c4900395fd955b876ecd7a0492347dec"
FLAGS = ["-stage", "compute", "-profile", "spirv_1_3", "-O3", "-fvk-use-entrypoint-name"]
ENTRIES = {
    "guided": ["reduce_source", "fit_coefficients", "average_coefficients", "apply_exposure"],
    "pyramid": ["setup_weights", "downsample"],
    "fusion": ["reconstruct", "convert_exposure"],
    "tonemap": ["compute_main"],
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compiler(download=False):
    base = ROOT / ".tools/mobile"
    exe = base / f"slang-{VERSION}/bin/slangc.exe"
    if not exe.exists() and download:
        base.mkdir(parents=True, exist_ok=True)
        archive = base / ARCHIVE
        if not archive.exists():
            urllib.request.urlretrieve(URL, archive)
        if digest(archive) != SHA:
            raise RuntimeError("Slang archive SHA256 mismatch")
        with zipfile.ZipFile(archive) as z:
            z.extractall(exe.parents[1])
    if not exe.exists():
        raise RuntimeError("Run with --download-tools to acquire pinned official Slang")
    return exe


def spirv_stats(assembly):
    # Count textual IR operations, not dynamic operations or GPU instructions.
    ops = Counter(re.findall(r"\b(Op\w+)\b", "\n".join(
        line for line in assembly.splitlines() if not line.lstrip().startswith(";"))))
    types = {}
    rows = []
    for line in assembly.splitlines():
        m = re.match(r"\s*(%\S+)\s*=\s*(Op\w+)\s*(.*)", line)
        if not m:
            continue
        ident, op, rest = m.groups()
        args = rest.split()
        rows.append((op, args))
        if op == "OpTypeFloat":
            types[ident] = int(args[0])
        elif op == "OpTypeVector" and args[0] in types:
            types[ident] = types[args[0]]
    arithmetic = {"OpFAdd", "OpFSub", "OpFMul", "OpFDiv", "OpFNegate", "OpFRem",
                  "OpFMod", "OpDot", "OpVectorTimesScalar", "OpExtInst"}
    widths = Counter(types.get(args[0]) for op, args in rows if op in arithmetic and args)
    return {"opcodes": dict(sorted(ops.items())),
            "float16_arithmetic_sites": widths[16], "float32_arithmetic_sites": widths[32],
            "image_sample_sites": sum(v for k, v in ops.items() if k.startswith("OpImageSample")),
            "image_read_sites": ops["OpImageRead"] + ops["OpImageFetch"],
            "image_write_sites": ops["OpImageWrite"], "loop_sites": ops["OpLoopMerge"],
            "capabilities": re.findall(r"OpCapability\s+(\w+)", assembly)}


def aoc_metrics(output):
    # Preserve repeated sections as arrays rather than accidentally overwriting them.
    result = {}
    for line in output.splitlines():
        m = re.match(r"\s*(.+?)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*%?\s*$", line)
        if m:
            result.setdefault(m[1].strip(), []).append(float(m[2]))
    return result


def aoc_sections(output):
    sections = {}
    current = None
    for line in output.splitlines():
        title = line.strip()
        if title in ('Shader Preamble Stats', 'Main Shader Stats', 'Latency Hiding Stats', 'Performance Stats'):
            current = title
            sections[current] = {}
        elif current:
            sections[current].update(aoc_metrics(line))
    return sections


def workload(width, height):
    if min(width, height) < 1:
        raise ValueError("Dimensions must be positive")
    w, h = (width + 3) // 4, (height + 3) // 4
    mips = [(max(1, w >> i), max(1, h >> i)) for i in range(min(16, min(w, h).bit_length()))]
    calls = []
    def add(entry, size):
        x, y = size
        calls.append(dict(entry=entry, size=[x, y], useful_threads=x*y,
                          launched_threads=((x+7)//8)*((y+7)//8)*64))
    add("reduce_source", (w, h))
    add("setup_weights", (w, h))
    for _ in range(2):
        for size in mips[1:]:
            add("downsample", size)
    for size in reversed(mips):
        add("reconstruct", size)
    for entry in ("convert_exposure", "fit_coefficients", "average_coefficients"):
        add(entry, (w, h))
    for entry in ("apply_exposure", "compute_main"):
        add(entry, (width, height))
    # Logical texture payload. Excludes row alignment, driver allocations and swapchain.
    payload = width*height*(16+2+8+8+4) + w*h*(16+2+8+8) + sum(x*y for x,y in mips)*36 + 2048
    return dict(low_size=[w,h], mip_sizes=mips, dispatches=calls,
                texture_payload_bytes=payload, inverse_lut_bytes=2048)


def run(command, log, cwd=ROOT):
    p = subprocess.run([str(x) for x in command], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    log.write_text(p.stdout + p.stderr, encoding="utf-8")
    if p.returncode:
        raise RuntimeError(f"Compiler failed ({p.returncode}); see {log}")
    return p.stdout + p.stderr


def export_pass(exe, module, entry, dest):
    dest.mkdir(parents=True, exist_ok=True)
    commands = []
    for target, suffix in (("spirv", "spv"), ("spirv-asm", "spvasm")):
        cmd = [exe, ROOT/f"shaders/{module}.slang", "-entry", entry, *FLAGS,
               "-target", target, "-o", dest/f"shader.{suffix}"]
        run(cmd, dest/f"{suffix}.log")
        commands.append([str(x) for x in cmd])
    return dict(bytes=(dest/"shader.spv").stat().st_size,
                sha256=digest(dest/"shader.spv"),
                spirv=spirv_stats((dest/"shader.spvasm").read_text()), commands=commands)


def markdown(report):
    w = report["workload"]
    lines = ["# Mobile shader baseline", "", f"Target: **{report['config']['target']}**. Status: **{report['status']}**.", "",
             "Portable SPIR-V code statistics are not Adreno ISA counts, cycles, occupancy or GPU timing.",
             "Uniform branches and loops remain in the modules; sites are not per-pixel execution counts.", "",
             f"Source/display: {report['config']['size']}; Fusion: {w['low_size']}; {len(w['mip_sizes'])} levels.",
             f"Fresh-frame dispatches: {len(w['dispatches'])}. Logical texture payload: {w['texture_payload_bytes']/1048576:.2f} MiB.", "",
             "| Entry | SPV bytes | FP16 sites | FP32 sites | Sample/read/write sites | Loop sites |",
             "|---|---:|---:|---:|---|---:|"]
    for name, p in report["passes"].items():
        s = p["spirv"]
        lines.append(f"| {name} | {p['bytes']} | {s['float16_arithmetic_sites']} | {s['float32_arithmetic_sites']} | {s['image_sample_sites']}/{s['image_read_sites']}/{s['image_write_sites']} | {s['loop_sites']} |")
    if report['aoc']:
        lines += ['', '## Adreno offline estimates', '',
                  '| Entry | Main instructions | Register footprint | Scratch bytes | ALU fiber occupancy % |',
                  '|---|---:|---:|---:|---:|']
        for name, p in report['passes'].items():
            main = p['adreno_sections']['Main Shader Stats']
            keys = ['Total instruction count', 'Overall register footprint per shader instance',
                    'Scratch memory usage per shader instance', 'ALU fiber occupancy percentage']
            values = [str(main[k][0]) if k in main else 'N/A' for k in keys]
            lines.append('| '+name+' | '+' | '.join(values)+' |')
        lines += ['', 'Preamble is reported separately in JSON. Register/occupancy definitions differ from Mali; do not compare their numerical values directly.']
    lines += ["", "Adreno estimates and raw command logs are in report.json and each pass directory.",
              "AOC metrics are null when unavailable; even successful AOC analysis does not measure frame time.",
              "Calibration is initialization-only and excluded. Static-image viewer caching is excluded.", ""]
    return "\n".join(lines)


def compare(old, new):
    for key in ('schema', 'config', 'compiler', 'aoc'):
        if old[key] != new[key]:
            raise ValueError(f"Incompatible baseline: {key}")
    if old['passes'].keys() != new['passes'].keys():
        raise ValueError('Incompatible entry points')
    return {name: {metric: p['spirv'][metric] - old['passes'][name]['spirv'][metric]
                   for metric in ('float16_arithmetic_sites', 'float32_arithmetic_sites',
                                  'image_sample_sites', 'image_read_sites', 'image_write_sites', 'loop_sites')}
            for name, p in new['passes'].items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-tools", action="store_true")
    parser.add_argument("--aoc", default=os.environ.get("AOC_PATH") or shutil.which("aoc"))
    parser.add_argument("--require-aoc", action="store_true")
    parser.add_argument("--arch", choices=['a730', 'a750'], default='a730',
                        help="Adreno target; default a730 (Snapdragon 8 Gen 1)")
    parser.add_argument("--compare", type=Path, help="Compare portable IR sites against a compatible JSON baseline")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--out", type=Path, help="Defaults to outputs/mobile/<arch>")
    args = parser.parse_args()
    work = workload(args.width, args.height)
    exe = compiler(args.download_tools)
    out = (args.out or ROOT / 'outputs/mobile' / args.arch).resolve()
    out.mkdir(parents=True, exist_ok=True)
    version = run([exe, "-version"], out / "slang-version.txt").strip()
    if version != VERSION:
        raise RuntimeError(f"Expected Slang {VERSION}, got {version}")
    local_aoc = ROOT / '.tools/mobile/aoc-7.0.15/installed/aoc.exe'
    aoc = Path(args.aoc).resolve() if args.aoc else (local_aoc if local_aoc.exists() else None)
    if aoc and not aoc.is_file():
        raise RuntimeError(f"AOC executable not found: {aoc}")
    report = dict(schema=1, status="aoc-complete" if aoc else "portable-only; AOC unavailable",
                  config=dict(target=args.arch, size=[args.width,args.height], fusion_scale=4,
                              max_levels=16, flags=FLAGS, uniform_specialization=False),
                  compiler=dict(version=version, sha256=digest(exe), url=URL, archive_sha256=SHA),
                  aoc=dict(sha256=digest(aoc), path=str(aoc)) if aoc else None,
                  source_sha256={str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/"shaders").glob("*.slang"))},
                  workload=work, passes={})
    # Remove the previous report first so a failed rerun cannot look successful.
    for filename in ("report.json", "report.md"):
        (out / filename).unlink(missing_ok=True)
    for module, entries in ENTRIES.items():
        for entry in entries:
            dest = out / entry
            compiled = export_pass(exe, module, entry, dest)
            metrics = None
            if aoc:
                cmd = [aoc, "-api=Vulkan", f"-arch={args.arch}", "-cs", "-entry_point_cs", entry,
                       dest/"shader.spv", "-dump=all"]
                raw = run(cmd, dest/"aoc.log", cwd=dest)
                if 'Compilation succeeded.' not in raw:
                    raise RuntimeError(f'AOC did not confirm compilation: {dest/"aoc.log"}')
                compiled['commands'].append([str(x) for x in cmd])
                compiled['adreno_sections'] = aoc_sections(raw)
                report['aoc']['version'] = re.search(r'AOC Version\s*:\s*(\S+)', raw).group(1)
                report['aoc']['compiler_version'] = re.search(r'Compiler Version\s*:\s*(\S+)', raw).group(1)
                metrics = aoc_metrics(raw)
                if not any("Total instruction count" in k for k in metrics):
                    raise RuntimeError(f"AOC returned no recognized instruction metrics: {dest/'aoc.log'}")
            report["passes"][entry] = dict(compiled, adreno=metrics)
            print(f"Compiled {entry}", flush=True)
    (out/"report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    (out/"report.md").write_text(markdown(report), encoding="utf-8")
    if args.compare:
        delta = compare(json.loads(args.compare.read_text(encoding='utf-8')), report)
        (out/'comparison.json').write_text(json.dumps(delta, indent=2)+'\n', encoding='utf-8')
    print(out/"report.md")
    if args.require_aoc and not aoc:
        raise SystemExit("Portable baseline saved, but required AOC is unavailable")


if __name__ == "__main__":
    main()
