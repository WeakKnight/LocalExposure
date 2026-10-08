"""Current Bart versus independent UE Fusion/Bilateral: matched whole-chain GPU timing.

Static EXR workload, not a game capture. No UI, readbacks or cached processing in timing.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import random
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import numpy as np
import slangpy as spy
from fine_residual import FineResidualToneMapper
from tone_mapper import ToneMapper
from ue_local_exposure import UEParameters,UnrealLocalExposure
from tools.profiling.gpu_timer import GpuTimer
from tools.profiling.compare_unreal import packed_source,distribution
from tools.render_comparison import digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations',type=int,default=60)
    parser.add_argument('--warmup',type=int,default=8)
    parser.add_argument('--highlight',type=float,default=.5)
    parser.add_argument('--shadow',type=float,default=.8)
    parser.add_argument('--out',type=Path,default=ROOT/'docs/performance/baselines/current-algorithms.json')
    args=parser.parse_args()
    if args.iterations<1 or args.warmup<0 or not(0<=args.highlight<=1 and 0<=args.shadow<=1):
        parser.error('Invalid iterations, warmup or contrast')
    d=spy.Device(enable_hot_reload=False)
    timer=GpuTimer(d)
    session=d.create_slang_session(compiler_options={'include_paths':[ROOT/'shaders']})
    pack=d.create_compute_kernel(session.load_program(str(ROOT/'tools/profiling/android/pack_source.slang'),['pack_source']))
    baseline=d.create_compute_kernel(session.load_program('reference_apply.slang',['tonemap_baseline']))
    mappers={
        'bart_ue_fine':FineResidualToneMapper(d,curve_mode='ue-film'),
        'bart_z_fine':FineResidualToneMapper(d,curve_mode='z'),
        'bart_ue_full':ToneMapper(d,curve_mode='ue-film'),
        'ue_fusion_native':UnrealLocalExposure(d,'ue-fusion',parameters=UEParameters(storage='native')),
        'ue_fusion_fp32':UnrealLocalExposure(d,'ue-fusion',parameters=UEParameters(storage='fp32')),
        'ue_bilateral_native':UnrealLocalExposure(d,'ue-bilateral',parameters=UEParameters(storage='native')),
        'ue_bilateral_fp32':UnrealLocalExposure(d,'ue-bilateral',parameters=UEParameters(storage='fp32')),
    }
    report=dict(date='2026-10-08',backend=dict(adapter=d.info.adapter_name,api=d.info.api_name,
        os=platform.platform(),slangpy=spy.__version__,driver='OS-bundled Metal driver; separate revision not queried',timer=timer.kind),
        settings=dict(resolutions=[[1920,1080],[3840,2160]],global_ev=0,highlight_contrast=args.highlight,
        shadow_contrast=args.shadow,sigma=.2,levels=16,input='R11G11B10_FLOAT',output='RGBA16_FLOAT linear SDR',
        luminance='equal RGB',iterations=args.iterations,warmup=args.warmup,seed=8108,
        ue_defaults=asdict(UEParameters())),
        scope='Static EXR uploads outside timing. Same HDR texture, global EV and final ACES/output. '
        'Every graph recomputes all passes. UE desktop reduction chain included. Whole-command GPU timestamps, '
        'not per-pass sums or CPU time. No visualization, diagnostics, readbacks, allocation or compilation in measurement. '
        'Algorithm/storage outputs differ; not a quality-matched speedup or graphics-produced game/phone workload.',
        workloads=[])
    rng=random.Random(8108)
    for w,h in report['settings']['resolutions']:
        output=mappers['bart_ue_fine'].create_texture(w,h,spy.Format.rgba16_float)
        for asset in sorted((ROOT/'Assets').glob('*.exr')):
            source=packed_source(d,asset,w,h,pack)
            records={'baseline':lambda enc:baseline.dispatch(thread_count=[w,h,1],vars=dict(
                fullSource=source,colorOutput=output,globalEV=0),command_encoder=enc)}
            for name,m in mappers.items():
                if name.startswith('bart'):
                    records[name]=lambda enc,m=m:m.record_processing(enc,source,0,6*(1-args.highlight),6*(1-args.shadow),.2)
                else:
                    records[name]=lambda enc,m=m:m.record_processing(enc,source,0,args.highlight,args.shadow)
            # Compile and allocate outside timestamps, then validate finite output.
            for name,record in records.items():
                enc=d.create_command_encoder();record(enc);d.submit_command_buffer(enc.finish())
                pixels=(output if name=='baseline' else mappers[name].final_color).to_numpy()
                if not np.isfinite(pixels).all():raise RuntimeError('Nonfinite output: '+name)
            for _ in range(args.warmup):
                for record in records.values():timer.measure(record)
            samples={name:[] for name in records}
            orders=[]
            for _ in range(args.iterations):
                order=list(records);rng.shuffle(order);orders.append(order)
                for name in order:samples[name].append(timer.measure(records[name]))
            measurements={name:dict(chain=distribution(values)) for name,values in samples.items()}
            for name in mappers:
                measurements[name]['local_exposure_increment']=distribution(np.array(samples[name])-samples['baseline'])
            report['workloads'].append(dict(scene=asset.stem,width=w,height=h,finite=True,
                                            measurements=measurements,round_order=orders))
            print(f'{asset.stem} {w}x{h}',{name:round(v['chain']['median_ms'],4) for name,v in measurements.items()},flush=True)
    paths=[Path(__file__),ROOT/'tone_mapper.py',ROOT/'fine_residual.py',ROOT/'ue_film_curve.py',ROOT/'zcurve.py',
           ROOT/'fusion_lookup.py',ROOT/'ue_local_exposure.py',ROOT/'tools/profiling/gpu_timer.py',
           ROOT/'tools/profiling/compare_unreal.py',ROOT/'tools/render_comparison.py',
           ROOT/'tools/profiling/android/pack_source.slang',*sorted((ROOT/'shaders').rglob('*.slang')),
           *sorted((ROOT/'Assets').glob('*.exr'))]
    report['sources']={p.relative_to(ROOT).as_posix():digest(p) for p in paths}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print('Saved',args.out,flush=True)

if __name__=='__main__':main()
