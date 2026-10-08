"""Analytic UE film in Bart: independent-reference images and matched GPU timing."""
import argparse
import json
import platform
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
from PIL import Image, ImageDraw
import slangpy as spy
from fine_residual import FineResidualToneMapper
from tone_mapper import ToneMapper, create_hdr_texture, load_exr
from tools.profiling.gpu_timer import GpuTimer
from tools.profiling.android.quality_sweep import codes
from tools.profiling.android.quality import full_resolution_quality
from tools.render_comparison import digest, heatmap, sources
from tools.validate_asset_matrix import PRESETS

OUT = ROOT / 'docs/images/ue-film'
FULL = ROOT / 'outputs/ue-film'


def fingerprint():
    result = sources()
    for p in [Path(__file__), ROOT/'ue_film_curve.py', ROOT/'ue_local_exposure.py',
              ROOT/'tools/profiling/gpu_timer.py', ROOT/'tools/validate_asset_matrix.py',
              *sorted((ROOT/'Assets').glob('*.exr'))]:
        result[p.relative_to(ROOT).as_posix()] = digest(p)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--iterations',type=int,default=60)
    args=parser.parse_args()
    if args.check:
        record=json.loads((OUT/'manifest.json').read_text())
        assert record['sources']==fingerprint(), 'Stale sources'
        for name,value in record['artifacts'].items():
            assert digest(OUT/name)==value, 'Stale artifact: '+name
        print('UE film sources and images are current.')
        return
    OUT.mkdir(parents=True,exist_ok=True); FULL.mkdir(parents=True,exist_ok=True)
    d=spy.Device(enable_hot_reload=False)
    timer=GpuTimer(d)
    ref=ToneMapper(d,curve_mode='ue-film')
    opt=FineResidualToneMapper(d,curve_mode='ue-film')
    z=FineResidualToneMapper(d)
    baseline=d.create_compute_kernel(z.session.load_program('reference_apply.slang',['tonemap_baseline']))
    settings=dict(width=1920,height=1080,input='RGBA32_FLOAT',output='RGBA16_FLOAT linear SDR',
                  sigma=.2,curve='ue-film',luminance='equal RGB; exposed floor 2^-8',
                  presets=PRESETS,iterations=args.iterations,warmup=8,seed=840)
    report=dict(settings=settings,backend=dict(api=d.info.api_name,adapter=d.info.adapter_name,
        os=platform.platform(),slangpy=spy.__version__,timer=timer.kind,
        driver='Apple OS-bundled Metal driver; no separate driver revision queried'),
        scope='Static HDR EXRs. No game/phone extrapolation. Whole command GPU time; no debug/display/readback. '
              'Z LUT versus UE analytic changes curve behavior as well as execution; not an isolated ALU/LUT comparison.',
        cases=[],timings={},artifacts={})
    rng=random.Random(840)
    def render(m,source,ev,hi,sh):
        enc=d.create_command_encoder();m.record_processing(enc,source,ev,hi,sh,.2)
        d.submit_command_buffer(enc.finish())
        pixels=m.final_color.to_numpy()
        assert np.isfinite(pixels).all()
        return codes(pixels)
    def save(im,name):
        im.save(OUT/name);report['artifacts'][name]=digest(OUT/name)
    def measure(source,label):
        output=z.create_texture(source.width,source.height,spy.Format.rgba16_float)
        records=dict(baseline=lambda enc:baseline.dispatch(thread_count=[source.width,source.height,1],
            vars=dict(fullSource=source,colorOutput=output,globalEV=0),command_encoder=enc),
            z_lookup=lambda enc:z.record_processing(enc,source,0,1.2,1.2,.2),
            ue_analytic=lambda enc:opt.record_processing(enc,source,0,1.2,1.2,.2))
        for _ in range(8):
            for fn in records.values():timer.measure(fn)
        samples={key:[] for key in records}
        for _ in range(args.iterations):
            order=list(records);rng.shuffle(order)
            for key in order:samples[key].append(timer.measure(records[key]))
        stats={key:dict(median_ms=float(np.median(v)),p10_ms=float(np.percentile(v,10)),
                       p90_ms=float(np.percentile(v,90)),samples_ms=v) for key,v in samples.items()}
        for key in ('z_lookup','ue_analytic'):
            stats[key]['increment_median_ms']=float(np.median(np.array(samples[key])-samples['baseline']))
        report['timings'][label]=stats
        print(label,{k:round(v['median_ms'],4) for k,v in stats.items()},flush=True)
    for path in sorted((ROOT/'Assets').glob('*.exr')):
        native=load_exr(d,path)
        rgba=native.to_numpy()
        small=np.stack([np.asarray(Image.fromarray(rgba[...,c]).resize((1920,1080),Image.Resampling.BILINEAR)) for c in range(4)],axis=-1)
        source=create_hdr_texture(d,small)
        scene=path.stem
        sheet=Image.new('RGB',(1440,4*294),(22,24,29));draw=ImageDraw.Draw(sheet)
        for row,p in enumerate(PRESETS):
            ev,hi,sh=p['global_ev'],6*(1-p['highlight_contrast']),6*(1-p['shadow_contrast'])
            a=render(ref,source,ev,hi,sh);b=render(opt,source,ev,hi,sh)
            quality=full_resolution_quality(a,b)
            report['cases'].append(dict(scene=scene,preset=p['name'],quality=quality))
            err=heatmap(abs(a.astype(np.int16)-b.astype(np.int16)).max(-1))
            for col,(label,pixels) in enumerate([('reference',a),('fine-residual',b),('error',err)]):
                Image.fromarray(pixels).save(FULL/f'{scene}-{p["name"]}-{label}.png')
                draw.text((col*480+8,row*294+5),p['name']+' | '+label,fill='white')
                sheet.paste(Image.fromarray(pixels).resize((480,270),Image.Resampling.LANCZOS),(col*480,row*294+24))
            print(scene,p['name'],quality,flush=True)
        save(sheet,scene+'.png')
        measure(source,scene+'-1920x1080')
        if scene=='veranda_4k':
            a=render(ref,native,0,2.856,1.2);b=render(opt,native,0,2.856,1.2);old=render(z,native,0,2.856,1.2)
            report['native_halo_quality']=full_resolution_quality(a,b)
            sheet=Image.new('RGB',(1440,804),(22,24,29));draw=ImageDraw.Draw(sheet)
            for col,(label,pixels) in enumerate([('Z LUT fine residual',old),('UE film reference',a),('UE film fine residual',b)]):
                im=Image.fromarray(pixels);im.save(FULL/f'native-{col}.png')
                draw.text((col*480+8,5),label,fill='white')
                sheet.paste(im.resize((480,240),Image.Resampling.LANCZOS),(col*480,24))
                sheet.paste(im.crop((2150,560,2850,1310)).resize((480,514)),(col*480,266))
            save(sheet,'native-edge-comparison.png')
            error=abs(a.astype(np.int16)-b.astype(np.int16)).max(-1)
            Image.fromarray(heatmap(error)).save(FULL/'native-error.png')
            y,x=np.unravel_index(error.argmax(),error.shape)
            crop=(max(0,min(x-128,native.width-256)),max(0,min(y-128,native.height-256)))
            box=(*crop,crop[0]+256,crop[1]+256)
            detail=Image.new('RGB',(768,280),(22,24,29));draw=ImageDraw.Draw(detail)
            for col,(label,pixels) in enumerate([('reference',a),('fine residual',b),('error',heatmap(error))]):
                draw.text((col*256+8,5),label,fill='white');detail.paste(Image.fromarray(pixels).crop(box),(col*256,24))
            save(detail,'native-worst-error.png')
            measure(native,scene+'-4096x2048')
    report['sources']=fingerprint()
    (OUT/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
