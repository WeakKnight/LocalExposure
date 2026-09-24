"""Validate every EXR at representative UI parameters against the independent reference."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw
from tools.render_comparison import digest, heatmap, sources

PRESETS = [
    dict(name='default', global_ev=0, highlight_contrast=.8, shadow_contrast=.8),
    dict(name='dark-shadow-lift', global_ev=-2, highlight_contrast=.9, shadow_contrast=.5),
    dict(name='bright-highlight-protection', global_ev=2, highlight_contrast=.5, shadow_contrast=.9),
    dict(name='strong-balanced', global_ev=0, highlight_contrast=.5, shadow_contrast=.5),
]
OUT = ROOT / 'docs/images/parameter-matrix'
FULL = ROOT / 'outputs/quality/parameter-matrix'
SETTINGS = dict(width=1920, height=1080, sigma=.2, fusion_scale=4,
                input_format='R11G11B10_FLOAT', output_encoding='sRGB8', presets=PRESETS)


def fingerprint():
    result = sources()
    for path in [Path(__file__).resolve(), ROOT / 'main.py', *sorted((ROOT / 'Assets').glob('*.exr'))]:
        result[path.relative_to(ROOT).as_posix()] = digest(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check source and artifact freshness without a GPU')
    args = parser.parse_args()
    hashes = fingerprint()
    if args.check:
        record = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
        if record['sources'] != hashes or record['settings'] != SETTINGS:
            raise SystemExit('Stale parameter matrix: run python tools/validate_asset_matrix.py')
        for name, expected in record['artifacts'].items():
            if not (OUT / name).exists() or digest(OUT / name) != expected:
                raise SystemExit(f'Missing or changed artifact: {name}')
        print('Parameter matrix sources, settings and artifacts are current.')
        raise SystemExit(0 if record['accepted'] else 1)

    import OpenEXR
    import slangpy as spy
    from main import contrast_scale_to_ev
    from tone_mapper import ToneMapper, create_hdr_texture
    from tools.profiling.android.quality import image_quality
    from tools.profiling.android.quality_sweep import Candidate, codes
    from tools.profiling.android.variants import DEFAULT_VARIANT, VARIANTS

    device = spy.Device(enable_hot_reload=False)
    mapper = ToneMapper(device, fusion_scale=4)
    candidate = Candidate(device, mapper, DEFAULT_VARIANT)
    pack = device.create_compute_kernel(device.create_slang_session().load_program(
        str(ROOT / 'tools/profiling/android/pack_source.slang'), ['pack_source']))
    OUT.mkdir(parents=True, exist_ok=True)
    FULL.mkdir(parents=True, exist_ok=True)
    w, h = SETTINGS['width'], SETTINGS['height']
    records, artifacts = [], {}
    assets = sorted((ROOT / 'Assets').glob('*.exr'))
    if not assets:
        raise RuntimeError('No EXR test assets found')
    for asset in assets:
        with OpenEXR.File(str(asset), separate_channels=True) as exr:
            rgb = np.stack([exr.channels()[c].pixels for c in 'RGB'], axis=-1).astype(np.float32)
        rgb = np.clip(np.nan_to_num(rgb, nan=0, posinf=65535, neginf=0), 0,
                      np.array([65024, 65024, 64512], dtype=np.float32))
        rgb = np.stack([np.asarray(Image.fromarray(rgb[..., c]).resize(
            (w, h), Image.Resampling.BILINEAR)) for c in range(3)], axis=-1)
        source = create_hdr_texture(device, np.concatenate([rgb, np.ones((h, w, 1), np.float32)], axis=-1))
        packed = mapper.create_texture(w, h, spy.Format.r11g11b10_float)
        pack.dispatch(thread_count=[w, h, 1], vars=dict(inputTexture=source, outputTexture=packed))
        sheet = Image.new('RGB', (1920, 400 * len(PRESETS)), (22, 24, 29))
        draw = ImageDraw.Draw(sheet)
        for index, preset in enumerate(PRESETS):
            ev = preset['global_ev']
            highlight = contrast_scale_to_ev(preset['highlight_contrast'])
            shadow = contrast_scale_to_ev(preset['shadow_contrast'])
            encoder = device.create_command_encoder()
            mapper.prepare_weights(encoder, packed, ev, highlight, shadow, SETTINGS['sigma'])
            mapper.prepare_result(encoder, packed, ev)
            device.submit_command_buffer(encoder.finish())
            reference_linear = mapper.final_color.to_numpy()
            optimized_linear, coefficients = candidate.render(packed, ev, sigma=SETTINGS['sigma'],
                                                              highlight_ev=highlight, shadow_ev=shadow)
            finite = all(np.isfinite(x).all() for x in [reference_linear, optimized_linear, coefficients])
            key = f'{asset.stem}-{preset["name"]}'
            if not finite:
                records.append(dict(scene=asset.stem, preset=preset, quality=dict(accepted=False, finite=False)))
                print(key, 'NON-FINITE', flush=True)
                continue
            reference, optimized = codes(reference_linear), codes(optimized_linear)
            quality = image_quality(reference, optimized)
            error = abs(reference.astype(np.int16) - optimized.astype(np.int16)).max(axis=-1)
            quality['pixels_over4'] = int((error > 4).sum())
            quality['pixels_over12'] = int((error > 12).sum())
            full_artifacts = {}
            for label, pixels in [('reference', reference), ('optimized', optimized), ('error', heatmap(error))]:
                path = FULL / f'{key}-{label}.png'
                Image.fromarray(pixels).save(path)
                full_artifacts[path.relative_to(ROOT).as_posix()] = digest(path)
            peak = error.reshape(h // 3, 3, w // 3, 3).max(axis=(1, 3))
            top = index * 400
            title = f'{preset["name"]} | EV {ev:+} | Highlight {preset["highlight_contrast"]} / Shadow {preset["shadow_contrast"]}'
            draw.text((8, top + 5), title, fill='white')
            for column, pixels in enumerate([reference, optimized, heatmap(peak)]):
                image = Image.fromarray(pixels)
                if column < 2:
                    image = image.resize((640, 360), Image.Resampling.LANCZOS)
                sheet.paste(image, (column * 640, top + 22))
            draw.text((8, top + 384), f'Full reference | optimized | error (0 black, 1 blue, 3 cyan, 6 yellow, >=12 red). '
                      f'RMSE {quality["rmse_codes"]:.3f}; max {quality["max_codes"]:.0f}; '
                      f'{"PASS" if quality["accepted"] else "FAIL"}', fill='white')
            y, x = np.unravel_index(error.argmax(), error.shape)
            x0, y0 = max(0, min(w - 192, int(x) - 96)), max(0, min(h - 192, int(y) - 96))
            crop = np.concatenate([p[y0:y0 + 192, x0:x0 + 192] for p in [reference, optimized, heatmap(error)]], axis=1)
            crop_name = f'{key}-worst.png'
            Image.fromarray(crop).save(OUT / crop_name)
            artifacts[crop_name] = digest(OUT / crop_name)
            records.append(dict(scene=asset.stem, preset=preset, highlight_ev=highlight, shadow_ev=shadow,
                                quality=quality, worst_pixel_xy=[int(x), int(y)], worst_crop=crop_name,
                                full_resolution_artifacts=full_artifacts))
            print(key, quality, flush=True)
        name = f'{asset.stem}.png'
        sheet.save(OUT / name)
        artifacts[name] = digest(OUT / name)
    accepted = all(r['quality']['accepted'] for r in records)
    record = dict(settings=SETTINGS, sources=hashes, artifacts=artifacts, cases=records, accepted=accepted,
                  variant=DEFAULT_VARIANT, variant_config=VARIANTS[DEFAULT_VARIANT],
                  backend=dict(api=device.info.api_name, adapter=device.info.adapter_name),
                  comparison='Same desktop backend, not phone captures. Independent unfused full pyramid reference; '
                             'both paths use quarter-width/height Fusion, Guided upsampling and shared calibration.',
                  error='Full-resolution sRGB8 metrics. Fixed 0..12 max-channel heatmap; overview uses 3x3 peak pooling.')
    (OUT / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    lines = ['# Asset and parameter validation', '', record['comparison'], '',
             f'Result: {sum(r["quality"]["accepted"] for r in records)}/{len(records)} cases pass all fixed gates.', '',
             f'Backend: {device.info.api_name}, {device.info.adapter_name}. 1920×1080 R11G11B10 input, sigma 0.2.', '',
             'Contrast Scale uses the viewer mapping: bracket magnitude = 6 × (1 − scale) EV.', '',
             '| Scene | Preset | Global EV | Highlight / Shadow | RMSE | P99 | Max | Pixels >4 (%) | Gate |',
             '| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |']
    for r in records:
        q, p = r['quality'], r['preset']
        lines.append(f'| {r["scene"]} | {p["name"]} | {p["global_ev"]:+} | {p["highlight_contrast"]} / {p["shadow_contrast"]} | '
                     + (f'{q["rmse_codes"]:.4f} | {q["p99_codes"]:.0f} | {q["max_codes"]:.0f} | {100*q["fraction_pixels_over4"]:.5f} | '
                        if q['finite'] else '— | — | — | — | ') + ('PASS' if q['accepted'] else 'FAIL') + ' |')
    lines += ['', 'Errors are sRGB8 code values. Fixed gates: RMSE ≤0.75, P99 ≤3, max ≤12, pixels >4 ≤0.1%. '
              'Numerical gates supplement visual inspection; this is not an exhaustive parameter sweep.', '',
              'Each overview row shows reference / optimized / absolute error. The error scale is shared across all cases. '
              'Worst-pixel crops and source hashes are indexed in [manifest.json](manifest.json). '
              'Full-resolution triples are generated locally in `outputs/quality/parameter-matrix`.', '']
    for r in records:
        if not r['quality']['accepted']:
            q = r['quality']
            lines += [f'Failed case: **{r["scene"]} / {r["preset"]["name"]}**. '
                      + (f'{q["pixels_over12"]} pixels exceed 12 codes; {q["pixels_over4"]} exceed 4. '
                         f'[Worst-pixel crop]({r["worst_crop"]}) (reference / optimized / error). '
                         if q['finite'] else 'Non-finite render. ')
                      + 'The failure is retained; thresholds are unchanged.', '']
    for asset in assets:
        lines += [f'## {asset.stem}', '', f'![Comparison]({asset.stem}.png)', '']
    lines += ['Regenerate: `python tools/validate_asset_matrix.py`; check freshness: '
              '`python tools/validate_asset_matrix.py --check`. All cases run even when a numerical gate fails; '
              'the final exit code is nonzero if any case fails.', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    raise SystemExit(0 if accepted else 1)


if __name__ == '__main__':
    main()
