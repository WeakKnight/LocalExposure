"""Regenerate README comparisons: .venv/Scripts/python.exe tools/render_examples.py."""
from pathlib import Path
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import slangpy as spy
from tone_mapper import ROOT, load_exr, create_hdr_texture
from tools.profiling.controls.legacy_guided import LegacyGuidedToneMapper
from tools.profiling.android.quality_sweep import Candidate, codes
from tools.profiling.android.variants import DEFAULT_VARIANT
from tools.render_walkthrough import CaptureFinal, save_walkthrough


def main():
    device = spy.Device(enable_hot_reload=False)
    mapper = LegacyGuidedToneMapper(device)
    candidate = Candidate(device, mapper, DEFAULT_VARIANT)
    candidate.final = CaptureFinal(candidate.final)
    session = device.create_slang_session(compiler_options={'include_paths': [ROOT/'shaders']})
    baseline = device.create_compute_kernel(session.load_program('reference_apply.slang', ['tonemap_baseline']))
    w, h = 1200, 600
    for scene, ev in [('sundowner_deck', -2.0), ('veranda', -1.0)]:
        rgb = load_exr(device, ROOT / 'Assets' / f'{scene}_4k.exr').to_numpy()[...,:3]
        rgb = np.stack([np.asarray(Image.fromarray(rgb[...,c]).resize(
            (w,h), Image.Resampling.BILINEAR)) for c in range(3)], axis=-1)
        source = create_hdr_texture(device, np.concatenate([rgb, np.ones((h,w,1), np.float32)], axis=-1))
        output = mapper.create_texture(w,h,spy.Format.rgba16_float)
        baseline.dispatch(thread_count=[w,h,1], vars=dict(fullSource=source,
            colorOutput=output, globalEV=ev))
        before = output.to_numpy()
        encoder = device.create_command_encoder()
        mapper.prepare_weights(encoder, source, ev, 3.0, 3.0, .2)
        device.submit_command_buffer(encoder.finish())
        after, residual = candidate.render(source, ev, bracket=3.0, sigma=.2)
        if not all(np.isfinite(x).all() for x in (before, after, residual)):
            raise ValueError(f'Non-finite example: {scene}')
        for label, pixels in [('before', before), ('after', after)]:
            path = ROOT/'docs/images'/f'{scene}-{label}.png'
            Image.fromarray(codes(pixels)).save(path)
            print(f'Saved {path} ({DEFAULT_VARIANT if label == "after" else "tonemap only"})')
        if scene == 'veranda':
            save_walkthrough(device, mapper, candidate.final, baseline, source, after, ev, 3.0)
    device.wait()


if __name__ == '__main__':
    main()
