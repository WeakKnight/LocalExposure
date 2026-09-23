"""Measure validated streaming-buffer effective bandwidth on an Android Vulkan GPU."""
import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from .benchmark import ADB, NDK, TOOLS, run, select_device
from .prepare import ROOT, sha
from tools.profiling.mobile_profile import compiler, FLAGS

REMOTE='/data/local/tmp/local-exposure-bandwidth'


def bandwidth_stats(payload_bytes, milliseconds):
    ms=np.asarray(milliseconds,dtype=float)
    if payload_bytes<=0 or not ms.size or not np.isfinite(ms).all() or np.any(ms<=0):
        raise ValueError('Invalid bandwidth samples')
    # Decimal GB/s: bytes / (milliseconds * 1e6), including reads + writes.
    gbps=payload_bytes/(ms*1e6)
    return dict(samples=int(ms.size),median_gbps=float(np.median(gbps)),p05_gbps=float(np.percentile(gbps,5)),
                p95_gbps=float(np.percentile(gbps,95)),median_ms=float(np.median(ms)))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--serial')
    ap.add_argument('--sizes-mib',type=int,nargs='+',default=[1,8,32,128],help='Bytes in each individual source/destination buffer')
    ap.add_argument('--pairs',type=int,default=3)
    ap.add_argument('--frames',type=int,default=96)
    ap.add_argument('--warmup',type=int,default=48)
    ap.add_argument('--interval-ms',type=int,default=0)
    args=ap.parse_args()
    if not args.sizes_mib or min(args.sizes_mib)<1 or max(args.sizes_mib)>128 or args.pairs not in (1,2,3):
        ap.error('Use 1..128 MiB buffers and 1..3 pairs')
    if args.frames<1 or min(args.warmup,args.interval_ms)<0: ap.error('Invalid sampling configuration')
    if args.out.exists(): raise ValueError('Choose a new result directory')
    adb=[ADB,'-s',select_device(ADB,args.serial)]
    args.out.mkdir(parents=True)
    deploy=args.out/'deploy'; deploy.mkdir()
    commands=[]
    clang=NDK/'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    source=Path(__file__).with_suffix('.cpp')
    command=[clang,'--target=aarch64-linux-android29','-std=c++17','-O2','-static-libstdc++','-I',TOOLS,
        source,'-lvulkan','-o',deploy/'bandwidth']
    run(command); commands.append(list(map(str,command)))
    for entry in ('initialize','stream_copy'):
        command=[compiler(),Path(__file__).with_suffix('.slang'),'-entry',entry,*FLAGS,
            '-target','spirv','-o',deploy/f'{entry}.spv','-reflection-json',deploy/f'{entry}.json']
        run(command); commands.append(list(map(str,command)))
        reflection=json.loads((deploy/f'{entry}.json').read_text())
        bindings={p['name']:p['binding'] for p in reflection['parameters']}
        if bindings['elementCount']['offset']!=0 or bindings['sourceData']['index']!=1 or bindings['destinationData']['index']!=2:
            raise ValueError('Unexpected shader binding layout')
    run([*adb,'shell','mkdir','-p',REMOTE]); run([*adb,'push',str(deploy)+'/.' ,REMOTE])
    summary=dict(schema=1,metric='effective logical read+write GB/s, decimal units; NOT hardware DRAM counter bandwidth',
        pattern='Three disjoint pairs by default, deterministic hashed uint4 input, full output verification after every block',
        commands=commands,files={p.name:sha(p) for p in deploy.iterdir()},runner_sha256=sha(source.with_name('runner.cpp')),
        native_source_sha256=sha(source),shader_source_sha256=sha(Path(__file__).with_suffix('.slang')),cases=[])
    for size in args.sizes_mib:
        dest=args.out/f'{size}MiB'; dest.mkdir()
        # Observe state without attempting clock/thermal controls or root access.
        (dest/'battery-before.txt').write_text(run([*adb,'shell','dumpsys','battery']),encoding='utf-8')
        log=run([*adb,'shell',f'cd {REMOTE} && chmod 755 bandwidth && ./bandwidth {size*1048576} {args.pairs} {args.frames} {args.warmup} {args.interval_ms}'],timeout=300)
        (dest/'run.log').write_text(log,encoding='utf-8')
        run([*adb,'pull',REMOTE+'/bandwidth.json',dest/'samples.json'])
        (dest/'battery-after.txt').write_text(run([*adb,'shell','dumpsys','battery']),encoding='utf-8')
        raw=json.loads((dest/'samples.json').read_text())
        modes={mode:bandwidth_stats(raw['payload_bytes_per_sample'],[v for b in raw['blocks'] if b['mode']==mode for v in b['gpu_ms']])
               for mode in ('compute_copy','transfer_copy')}
        case=dict(size_mib=size,working_set_bytes=raw['working_set_bytes'],payload_bytes_per_sample=raw['payload_bytes_per_sample'],
                  gpu=raw['gpu'],driver_version=raw['driver_version'],interval_ms=raw['interval_ms'],
                  performance_query_extensions=raw['performance_query_extensions'],modes=modes,
                  validated=all(b['mismatches']==0 for b in raw['blocks']),
                  blocks=[dict(mode=b['mode'],**bandwidth_stats(raw['payload_bytes_per_sample'],b['gpu_ms'])) for b in raw['blocks']])
        if not case['validated']: raise ValueError('Readback verification failed')
        summary['cases'].append(case)
        (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(f'{size} MiB x {args.pairs} pairs: compute {modes["compute_copy"]["median_gbps"]:.2f}, transfer {modes["transfer_copy"]["median_gbps"]:.2f} GB/s',flush=True)
    rows=['# Android effective streaming bandwidth','',summary['metric'],'',
          '| Working set MiB | Compute GB/s | Transfer GB/s | Validated |','|---:|---:|---:|---|']
    for c in summary['cases']:
        rows.append(f'| {c["working_set_bytes"]/1048576:.0f} | {c["modes"]["compute_copy"]["median_gbps"]:.2f} | {c["modes"]["transfer_copy"]["median_gbps"]:.2f} | {c["validated"]} |')
    rows += ['', 'Rates count source reads plus destination writes. Copy throughput counting only bytes copied is half this value. '
             'Large working sets reduce the likelihood of all data fitting in caches, but do not prove a cold-cache or pure DRAM measurement. '
             'Buffer transfer/compute paths are different from sampled-texture kernels. No physical memory counter or peak-bandwidth claim. '
             'Initialization, full readback validation and CPU waits are outside GPU intervals. Inspect per-block DVFS variation in summary.json.','']
    (args.out/'report.md').write_text('\n'.join(rows),encoding='utf-8')


if __name__=='__main__': main()
