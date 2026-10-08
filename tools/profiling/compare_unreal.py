"""Matched Bart/UE images and whole-chain GPU timing on static EXR inputs.

No CPU stopwatch, visualization dispatches, diagnostic writes or cached passes
are included in timing. These are standalone ports, not Unreal engine captures.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import OpenEXR
from PIL import Image, ImageDraw
import slangpy as spy

from tone_mapper import ToneMapper, create_hdr_texture
from tools.profiling.controls.legacy_guided import LegacyGuidedToneMapper
from ue_local_exposure import UEParameters, UnrealLocalExposure
from tools.profiling.gpu_timer import GpuTimer
from tools.profiling.android.quality_sweep import codes
from tools.render_comparison import digest, heatmap
from tools.validate_asset_matrix import PRESETS


def fingerprints():
    files = [ROOT / 'tone_mapper.py', ROOT / 'ue_local_exposure.py', ROOT / 'zcurve.py',
             ROOT / 'requirements.txt', Path(__file__).resolve(),
             ROOT / 'tools/profiling/gpu_timer.py', ROOT / 'tools/validate_asset_matrix.py',
             ROOT / 'tools/profiling/android/quality_sweep.py', ROOT / 'tools/render_comparison.py',
             ROOT / 'tools/profiling/android/pack_source.slang']
    files += sorted((ROOT / 'shaders').rglob('*.slang'))
    files += sorted((ROOT / 'Assets').glob('*.exr'))
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in files}


def packed_source(device, asset, width, height, pack):
    with OpenEXR.File(str(asset), separate_channels=True) as exr:
        rgb = np.stack([exr.channels()[c].pixels for c in 'RGB'], axis=-1).astype(np.float32)
    rgb = np.clip(np.nan_to_num(rgb, nan=0, posinf=65535, neginf=0), 0, [65024, 65024, 64512])
    rgb = np.stack([np.asarray(Image.fromarray(rgb[..., c].astype(np.float32)).resize(
        (width, height), Image.Resampling.BILINEAR)) for c in range(3)], axis=-1)
    source = create_hdr_texture(device, np.concatenate([rgb, np.ones((height, width, 1), np.float32)], axis=-1))
    result = device.create_texture(width=width, height=height, format=spy.Format.r11g11b10_float,
        usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
    pack.dispatch(thread_count=[width, height, 1], vars=dict(inputTexture=source, outputTexture=result))
    device.wait()
    return result


def distribution(values):
    return dict(median_ms=float(np.median(values)), p10_ms=float(np.percentile(values, 10)),
                p90_ms=float(np.percentile(values, 90)), samples_ms=[float(x) for x in values])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--iterations', type=int, default=30)
    parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--device', choices=['automatic', 'metal', 'vulkan', 'd3d12'], default='automatic')
    parser.add_argument('--ue-profile', choices=['desktop', 'mobile'], default='desktop')
    parser.add_argument('--out', type=Path, default=ROOT / 'docs/images/unreal')
    parser.add_argument('--check', action='store_true', help='Check code and image freshness without a GPU')
    args = parser.parse_args()
    if min(args.width, args.height, args.iterations) < 1 or args.warmup < 0:
        parser.error('Dimensions and iterations must be positive; warmup must be nonnegative')
    parameters = UEParameters(profile=args.ue_profile)
    settings = dict(width=args.width, height=args.height, iterations=args.iterations, warmup=args.warmup,
                    presets=PRESETS, ue_parameters=asdict(parameters), input_format='R11G11B10_FLOAT',
                    output_format='RGBA16_FLOAT linear SDR', levels=16, sigma=.2, seed=8058)
    hashes = fingerprints()
    manifest_path = args.out / 'manifest.json'
    if args.check:
        manifest = json.loads(manifest_path.read_text())
        if manifest['sources'] != hashes or manifest['settings'] != settings:
            raise SystemExit('Stale UE comparison: regenerate with the recorded settings')
        for name, expected in manifest['artifacts'].items():
            if digest(args.out / name) != expected:
                raise SystemExit(f'Changed artifact: {name}')
        print('UE comparison sources, settings and images are current.')
        return

    device = spy.Device(type=getattr(spy.DeviceType, args.device), enable_hot_reload=False)
    timer = GpuTimer(device)
    pack = device.create_compute_kernel(device.create_slang_session().load_program(
        str(ROOT / 'tools/profiling/android/pack_source.slang'), ['pack_source']))
    bart = LegacyGuidedToneMapper(device)
    full = ToneMapper(device, fusion_scale=1)
    full.curve = bart.curve
    fusion = UnrealLocalExposure(device, 'ue-fusion', parameters=parameters)
    bilateral = UnrealLocalExposure(device, 'ue-bilateral', parameters=parameters)
    controls = {name: UnrealLocalExposure(device, name, parameters=UEParameters(profile=args.ue_profile, storage='fp32'))
                for name in ['ue-fusion', 'ue-bilateral']}
    algorithms = {'bart-guided': bart, 'bart-full': full, 'ue-fusion': fusion, 'ue-bilateral': bilateral}
    labels = {'baseline': 'Global only', 'bart-guided': 'Bart 1/4 guided', 'bart-full': 'Bart full reference',
              'ue-fusion': 'UE Fusion native', 'ue-bilateral': 'UE Bilateral native'}
    args.out.mkdir(parents=True, exist_ok=True)
    full_out = ROOT / 'outputs/unreal/comparison'
    full_out.mkdir(parents=True, exist_ok=True)
    artifacts, cases, measurements = {}, [], []
    random_order = random.Random(settings['seed'])

    def save(pixels, name):
        Image.fromarray(pixels).save(args.out / name)
        artifacts[name] = digest(args.out / name)

    def submit(record):
        encoder = device.create_command_encoder()
        record(encoder)
        device.submit_command_buffer(encoder.finish())
        device.wait()

    for asset in sorted((ROOT / 'Assets').glob('*.exr')):
        source = packed_source(device, asset, args.width, args.height, pack)
        for mapper in [fusion, bilateral, *controls.values()]:
            mapper.allocate(source)
        baseline_output = fusion.create_texture(args.width, args.height, spy.Format.rgba16_float)
        overview = Image.new('RGB', (2400, 300 * len(PRESETS)), (22, 24, 29))
        draw = ImageDraw.Draw(overview)
        precision_sheet = Image.new('RGB', (1920, 300 * len(PRESETS)), (22, 24, 29))
        precision_draw = ImageDraw.Draw(precision_sheet)

        for row, preset in enumerate(PRESETS):
            ev, hc, sc = preset['global_ev'], preset['highlight_contrast'], preset['shadow_contrast']
            def baseline(encoder):
                fusion.kernels['baseline'].dispatch(thread_count=[args.width, args.height, 1],
                    vars=dict(parameters.bindings(ev, hc, sc), hdrSource=source, colorOutput=baseline_output),
                    command_encoder=encoder)
            records = {'baseline': baseline}
            for name, mapper in algorithms.items():
                if name.startswith('bart'):
                    records[name] = lambda enc, m=mapper: m.record_processing(enc, source, ev, 6 * (1 - hc), 6 * (1 - sc))
                else:
                    records[name] = lambda enc, m=mapper: m.record_processing(enc, source, ev, hc, sc)
            pixels = {}
            for name, record in records.items():
                submit(record)
                linear = (baseline_output if name == 'baseline' else algorithms[name].final_color).to_numpy()
                if not np.isfinite(linear).all():
                    raise RuntimeError(f'{asset.stem}/{preset["name"]}/{name}: nonfinite image')
                pixels[name] = codes(linear)
                Image.fromarray(pixels[name]).save(full_out / f'{asset.stem}-{preset["name"]}-{name}.png')
            cases.append(dict(scene=asset.stem, preset=preset, finite=True))
            title = f'{asset.stem} | {preset["name"]} | EV {ev:+} | highlight {hc}, shadow {sc}'
            draw.text((8, row * 300 + 2), title, fill='white')
            for column, name in enumerate(records):
                draw.text((column * 480 + 8, row * 300 + 16), labels[name], fill='white')
                overview.paste(Image.fromarray(pixels[name]).resize((480, 270), Image.Resampling.LANCZOS),
                               (column * 480, row * 300 + 30))
            for index, (name, control) in enumerate(controls.items()):
                submit(lambda enc, m=control: m.record_processing(enc, source, ev, hc, sc))
                control_pixels = codes(control.final_color.to_numpy())
                if not np.isfinite(control.final_color.to_numpy()).all():
                    raise RuntimeError('Nonfinite FP32 precision control')
                error = abs(pixels[name].astype(np.int16) - control_pixels.astype(np.int16)).max(axis=-1)
                cases[-1][name + '_storage_error'] = dict(max_codes=int(error.max()),
                    rmse_codes=float(np.sqrt(np.mean((pixels[name].astype(float) - control_pixels) ** 2))),
                    fraction_ge12=float((error >= 12).mean()))
                precision_draw.text((index * 960 + 8, row * 300 + 2), title + ' | ' + name, fill='white')
                for col, image in enumerate([control_pixels, heatmap(error)]):
                    precision_sheet.paste(Image.fromarray(image).resize((480, 270), Image.Resampling.LANCZOS),
                                          (index * 960 + col * 480, row * 300 + 30))
                precision_draw.text((index * 960 + 8, row * 300 + 16), 'FP32 control | native storage error (0..12 codes)', fill='white')

            # Default preset timing only; all other presets remain image checks.
            if row == 0:
                for _ in range(args.warmup):
                    for record in records.values():
                        submit(record)
                durations = {name: [] for name in records}
                for _ in range(args.iterations):
                    order = list(records)
                    random_order.shuffle(order)
                    for name in order:
                        durations[name].append(timer.measure(records[name]))
                for name, samples in durations.items():
                    entry = dict(scene=asset.stem, algorithm=name, whole_chain=distribution(samples))
                    if name != 'baseline':
                        entry['incremental_over_baseline'] = distribution(np.array(samples) - durations['baseline'])
                    measurements.append(entry)
                    print(asset.stem, name, round(entry['whole_chain']['median_ms'], 4), 'GPU ms', flush=True)
        save(np.asarray(overview), asset.stem + '.png')
        save(np.asarray(precision_sheet), asset.stem + '-precision.png')
    manifest = dict(settings=settings, sources=hashes, artifacts=artifacts, cases=cases, measurements=measurements,
        backend=dict(api=device.info.api_name, adapter=device.info.adapter_name, os=platform.platform(),
                     python=platform.python_version(), slangpy=spy.__version__, timer=timer.kind),
        scope='Static bilinear-resized EXRs; same packed input and ACES RGBA16F output. No UE engine capture, '
              'game HDR producer, auto-eye-adaptation history, display, GUI, diagnostic outputs, uploads, '
              'calibration, compilation or resource allocation in GPU timing. Bart viewer reference graphs; '
              'mobile optimized fine-residual DEFAULT_VARIANT is a separate implementation, not timed here.',
        timing='Single whole-command submission per measurement. All passes recomputed; randomized interleaving. '
               'Incremental samples subtract same-round global-only sample. No per-pass sums.')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
