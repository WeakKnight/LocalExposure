"""Reproduce the viewer halo, ablate initialization, and time matched static HDR.

GPU timings exclude debug outputs, display, readback, allocation and calibration.
This is a desktop EXR workload, not a game or phone performance measurement.
"""
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
from tools.profiling.controls.legacy_guided import LegacyGuidedToneMapper
from tools.profiling.gpu_timer import GpuTimer
from tools.profiling.android.quality_sweep import codes
from tools.profiling.android.quality import full_resolution_quality
from tools.render_comparison import digest, heatmap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=60)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/halo')
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error('iterations must be positive')
    args.out.mkdir(parents=True, exist_ok=True)
    device = spy.Device(enable_hot_reload=False)
    timer = GpuTimer(device)
    old = LegacyGuidedToneMapper(device)
    full = ToneMapper(device, fusion_scale=1)
    fixed = FineResidualToneMapper(device)
    hybrid = FineResidualToneMapper(device)
    for mapper in [full, fixed, hybrid]:
        mapper.curve = old.curve
    hybrid.kernels['initialize'] = device.create_compute_kernel(device.create_slang_session().load_program(
        str(Path(__file__).with_name('halo_average_first.slang')), ['initialize_average_first']))
    baseline = device.create_compute_kernel(old.session.load_program(str(ROOT / 'tools/profiling/controls/guided.slang'), ['tonemap_baseline']))
    original = load_exr(device, ROOT / 'Assets/veranda_4k.exr')
    rgba = original.to_numpy()
    small = np.stack([np.asarray(Image.fromarray(rgba[..., c]).resize((1920, 1080),
        Image.Resampling.BILINEAR)) for c in range(4)], axis=-1)
    sources = {'native-4096x2048': original, 'resized-1920x1080': create_hdr_texture(device, small)}
    settings = dict(global_ev=0, highlight_ev=2.856, shadow_ev=1.2, sigma=.2,
        source_format='RGBA32_FLOAT', output_format='RGBA16_FLOAT linear SDR',
        iterations=args.iterations, warmup=8, seed=823)
    result = dict(settings=settings, backend=dict(api=device.info.api_name,
        adapter=device.info.adapter_name, os=platform.platform(), slangpy=spy.__version__,
        driver='Apple Metal OS-bundled driver; separate driver revision not exposed by SlangPy',
        timer=timer.kind), workloads={},
        scope='Static HDR EXR, same source/calibration/ACES and output format; all passes recomputed. '
              'No graphics HDR producer, game/phone claim, GUI/debug outputs or per-pass timing sums.')
    rng = random.Random(settings['seed'])
    for workload, source in sources.items():
        mappers = dict(old_guided=old, average_first_fine_apply=hybrid, fixed=fixed, reference=full)
        pixels = {}
        for name, mapper in mappers.items():
            enc = device.create_command_encoder()
            mapper.record_processing(enc, source, 0, 2.856, 1.2, .2)
            device.submit_command_buffer(enc.finish())
            linear = mapper.final_color.to_numpy()
            if not np.isfinite(linear).all():
                raise RuntimeError('Nonfinite output: ' + name)
            pixels[name] = codes(linear)
            Image.fromarray(pixels[name]).save(args.out / f'{workload}-{name}.png')
        qualities = {name: full_resolution_quality(pixels['reference'], p)
                     for name, p in pixels.items() if name != 'reference'}
        for name in qualities:
            error = abs(pixels[name].astype(np.int16) - pixels['reference'].astype(np.int16)).max(-1)
            Image.fromarray(heatmap(error)).save(args.out / f'{workload}-{name}-error.png')
        if source.width == 4096:
            sheet = Image.new('RGB', (1440, 804), (22, 24, 29))
            for i, name in enumerate(['reference', 'old_guided', 'fixed']):
                im = Image.fromarray(pixels[name])
                ImageDraw.Draw(sheet).text((i * 480 + 8, 5), name, fill='white')
                sheet.paste(im.resize((480, 240), Image.Resampling.LANCZOS), (i * 480, 24))
                sheet.paste(im.crop((2150, 560, 2850, 1310)).resize((480, 514)), (i * 480, 266))
            sheet.save(args.out / 'edge-comparison.png')
        output = old.create_texture(source.width, source.height, spy.Format.rgba16_float)
        records = {'baseline': lambda enc: baseline.dispatch(thread_count=[source.width, source.height, 1],
            vars=dict(fullSource=source, colorOutput=output, globalEV=0), command_encoder=enc)}
        for name, mapper in [('old_guided', old), ('fixed', fixed)]:
            records[name] = lambda enc, m=mapper: m.record_processing(enc, source, 0, 2.856, 1.2, .2)
        for _ in range(settings['warmup']):
            for record in records.values():
                timer.measure(record)
        samples = {name: [] for name in records}
        for _ in range(args.iterations):
            order = list(records)
            rng.shuffle(order)
            for name in order:
                samples[name].append(timer.measure(records[name]))
        timings = {}
        for name, values in samples.items():
            timings[name] = dict(median_ms=float(np.median(values)),
                p10_ms=float(np.percentile(values, 10)), p90_ms=float(np.percentile(values, 90)), samples_ms=values)
            if name != 'baseline':
                timings[name]['increment_median_ms'] = float(np.median(np.array(values) - samples['baseline']))
        result['workloads'][workload] = dict(quality=qualities, timing=timings)
        print(workload, json.dumps(dict(quality=qualities, timing={k: {a: b for a, b in v.items()
            if a != 'samples_ms'} for k, v in timings.items()})), flush=True)
    paths = [ROOT / name for name in ['tone_mapper.py', 'fine_residual.py', 'fusion_lookup.py',
        'zcurve.py', 'tools/profiling/diagnose_halo.py', 'tools/profiling/halo_average_first.slang',
        'tools/profiling/gpu_timer.py', 'Assets/veranda_4k.exr']]
    paths += sorted((ROOT / 'shaders').rglob('*.slang'))
    paths += [ROOT / 'tools/profiling/controls/legacy_guided.py',
              ROOT / 'tools/profiling/controls/guided.slang']
    result['sources'] = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    (args.out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
