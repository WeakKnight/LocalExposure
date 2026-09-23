"""Independently audit Vulkan timestamp units, clock correlation and dispatch scaling."""
import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from .benchmark import ADB, NDK, TOOLS, run, select_device
from .prepare import sha

REMOTE='/data/local/tmp/local-exposure-timer-audit'


def analyze(normal, calibrated):
    cases={c['name']:dict(gpu_median_ms=float(np.median(c['gpu_ms'])),
        cpu_median_ms=float(np.median(c['cpu_ms']))) for c in normal['cases']}
    clocks=[]
    for key in ('calibrated_clock','calibrated_clock_after'):
        clock=calibrated[key]
        if not clock['available']:
            return dict(verified=False,reason='Calibrated timestamp extension unavailable',cases=cases)
        s=clock['samples']; a,b=s[0],s[-1]
        host_ns=b['host_ns']-a['host_ns']
        device_ns=(b['device_ticks']-a['device_ticks'])*calibrated['timestamp_period_ns']
        if host_ns<=0 or device_ns<=0:
            raise ValueError('Nonmonotone calibrated clocks')
        clocks.append(dict(phase=key,gpu_over_host_ratio=device_ns/host_ns,
            max_deviation_ns=max(x['max_deviation_ns'] for x in s)))
    lo=calibrated['calibrated_clock']['samples'][-1]['device_ticks']
    hi=calibrated['calibrated_clock_after']['samples'][0]['device_ticks']
    ticks=[t for c in calibrated['cases'] for pair in c['ticks'] for t in pair]
    enclosed=all(lo<=t<=hi for t in ticks)
    finite=all(np.isfinite(c['gpu_ms']).all() and np.isfinite(c['cpu_ms']).all()
               and min(c['gpu_ms'])>=0 for r in (normal,calibrated) for c in r['cases'])
    cpu_encloses=all(g<=h+.02 for r in (normal,calibrated) for c in r['cases']
                     for g,h in zip(c['gpu_ms'],c['cpu_ms']))
    scale=cases['empty_32400_groups_x16']['gpu_median_ms']/cases['empty_32400_groups']['gpu_median_ms']
    checks=dict(finite=finite,clock_rate_agreement=all(abs(c['gpu_over_host_ratio']-1)<1e-4 for c in clocks),
        query_ticks_within_calibrated_bounds=enclosed,cpu_interval_encloses_gpu=cpu_encloses,
        zero_dispatch_median_below_10us=cases['timestamps_only']['gpu_median_ms']<.01,
        empty_repeat_scaling=14<scale<18)
    return dict(verified=all(checks.values()),checks=checks,clock_calibrations=clocks,
        empty_x16_ratio=scale,cases=cases,
        limits='Validates this driver and these measurements, not universal GPU profiler correctness. Dispatch scaling is empirical; clocks/power remain uncontrolled.')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle',required=True,type=Path,help='A diagnose.py empty_probe case directory (8x8 groups)')
    ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--serial')
    args=ap.parse_args()
    if args.out.exists(): raise ValueError('Choose a new audit directory')
    manifest=json.loads((args.bundle/'manifest.json').read_text())
    if [p['entry'] for p in manifest['passes']]!=['empty_probe','tonemap_baseline']:
        raise ValueError('Expected an empty + tonemap diagnostic bundle')
    if any(p.get('group_size',[8,8,1])!=[8,8,1] for p in manifest['passes']):
        raise ValueError('This fixed-shape audit requires 8x8 shaders')
    if (manifest['width'],manifest['height'])!=(1920,1080):
        raise ValueError('This audit currently fixes the tonemap workload to 1080p')
    adb=[ADB,'-s',select_device(ADB,args.serial)]
    args.out.mkdir(parents=True)
    clang=NDK/'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    source=Path(__file__).with_suffix('.cpp')
    command=[clang,'--target=aarch64-linux-android29','-std=c++17','-O2','-static-libstdc++','-I',TOOLS,
        source,'-lvulkan','-o',args.out/'timer-audit']
    run(command)
    deploy=args.out/'deploy'; deploy.mkdir()
    files=['manifest.json']+[p['entry']+'.spv' for p in manifest['passes']]+[p['uniform'] for p in manifest['passes']]
    files += [r['file'] for r in manifest['resources'] if 'file' in r]
    for name in set(files): shutil.copy2(args.bundle/name,deploy/name)
    shutil.copy2(args.out/'timer-audit',deploy/'timer-audit')
    run([*adb,'shell','mkdir','-p',REMOTE]); run([*adb,'push',str(deploy)+'/.' ,REMOTE])
    for mode in ('normal','calibrated'):
        result=run([*adb,'shell',f'cd {REMOTE} && chmod 755 timer-audit && ./timer-audit {mode}'])
        (args.out/f'{mode}.log').write_text(result)
        run([*adb,'pull',REMOTE+'/timer-audit.json',args.out/f'{mode}.json'])
    summary=analyze(*[json.loads((args.out/f'{mode}.json').read_text()) for mode in ('normal','calibrated')])
    summary['provenance']=dict(command=list(map(str,command)),compiler_sha256=sha(clang),
        source_sha256=sha(source),runner_sha256=sha(source.with_name('runner.cpp')),
        bundle_sha256=sha(args.bundle/'manifest.json'),binary_sha256=sha(args.out/'timer-audit'))
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not summary['verified']: raise RuntimeError('Timer audit did not verify all checks')


if __name__=='__main__': main()
