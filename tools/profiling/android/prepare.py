"""Bake a reproducible, uncached production frame and desktop reference using SlangPy."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np
import OpenEXR
from PIL import Image
import slangpy as spy

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tone_mapper import ToneMapper, create_hdr_texture
from tools.profiling.mobile_profile import compiler, FLAGS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(out, width, height, image, ev=0.):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with OpenEXR.File(str(image), separate_channels=True) as exr:
        rgb = np.stack([exr.channels()[c].pixels for c in 'RGB'], axis=-1).astype('float32')
    rgb = np.maximum(np.nan_to_num(rgb, nan=0., posinf=65535., neginf=0.), 0.)
    rgb = np.stack([np.asarray(Image.fromarray(rgb[..., c]).resize(
        (width, height), Image.Resampling.BILINEAR)) for c in range(3)], axis=-1)
    rgba = np.concatenate([rgb, np.ones((height, width, 1), 'float32')], axis=-1)
    device = spy.Device(enable_hot_reload=False)
    mapper = ToneMapper(device)
    source = create_hdr_texture(device, rgba)
    enc = device.create_command_encoder()
    mapper.prepare_weights(enc, source, ev, 1.2, 1.2, .2)
    mapper.prepare_result(enc, source, ev)
    device.submit_command_buffer(enc.finish())
    # The original viewer entry provides the independent final-color reference.
    mapper.final_color.to_numpy()  # Wait for the desktop reference dispatches.
    curve = mapper.curve
    resources = []
    def resource(name, tex, data=None, dump=False, one_d=False):
        fmt = str(tex.format).split('.')[-1]
        formats = {'rgba32_float': (109, 16), 'rg32_float': (103, 8),
                   'r32_float': (100, 4), 'r16_float': (76, 2), 'rgba16_float': (97, 8)}
        vk, bpp = formats[fmt]
        r = dict(name=name, width=tex.width, height=tex.height or 1,
                 levels=tex.mip_count, format=vk, format_name=fmt, bpp=bpp,
                 one_d=one_d, dump=dump)
        if data is not None:
            r['file'] = name + '.bin'
            np.ascontiguousarray(data).tofile(out / r['file'])
        resources.append(r)
    resource('source', source, rgba)
    resource('inverse', curve.texture, curve.inverse_nodes, one_d=True)
    for name, tex in [('reduced', mapper.work_source), ('luminance', mapper.luminance_pyramid),
                      ('weights', mapper.weight_pyramid), ('reconstructed', mapper.reconstructed),
                      ('exposure', mapper.low_exposure), ('coefficients', mapper.coefficients),
                      ('averaged', mapper.averaged_coefficients), ('final', mapper.final_color)]:
        resource(name, tex, dump=True)
        np.ascontiguousarray(tex.to_numpy()).tofile(out / (name + '.reference.bin'))
    resource('baseline', mapper.base_color)
    manifest = dict(schema=1, width=width, height=height, resources=resources, passes=[],
                    config=dict(globalEV=ev, highlightEV=1.2, shadowEV=1.2, sigma=.2, fusion_scale=4),
                    calibration=curve.report, image=dict(path=str(image.resolve()), sha256=sha(image)),
                    reference_backend=str(device.info), shaders={p.name: sha(p) for p in (ROOT/'shaders').glob('*.slang')})
    modules = dict(reduce_source='guided', fit_coefficients='guided', average_coefficients='guided', apply_exposure='guided',
                   apply_exposure_production='guided', tonemap_baseline='guided',
                   setup_weights='pyramid', downsample='pyramid', reconstruct='fusion', convert_exposure='fusion')
    reflections = {}
    exe = compiler()
    manifest['slangc_sha256'] = sha(exe)
    manifest['commands'] = []
    for entry, module in modules.items():
        cmd = [str(exe), str(ROOT/'shaders'/f'{module}.slang'), '-entry', entry, *FLAGS,
               '-target', 'spirv', '-o', str(out/f'{entry}.spv'),
               '-reflection-json', str(out/f'{entry}.reflection.json')]
        result = subprocess.run(cmd, capture_output=True, text=True)
        (out/f'{entry}.compile.log').write_text(result.stdout+result.stderr)
        result.check_returncode()
        reflections[entry] = json.loads((out/f'{entry}.reflection.json').read_text())
        manifest['commands'].append(cmd)
    cb = {k: v for k, v in curve.bindings().items() if k not in ('inverseLut', 'inverseSampler')}
    cb.update(globalEV=ev, highlightEV=1.2, shadowEV=1.2, sigma=.2, reductionRows=4, guided=True)
    def view(name, mip=0):
        return dict(resource=name, mip=mip)
    def add(entry, label, w, h, bindings, constants=None, baseline=False):
        ref = reflections[entry]
        params = {p['name']: p for p in ref['parameters']}
        used = ref['entryPoints'][0]['bindings']
        uniform = bytearray(256)
        c = {**cb, **(constants or {})}
        descriptors = []
        for item in used:
            name, binding = item['name'], item['binding']
            t = params[name]['type']
            if binding['kind'] == 'uniform':
                if name not in c:
                    continue
                values = np.asarray(c[name]).ravel().tolist()
                scalar = t.get('elementType', t)['scalarType']
                fmt = 'f' if scalar == 'float32' else 'I'
                struct.pack_into('<'+fmt*len(values), uniform, binding['offset'], *values)
            elif binding.get('used', 0):
                if binding.get('space', 0) != 0:
                    raise ValueError('Only descriptor set 0 supported')
                descriptor = dict(binding=binding['index'], name=name)
                if t['kind'] == 'samplerState':
                    descriptor['type'] = 0
                else:
                    descriptor['type'] = 3 if t.get('access') == 'readWrite' else 2
                    descriptor.update(bindings[name])  # Fail on missing used resource.
                descriptors.append(descriptor)
        path = f'{len(manifest["passes"]):02d}.uniform.bin'
        (out/path).write_bytes(uniform)
        manifest['passes'].append(dict(entry=entry, label=label, width=w, height=h,
                                       descriptors=descriptors, uniform=path, baseline=baseline))
    w, h = mapper.work_source.width, mapper.work_source.height
    add('reduce_source', 'reduce_source', w, h, dict(fullSource=view('source'), reducedOutput=view('reduced')))
    add('setup_weights', 'setup_weights', w, h, dict(hdrSource=view('reduced'),
        luminanceOutput=view('luminance'), weightOutput=view('weights')))
    levels = mapper.reconstructed.mip_count
    for name in ('luminance', 'weights'):
        for mip in range(1, levels):
            add('downsample', f'{name}_mip{mip}', max(1,w>>mip), max(1,h>>mip),
                dict(inputTexture=view(name,mip-1), outputTexture=view(name,mip)))
    for mip in reversed(range(levels)):
        add('reconstruct', f'reconstruct_mip{mip}', max(1,w>>mip), max(1,h>>mip),
            dict(fineLuminance=view('luminance',mip), coarseLuminance=view('luminance',min(mip+1,levels-1)),
                 layerWeights=view('weights',mip), previousResult=view('exposure') if mip==levels-1 else view('reconstructed',mip+1),
                 reconstructionOutput=view('reconstructed',mip)), dict(isCoarsest=mip==levels-1))
    add('convert_exposure','convert_exposure',w,h,dict(hdrSource=view('reduced'), fusedLightness=view('reconstructed'),
         exposureOutput=view('exposure'), inverseLut=view('inverse')))
    add('fit_coefficients','fit_coefficients',w,h,dict(reducedSource=view('reduced'),lowExposure=view('exposure'),coefficientOutput=view('coefficients')))
    add('average_coefficients','average_coefficients',w,h,dict(coefficients=view('coefficients'),averagedOutput=view('averaged')))
    add('apply_exposure_production','apply_exposure_production',width,height,
        dict(fullSource=view('source'),lowExposure=view('exposure'),averagedCoefficients=view('averaged'),colorOutput=view('final')))
    add('tonemap_baseline','tonemap_baseline',width,height,dict(fullSource=view('source'),colorOutput=view('baseline')),baseline=True)
    # A separate untimed device process runs the existing viewer application
    # entry as the same-GPU reference. Its debug textures never exist in the
    # measured process. Cross-vendor desktop comparison is reported separately.
    add('apply_exposure','viewer_reference',width,height,
        dict(fullSource=view('source'),lowExposure=view('exposure'),averagedCoefficients=view('averaged'),
             colorOutput=view('final'),baseOutput=view('baseline'),fullExposureOutput=view('debug_exposure')))
    reference_pass = manifest['passes'].pop()
    manifest['reference_pass'] = reference_pass
    manifest['reference_resource'] = dict(name='debug_exposure',width=width,height=height,levels=1,
        format=76,format_name='r16_float',bpp=2,one_d=False,dump=False)
    manifest['files'] = {p.name:sha(p) for p in out.iterdir() if p.suffix in ('.bin','.spv')}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Prepared {width}x{height}, {len(manifest["passes"])-1} production dispatches', flush=True)
    return manifest
