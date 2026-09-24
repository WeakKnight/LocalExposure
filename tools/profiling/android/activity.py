"""Package and run a foreground NativeActivity benchmark with actual presentation."""
import argparse,json,shutil,subprocess,time,zipfile,copy
from datetime import datetime, timezone
import numpy as np
from pathlib import Path
from .benchmark import ADB,NDK,TOOLS,run,select_device,stats
from .prepare import sha
PACKAGE='org.localexposure.benchmark'
active_adb=None

def sample_stats(values):
    a=np.asarray(values)
    if a.size==0 or not np.isfinite(a).all() or (a<0).any():raise ValueError("Invalid timing samples")
    return dict(count=len(a),median=float(np.median(a)),p95=float(np.percentile(a,95)),min=float(a.min()),max=float(a.max()),mean=float(a.mean()))

def main():
    global active_adb
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('bundle',type=Path);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--bootstrap',action='store_true',help='Install pinned Android and APK packaging tools locally')
    ap.add_argument('--serial',help='Authorized Android device serial')
    ap.add_argument('--custom-driver',type=Path,help='Opt-in extracted AdrenoTools driver directory (process-local)')
    ap.add_argument('--tile-memory',choices=['guided','averaged'],help='Opt-in tile residency; requires supported driver')
    ap.add_argument('--frames',type=int,default=90);ap.add_argument('--warmup',type=int,default=30)
    ap.add_argument('--hdr-producer',action='store_true')
    ap.add_argument('--joint-submission',action='store_true',help='Include the common graphics producer in one submission and both headline timestamp intervals')
    ap.add_argument('--dedicated-compute',action='store_true')
    ap.add_argument('--separate-queue',action='store_true')
    ap.add_argument('--graphics-draws',type=int,default=1);ap.add_argument('--fps',type=float,default=45)
    ap.add_argument('--rounds',type=int,default=3);ap.add_argument('--no-graphics-context',action='store_true')
    args=ap.parse_args()
    from . import activity_toolchain
    if args.bootstrap:
        from .benchmark import bootstrap
        bootstrap();activity_toolchain.bootstrap()
    sdk,platform,java=activity_toolchain.paths()
    if min(args.frames,args.rounds,args.graphics_draws,args.fps)<=0 or args.warmup<0:ap.error('Invalid measurement counts/cadence')
    if (args.separate_queue or args.dedicated_compute or args.hdr_producer) and args.no_graphics_context:ap.error('Requested mode requires graphics context')
    if args.separate_queue and args.dedicated_compute:ap.error('Choose one queue configuration')
    if args.joint_submission and (args.separate_queue or args.dedicated_compute or args.no_graphics_context):ap.error('Joint submission requires one graphics/compute queue and a graphics producer')
    if args.tile_memory and (not args.joint_submission or not args.hdr_producer or args.separate_queue or args.dedicated_compute):ap.error('Tile test requires single-queue joint HDR producer')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    bundle=args.bundle.resolve();manifest=json.loads((bundle/'manifest.json').read_text())
    if args.tile_memory:
        manifest['tile_resources']=['guide_ev','averaged'] if args.tile_memory=='guided' else ['averaged']
    if args.dedicated_compute and any('attachment' in p for p in manifest['passes']):raise ValueError('Dedicated mode requires compute-only production passes')
    original=manifest.get('unfused_passes',manifest['passes'])
    if args.hdr_producer:
        context=copy.deepcopy(manifest['reference_resolve'])
        context.update(label='graphics_hdr_producer',attachment='source',attachment_format=122,baseline=True)
        for d in context['descriptors']:
            if d.get('name')=='fullSource':d['resource']='immutable_source'
        source=next(r for r in manifest['resources'] if r['name']=='source')
        if source['format']!=122:raise ValueError('HDR producer requires R11G11B10 source')
        immutable=copy.deepcopy(source);immutable.update(name='immutable_source',dump=False,sampled_only=True)
        manifest['resources'].append(immutable)
        source.update(attachment=True,sampled_attachment=True);source.pop('sampled_only',None)
    else:
        context=copy.deepcopy(next(p for p in original if p['entry']=='baseline_fragment'))
        context.update(label='graphics_context',attachment='context_color',baseline=True)
        manifest['resources'].append(dict(name='context_color',width=manifest['width'],height=manifest['height'],levels=1,format=43,format_name='rgba8_srgb',bpp=4,one_d=False,dump=False,attachment=True))
    manifest['passes'].append(context)
    settings=dict(frames=args.frames,warmup=args.warmup,rounds=args.rounds,graphics_context=not args.no_graphics_context,hdr_producer=args.hdr_producer,joint_submission=args.joint_submission,separate_queue=args.separate_queue,dedicated_compute=args.dedicated_compute,graphics_draws=args.graphics_draws,fps=args.fps)
    settings['tile_memory']=args.tile_memory
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    keytool=java.with_name('keytool.exe')
    clang=NDK/'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    source=Path(__file__).with_suffix('.cpp');driver_args=['-lvulkan'];driver_record=None
    if args.custom_driver:
        from . import custom_driver
        driver_record=custom_driver.provenance(args.custom_driver)
        source=custom_driver.activity_source(out);driver_args=custom_driver.link_args()
    cmd=[clang,'--target=aarch64-linux-android29','-std=c++17','-O2','-shared','-fPIC','-static-libstdc++','-I',TOOLS,source,*driver_args,'-landroid','-llog','-o',out/'liblocalexposure.so']
    run(cmd)
    xml=f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{PACKAGE}" android:versionCode="1" android:versionName="1.0"><uses-sdk android:minSdkVersion="29" android:targetSdkVersion="35"/><uses-feature android:name="android.hardware.vulkan.level" android:version="1" android:required="true"/><application android:label="Local Exposure Benchmark" android:hasCode="false" android:debuggable="true" android:extractNativeLibs="true"><activity android:name="android.app.NativeActivity" android:exported="true" android:screenOrientation="landscape" android:configChanges="orientation|screenSize|keyboardHidden"><meta-data android:name="android.app.lib_name" android:value="localexposure"/><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>'''
    (out/'AndroidManifest.xml').write_text(xml)
    run([sdk/'aapt2.exe','link','-I',platform,'--manifest',out/'AndroidManifest.xml','-o',out/'unsigned.apk'])
    with zipfile.ZipFile(out/'unsigned.apk','a',compression=zipfile.ZIP_DEFLATED) as z:
        z.write(out/'liblocalexposure.so','lib/arm64-v8a/liblocalexposure.so')
        if args.custom_driver:
            library,files=custom_driver.driver_files(args.custom_driver)
            for p in (custom_driver.BUILD/'src/hook').glob('*.so'):z.write(p,'lib/arm64-v8a/'+p.name)
            for p in files:z.write(p,'assets/bundle/'+p.name)
            z.writestr('assets/bundle/custom-driver-name.txt',library)
        for p in bundle.iterdir():
            if p.suffix=='.spv' or (p.suffix=='.bin' and not p.name.endswith(('.reference.bin','.device.bin','.phone-reference.bin'))):z.write(p,'assets/bundle/'+p.name)
        z.writestr('assets/bundle/manifest.json',json.dumps(manifest));z.writestr('assets/bundle/activity.json',json.dumps(settings))
    run([sdk/'zipalign.exe','-f','4',out/'unsigned.apk',out/'aligned.apk'])
    key=TOOLS/'local-exposure-debug.jks'
    if not key.exists():run([keytool,'-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','androiddebugkey','-keyalg','RSA','-keysize','2048','-validity','10000','-dname','CN=Local Exposure Benchmark'])
    run([java,'-jar',sdk/'lib/apksigner.jar','sign','--ks',key,'--ks-pass','pass:android','--key-pass','pass:android','--out',out/'benchmark.apk',out/'aligned.apk'])
    serial=select_device(ADB,args.serial)
    adb=[ADB,'-s',serial];active_adb=adb
    run([*adb,'install','-r',out/'benchmark.apk'])
    run([*adb,'shell','am','force-stop',PACKAGE])
    run([*adb,'shell','run-as',PACKAGE,'mkdir','-p','files'])
    run([*adb,'shell','run-as',PACKAGE,'sh','-c',"'echo pending > files/status.txt'"])
    metadata=dict(started_utc=datetime.now(timezone.utc).isoformat(),serial=serial,
        custom_driver=driver_record,
        command=list(map(str,cmd)),library_sha256=sha(out/'liblocalexposure.so'),
        bundle=str(bundle),manifest_sha256=sha(bundle/'manifest.json'),execution_manifest_sha256=sha(out/'manifest.json'),settings=settings,
        source_sha256={p:sha(Path(__file__).with_name(p)) for p in ('activity.cpp','runner.cpp')},
        tool_sha256={str(p):sha(p) for p in (clang,java,sdk/'aapt2.exe',sdk/'lib/apksigner.jar',ADB)})
    (out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(run([*adb,'shell','am','start','-n',PACKAGE+'/android.app.NativeActivity']),flush=True)
    deadline=time.monotonic()+120+(args.frames+args.warmup)*args.rounds*2/20
    last='';last_telemetry=0.;started=time.monotonic()
    while time.monotonic()<deadline:
        if time.monotonic()-last_telemetry>=10:
            try:telemetry=run([*adb,'shell','dumpsys battery; dumpsys thermalservice'],timeout=15)
            except (RuntimeError,subprocess.TimeoutExpired) as e:telemetry='Telemetry transport error: '+str(e)
            with (out/'telemetry.jsonl').open('a') as f:f.write(json.dumps(dict(elapsed_s=time.monotonic()-started,text=telemetry))+'\n')
            last_telemetry=time.monotonic()
        try:status=run([*adb,'shell','run-as',PACKAGE,'cat','files/status.txt'],timeout=15).strip()
        except (RuntimeError,subprocess.TimeoutExpired):
            print('ADB transport interrupted; application continues, retrying status.',flush=True)
            time.sleep(2);continue
        if status!=last:print(status,flush=True);last=status
        if status=='complete':break
        if status.startswith('ERROR:'):raise RuntimeError(status)
        time.sleep(2)
    else:raise RuntimeError('Activity timed out; inspect application log')
    for name in ['activity-result.json','surface.json','final.device.bin']:
        for attempt in range(3):
            p=subprocess.run([str(a) for a in [*adb,'exec-out','run-as',PACKAGE,'cat','files/'+name]],capture_output=True,timeout=60)
            if p.returncode==0 and p.stdout:
                if name=='final.device.bin' and len(p.stdout)==manifest['width']*manifest['height']*4:break
                if name.endswith('.json'):
                    try:json.loads(p.stdout);break
                    except (ValueError,UnicodeDecodeError):pass
            time.sleep(1)
        else:raise RuntimeError(f'Cannot retrieve {name}: {p.stderr!r}')
        (out/name).write_bytes(p.stdout)
    raw=json.loads((out/'activity-result.json').read_text())
    if raw.get('interrupted'):raise RuntimeError('Activity was interrupted; incomplete measurement')
    keys=['gpu_ms','cpu_ms','frame_work_wall_ms']+([] if args.joint_submission else ['context_gpu_ms'])
    summary={kind:{key:sample_stats([v for b in raw['blocks'] if b['kind']==kind for v in b[key]]) for key in keys} for kind in ['fusion','baseline']}
    summary['increment_ms']=summary['fusion']['gpu_ms']['median']-summary['baseline']['gpu_ms']['median']
    summary['same_output_as_headless']=(out/'final.device.bin').read_bytes()==(bundle/'final.device.bin').read_bytes()
    context_name='graphics HDR producer' if args.hdr_producer else 'graphics context draw'
    summary['note']=('Foreground with '+context_name if not args.no_graphics_context else 'Foreground present-only, no graphics precursor')+'; offscreen-to-swapchain blit/present excluded from core timestamps. Not direct swapchain storage integration.'
    if args.joint_submission:summary['note']='Single submission: headline GPU/CPU intervals include common '+context_name+' plus Fusion/tonemap, or the same graphics work plus tonemap baseline. Difference cancels the common producer nominally; presentation excluded. Raw context_gpu_ms zeros are unused placeholders, not measured zero producer cost.'
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    metadata['completed_utc']=datetime.now(timezone.utc).isoformat()
    metadata['device']=raw.get('device')
    (out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not summary['same_output_as_headless']:raise RuntimeError('Foreground final output differs from headless')
if __name__=='__main__':
    try:main()
    except Exception:
        if active_adb:
            try:run([*active_adb,'shell','am','force-stop',PACKAGE],timeout=15)
            except Exception:pass
        raise
