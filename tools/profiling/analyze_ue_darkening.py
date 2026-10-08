"""Isolate luminance, resolution and packed-stage errors at matched UE film settings."""
import argparse
import gc
import hashlib
import platform
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import numpy as np
from PIL import Image, ImageDraw
import slangpy as spy
from tone_mapper import ToneMapper,load_exr,create_hdr_texture
from fine_residual import FineResidualToneMapper
from ue_local_exposure import UEParameters,UnrealLocalExposure
from tools.profiling.android.quality_sweep import codes


def decoded(texture):
    raw=texture.to_numpy()
    if texture.format != spy.Format.r11g11b10_float:
        return raw[...,:3]
    packed=np.ascontiguousarray(raw).view(np.uint32).reshape(texture.height,texture.width)
    channels=[]
    for shift,bits in [(0,6),(11,6),(22,5)]:
        word=(packed>>shift)&((1<<(bits+5))-1)
        mant=(word&((1<<bits)-1)).astype(np.float64)
        exponent=(word>>bits).astype(np.int32)
        channels.append(np.where(exponent==0,np.ldexp(mant,1-15-bits),
                                 np.ldexp(1+mant/(1<<bits),exponent-15)))
    return np.stack(channels,axis=-1)


def store_probe(device):
    # Isolate the native write conversion from all fusion/filtering operations.
    a=np.repeat(np.linspace(.1,1.04,4097,dtype=np.float32)[None,:,None],4,axis=-1)
    source=create_hdr_texture(device,a)
    packed=device.create_texture(width=a.shape[1],height=1,format=spy.Format.r11g11b10_float,
        usage=spy.TextureUsage.shader_resource|spy.TextureUsage.unordered_access)
    kernel=device.create_compute_kernel(device.create_slang_session().load_program(
        str(ROOT/'tools/profiling/android/pack_source.slang'),['pack_source']))
    kernel.dispatch(thread_count=[a.shape[1],1,1],vars=dict(inputTexture=source,outputTexture=packed))
    delta=decoded(packed)-a[...,:3]
    return dict(input_range=[.1,1.04],samples=4097,mean_error=delta.mean(axis=(0,1)).tolist(),
        negative_fraction=(delta<0).mean(axis=(0,1)).tolist(),
        positive_fraction=(delta>0).mean(axis=(0,1)).tolist(),max_abs=abs(delta).max(axis=(0,1)).tolist())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'outputs/ue-darkening')
    out=parser.parse_args().out;out.mkdir(parents=True,exist_ok=True)
    d=spy.Device(enable_hot_reload=False)
    source=load_exr(d,ROOT/'Assets/veranda_4k.exr')
    rgb=source.to_numpy()[...,:3]
    mask=rgb.max(-1)>1e-5
    rows={}; snapshots={}; gains={}; stages={}
    configs=[('bart_fine',None),('bart_full',None),('ue_fp32_rec709','rec709'),
             ('ue_fp32_uniform','uniform'),('ue_packed_exposures','exposures'),
             ('ue_packed_weights','weights'),('ue_packed_results','results'),('ue_native','native')]
    for name,kind in configs:
        if kind is None:
            m=(FineResidualToneMapper if name=='bart_fine' else ToneMapper)(d,curve_mode='ue-film')
        else:
            p=UEParameters(storage='native' if kind=='native' else 'fp32',
                           luminance_method='rec709' if kind=='rec709' else 'uniform')
            m=UnrealLocalExposure(d,parameters=p);m.allocate(source)
            if kind in ('exposures','weights','results'):
                setattr(m,kind,[m.create_texture(t.width,t.height,spy.Format.r11g11b10_float) for t in getattr(m,kind)])
        enc=d.create_command_encoder()
        if kind is None:
            m.prepare_weights(enc,source,0,3,1.2,.2);m.prepare_result(enc,source,0)
        else:
            m.execute(enc,source,m.create_output(source.width,source.height),0,highlight_ev=3,shadow_ev=1.2)
        d.submit_command_buffer(enc.finish())
        linear=m.final_color.to_numpy()[...,:3].astype(np.float32)
        gain=m.local_exposure.to_numpy().astype(np.float32).squeeze();gains[name]=gain
        snapshots[name]=codes(np.concatenate([linear,np.ones((*linear.shape[:2],1),np.float32)],axis=-1))
        Image.fromarray(snapshots[name]).save(out/(name+'.png'))
        ev=np.log2(np.maximum(gain,1e-20))
        rows[name]=dict(mean_display_linear_luminance=float((linear@np.array([.2126,.7152,.0722])).mean()),
                        mean_local_ev=float(ev[mask].mean()),median_local_ev=float(np.median(ev[mask])))
        if name=='ue_fp32_uniform':
            stages={k:[decoded(t) for t in getattr(m,k)] for k in ('exposures','weights','results')}
        if name=='ue_native':
            rows[name]['stage_errors']={}
            for k,refs in stages.items():
                errors=[]
                for i,(ref,t) in enumerate(zip(refs,getattr(m,k))):
                    delta=decoded(t)-ref
                    errors.append(dict(mip=i,size=[t.width,t.height],mean_delta=delta.mean(axis=(0,1)).tolist(),
                                       negative_fraction=(delta<0).mean(axis=(0,1)).tolist()))
                rows[name]['stage_errors'][k]=errors
        print(name,rows[name] if name!='ue_native' else {k:v for k,v in rows[name].items() if k!='stage_errors'},flush=True)
        d.wait();del m;gc.collect()
    pairs=[('bart_fine','bart_full'),('bart_full','ue_fp32_rec709'),
           ('bart_full','ue_fp32_uniform'),('bart_fine','ue_fp32_uniform'),
           ('ue_fp32_rec709','ue_fp32_uniform'),('ue_fp32_uniform','ue_native'),
           ('ue_fp32_uniform','ue_packed_exposures'),('ue_fp32_uniform','ue_packed_weights'),
           ('ue_fp32_uniform','ue_packed_results'),('bart_fine','ue_native')]
    differences={}
    for a,b in pairs:
        delta=np.log2(np.maximum(gains[b],1e-20)/np.maximum(gains[a],1e-20))[mask]
        pixel=snapshots[b].astype(np.float32)-snapshots[a].astype(np.float32)
        differences[a+' -> '+b]=dict(mean_ev=float(delta.mean()),median_ev=float(np.median(delta)),
            p05_ev=float(np.percentile(delta,5)),p95_ev=float(np.percentile(delta,95)),
            fraction_darker_005=float((delta<-.05).mean()),rmse_srgb8=float(np.sqrt((pixel**2).mean())),
            max_srgb8=float(abs(pixel).max()))
    sheet=Image.new('RGB',(1440,2*294),(22,24,29));draw=ImageDraw.Draw(sheet)
    for i,name in enumerate(['bart_fine','bart_full','ue_fp32_rec709','ue_fp32_uniform','ue_packed_results','ue_native']):
        x,y=(i%3)*480,(i//3)*294
        draw.text((x+8,y+5),name,fill='white')
        sheet.paste(Image.fromarray(snapshots[name]).resize((480,270),Image.Resampling.LANCZOS),(x,y+24))
    sheet.save(out/'comparison.png')
    report=dict(settings=dict(scene='veranda_4k.exr',size=[source.width,source.height],global_ev=0,
                highlight_contrast=.5,shadow_contrast=.8,sigma=.2,input='RGBA32F',bart_luminance='equal RGB'),
                device=d.info.adapter_name,api=d.info.api_name,os=platform.platform(),slangpy=spy.__version__,
                rows=rows,differences=differences,store_probe=store_probe(d))
    paths=[Path(__file__),ROOT/'tone_mapper.py',ROOT/'fine_residual.py',ROOT/'ue_film_curve.py',
           ROOT/'ue_local_exposure.py',ROOT/'Assets/veranda_4k.exr',
           ROOT/'tools/profiling/android/pack_source.slang',*sorted((ROOT/'shaders').rglob('*.slang'))]
    report['sources']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(differences,indent=2),flush=True)

if __name__=='__main__':main()
