"""Production texture traffic models; neither model measures physical DRAM traffic."""
import argparse
import json
from pathlib import Path


def estimate(manifest, fps=45):
    resources = {r['name']: r for r in manifest['resources']}
    def size(name, mip=0):
        r = resources[name]
        return max(1, r['width'] >> mip) * max(1, r['height'] >> mip) * r['bpp']
    rows = []
    for p in manifest['passes']:
        if p['baseline']:
            continue
        n = p['width'] * p['height']
        descriptors = {d['name']: d for d in p['descriptors'] if 'resource' in d}
        reads, writes = {}, {}
        taps = 0
        def read(binding, count=1, filtered=False):
            nonlocal taps
            d = descriptors[binding]
            r = resources[d['resource']]
            reads[(d['resource'], d['mip'])] = size(d['resource'], d['mip'])
            taps += count * r['bpp'] * (2 if r.get('one_d') else 4) if filtered else count * r['bpp']
        def write(binding):
            d = descriptors[binding]
            writes[(d['resource'], d['mip'])] = size(d['resource'], d['mip'])
        entry = p['entry']
        if entry == 'tail_reconstruct':
            read('fineLuminance',n);read('layerWeights',n);write('reconstructionOutput')
        elif entry == 'downsample_compact':
            read('coarseLuminance',n*4,True)
            if 'layerWeights' in descriptors:read('layerWeights',n*4,True)
            write('lightnessOutput')
            if 'weightsOutput' in descriptors:write('weightsOutput')
        elif entry == 'guided_moments':
            read('compactSource',n*5,True);write('momentOutput')
        elif entry == 'reconstruct_guided':
            gx,gy=p['group_size'][:2]
            config=manifest['config'].get('variant_settings',{})
            threads=gx*gy
            gx,gy=config.get('tile_x',gx),config.get('tile_y',16 if config.get('guided_vertical') else gy)
            radius=config.get('guided_radius',2)
            loads=((p['width']+gx-1)//gx)*((p['height']+gy-1)//gy)*(gx+4*radius)*(gy+4*radius)
            if config.get('guided_direct_moments'):
                groups=((p['width']+gx-1)//gx)*((p['height']+gy-1)//gy)
                # A batch shares its horizontal halo. Count the per-thread anchor
                # too; texture cache/broadcast savings are unknown.
                batch=config.get('direct_batch',2)
                loads=groups*(((gx+2*radius+batch-1)//batch)*(gy+4*radius)*(batch+2*radius)+threads)
            if 'momentSource' in descriptors:
                coefficient_loads=((p['width']+gx-1)//gx)*((p['height']+gy-1)//gy)*(gx+2*radius)*(gy+2*radius)
                read('momentSource',coefficient_loads*3,True);write('averagedOutput')
            elif manifest['config'].get('variant_settings',{}).get('precomputed_ev'):
                read('compactSource',loads);write('averagedOutput')
            else:
                read('fineLuminance',loads); read('layerWeights',loads)
                if resources['luminance']['levels']>1:
                    read('coarseLuminance',loads,True); read('previousResult',loads,True)
                read('compactSource',loads); read('inverseLut',loads,True); write('averagedOutput')
        elif entry == 'reduce_horizontal':
            read('fullSource',n*4,True);write('horizontalOutput')
        elif entry == 'reduce_setup_vertical':
            read('horizontalSource',n*2,True);write('compactOutput');write('lightnessOutput')
            if 'weightsOutput' in descriptors:write('weightsOutput')
            if 'baseLightnessOutput' in descriptors:write('baseLightnessOutput')
        elif entry in ('reduce_setup','reduce_setup_cooperative','reduce_setup_gather'):
            gather=(entry=='reduce_setup_gather' or (entry=='reduce_setup_cooperative' and manifest['config'].get('variant_settings',{}).get('wave_reduction'))) and manifest['width']==4*p['width'] and manifest['height']==4*p['height']
            read('fullSource', n*(12 if gather else manifest['config'].get('variant_settings',{}).get('reduction_grid',4)**2), True); write('compactOutput'); write('lightnessOutput')
            if 'weightsOutput' in descriptors:write('weightsOutput')
            if 'baseLightnessOutput' in descriptors:write('baseLightnessOutput')
        elif entry == 'reconstruct_ev':
            read('fineLuminance',n);read('coarseLuminance',n,True);read('previousResult',n,True)
            if 'layerWeights' in descriptors:read('layerWeights',n)
            read('compactSource',n);read('inverseLut',n,True);write('compactOutput')
            if 'baseLightness' in descriptors:read('baseLightness',n)
        elif entry == 'reconstruct_exposure':
            read('fineLuminance', n)
            if 'layerWeights' in descriptors:read('layerWeights', n)
            if resources['luminance']['levels']>1:
                read('coarseLuminance', n, True); read('previousResult', n, True)
            read('compactSource',n); read('inverseLut',n,True); write('exposureOutput')
        elif entry == 'fit_compact':
            loads=((p['width']+7)//8)*((p['height']+7)//8)*144
            read('compactSource',loads); read('lowExposure',loads); write('coefficientOutput')
        elif entry == 'reduce_source':
            read('fullSource', n*16, True); write('reducedOutput')
        elif entry == 'setup_weights':
            read('hdrSource', n); write('luminanceOutput'); write('weightOutput')
        elif entry == 'downsample':
            read('inputTexture', n*4, True); write('outputTexture')
        elif entry in ('reconstruct','reconstruct_compact'):
            read('fineLuminance', n)
            if 'layerWeights' in descriptors:read('layerWeights', n)
            mip = descriptors['fineLuminance']['mip']
            if mip < resources['luminance']['levels']-1:
                read('coarseLuminance', n, True); read('previousResult', n, True)
            write('reconstructionOutput')
        elif entry == 'convert_exposure':
            read('hdrSource', n); read('fusedLightness', n)
            read('inverseLut', n, True); write('exposureOutput')
        elif entry == 'fit_coefficients':
            loads = ((p['width']+7)//8)*((p['height']+7)//8)*144
            read('reducedSource', loads); read('lowExposure', loads); write('coefficientOutput')
        elif entry == 'average_coefficients':
            loads = ((p['width']+7)//8)*((p['height']+7)//8)*144
            read('coefficients', loads); write('averagedOutput')
        elif entry in ('apply_exposure_production','apply_fragment','apply_srgb_compute','apply_joint_compute'):
            # Source read + final write cancel against matched tonemap baseline.
            if 'jointGuideExposure' in descriptors:read('jointGuideExposure',n*4)
            else:read('averagedCoefficients', n, True)
        else:
            raise ValueError(f'Unaccounted production entry: {entry}')
        rows.append(dict(pass_name=p['label'], read_sweep_bytes=sum(reads.values()),
                         write_bytes=sum(writes.values()), expanded_read_bytes=taps))
    sweep = sum(r['read_sweep_bytes']+r['write_bytes'] for r in rows)
    expanded = sum(r['expanded_read_bytes']+r['write_bytes'] for r in rows)
    baseline = manifest['width']*manifest['height']*(resources['source']['bpp']+resources['baseline']['bpp'])
    return dict(width=manifest['width'],height=manifest['height'],fps=fps,rows=rows,fusion_scale=manifest['config'].get('fusion_scale',4),
                baseline_bytes=baseline,incremental_sweep_bytes=sweep,
                incremental_sweep_gbps=sweep*fps/1e9,
                incremental_expanded_bytes=expanded,incremental_expanded_gbps=expanded*fps/1e9,
                assumptions=[
                    'Increment over matched tonemap: final source read and output write cancel; all other production passes remain.',
                    'Sweep model charges every bound input mip once per pass, and every output once. Assumes within-pass reuse; ignores cross-pass reuse. Not a DRAM lower bound.',
                    'Expanded model includes zero-weight/duplicate texel slots even for aligned reduction samples. It charges each issued load and four texels per bilinear 2D sample (two for 1D), including duplicate/clamped taps. Not a DRAM upper bound.',
                    'Default reduction integrates 16 source locations; the divisible-size gather variant uses 12 component gathers covering the same 4x4 pixels. Separate guided stages load 144 entries per 8x8 group; fused guided uses output-tile halos, independently of thread-group size; direct moments count each horizontal batch and its halo plus a per-thread anchor load. Partial groups included; shared-memory accesses excluded.',
                    'Whole stored texel bytes charged even for RGB/alpha-only reads. Inverse LUT assumed queried at every low-res pixel; actual branch can skip.',
                    'No compression, cache-line transactions, write allocation, uniforms, instructions, metadata or unrelated GPU traffic modeled.',
                    'Calibration, uploads, viewer/debug resources and presentation excluded.'])


def markdown(result):
    r=result
    lines=['# Local Exposure incremental texture traffic','',
        f"{r['width']} x {r['height']}, {r['fps']:g} FPS; 1/{r['fusion_scale']} width/height guided Fusion.", '',
        '| Production pass | Read sweep MB | Write MB | Sweep total MB | Expanded taps total MB |',
        '|---|---:|---:|---:|---:|']
    for row in r['rows']:
        a,b,c = row['read_sweep_bytes'],row['write_bytes'],row['expanded_read_bytes']
        lines.append(f"| {row['pass_name']} | {a/1e6:.6f} | {b/1e6:.6f} | {(a+b)/1e6:.6f} | {(c+b)/1e6:.6f} |")
    lines += ['',f"Incremental sweep model: **{r['incremental_sweep_bytes']/1e6:.6f} MB/frame**, **{r['incremental_sweep_gbps']:.6f} GB/s**.",
        f"Incremental expanded-tap model: **{r['incremental_expanded_bytes']/1e6:.6f} MB/frame**, **{r['incremental_expanded_gbps']:.6f} GB/s**.",
        f"Matched tonemap baseline (excluded above): {r['baseline_bytes']/1e6:.6f} MB/frame.",'']
    lines += ['- '+a for a in r['assumptions']]
    return '\n'.join(lines)+'\n'


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('manifest',type=Path)
    ap.add_argument('--fps',type=float,default=45)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    result=estimate(json.loads(args.manifest.read_text()),args.fps)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
    args.out.with_suffix('.md').write_text(markdown(result),encoding='utf-8')
    print(markdown(result))
