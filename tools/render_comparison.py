"""Maintain README reference/optimized images; --check detects stale artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw

OUT = ROOT / 'docs/images/comparison'
SCENES = ['sundowner_deck', 'veranda']
SETTINGS = dict(width=1920, height=1080, global_ev=0.0, bracket_ev=1.2,
                sigma=0.2, fusion_scale=4, input_format='R11G11B10_FLOAT')


def digest(path):
    data = path.read_bytes()
    if path.suffix in {'.py', '.slang', '.txt'}:
        data = data.replace(b'\r\n', b'\n')  # Stable across Git checkout line endings.
    return hashlib.sha256(data).hexdigest()


def sources():
    paths = [ROOT / name for name in ['tone_mapper.py', 'zcurve.py', 'requirements.txt',
             'tools/render_comparison.py', 'tools/profiling/android/quality.py',
             'tools/profiling/android/quality_sweep.py', 'tools/profiling/android/variants.py',
             'tools/profiling/android/pack_source.slang']]
    paths += sorted((ROOT / 'shaders').rglob('*.slang'))
    paths += [ROOT / 'Assets' / f'{scene}_4k.exr' for scene in SCENES]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}


def heatmap(error):
    # Fixed scale shared by all scenes: black=0, blue=1, cyan=3, yellow=6, red>=12.
    stops = [0, 1, 3, 6, 12]
    colors = np.array([[0, 0, 0], [40, 65, 180], [0, 220, 220],
                       [255, 220, 0], [255, 40, 20]])
    return np.stack([np.interp(error, stops, colors[:, c]) for c in range(3)],
                    axis=-1).round().astype(np.uint8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    fingerprint = sources()
    if args.check:
        record = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
        if record['sources'] != fingerprint or record['settings'] != SETTINGS:
            raise SystemExit('Comparison is stale: run python tools/render_comparison.py')
        for name, expected in record['artifacts'].items():
            if not (OUT / name).exists() or digest(OUT / name) != expected:
                raise SystemExit(f'Missing or changed comparison artifact: {name}')
        print('Comparison sources, settings and artifacts are current.')
        return

    import OpenEXR
    import slangpy as spy
    from tone_mapper import ToneMapper, create_hdr_texture
    from tools.profiling.android.quality_sweep import Candidate, codes
    from tools.profiling.android.quality import image_quality
    from tools.profiling.android.variants import DEFAULT_VARIANT, VARIANTS

    device = spy.Device(enable_hot_reload=False)
    mapper = ToneMapper(device, fusion_scale=SETTINGS['fusion_scale'])
    candidate = Candidate(device, mapper, DEFAULT_VARIANT)
    session = device.create_slang_session()
    pack = device.create_compute_kernel(session.load_program(
        str(ROOT / 'tools/profiling/android/pack_source.slang'), ['pack_source']))
    OUT.mkdir(parents=True, exist_ok=True)
    w, h = SETTINGS['width'], SETTINGS['height']
    records, artifacts = [], {}

    def save(image, name):
        image.save(OUT / name)
        artifacts[name] = digest(OUT / name)

    for scene in SCENES:
        with OpenEXR.File(str(ROOT / 'Assets' / f'{scene}_4k.exr'), separate_channels=True) as exr:
            rgb = np.stack([exr.channels()[c].pixels for c in 'RGB'], axis=-1).astype(np.float32)
        rgb = np.clip(np.nan_to_num(rgb, nan=0, posinf=65535, neginf=0), 0,
                      np.array([65024, 65024, 64512], dtype=np.float32))
        rgb = np.stack([np.asarray(Image.fromarray(rgb[..., c]).resize(
            (w, h), Image.Resampling.BILINEAR)) for c in range(3)], axis=-1)
        source = create_hdr_texture(device, np.concatenate([rgb, np.ones((h, w, 1), np.float32)], axis=-1))
        packed = mapper.create_texture(w, h, spy.Format.r11g11b10_float)
        pack.dispatch(thread_count=[w, h, 1], vars=dict(inputTexture=source, outputTexture=packed))
        ev, bracket, sigma = SETTINGS['global_ev'], SETTINGS['bracket_ev'], SETTINGS['sigma']
        encoder = device.create_command_encoder()
        mapper.prepare_weights(encoder, packed, ev, bracket, bracket, sigma)
        mapper.prepare_result(encoder, packed, ev)
        device.submit_command_buffer(encoder.finish())
        reference_linear = mapper.final_color.to_numpy()
        optimized_linear, coefficients = candidate.render(packed, ev, bracket, sigma)
        if not all(np.isfinite(x).all() for x in [reference_linear, optimized_linear, coefficients]):
            raise RuntimeError(f'{scene}: non-finite render')
        reference, optimized = codes(reference_linear), codes(optimized_linear)
        quality = image_quality(reference, optimized)
        if not quality['accepted']:
            raise RuntimeError(f'{scene}: quality gate failed: {quality}')
        error = abs(reference.astype(np.int16) - optimized.astype(np.int16)).max(axis=-1)
        for name, pixels in [('reference', reference), ('optimized', optimized), ('error', heatmap(error))]:
            save(Image.fromarray(pixels), f'{scene}-{name}.png')
        # Peak pooling keeps sparse errors visible in the README preview.
        peak = error.reshape(h // 3, 3, w // 3, 3).max(axis=(1, 3))
        sheet = Image.new('RGB', (1920, 426), (22, 24, 29))
        draw = ImageDraw.Draw(sheet)
        for i, (pixels, label) in enumerate([(reference, 'Full reference'),
                                            (optimized, 'Optimized default')]):
            sheet.paste(Image.fromarray(pixels).resize((640, 360), Image.Resampling.LANCZOS), (640 * i, 26))
            draw.text((640 * i + 10, 7), label, fill='white')
        sheet.paste(Image.fromarray(heatmap(peak)), (1280, 26))
        draw.text((1290, 7), 'Error: max |RGB difference|, sRGB8 codes', fill='white')
        legend = heatmap(np.tile(np.linspace(0, 12, 240), (10, 1)))
        sheet.paste(Image.fromarray(legend), (1290, 392))
        for tick in [0, 1, 3, 6, 12]:
            draw.text((1290 + round(tick / 12 * 239), 405), str(tick), fill='white')
        draw.text((1550, 392), 'Fixed scale; 3x3 peak-error preview', fill='white')
        draw.text((10, 393), f'RMSE {quality["rmse_codes"]:.3f} codes | max {quality["max_codes"]:.0f} codes', fill='white')
        save(sheet, f'{scene}-comparison.png')
        records.append(dict(scene=scene, quality=quality))
        print(scene, quality, flush=True)
    record = dict(settings=SETTINGS, variant=DEFAULT_VARIANT, variant_config=VARIANTS[DEFAULT_VARIANT],
                  backend=dict(api=device.info.api_name, adapter=device.info.adapter_name),
                  sources=fingerprint, artifacts=artifacts, scenes=records,
                  reference='Independent unfused ToneMapper; full pyramid; quarter-width/height fusion + Guided.',
                  comparison='Same desktop backend, packed HDR input, calibration and final sRGB8 encoding; not phone captures.',
                  error='Absolute sRGB8 RGB error; heatmap max channel, fixed 0..12 scale; preview 3x3 max pooled.')
    (OUT / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
