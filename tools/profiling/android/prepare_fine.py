"""Export fine-residual production shaders with a separate full-resolution reference."""
import copy
import json
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace
import numpy as np
from fusion_lookup import bake_tables, SIZE
from .variants import VARIANTS


def prepare_fine(out, width, height, image, ev, source_format, output_format,
                 variant, highlight, shadow, sigma):
    from .prepare import prepare, ROOT, sha
    if output_format != 'rgba8_srgb':
        raise ValueError('Fine-residual mobile export requires rgba8_srgb output')
    out = Path(out)
    # Reuse the established graph builder; no changes to the legacy control.
    m = prepare(out, width, height, image, ev, source_format, output_format,
                True, True, 'guided-packed-coefficients',
                highlight_ev=highlight, shadow_ev=shadow, sigma=sigma)
    full_dir = out / 'full-reference'
    full = prepare(full_dir, width, height, image, ev, source_format, output_format,
                   False, False, 'lossless', highlight_ev=highlight,
                   shadow_ev=shadow, sigma=sigma, fusion_scale=1)
    for name in ('source.bin', 'inverse.bin'):
        if (out/name).read_bytes() != (full_dir/name).read_bytes():
            raise RuntimeError('Production/reference inputs or calibration differ')
    def reference_pass(stage):
        stage = copy.deepcopy(stage)
        original = stage['uniform']
        stage['uniform'] = 'full-' + original
        (out/stage['uniform']).write_bytes((full_dir/original).read_bytes())
        return stage
    m['unfused_passes'] = [reference_pass(p) for p in full['passes']]
    m['unfused_resources'] = full['resources']
    for key in ('reference_pass', 'reference_resolve'):
        if key in full: m[key] = reference_pass(full[key])
    for key in ('reference_resource', 'reference_resources'):
        if key in full: m[key] = full[key]
    (out/'final.reference.bin').write_bytes((full_dir/'final.reference.bin').read_bytes())
    values = {}
    for stage in m['passes']:
        reflection = json.loads((out/(stage['entry']+'.reflection.json')).read_text())
        data = (out/stage['uniform']).read_bytes()
        for parameter in reflection['parameters']:
            b = parameter['binding']
            if b['kind'] == 'uniform':
                values[parameter['name']] = data[b['offset']:b['offset']+b['size']]
    def scalar(name): return struct.unpack('<f', values[name])[0]
    curve = SimpleNamespace(parameters=np.array(struct.unpack('<4f',values['zParameters'])),
        max_lightness=scalar('zMaxLightness'), bindings=lambda:dict(zMaxInput=scalar('zMaxInput')))
    tables = bake_tables(curve, highlight, shadow, sigma)
    for name, table in zip(('fine_lookup','low_lookup'), tables):
        (out/(name+'.bin')).write_bytes(table.tobytes())
        m['resources'].append(dict(name=name,width=SIZE,height=1,levels=1,format=109,
            format_name='rgba32_float',bpp=16,one_d=True,dump=False,file=name+'.bin'))
    replacements = dict(reduce_setup_gather=ROOT/'shaders/fine_residual/initialize.slang',
        reconstruct_compact=ROOT/'shaders/fine_residual/reconstruct.slang',
        reconstruct_ev=ROOT/'shaders/fine_residual/reconstruct.slang',
        reconstruct_ev_fused=ROOT/'shaders/fine_residual/reconstruct.slang',
        apply_srgb_compute=Path(__file__).with_name('present.slang'))
    for entry, source in replacements.items():
        stages = [p for p in m['passes'] if p['entry']==entry]
        if not stages: continue
        cmd = list(next(c for c in m['commands'] if '-entry' in c and c[c.index('-entry')+1]==entry))
        cmd[1]=str(source)
        if entry=='apply_srgb_compute': cmd += ['-DFINE_RESIDUAL_LOOKUP=1']
        result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (out/(entry+'.compile.log')).write_text(result.stdout+result.stderr)
        result.check_returncode()
        m['commands'].append(cmd)
        reflection=json.loads((out/(entry+'.reflection.json')).read_text())
        for stage in stages:
            bindings={d['name']:d for d in stage['descriptors']}
            for n,r in [('fineLookup','fine_lookup'),('lowLookup','low_lookup'),
                        ('lowResidual','luminance'),('inverseLut','inverse')]:
                bindings[n]=dict(name=n,type=2,resource=r,mip=0)
            bindings['inverseSampler']=dict(name='inverseSampler',type=0)
            if entry=='apply_srgb_compute': bindings['averagedCoefficients']['resource']='guide_ev'
            used=[d for d in reflection['entryPoints'][0]['bindings']
                  if d['binding']['kind'] != 'uniform' and d['binding'].get('used')]
            missing=[d['name'] for d in used if d['name'] not in bindings]
            if missing: raise ValueError(f'{entry}: missing descriptors {missing}')
            stage['descriptors']=[dict(bindings[d['name']],binding=d['binding']['index'])
                for d in used]
            params=[p for p in reflection['parameters'] if p['binding']['kind']=='uniform']
            data=bytearray(max([p['binding']['offset']+p['binding']['size'] for p in params]+[0]))
            for p in params:
                b=p['binding'];value=values[p['name']]
                assert len(value)==b['size'],p['name']
                data[b['offset']:b['offset']+b['size']]=value
            (out/stage['uniform']).write_bytes(data)
            stage['has_uniform']=bool(params)
    m['passes']=[p for p in m['passes'] if p['entry']!='reconstruct_guided']
    m['resources']=[r for r in m['resources'] if r['name']!='averaged']
    for r in m['resources']: r['dump']=r['name']=='final'
    for r in m['unfused_resources']: r['dump']=r['name']=='final'
    m['config'].update(variant=variant,variant_settings=VARIANTS[variant],reference_fusion_scale=1)
    m['reference_description']='Independent full-resolution Fusion without Guided; shared packed HDR and calibration'
    m['files']={p.name:sha(p) for p in out.iterdir() if p.suffix in ('.bin','.spv')}
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    return m
