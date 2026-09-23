"""Build, deploy, measure and validate production Fusion on an attached Android GPU.

Run from the repository root: python -m tools.profiling.android.benchmark --bootstrap
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import zipfile

import numpy as np

from .prepare import ROOT, prepare, sha

TOOLS = ROOT / '.tools/mobile/android'
REMOTE = '/data/local/tmp/local-exposure-benchmark'
NDK = TOOLS / 'android-ndk-r30'
ADB = TOOLS / 'platform-tools/adb.exe'
JSON_SHA = 'aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63'


def run(args, **kwargs):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=kwargs.pop('timeout', 180), **kwargs)
    if p.returncode:
        raise RuntimeError(f'{args}\n{p.stdout}\n{p.stderr}')
    return p.stdout


def download(url, path, checksum=None, algorithm='sha256'):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix+'.partial')
        print(f'Downloading {url}', flush=True)
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(path)
    if checksum and hashlib.new(algorithm, path.read_bytes()).hexdigest() != checksum:
        raise RuntimeError(f'Checksum mismatch: {path}')


def bootstrap():
    if not ADB.exists():
        archive = TOOLS/'platform-tools-windows.zip'
        download('https://dl.google.com/android/repository/platform-tools-latest-windows.zip', archive)
        with zipfile.ZipFile(archive) as z:
            z.extractall(TOOLS)
    if not (NDK/'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe').exists():
        archive = TOOLS/'android-ndk-r30-windows.zip'
        download('https://dl.google.com/android/repository/android-ndk-r30-windows.zip', archive,
                 '9bf167a1985fa7d4a036186b78f702eab9179408', 'sha1')
        with zipfile.ZipFile(archive) as z:
            z.extractall(TOOLS)
    download('https://raw.githubusercontent.com/nlohmann/json/v3.12.0/single_include/nlohmann/json.hpp',
             TOOLS/'json.hpp', JSON_SHA)
    from tools.profiling.mobile_profile import compiler
    compiler(download=True)


def build(out):
    clang = NDK/'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    if not clang.exists() or not (TOOLS/'json.hpp').exists():
        raise RuntimeError('Missing Android toolchain. Run with --bootstrap.')
    if sha(TOOLS/'json.hpp') != JSON_SHA:
        raise RuntimeError('JSON dependency hash mismatch')
    command = [clang, '--target=aarch64-linux-android29', '-std=c++17', '-O2', '-static-libstdc++',
               '-I', TOOLS, Path(__file__).with_name('runner.cpp'), '-lvulkan', '-o', out/'le-benchmark']
    run(command)
    return dict(command=list(map(str,command)), compiler=run([clang,'--version']),
                compiler_sha256=sha(clang), runner_sha256=sha(out/'le-benchmark'),
                source_sha256=sha(Path(__file__).with_name('runner.cpp')), json_sha256=JSON_SHA)


def select_device(adb, serial=None):
    # Vendor desktop utilities can restart an older ADB server. Let it settle,
    # but never automatically choose among multiple phones.
    for attempt in range(3):
        output = run([adb,'devices','-l'])
        devices = [line.split() for line in output.splitlines() if len(line.split())>=2
                   and line.split()[1] in ('device','offline','unauthorized')]
        if devices:
            break
        if attempt<2:
            time.sleep(1)
    if serial:
        matches = [d for d in devices if d[0]==serial and d[1]=='device']
    else:
        matches = [d for d in devices if d[1]=='device']
    if len(matches)!=1:
        raise RuntimeError('Need exactly one authorized device; use --serial when multiple are attached.\n'+output)
    return matches[0][0]


def stats(values):
    a = np.asarray(values, dtype=float)
    if not a.size or not np.isfinite(a).all() or np.any(a<=0):
        raise ValueError('Invalid GPU timestamp samples')
    return dict(count=a.size, median=float(np.median(a)), p95=float(np.percentile(a,95)),
                min=float(a.min()), max=float(a.max()), mean=float(a.mean()))


def validate(bundle, manifest):
    report = {}
    for r in manifest['resources']:
        if not r['dump']:
            continue
        dtype = np.float16 if r['format_name'] in ('r16_float','rgba16_float') else np.float32
        a = np.fromfile(bundle/(r['name']+'.reference.bin'),dtype).astype(float)
        b = np.fromfile(bundle/(r['name']+'.device.bin'),dtype).astype(float)
        expected = r['width']*r['height']*r['bpp']//np.dtype(dtype).itemsize
        if a.size != expected or b.size != expected:
            raise ValueError(f'Invalid readback size for {r["name"]}')
        finite = bool(np.isfinite(a).all() and np.isfinite(b).all())
        error = abs(a-b)
        report[r['name']] = dict(finite=finite, max_abs=float(error.max()),
            rmse=float(np.sqrt(np.mean(error**2))), p99_abs=float(np.percentile(error,99)))
        if r['name']=='exposure' and finite and (a>0).all() and (b>0).all():
            ev = np.log2(b/a)
            report[r['name']].update(max_ev=float(abs(ev).max()), rmse_ev=float(np.sqrt(np.mean(ev**2))))
    # Cross-vendor transcendental/half rounding need tolerances, not bit identity.
    # Guard rails are explicit and fixed before measurements; report actual errors.
    final=report['final']; exposure=report['exposure']
    passed = all(r['finite'] for r in report.values()) and final['max_abs']<=.01 and final['rmse']<=.001
    passed = passed and exposure.get('max_ev',float('inf'))<=.05 and exposure.get('rmse_ev',float('inf'))<=.01
    desktop_passed=passed
    device_report={}
    for r in manifest['resources']:
        if r['dump']:
            actual=(bundle/(r['name']+'.device.bin')).read_bytes()
            expected=(bundle/(r['name']+'.phone-reference.bin')).read_bytes()
            device_report[r['name']]=dict(bitwise_equal=actual==expected)
    passed=all(x['bitwise_equal'] for x in device_report.values()) and all(r['finite'] for r in report.values())
    return dict(passed=passed, same_device=device_report, desktop_within_thresholds=desktop_passed, stages=report,
                thresholds=dict(final_max_abs=.01,final_rmse=.001,exposure_max_ev=.05,exposure_rmse_ev=.01),
                note='Acceptance: bitwise agreement with the viewer runtime on the same phone, all stages finite. Desktop thresholds are a separate portability check; inverse-curve sensitivity can amplify vendor sampling differences. Mip-0 readback of every stage.')


def summarize(raw):
    totals = {kind:stats([x for b in raw['blocks'] if b['kind']==kind for x in b['gpu_ms']]) for kind in ('fusion','baseline')}
    per_pass = {}
    diagnostic = np.array(raw['diagnostic_ms'])
    if diagnostic.shape[1] != len(raw['passes'])+1:
        raise ValueError('Diagnostic query count mismatch')
    for i,name in enumerate(raw['passes']):
        per_pass[name]=stats(diagnostic[:,i+1])
    return dict(totals=totals, per_pass=per_pass,
        median_difference_ms=totals['fusion']['median']-totals['baseline']['median'],
        blocks=[dict(round=b['round'], kind=b['kind'], **stats(b['gpu_ms'])) for b in raw['blocks']],
        warning='Diagnostic pass timings include barriers and timestamp serialization. Do not sum them as the production total. Baseline subtraction is descriptive: DVFS and workload differ.')


def report_markdown(out, meta, summary, validation):
    raw = meta['gpu']
    text = [f'# Android production benchmark: {raw["device"]}', '',
        f'Device: `{meta["properties"].get("ro.product.model")}` / `{meta["properties"].get("ro.soc.model")}`. '
        f'Input: {meta["width"]} × {meta["height"]}; Fusion: ceil(width/4) × ceil(height/4).', '',
        'GPU timestamps only. Every frame executes all production passes. No viewer, comparison output, EV debug output, '
        'presentation, calibration, input upload, compilation or readback is timed.', '',
        '| Whole-chain measurement | Median ms | P95 ms | Samples |','|---|---:|---:|---:|']
    for kind,s in summary['totals'].items():
        text.append(f'| {kind} | {s["median"]:.4f} | {s["p95"]:.4f} | {s["count"]} |')
    text += ['',f'Descriptive difference of medians: {summary["median_difference_ms"]:.4f} ms. '
             'Fusion includes the final tone operator; baseline runs the same tone operator alone.', '',
             '## Per-pass diagnostics', '',
             '| Pass | Median ms | P95 ms |','|---|---:|---:|']
    for name,s in sorted(summary['per_pass'].items(),key=lambda item:-item[1]['median']):
        text.append(f'| {name} | {s["median"]:.4f} | {s["p95"]:.4f} |')
    text += ['',summary['warning'],'','## Validation and limits','',
        f'Same-phone viewer-reference validation: **{"PASS" if validation["passed"] else "FAIL"}** (bitwise). '
        f'Desktop portability thresholds: **{"PASS" if validation["desktop_within_thresholds"] else "WARNING"}**. '
        f'Desktop final max absolute error {validation["stages"]["final"]["max_abs"]:.6g}; '
        f'RMSE {validation["stages"]["final"]["rmse"]:.6g}. See validation.json for exposure EV errors and thresholds.', '',
        'One static EXR, repeatedly recomputed; cached input data and resident resources. Headless compute with explicit '
        'pass barriers and GENERAL image layouts. No renderer contention, presentation, or sustained-gameplay claim. '
        'Stock device clocks and power policy; USB charging state is recorded. Results belong to the detected GPU, not Adreno 730.', '',
        'Raw GPU samples: `timings.json`. Environment/toolchain: `metadata.json`. '
        'Shader/input hashes, calibration and graph: `bundle/manifest.json`. Thermal snapshots: `telemetry.jsonl`.','']
    (out/'report.md').write_text('\n'.join(text),encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bootstrap',action='store_true')
    ap.add_argument('--serial')
    ap.add_argument('--adb',type=Path,default=ADB)
    ap.add_argument('--width',type=int,default=1920)
    ap.add_argument('--height',type=int,default=1080)
    ap.add_argument('--image',type=Path,default=ROOT/'Assets/veranda_4k.exr')
    ap.add_argument('--ev',type=float,default=0.)
    ap.add_argument('--warmup',type=int,default=60)
    ap.add_argument('--frames',type=int,default=120)
    ap.add_argument('--rounds',type=int,default=3)
    ap.add_argument('--interval-ms',type=int,default=16)
    ap.add_argument('--out',type=Path)
    ap.add_argument('--require-desktop-match',action='store_true',help='Also fail when cross-device portability thresholds are exceeded')
    args = ap.parse_args()
    if min(args.width,args.height,args.frames,args.rounds)<1 or min(args.warmup,args.interval_ms)<0 or not np.isfinite(args.ev):
        ap.error('Invalid dimensions, frame counts or exposure')
    if args.bootstrap:
        bootstrap()
    serial=select_device(args.adb,args.serial)
    adb=[args.adb,'-s',serial]
    # Only use our fixed remote directory. Serial/path arguments never enter shell strings.
    out=(args.out or ROOT/'outputs/android'/datetime.now().strftime('%Y%m%d-%H%M%S')).resolve()
    if (out/'metadata.json').exists():
        raise RuntimeError('Output directory already contains a run; choose a new --out to preserve it')
    out.mkdir(parents=True,exist_ok=True)
    properties={key:run([*adb,'shell','getprop',key]).strip() for key in
        ('ro.product.model','ro.soc.model','ro.board.platform','ro.build.version.release','ro.build.fingerprint','ro.product.cpu.abi')}
    print(properties,flush=True)
    if properties['ro.product.cpu.abi']!='arm64-v8a':
        raise RuntimeError('Runner requires arm64-v8a')
    toolchain=build(out)
    manifest=prepare(out/'bundle',args.width,args.height,args.image,args.ev)
    run([*adb,'shell','mkdir','-p',REMOTE])
    # Upload only inputs and programs, never desktop reference readbacks.
    deploy=out/'deploy'; deploy.mkdir(exist_ok=True)
    for name in ['manifest.json','le-benchmark'] + [p.name for p in (out/'bundle').iterdir()
            if p.suffix=='.spv' or (p.suffix=='.bin' and not p.name.endswith(('.reference.bin','.device.bin')))]:
        src=out/name if name=='le-benchmark' else out/'bundle'/name
        shutil.copy2(src,deploy/name)
    print(run([*adb,'push',str(deploy)+'/.' ,REMOTE]),flush=True)
    metadata=dict(schema=1,started_utc=datetime.now(timezone.utc).isoformat(),serial=serial,properties=properties,
                  width=args.width,height=args.height,toolchain=toolchain,adb_version=run([args.adb,'version']),
                  adb_sha256=sha(args.adb),git_head=run(['git','rev-parse','HEAD'],cwd=ROOT).strip(),
                  git_status=run(['git','status','--short'],cwd=ROOT),manifest_sha256=sha(out/'bundle/manifest.json'))
    (out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    shell=f'cd {REMOTE} && chmod 755 le-benchmark && ./le-benchmark {args.warmup} {args.frames} {args.rounds} {args.interval_ms}'
    started=time.monotonic()
    telemetry_command='dumpsys battery; dumpsys thermalservice; cat /sys/class/kgsl/kgsl-3d0/gpuclk; cat /sys/class/kgsl/kgsl-3d0/devfreq/cur_freq'
    with (out/'runner.log').open('w') as log, (out/'telemetry.jsonl').open('w') as telemetry:
        process=subprocess.Popen([str(x) for x in [*adb,'shell',shell]],stdout=log,stderr=subprocess.STDOUT)
        try:
            while True:
                snapshot=subprocess.run([str(x) for x in [*adb,'shell',telemetry_command]],capture_output=True,text=True,timeout=20)
                telemetry.write(json.dumps(dict(elapsed_s=time.monotonic()-started,stdout=snapshot.stdout,stderr=snapshot.stderr))+'\n'); telemetry.flush()
                try:
                    code=process.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic()-started>max(300,(args.warmup+args.frames)*(2*args.rounds+1)*max(args.interval_ms,10)/1000*3):
                        raise RuntimeError('Device run timed out')
            if code:
                raise RuntimeError((out/'runner.log').read_text())
        finally:
            if process.poll() is None:
                process.terminate()
                # Fixed process name belongs exclusively to this benchmark.
                subprocess.run([str(x) for x in [*adb,'shell','pkill','-x','le-benchmark']],capture_output=True,timeout=10)
    run([*adb,'pull',REMOTE+'/timings.json',out/'timings.json'])
    for r in manifest['resources']:
        if r['dump']:
            name=r['name']+'.device.bin'
            run([*adb,'pull',REMOTE+'/'+name,out/'bundle'/name])
    # Separate process, after timing: reference-only allocations and work cannot
    # contaminate the measured resource footprint or GPU timestamps.
    reference_log=run([*adb,'shell',f'cd {REMOTE} && ./le-benchmark 0 1 1 0 verify'])
    (out/'reference.log').write_text(reference_log)
    for r in manifest['resources']:
        if r['dump']:
            run([*adb,'pull',REMOTE+'/'+r['name']+'.device.bin',out/'bundle'/(r['name']+'.phone-reference.bin')])
    raw=json.loads((out/'timings.json').read_text())
    validation=validate(out/'bundle',manifest)
    summary=summarize(raw)
    metadata['gpu']={k:v for k,v in raw.items() if k not in ('blocks','diagnostic_ms')}
    for name,value in [('metadata',metadata),('validation',validation),('summary',summary)]:
        (out/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
    report_markdown(out,metadata,summary,validation)
    print(json.dumps(summary['totals'],indent=2),flush=True)
    print(f'Validation: {validation["passed"]}; report: {out/"report.md"}',flush=True)
    if not validation['passed'] or (args.require_desktop_match and not validation['desktop_within_thresholds']):
        raise RuntimeError('Numerical validation failed; timings are diagnostic only')


if __name__=='__main__':
    main()
