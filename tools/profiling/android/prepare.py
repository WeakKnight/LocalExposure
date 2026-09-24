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


def prepare(out, width, height, image, ev=0., source_format='rgba32_float', output_format='rgba16_float', compact=False, fused_guided=False, variant="lossless"):
    from .quality import VARIANTS
    variant_config=VARIANTS[variant]
    if variant_config.get('half_gather') and source_format!='r11g11b10_float':raise ValueError('Half gather requires finite R11G11B10 input')
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
    source_payload=rgba
    if source_format=='r11g11b10_float':
        packed=device.create_texture(width=width,height=height,format=spy.Format.r11g11b10_float,
            usage=spy.TextureUsage.shader_resource|spy.TextureUsage.unordered_access)
        packing_session=device.create_slang_session()
        packing=device.create_compute_kernel(packing_session.load_program(str(Path(__file__).with_name('pack_source.slang')),['pack_source']))
        packing.dispatch(thread_count=[width,height,1],vars=dict(inputTexture=source,outputTexture=packed))
        source=packed
        source_payload=source.to_numpy()  # Exact packed GPU bytes, not float RGBA.
    elif source_format!='rgba32_float':
        raise ValueError('Unsupported HDR source format')
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
                   'r32_float': (100, 4), 'r16_float': (76, 2), 'rgba16_float': (97, 8),
                   'r11g11b10_float': (122, 4)}
        vk, bpp = formats[fmt]
        r = dict(name=name, width=tex.width, height=tex.height or 1,
                 levels=tex.mip_count, format=vk, format_name=fmt, bpp=bpp,
                 one_d=one_d, dump=dump)
        if data is not None:
            r['file'] = name + '.bin'
            np.ascontiguousarray(data).tofile(out / r['file'])
        resources.append(r)
    resource('source', source, source_payload)
    resource('inverse', curve.texture, curve.inverse_nodes, one_d=True)
    for name, tex in [('reduced', mapper.work_source), ('luminance', mapper.luminance_pyramid),
                      ('weights', mapper.weight_pyramid), ('reconstructed', mapper.reconstructed),
                      ('exposure', mapper.low_exposure), ('coefficients', mapper.coefficients),
                      ('averaged', mapper.averaged_coefficients), ('final', mapper.final_color)]:
        resource(name, tex, dump=True)
        np.ascontiguousarray(tex.to_numpy()).tofile(out / (name + '.reference.bin'))
    resource('baseline', mapper.base_color)
    if output_format=='rgba8_srgb':
        for r in resources:
            if r['name'] in ('final','baseline'):
                r.update(format=43,format_name='rgba8_srgb',bpp=4,attachment=True)
        linear=mapper.final_color.to_numpy().astype(np.float32)
        rgb=linear[...,:3]
        srgb=np.where(rgb<=.0031308,12.92*rgb,1.055*np.maximum(rgb,0)**(1/2.4)-.055)
        encoded=np.concatenate([srgb,linear[...,3:4]],axis=-1)
        np.rint(np.clip(encoded,0,1)*255).astype(np.uint8).tofile(out/'final.reference.bin')
    elif output_format!='rgba16_float':
        raise ValueError('Unsupported output format')
    manifest = dict(schema=1, width=width, height=height, resources=resources, passes=[],
                    config=dict(globalEV=ev, highlightEV=1.2, shadowEV=1.2, sigma=.2, fusion_scale=4,source_format=source_format,output_format=output_format),
                    calibration=curve.report, image=dict(path=str(image.resolve()), sha256=sha(image)),
                    reference_backend=str(device.info), shaders={p.name: sha(p) for p in (ROOT/'shaders').glob('*.slang')})
    manifest['benchmark_shaders']={p.name:sha(p) for p in Path(__file__).parent.glob('*.slang')}
    modules = dict(reduce_source='guided', fit_coefficients='guided', average_coefficients='guided', apply_exposure='guided',
                   apply_exposure_production='guided', tonemap_baseline='guided',
                   setup_weights='pyramid', downsample='pyramid', reconstruct='fusion', convert_exposure='fusion')
    if output_format=='rgba8_srgb':
        modules.update(fullscreen_vertex='present',apply_fragment='present',baseline_fragment='present',reference_fragment='present')
    if variant_config.get('compute_srgb'):
        modules.update(apply_srgb_compute='present',baseline_srgb_compute='present')
    if variant_config.get('joint_upsample'):modules.update(apply_joint_compute='joint')
    if compact:
        modules.update(reduce_setup_gather='fusion_compact', guided_moments='fusion_compact', reduce_horizontal='fusion_compact', reduce_setup_vertical='fusion_compact', reduce_setup_cooperative='fusion_compact', tail_reconstruct='fusion_compact', reconstruct_ev='fusion_compact', reduce_setup='fusion_compact', reconstruct_exposure='fusion_compact', fit_compact='fusion_compact', reconstruct_compact='fusion_compact', reconstruct_guided='fusion_compact', downsample_compact='fusion_compact')
    if compact or fused_guided:
        modules['reconstruct_ev_fused'] = 'fusion_compact'
    reflections = {}
    exe = compiler()
    manifest['slangc_sha256'] = sha(exe)
    manifest['commands'] = []
    for entry, module in modules.items():
        path=Path(__file__).with_name(module+'.slang') if module in ('present','joint') else ROOT/'shaders'/f'{module}.slang'
        flags=list(FLAGS)
        if module in ('present','joint'): flags[1]='compute' if entry.endswith('_compute') else ('vertex' if entry=='fullscreen_vertex' else 'fragment')
        if module in ('fusion_compact','present'):
            flags += [f"-DWORK_X={variant_config.get('work_x',8)}",f"-DWORK_Y={variant_config.get('work_y',8)}"]
        if module=='fusion_compact':
            flags += [f"-DHALF_ROW_COEFFICIENTS={int(variant_config.get('half_row_coefficients',False))}"]
            flags += [f"-DREUSE_MOMENT_STORAGE={int(variant_config.get('reuse_moment_storage',False))}"]
            flags += [f"-DDIRECT_BATCH={variant_config.get('direct_batch',2)}", f"-DTAIL_X={variant_config.get('tail_x',8)}"]
            flags += [f"-DDIRECT_RESIDUAL_WEIGHTS={int(variant_config.get('direct_residual_weights',False))}"]
            flags += [f"-DGUIDED_GATHER_ROWS={int(variant_config.get('guided_gather_rows',False))}"]
            flags += [f"-DGUIDED_DIRECT_MOMENTS={int(variant_config.get('guided_direct_moments',False))}"]
            flags += [f"-DGUIDED_STATIC_WINDOWS={int(variant_config.get('guided_static_windows',False))}"]
            flags += [f"-DGUIDED_VERTICAL={variant_config.get('guided_vertical',1)}",f"-DGUIDED_THREADS_Y={variant_config.get('guided_threads_y',variant_config.get('tile_y',16))}"]
            flags += [f"-DGUIDED_BATCH={variant_config.get('guided_batch',1)}",f"-DGUIDED_SLIDING={int(variant_config.get('guided_sliding',False))}"]
            flags += [f"-DWAVE_REDUCTION={int(variant_config.get('wave_reduction',False))}"]
            flags += [f"-DSHARED_PADDING={variant_config.get('shared_padding',0)}",f"-DHALF_MOMENT_PRODUCTS={int(variant_config.get('half_moment_products',False))}",f"-DREDUCTION_GRID={variant_config.get('reduction_grid',4)}",f"-DGUIDED_RADIUS={variant_config.get('guided_radius',2)}",f"-DCACHED_BASELINE={int(variant_config.get('cached_baseline',False))}",f"-DLOG_EXPOSURE={int(variant_config.get('log_exposure',False))}",f"-DTILE_X={variant_config.get('tile_x',16)}",f"-DTILE_Y={variant_config.get('tile_y',16)}",f"-DSEPARABLE_GUIDED={int(variant_config.get('separable_guided',False))}",f"-DREDUCTION_LOAD={int(variant_config.get('reduction_load',False))}",f"-DREUSE_SHARED={int(variant_config.get('reuse_shared',False))}",f"-DSINGLE_WEIGHT={int(variant_config.get('single_weight',False))}",f"-DPRECOMPUTED_EV={int(variant_config.get('precomputed_ev',False))}",f"-DCURVE_LOG={int(variant_config.get('curve_log',False))}",f"-DRESIDUAL_PYRAMID={int(variant_config.get('residual_pyramid',False))}",f"-DPACKED_RESIDUAL={int(variant_config.get('packed_residual',False))}",f"-DPACKED_WEIGHT_BIAS={variant_config.get('packed_weight_bias',0.0)}",f"-DRESIDUAL_SCALE={variant_config.get('residual_scale',1.0)}",f"-DMOMENT_INPUT={int(variant_config.get('moment_input',False))}",f"-DLOG_PRODUCT={int(variant_config.get('log_product',False))}",f"-DSCALAR_REDUCTION={int(variant_config.get('scalar_reduction',False))}",f"-DHALF_GATHER={int(variant_config.get('half_gather',False))}",f"-DGATHER_X={variant_config.get('gather_x',8)}",f"-DGATHER_Y={variant_config.get('gather_y',8)}"]
        cmd = [str(exe), str(path), '-I',str(ROOT/'shaders'), '-entry', entry, *flags,
               '-target', 'spirv', '-o', str(out/f'{entry}.spv'),
               '-reflection-json', str(out/f'{entry}.reflection.json')]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
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
        path = f'{len(manifest["passes"]):02d}-{entry}.uniform.bin'
        (out/path).write_bytes(uniform)
        manifest['passes'].append(dict(entry=entry, label=label, width=w, height=h,
                                       group_size=ref['entryPoints'][0].get('threadGroupSize',[8,8,1]),
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
    add('apply_fragment' if output_format=='rgba8_srgb' else 'apply_exposure_production','apply_exposure_production',width,height,
        dict(fullSource=view('source'),lowExposure=view('exposure'),averagedCoefficients=view('averaged'),colorOutput=view('final')))
    if output_format=='rgba8_srgb': manifest['passes'][-1]['attachment']='final'
    add('baseline_fragment' if output_format=='rgba8_srgb' else 'tonemap_baseline','tonemap_baseline',width,height,dict(fullSource=view('source'),colorOutput=view('baseline')),baseline=True)
    if output_format=='rgba8_srgb': manifest['passes'][-1]['attachment']='baseline'
    # A separate untimed device process runs the existing viewer application
    # entry as the same-GPU reference. Its debug textures never exist in the
    # measured process. Cross-vendor desktop comparison is reported separately.
    add('apply_exposure','viewer_reference',width,height,
        dict(fullSource=view('source'),lowExposure=view('exposure'),averagedCoefficients=view('averaged'),
             colorOutput=view('viewer_linear' if output_format=='rgba8_srgb' else 'final'),
             baseOutput=view('viewer_base' if output_format=='rgba8_srgb' else 'baseline'),fullExposureOutput=view('debug_exposure')))
    reference_pass = manifest['passes'].pop()
    manifest['reference_pass'] = reference_pass
    manifest['reference_resource'] = dict(name='debug_exposure',width=width,height=height,levels=1,
        format=76,format_name='r16_float',bpp=2,one_d=False,dump=False)
    if output_format=='rgba8_srgb':
        manifest['reference_resources']=[dict(name=name,width=width,height=height,levels=1,
            format=97,format_name='rgba16_float',bpp=8,one_d=False,dump=False) for name in ('viewer_linear','viewer_base')]
        add('reference_fragment','reference_resolve',width,height,dict(fullSource=view('viewer_linear')))
        manifest['reference_resolve']=manifest['passes'].pop()
        manifest['reference_resolve']['attachment']='final'
    if compact:
        import copy
        # Reference process runs the entire unfused graph, not merely its final entry.
        manifest['unfused_passes']=copy.deepcopy(manifest['passes'])
        manifest['unfused_resources']=copy.deepcopy(resources)
        resources[:]=[r for r in resources if r['name']!='reduced']
        next(r for r in resources if r['name']=='reconstructed')['dump']=False
        resources.append(dict(name='compact',width=w,height=h,levels=1,format=103,
                              format_name='rg32_float',bpp=8,one_d=False,dump=False))
        weight_resource=next(r for r in resources if r['name']=='weights')
        weight_resource.update(format=103,format_name='rg32_float',bpp=8)
        lum=np.fromfile(out/'luminance.reference.bin',np.float32).reshape(-1,4)
        weights=np.fromfile(out/'weights.reference.bin',np.float32).reshape(-1,4)
        lum[...,3]=weights[...,0]
        lum.tofile(out/'luminance.reference.bin')
        weights[...,1:3].copy().tofile(out/'weights.reference.bin')
        old_passes=manifest['passes']
        manifest['passes']=[]
        if variant_config.get('residual_pyramid'):
            resources.append(dict(name='base_lightness',width=w,height=h,levels=1,format=100,format_name='r32_float',bpp=4,one_d=False,dump=False))
        if variant_config.get('separable_reduction'):
            resources.append(dict(name='horizontal',width=w,height=h*4,levels=1,format=103,format_name='rg32_float',bpp=8,one_d=False,dump=False))
            add('reduce_horizontal','reduce_horizontal',w,h*4,dict(fullSource=view('source'),horizontalOutput=view('horizontal')))
        add('reduce_setup_vertical' if variant_config.get('separable_reduction') else ('reduce_setup_cooperative' if variant_config.get('cooperative_reduction') else ('reduce_setup_gather' if variant_config.get('gather_reduction') else 'reduce_setup')),'reduce_setup',w,h,dict(fullSource=view('source'),compactOutput=view('compact'),**(dict(horizontalSource=view('horizontal')) if variant_config.get('separable_reduction') else {}),
            lightnessOutput=view('luminance'),weightsOutput=view('weights'),**(dict(baseLightnessOutput=view('base_lightness')) if variant_config.get('residual_pyramid') else {})))
        if variant_config.get('cooperative_reduction'):manifest['passes'][-1]['dispatch_groups']=[(w+7)//8,(h+7)//8,1]
        # A tail candidate only launches when its complete shared footprint fits.
        tail_mip=1
        while tail_mip<levels-1 and (max(1,w>>tail_mip)>variant_config.get('tail_max_width',32) or max(1,h>>tail_mip)>variant_config.get('tail_max_height',16)):tail_mip+=1
        use_tail=variant_config.get('tail_fusion') and tail_mip<levels-1
        manifest['config']['tail_mip']=tail_mip if use_tail else None
        fuse_fine = (variant_config.get('fused_fine_reconstruction', False)
                     and variant_config.get('residual_pyramid') and variant_config.get('precomputed_ev')
                     and levels > 3 and (not use_tail or tail_mip >= 3))
        manifest['config']['fused_fine_reconstruction'] = bool(fuse_fine)
        for mip in range(1,tail_mip+1 if use_tail else levels):
            add('downsample_compact',f'pyramids_mip{mip}',max(1,w>>mip),max(1,h>>mip),
                dict(coarseLuminance=view('luminance',mip-1),layerWeights=view('weights',mip-1),
                     lightnessOutput=view('luminance',mip),weightsOutput=view('weights',mip)))
        if use_tail:
            add('tail_reconstruct',f'tail_from_mip{tail_mip}',max(1,w>>tail_mip),max(1,h>>tail_mip),
                dict(fineLuminance=view('luminance',tail_mip),layerWeights=view('weights',tail_mip),reconstructionOutput=view('reconstructed',tail_mip)),dict(tailLevels=levels-tail_mip))
            # Logical image size is retained, but one 8x8 workgroup covers all pixels.
            manifest['passes'][-1]['dispatch_groups']=[1,1,1]
        for mip in reversed(range(1,tail_mip if use_tail else levels)):
            if fuse_fine and mip < 3:
                continue
            add('reconstruct_compact',f'reconstruct_mip{mip}',max(1,w>>mip),max(1,h>>mip),
                dict(fineLuminance=view('luminance',mip),coarseLuminance=view('luminance',min(mip+1,levels-1)),
                     layerWeights=view('weights',mip),previousResult=view('exposure') if mip==levels-1 else view('reconstructed',mip+1),
                     reconstructionOutput=view('reconstructed',mip)),dict(isCoarsest=mip==levels-1))
        add('reconstruct_exposure','reconstruct_exposure',w,h,dict(compactSource=view('compact'),
            fineLuminance=view('luminance'),coarseLuminance=view('luminance',min(1,levels-1)),
            layerWeights=view('weights'),previousResult=view('reconstructed',min(1,levels-1)),
            exposureOutput=view('exposure'),inverseLut=view('inverse'),**(dict(baseLightness=view('base_lightness')) if variant_config.get('residual_pyramid') else {})),dict(isCoarsest=levels==1))
        add('fit_compact','fit_compact',w,h,dict(compactSource=view('compact'),lowExposure=view('exposure'),
            coefficientOutput=view('coefficients')))
        manifest['passes'].extend(p for p in old_passes if p['label'] in
            ('average_coefficients','apply_exposure_production','tonemap_baseline'))
        manifest['config']['compact']=True
        if fused_guided:
            compact_passes=manifest['passes']
            manifest['passes']=[]
            if variant_config.get('precomputed_ev'):
                resources.append(dict(name='guide_ev',width=w,height=h,levels=1,format=103,format_name='rg32_float',bpp=8,one_d=False,dump=False))
                add('reconstruct_ev_fused' if fuse_fine else 'reconstruct_ev','reconstruct_ev',w,h,dict(compactSource=view('compact'),compactOutput=view('guide_ev'),
                    fineLuminance=view('luminance'),coarseLuminance=view('luminance',min(1,levels-1)),layerWeights=view('weights'),
                    previousResult=view('reconstructed',3 if fuse_fine else min(1,levels-1)),inverseLut=view('inverse'),
                    **(dict(mip1Weights=view('weights',1),mip2Weights=view('weights',2),mip2Luminance=view('luminance',2),mip3Luminance=view('luminance',3)) if fuse_fine else {}),
                    **(dict(baseLightness=view('base_lightness')) if variant_config.get('residual_pyramid') else {})),dict(isCoarsest=levels==1))
            if variant_config.get('moment_input'):
                resources.append(dict(name='moments',width=w,height=h,levels=1,format=109,format_name='rgba32_float',bpp=16,one_d=False,dump=False))
                add('guided_moments','guided_moments',w,h,dict(compactSource=view('guide_ev'),momentOutput=view('moments')))
            add('reconstruct_guided','reconstruct_guided',w,h,dict(compactSource=view('guide_ev' if variant_config.get('precomputed_ev') else 'compact'),
                fineLuminance=view('luminance'),coarseLuminance=view('luminance',min(1,levels-1)),
                layerWeights=view('weights'),previousResult=view('reconstructed',min(1,levels-1)),
                averagedOutput=view('averaged'),inverseLut=view('inverse'),**(dict(momentSource=view('moments')) if variant_config.get('moment_input') else {})),dict(isCoarsest=levels==1))
            if variant_config.get('guided_vertical'):
                manifest['passes'][-1]['dispatch_groups']=[(w+15)//16,(h+15)//16,1]
            fused_passes=manifest['passes'][:]
            manifest['passes']=[]
            for p in compact_passes:
                if p['entry']=='reconstruct_exposure': manifest['passes'].extend(fused_passes)
                elif p['entry'] not in ('fit_compact','average_coefficients'): manifest['passes'].append(p)
            resources[:]=[r for r in resources if r['name'] not in ('exposure','coefficients')]
            for p in manifest['passes']:
                for d in p['descriptors']:
                    if d.get('resource')=='exposure': d['resource']='compact'
            manifest['config']['fused_guided']=True

    if variant_config.get('joint_upsample'):
        manifest['passes']=[p for p in manifest['passes'] if p['entry']!='reconstruct_guided']
        resources[:]=[r for r in resources if r['name']!='averaged']
    if variant_config.get('compute_srgb'):
        if 'unfused_passes' not in manifest:
            import copy
            manifest['unfused_passes']=copy.deepcopy(manifest['passes'])
            manifest['unfused_resources']=copy.deepcopy(resources)
        chain=manifest['passes']
        manifest['passes']=[]
        add('apply_joint_compute' if variant_config.get('joint_upsample') else 'apply_srgb_compute','apply_exposure_production',width,height,dict(fullSource=view('source'),
            lowExposure=view('compact' if fused_guided else 'exposure'),averagedCoefficients=view('averaged'),srgbOutput=view('final'),**(dict(jointGuideExposure=view('guide_ev')) if variant_config.get('joint_upsample') else {})))
        add('baseline_srgb_compute','tonemap_baseline',width,height,dict(fullSource=view('source'),srgbOutput=view('baseline')),baseline=True)
        manifest['passes']=chain[:-2]+manifest['passes']
        for r in resources:
            if r['name'] in ('final','baseline'):
                r.pop('attachment',None)
                r['storage_view_format']=37 # UNORM view; image format remains R8G8B8A8_SRGB.
    manifest['config']['variant']=variant
    manifest['config']['variant_settings']=variant_config
    if variant_config.get('half_aux'):
        for r in resources:
            if r['name'] in ('weights','averaged') and not (r['name']=='weights' and (variant_config.get('weight_unorm') or variant_config.get('residual_pyramid'))):
                r.update(format=83,format_name='rg16_float',bpp=4)
                file=out/(r['name']+'.reference.bin')
                np.fromfile(file,np.float32).astype(np.float16).tofile(file)
    if variant_config.get('residual_pyramid'):
        next(r for r in resources if r['name']=='luminance').update(**(dict(format=103,format_name='rg32_float',bpp=8) if variant_config.get('residual_float') else dict(format=83,format_name='rg16_float',bpp=4)))
        next(r for r in resources if r['name']=='weights').update(format=77,format_name='rg16_unorm',bpp=4)
        lum=np.fromfile(out/'luminance.reference.bin',np.float32).reshape(-1,4)
        weights=np.fromfile(out/'weights.reference.bin',np.float32).reshape(-1,2)
        if variant_config.get('packed_residual'):
            next(r for r in resources if r['name']=='luminance').update(format=97,format_name='rgba16_float',bpp=8)
            resources[:]=[r for r in resources if r['name']!='weights']
            np.stack([(lum[:,0]-lum[:,1])*variant_config.get('residual_scale',1),(lum[:,2]-lum[:,1])*variant_config.get('residual_scale',1),lum[:,3]-variant_config.get('packed_weight_bias',0),weights[:,1]-variant_config.get('packed_weight_bias',0)],axis=-1).astype(np.float16).tofile(out/'luminance.reference.bin')
        else:np.stack([(lum[:,0]-lum[:,1])*variant_config.get('residual_scale',1),(lum[:,2]-lum[:,1])*variant_config.get('residual_scale',1)],axis=-1).astype(np.float32 if variant_config.get('residual_float') else np.float16).tofile(out/'luminance.reference.bin')
        np.rint(np.clip(np.stack([lum[:,3],weights[:,1]],axis=-1),0,1)*65535).astype(np.uint16).tofile(out/'weights.reference.bin')
        if variant_config.get('packed_snorm'):
            next(r for r in resources if r['name']=='luminance').update(format=92,format_name='rgba16_snorm',bpp=8)
            packed=np.stack([lum[:,0]-lum[:,1],lum[:,2]-lum[:,1],lum[:,3],weights[:,1]],axis=-1)
            np.rint(np.clip(packed,-1,1)*32767).astype(np.int16).tofile(out/'luminance.reference.bin')
    elif variant_config.get('weight_unorm'):
        next(r for r in resources if r['name']=='weights').update(format=70,format_name='r16_unorm',bpp=2)
        file=out/'weights.reference.bin'
        np.rint(np.clip(np.fromfile(file,np.float32).reshape(-1,2)[:,0],0,1)*65535).astype(np.uint16).tofile(file)
    elif variant_config.get('single_weight'):
        next(r for r in resources if r['name']=='weights').update(format=76,format_name='r16_float',bpp=2)
        file=out/'weights.reference.bin'
        np.fromfile(file,np.float16).reshape(-1,2)[:,0].copy().tofile(file)
    for r in resources:
        if (r['name']=='guide_ev' and variant_config.get('half_guide')) or (r['name']=='compact' and variant_config.get('half_compact')):
            r.update(format=83,format_name='rg16_float',bpp=4)
    if variant_config.get('readonly_input'):
        for r in resources:
            if r['name'] in ('source','inverse'):r['sampled_only']=True
    manifest['files'] = {p.name:sha(p) for p in out.iterdir() if p.suffix in ('.bin','.spv')}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    draws=sum('attachment' in p for p in manifest['passes'] if not p['baseline'])
    print(f'Prepared {width}x{height}, {len(manifest["passes"])-1-draws} compute dispatches + {draws} draws', flush=True)
    return manifest
