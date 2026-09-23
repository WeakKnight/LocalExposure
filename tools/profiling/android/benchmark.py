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
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=kwargs.pop('timeout', 180), **kwargs)
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
        dtype = np.int16 if r['format_name']=='rgba16_snorm' else np.uint16 if r['format_name'] in ('r16_unorm','rg16_unorm') else (np.uint8 if r['format_name']=='rgba8_srgb' else (np.float16 if r['format_name'] in ('r16_float','rg16_float','rgba16_float') else np.float32))
        a = np.fromfile(bundle/(r['name']+'.reference.bin'),dtype).astype(float)
        b = np.fromfile(bundle/(r['name']+'.device.bin'),dtype).astype(float)
        expected = r['width']*r['height']*r['bpp']//np.dtype(dtype).itemsize
        if a.size != expected or b.size != expected:
            raise ValueError(f'Invalid readback size for {r["name"]}')
        if dtype==np.uint8: a,b=a/255.,b/255.
        if dtype==np.int16: a,b=np.maximum(a/32767.,-1),np.maximum(b/32767.,-1)
        if dtype==np.uint16: a,b=a/65535.,b/65535.
        finite = bool(np.isfinite(a).all() and np.isfinite(b).all())
        error = abs(a-b)
        report[r['name']] = dict(finite=finite, max_abs=float(error.max()),
            rmse=float(np.sqrt(np.mean(error**2))), p99_abs=float(np.percentile(error,99)))
        if r['name']=='exposure' and finite and (a>0).all() and (b>0).all():
            ev = np.log2(b/a)
            report[r['name']].update(max_ev=float(abs(ev).max()), rmse_ev=float(np.sqrt(np.mean(ev**2))))
    # Cross-vendor transcendental/half rounding need tolerances, not bit identity.
    # Guard rails are explicit and fixed before measurements; report actual errors.
    final=report['final']; exposure=report.get('exposure')
    if exposure is None and not manifest.get('config',{}).get('fused_guided'):
        raise ValueError('Missing exposure validation for an unfused graph')
    passed = all(r['finite'] for r in report.values()) and final['max_abs']<=.01 and final['rmse']<=.001
    if exposure is not None:
        passed = passed and exposure.get('max_ev',float('inf'))<=.05 and exposure.get('rmse_ev',float('inf'))<=.01
    desktop_passed=passed
    device_report={}
    for r in manifest['resources']:
        if r['dump']:
            actual=(bundle/(r['name']+'.device.bin')).read_bytes()
            expected=(bundle/(r['name']+'.phone-reference.bin')).read_bytes()
            equal=actual==expected
            if r['format_name']=='rgba8_srgb':
                error=int(abs(np.frombuffer(actual,np.uint8).astype(int)-np.frombuffer(expected,np.uint8).astype(int)).max())
                device_report[r['name']]=dict(bitwise_equal=equal,max_unorm_steps=error,accepted=error<=1)
            else:
                device_report[r['name']]=dict(bitwise_equal=equal,accepted=equal)
    quality=None
    if manifest.get('config',{}).get('variant','lossless')!='lossless':
        from .quality import image_quality
        final_resource=next(r for r in manifest['resources'] if r['name']=='final')
        if final_resource['format_name']!='rgba8_srgb': raise ValueError('Approximate quality gate requires sRGB8 output')
        shape=(final_resource['height'],final_resource['width'],4)
        actual=np.fromfile(bundle/'final.device.bin',np.uint8).reshape(shape)
        expected=np.fromfile(bundle/'final.phone-reference.bin',np.uint8).reshape(shape)
        quality=image_quality(expected,actual)
        for name,r in device_report.items():
            r['accepted']=quality['accepted'] if name=='final' else (r['bitwise_equal'] if manifest['config'].get('variant_settings',{}).get('unfused_control') else report[name]['finite'])
            r['acceptance_mode']='approximate; image quality gate and finite intermediates'
    passed=all(x['accepted'] for x in device_report.values()) and all(r['finite'] for r in report.values())
    return dict(passed=passed, quality=quality, same_device=device_report, desktop_within_thresholds=desktop_passed, stages=report,
                omitted_checks=['exposure EV portability (intermediate removed by fusion)'] if exposure is None else [],
                thresholds=dict(final_max_abs=.01,final_rmse=.001,exposure_max_ev=.05,exposure_rmse_ev=.01),
                note='Acceptance: finite stages; same-phone core stages bitwise, RGBA16F final bitwise, sRGB8 final at most one UNORM step versus viewer compute + hardware-sRGB reference. Desktop thresholds are a separate portability check. Mip-0 readback of every stage.')


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
    if 'tonemap_bandwidth' in summary:
        bw=summary['tonemap_bandwidth']
        text += ['',f'HDR input `{bw["input_format"]}`, output `{bw["output_format"]}`. '
            f'Tonemap nominal read + write payload: **{bw["bytes_per_frame"]/1e6:.4f} MB/frame**; '
            f'effective payload throughput: **{bw["effective_gbps"]:.2f} GB/s**. '
            'This is not measured DRAM traffic.']
        if bw['target_fps']:
            text.append(f'At {bw["target_fps"]:g} FPS: **{bw["average_gbps"]:.4f} GB/s** nominal average tonemap traffic. Fusion intermediate traffic is additional.')
        if bw.get('srgb_encoding')=='shader':
            text.append('The final passes use compute and explicit sRGB encoding through a compatible UNORM storage view of the actual sRGB image. Swapchain acquisition/presentation are excluded; renderer integration requires a compatible storage-capable image/view.')
        elif bw['output_format']=='rgba8_srgb':
            text.append('The final passes use a fullscreen fragment shader and a real VK_FORMAT_R8G8B8A8_SRGB color attachment; hardware performs sRGB encoding. Offscreen attachment store is included; swapchain acquisition and presentation are excluded.')
    if 'local_exposure_traffic' in summary:
        traffic=summary['local_exposure_traffic']
        text += ['',f"Local Exposure incremental texture sweep model: **{traffic['incremental_sweep_bytes']/1e6:.4f} MB/frame**. See [per-pass traffic and assumptions](local-exposure-traffic.md). This is an accounting model, not measured DRAM traffic."]
    if validation.get('quality'):
        text += ['', 'Approximate candidate image quality versus the full unfused phone reference: `'+json.dumps(validation['quality'])+'`.']
    text += ['',f'Descriptive difference of medians: {summary["median_difference_ms"]:.4f} ms. '
             'Fusion includes the final tone operator; baseline runs the same tone operator alone.', '',
             '## Per-pass diagnostics', '',
             '| Pass | Median ms | P95 ms |','|---|---:|---:|']
    for name,s in sorted(summary['per_pass'].items(),key=lambda item:-item[1]['median']):
        text.append(f'| {name} | {s["median"]:.4f} | {s["p95"]:.4f} |')
    check_mode='approximate image gate; retained intermediate values must be finite' if validation.get('quality') else 'core stages bitwise; sRGB8 final allows one UNORM step'
    text += ['',summary['warning'],'','## Validation and limits','',
        f'Same-phone viewer-reference validation: **{"PASS" if validation["passed"] else "FAIL"}** ({check_mode}). '
        f'Desktop portability thresholds: **{"PASS" if validation["desktop_within_thresholds"] else "WARNING"}**. '
        f'Desktop final max absolute error {validation["stages"]["final"]["max_abs"]:.6g}; '
        f'RMSE {validation["stages"]["final"]["rmse"]:.6g}. See validation.json for retained-stage errors and thresholds.', '',
        'One static EXR, repeatedly recomputed; cached input data and resident resources. Headless Vulkan with explicit '
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
    pacing=ap.add_mutually_exclusive_group()
    pacing.add_argument('--interval-ms',type=float)
    pacing.add_argument('--fps',type=float,help='Nominal submission cadence and average bandwidth accounting, e.g. 45')
    ap.add_argument('--source-format',choices=['rgba32_float','r11g11b10_float'],default='rgba32_float')
    ap.add_argument('--output-format',choices=['rgba16_float','rgba8_srgb'],default='rgba16_float',help='rgba8_srgb uses a real offscreen sRGB color attachment and fragment shader')
    from .quality import VARIANTS
    ap.add_argument('--variant',choices=list(VARIANTS),default='lossless',help='Approximate candidates imply fused guided and require sRGB output')
    ap.add_argument('--fused-guided',action='store_true',help='Also fuse finest reconstruction, inverse and both guided stages; implies --compact')
    ap.add_argument('--compact',action='store_true',help='Validate production pass fusion and compact FP32 luminance/guide storage against the unfused graph')
    ap.add_argument('--out',type=Path)
    ap.add_argument('--require-desktop-match',action='store_true',help='Also fail when cross-device portability thresholds are exceeded')
    args = ap.parse_args()
    if VARIANTS[args.variant].get('unfused_control') and (args.compact or args.fused_guided):
        ap.error('compute-control must retain the unfused graph')
    args.fused_guided |= args.variant!='lossless' and not VARIANTS[args.variant].get('unfused_control')
    args.compact |= args.fused_guided
    if args.variant!='lossless' and args.output_format!='rgba8_srgb': ap.error('Variants require --output-format rgba8_srgb')
    if args.fps is not None and (not np.isfinite(args.fps) or args.fps<=0):
        ap.error('FPS must be finite and positive')
    args.interval_ms=1000/args.fps if args.fps else (16. if args.interval_ms is None else args.interval_ms)
    if not np.isfinite(args.interval_ms): ap.error('Invalid pacing')
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
    # A failed foreground-harness transport must not leave our own GPU work
    # running concurrently with a new headless measurement.
    run([*adb,'shell','am','force-stop','org.localexposure.benchmark'])
    properties={key:run([*adb,'shell','getprop',key]).strip() for key in
        ('ro.product.model','ro.soc.model','ro.board.platform','ro.build.version.release','ro.build.fingerprint','ro.product.cpu.abi')}
    print(properties,flush=True)
    if properties['ro.product.cpu.abi']!='arm64-v8a':
        raise RuntimeError('Runner requires arm64-v8a')
    toolchain=build(out)
    manifest=prepare(out/'bundle',args.width,args.height,args.image,args.ev,args.source_format,args.output_format,args.compact,args.fused_guided,args.variant)
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
                snapshot=subprocess.run([str(x) for x in [*adb,'shell',telemetry_command]],capture_output=True,
                                        text=True,encoding='utf-8',errors='replace',timeout=20)
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
    if manifest['config'].get('variant_settings',{}).get('packed_residual'):
        run([*adb,'pull',REMOTE+'/weights.device.bin',out/'bundle/weights.phone-reference.bin'])
    if manifest['config'].get('compact') and any(r['name']=='luminance' and r['dump'] for r in manifest['resources']):
        # Decode the legacy graph reference into the lossless production layout.
        lum=np.fromfile(out/'bundle/luminance.phone-reference.bin',np.float32).reshape(-1,4)
        weights=np.fromfile(out/'bundle/weights.phone-reference.bin',np.float32).reshape(-1,4)
        lum[:,3]=weights[:,0]
        lum.tofile(out/'bundle/luminance.phone-reference.bin')
        weights[:,1:3].copy().tofile(out/'bundle/weights.phone-reference.bin')
    if manifest['config'].get('variant_settings',{}).get('half_aux'):
        for name in ('weights','averaged'):
            if name=='weights' and (manifest['config'].get('variant_settings',{}).get('weight_unorm') or manifest['config'].get('variant_settings',{}).get('residual_pyramid')):continue
            file=out/'bundle'/f'{name}.phone-reference.bin'
            if file.exists(): np.fromfile(file,np.float32).astype(np.float16).tofile(file)
    if manifest['config'].get('variant_settings',{}).get('residual_pyramid'):
        lum=np.fromfile(out/'bundle/luminance.phone-reference.bin',np.float32).reshape(-1,4)
        weights=np.fromfile(out/'bundle/weights.phone-reference.bin',np.float32).reshape(-1,2)
        if manifest['config'].get('variant_settings',{}).get('packed_residual'):
            np.stack([(lum[:,0]-lum[:,1])*manifest['config']['variant_settings'].get('residual_scale',1),(lum[:,2]-lum[:,1])*manifest['config']['variant_settings'].get('residual_scale',1),lum[:,3]-manifest['config']['variant_settings'].get('packed_weight_bias',0),weights[:,1]-manifest['config']['variant_settings'].get('packed_weight_bias',0)],axis=-1).astype(np.float16).tofile(out/'bundle/luminance.phone-reference.bin')
        else:np.stack([(lum[:,0]-lum[:,1])*manifest['config']['variant_settings'].get('residual_scale',1),(lum[:,2]-lum[:,1])*manifest['config']['variant_settings'].get('residual_scale',1)],axis=-1).astype(np.float32 if manifest['config']['variant_settings'].get('residual_float') else np.float16).tofile(out/'bundle/luminance.phone-reference.bin')
        np.rint(np.clip(np.stack([lum[:,3],weights[:,1]],axis=-1),0,1)*65535).astype(np.uint16).tofile(out/'bundle/weights.phone-reference.bin')
        if manifest['config'].get('variant_settings',{}).get('packed_snorm'):
            packed=np.stack([lum[:,0]-lum[:,1],lum[:,2]-lum[:,1],lum[:,3],weights[:,1]],axis=-1)
            np.rint(np.clip(packed,-1,1)*32767).astype(np.int16).tofile(out/'bundle/luminance.phone-reference.bin')
    elif manifest['config'].get('variant_settings',{}).get('weight_unorm'):
        file=out/'bundle/weights.phone-reference.bin'
        np.rint(np.clip(np.fromfile(file,np.float32).reshape(-1,2)[:,0],0,1)*65535).astype(np.uint16).tofile(file)
    elif manifest['config'].get('variant_settings',{}).get('single_weight'):
        file=out/'bundle/weights.phone-reference.bin'
        np.fromfile(file,np.float16).reshape(-1,2)[:,0].copy().tofile(file)
    raw=json.loads((out/'timings.json').read_text())
    validation=validate(out/'bundle',manifest)
    if args.variant!='lossless':
        from .quality import save_comparison
        save_comparison(out/'bundle',manifest)
    summary=summarize(raw)
    from tools.profiling.android.traffic import estimate, markdown
    summary['local_exposure_traffic']=estimate(manifest, args.fps or (1000/args.interval_ms if args.interval_ms else 0))
    (out/'local-exposure-traffic.md').write_text(markdown(summary['local_exposure_traffic']),encoding='utf-8')
    source=next(r for r in manifest['resources'] if r['name']=='source')
    target=next(r for r in manifest['resources'] if r['name']=='baseline')
    payload=args.width*args.height*(source['bpp']+target['bpp'])
    summary['tonemap_bandwidth']=dict(srgb_encoding='shader' if manifest['config'].get('variant_settings',{}).get('compute_srgb') else 'attachment',input_format=source['format_name'],output_format=target['format_name'],
        bytes_per_frame=payload,effective_gbps=payload/(summary['totals']['baseline']['median']*1e6),
        target_fps=args.fps,average_gbps=payload*args.fps/1e9 if args.fps else None,
        metric='Nominal texel payload, reads+writes; not hardware DRAM counters; excludes Fusion intermediates')
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
