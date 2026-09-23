"""Export Slang compute shaders and analyze them with Arm Mali Offline Compiler."""
import argparse
import json
import os
from pathlib import Path
import shutil

try:
    from .mobile_profile import ROOT, VERSION, FLAGS, ENTRIES, compiler, digest, run, export_pass, workload
except ImportError:
    from mobile_profile import ROOT, VERSION, FLAGS, ENTRIES, compiler, digest, run, export_pass, workload


def summarize(raw, core):
    if raw.get('schema') != {'name': 'performance', 'version': 2}:
        raise ValueError('Unsupported malioc JSON schema; inspect raw report')
    shaders = raw['shaders']
    if len(shaders) != 1 or shaders[0]['hardware']['core'] != core:
        raise ValueError('Unexpected shader count or target GPU')
    shader = shaders[0]
    variants = []
    for variant in shader['variants']:
        props = {p['name']: p['value'] for p in variant['properties']}
        perf = variant['performance']
        cycles = {}
        for key in ('total_cycles', 'shortest_path_cycles', 'longest_path_cycles'):
            counts = perf[key]['cycle_count']
            if len(counts) != len(perf['pipelines']):
                raise ValueError('Mismatched pipeline counts')
            cycles[key] = dict(zip(perf['pipelines'], counts))
        variants.append(dict(name=variant['name'], properties=props, cycles=cycles,
                             bound=perf['total_cycles']['bound_pipelines']))
    if not variants:
        raise ValueError('No compiled variants')
    return dict(driver=shader['driver'], hardware=shader['hardware'], variants=variants,
                warnings=shader['warnings'], notes=shader['notes'])


def markdown(report):
    lines = ['# Mali shader baseline', '',
        f"Target: **{report['config']['target']}**. Compiler: **{report['malioc']['version'].splitlines()[0]}**.",
        '', 'All nine compute entries compiled successfully. These are offline estimates, not measured GPU time.',
        'Cycle columns are the compiler’s total instruction-cycle estimates; do not sum them across pipelines or multiply them into frame milliseconds.',
        'Runtime branches and loops are retained. Inspect raw JSON shortest/longest paths, variants and warnings.', '',
        '| Entry / variant | Work regs | Occupancy % | FP16 arithmetic % | Spill bytes | Arithmetic | Load/store | Texture | Bound |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for entry, data in report['passes'].items():
        for variant in data['mali']['variants']:
            p = variant['properties']
            c = variant['cycles']['total_cycles']
            lines.append(f"| {entry} / {variant['name']} | {p.get('work_registers_used', 'N/A')} | {p.get('thread_occupancy', 'N/A')} | {p.get('fp16_arithmetic', 'N/A')} | {p.get('stack_spill_bytes', 'N/A')} | {c.get('arith_total', 0):.3f} | {c.get('load_store', 0):.3f} | {c.get('texture', 0):.3f} | {', '.join(variant['bound'])} |")
    w = report['workload']
    lines += ['', f"Workload: {report['config']['size']}, Fusion {w['low_size']}, {len(w['mip_sizes'])} levels, {len(w['dispatches'])} dispatches.",
              f"Logical texture payload: {w['texture_payload_bytes']/1048576:.2f} MiB; inverse LUT: 2 KiB.",
              'The payload includes viewer base/final outputs; it is not measured bandwidth or physical allocation.',
              'Calibration and static-image caching are excluded. Exported SPIR-V and raw malioc reports are under outputs/mobile/mali/.', '']
    return '\n'.join(lines)


def compare(old, new):
    for key in ('schema', 'config', 'slang', 'malioc'):
        if old[key] != new[key]:
            raise ValueError(f'Incompatible Mali baseline: {key}')
    if old['passes'].keys() != new['passes'].keys():
        raise ValueError('Entry points changed')
    delta = {}
    for entry, data in new['passes'].items():
        prev = old['passes'][entry]['mali']
        cur = data['mali']
        if (prev['driver'], prev['hardware']) != (cur['driver'], cur['hardware']):
            raise ValueError('Driver or hardware changed')
        a = {v['name']:v for v in prev['variants']}
        b = {v['name']:v for v in cur['variants']}
        if a.keys() != b.keys():
            raise ValueError('Compiled variants changed')
        delta[entry] = {name: {
            'properties': {k:v-a[name]['properties'][k] for k,v in item['properties'].items()
                           if type(v) in (int, float) and k in a[name]['properties']},
            'total_cycles': {k:v-a[name]['cycles']['total_cycles'][k]
                             for k,v in item['cycles']['total_cycles'].items()}}
            for name,item in b.items()}
    return delta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', default='Immortalis-G720')
    parser.add_argument('--malioc', default=os.environ.get('MALIOC_PATH') or shutil.which('malioc'))
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--out', type=Path, default=ROOT/'outputs/mobile/mali')
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    candidates = sorted((ROOT/'.tools/mobile/arm-2026.5').rglob('malioc.exe'))
    malioc = Path(args.malioc).resolve() if args.malioc else (candidates[0] if len(candidates)==1 else None)
    if malioc is None or not malioc.is_file():
        parser.error('Run tools/profiling/install_mali.ps1 or provide --malioc')
    exe = compiler()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in ('report.json','report.md','comparison.json'):
        (out/name).unlink(missing_ok=True)
    version = run([exe, '-version'], out/'slang-version.txt').strip()
    if version != VERSION:
        raise ValueError('Unexpected Slang version')
    mv = run([malioc, '--version'], out/'malioc-version.txt').strip()
    run([malioc, '--list'], out/'supported-gpus.txt')
    run([malioc, '--info', '--core', args.core], out/'gpu-info.txt')
    report = dict(schema=1, status='malioc-complete',
        config=dict(target=args.core, size=[args.width,args.height], fusion_scale=4, max_levels=16,
                    flags=FLAGS, uniform_specialization=False),
        slang=dict(version=version, sha256=digest(exe)),
        malioc=dict(version=mv, files={str(p.relative_to(malioc.parent)):digest(p) for p in sorted(malioc.parent.rglob('*'))
                                     if p.suffix.lower() in ('.exe','.dll')}),
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/'shaders').glob('*.slang'))},
        workload=workload(args.width,args.height), passes={})
    for module, entries in ENTRIES.items():
        for entry in entries:
            dest = out/entry
            compiled = export_pass(exe,module,entry,dest)
            target = dest/'malioc.json'
            target.unlink(missing_ok=True)
            cmd = [malioc,'--vulkan','--spirv','--compute','--core',args.core,'--name',entry,
                   '--format','json','--detailed',dest/'shader.spv','-o',target]
            run(cmd,dest/'malioc.log')
            raw = json.loads(target.read_text(encoding='utf-8'))
            compiled['commands'].append([str(x) for x in cmd])
            compiled['mali'] = summarize(raw,args.core)
            report['passes'][entry] = compiled
            print(f'Analyzed {entry}',flush=True)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (out/'report.md').write_text(markdown(report),encoding='utf-8')
    if args.compare:
        delta = compare(json.loads(args.compare.read_text(encoding='utf-8')),report)
        (out/'comparison.json').write_text(json.dumps(delta,indent=2)+'\n',encoding='utf-8')
    print(out/'report.md')


if __name__ == '__main__':
    main()
