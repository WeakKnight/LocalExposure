"""Compare tone mapping against matched bandwidth/dispatch controls on the phone.

Reuses a benchmark bundle, without changing production precision or algorithms.
"""
import argparse
import copy
import json
import re
import struct
from pathlib import Path
import shutil

import numpy as np

from .benchmark import ADB, build, run, select_device, stats
from .prepare import ROOT, sha
from tools.profiling.mobile_profile import compiler, FLAGS

REMOTE = '/data/local/tmp/local-exposure-diagnostics'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--serial')
    ap.add_argument('--frames',type=int,default=180)
    ap.add_argument('--warmup',type=int,default=120)
    ap.add_argument('--intervals',type=int,nargs='+',default=[16,0])
    ap.add_argument('--probes',nargs='+',default=['copy_probe','fill_probe','empty_probe'])
    ap.add_argument('--half-source',action='store_true',help='Diagnostic storage-format experiment; not lossless and never applied to production')
    ap.add_argument('--empty-dimensions',type=int,nargs=2,help='Override only the empty probe dispatch dimensions to measure launch scaling')
    ap.add_argument('--group-size',type=int,nargs=2,default=[8,8],help='Diagnostic workgroup shape, also applied to tonemap (not to production shaders)')
    args=ap.parse_args()
    if args.frames<1 or args.warmup<0 or not args.intervals or min(args.intervals)<0:
        ap.error('Invalid frame counts or pacing')
    if min(args.group_size)<1 or np.prod(args.group_size)>1024:
        ap.error('Invalid workgroup size')
    if args.empty_dimensions and min(args.empty_dimensions)<1:
        ap.error('Empty dispatch dimensions must be positive')
    if args.out.exists():
        raise ValueError('Choose a new diagnostics directory')
    args.out.mkdir(parents=True)
    adb=[ADB,'-s',select_device(ADB,args.serial)]
    toolchain=build(args.out)
    original=json.loads((args.bundle/'manifest.json').read_text())
    source=next(r for r in original['resources'] if r['name']=='source')
    w,h=source['width'],source['height']
    if source['format_name']!='rgba32_float':
        raise ValueError('Expected the production RGBA32F input')
    base=original['passes'][-1]
    if base['entry']!='tonemap_baseline':
        raise ValueError('Missing matched baseline')
    summary=dict(schema=1,purpose='tonemap diagnosis, not a production optimization',width=w,height=h,
        original_manifest_sha256=sha(args.bundle/'manifest.json'),toolchain=toolchain,
        source_format='rgba16_float' if args.half_source else 'rgba32_float',cases=[])
    for interval in args.intervals:
        for probe in args.probes:
            if probe not in ('copy_probe','fill_probe','empty_probe'):
                raise ValueError('Unknown probe')
            case=f'{probe}-{interval}ms'; dest=args.out/case; dest.mkdir()
            m=copy.deepcopy(original)
            m['resources']=[r for r in m['resources'] if r['name'] in ('source','final','baseline')]
            for r in m['resources']:
                r['dump']=r['name'] in ('final','baseline')
            src=next(r for r in m['resources'] if r['name']=='source')
            data=np.fromfile(args.bundle/'source.bin',np.float32)
            if args.half_source:
                data=data.astype(np.float16)
                if not np.isfinite(data).all():
                    raise ValueError('Half-source diagnostic would overflow')
                src.update(format=97,format_name='rgba16_float',bpp=8)
            data.tofile(dest/'source.bin')
            shutil.copy2(args.bundle/(base['entry']+'.spv'),dest/(base['entry']+'.spv'))
            base=copy.deepcopy(base)
            if args.group_size!=[8,8]:
                text=(ROOT/'shaders/guided.slang').read_text()
                text,count=re.subn(r'\[numthreads\(8, 8, 1\)\](\s*void tonemap_baseline)',
                    f'[numthreads({args.group_size[0]}, {args.group_size[1]}, 1)]'+r'\1',text)
                if count!=1: raise ValueError('Cannot locate baseline group shape')
                (dest/'guided-diagnostic.slang').write_text(text)
                run([compiler(),dest/'guided-diagnostic.slang','-I',ROOT/'shaders','-entry',base['entry'],*FLAGS,
                     '-target','spirv','-o',dest/(base['entry']+'.spv')])
            base['group_size']=[*args.group_size,1]
            shutil.copy2(args.bundle/base['uniform'],dest/base['uniform'])
            command=[compiler(),Path(__file__).with_name('probes.slang'),'-I',ROOT/'shaders',
                f'-DPROBE_GROUP_X={args.group_size[0]}',f'-DPROBE_GROUP_Y={args.group_size[1]}','-entry',probe,*FLAGS,
                '-target','spirv','-o',dest/(probe+'.spv'),'-reflection-json',dest/'reflection.json']
            run(command)
            reflection=json.loads((dest/'reflection.json').read_text())
            types={p['name']:p['type'] for p in reflection['parameters']}
            descriptors=[]
            for p in reflection['entryPoints'][0]['bindings']:
                if p['binding']['kind']!='descriptorTableSlot' or not p['binding'].get('used'):
                    continue
                name=p['name']; typ=types[name]
                descriptors.append(dict(name=name,binding=p['binding']['index'],
                    type=3 if typ.get('access')=='readWrite' else 2,
                    resource='source' if name=='inputTexture' else 'final',mip=0))
            # globalEV is the only scalar in this diagnostic module, at offset 0.
            uniform=bytearray(256)
            struct.pack_into('<f',uniform,0,m['config']['globalEV'])
            (dest/'probe.uniform.bin').write_bytes(uniform)
            control=dict(entry=probe,label=probe,width=w,height=h,descriptors=descriptors,
                         uniform='probe.uniform.bin',baseline=False,group_size=[*args.group_size,1])
            if probe=='empty_probe' and args.empty_dimensions:
                control.update(width=args.empty_dimensions[0],height=args.empty_dimensions[1])
            m['passes']=[control,base]
            (dest/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
            shutil.copy2(args.out/'le-benchmark',dest/'le-benchmark')
            run([*adb,'shell','mkdir','-p',REMOTE])
            run([*adb,'push',str(dest)+'/.' ,REMOTE])
            log=run([*adb,'shell',f'cd {REMOTE} && chmod 755 le-benchmark && ./le-benchmark {args.warmup} {args.frames} 2 {interval}'],timeout=240)
            (dest/'runner.log').write_text(log)
            run([*adb,'pull',REMOTE+'/timings.json',dest/'timings.json'])
            for name in ('final','baseline'):
                run([*adb,'pull',REMOTE+'/'+name+'.device.bin',dest/(name+'.device.bin')])
            actual=np.fromfile(dest/'final.device.bin',np.float16).reshape(h,w,4)
            expected=data.reshape(h,w,4).astype(np.float32).copy()
            if probe=='copy_probe':
                expected[...,:3]=np.maximum(expected[...,:3],0)*np.exp2(m['config']['globalEV'])
                expected[...,3]=1
                error=float(abs(actual.astype(float)-expected.astype(np.float16).astype(float)).max())
                # The baseline bundle uses global EV 0; other EV values can
                # produce one FP16 step of cross-device transcendental error.
                if error>max(1e-3,float(abs(expected).max())*.001):
                    raise ValueError(f'Copy validation failed: {error}')
            elif probe=='fill_probe':
                error=float(abs(actual-np.array([.25,.5,.75,1],np.float16)).max())
                if error: raise ValueError('Fill validation failed')
            else:
                error=float(abs(actual).max())
                if error: raise ValueError('Empty kernel changed output')
            raw=json.loads((dest/'timings.json').read_text())
            tone=stats([v for b in raw['blocks'] if b['kind']=='baseline' for v in b['gpu_ms']])
            control_stats=stats([v for b in raw['blocks'] if b['kind']=='fusion' for v in b['gpu_ms']])
            result=dict(name=case,interval_ms=interval,probe=probe,gpu=raw['device'],tone=tone,control=control_stats,
                group_size=args.group_size,tone_shader_sha256=sha(dest/(base['entry']+'.spv')),
                dispatch_dimensions=[control['width'],control['height']],
                control_validation_max_abs=error,shader_sha256=sha(dest/(probe+'.spv')),
                input_sha256=sha(dest/'source.bin'),compile_command=list(map(str,command)))
            host=[v for b in raw['blocks'] if b['kind']=='baseline' for v in b.get('cpu_submit_wait_query_ms',[])]
            if host:
                result['tone_cpu_submit_wait_query_ms']=stats(host)
            tone_image=np.fromfile(dest/'baseline.device.bin',np.float16)
            if tone_image.size!=w*h*4 or not np.isfinite(tone_image).all():
                raise ValueError('Invalid baseline readback')
            result['tone_output_sha256']=sha(dest/'baseline.device.bin')
            summary['cases'].append(result)
            (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            print(f'{case}: tone {tone["median"]:.4f} ms; control {control_stats["median"]:.4f} ms',flush=True)


if __name__=='__main__':
    main()
