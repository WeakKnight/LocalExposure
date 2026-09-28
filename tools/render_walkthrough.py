"""Documentation-only inspection of an actual fine-residual render."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import slangpy as spy

from tone_mapper import ROOT
from tools.profiling.android.quality_sweep import codes
from tools.profiling.android.variants import DEFAULT_VARIANT


class CaptureFinal:
    """Retain bound textures without altering or adding production dispatches."""
    def __init__(self, kernel):
        self.kernel = kernel

    def dispatch(self, **kwargs):
        self.bindings = dict(kwargs['vars'])
        return self.kernel.dispatch(**kwargs)


def save_walkthrough(device, mapper, capture, baseline, source, after, ev, bracket):
    if 'lowResidual' not in capture.bindings:
        raise ValueError('Walkthrough requires the fine-residual production path')
    w, h = source.width, source.height
    session = device.create_slang_session(compiler_options={'include_paths': [ROOT/'shaders']})
    shader = Path(__file__).with_name('fusion_walkthrough.slang')
    inspect = device.create_compute_kernel(session.load_program(str(shader), ['inspect_fusion']))
    diagnostic = mapper.create_texture(w, h, spy.Format.rgba32_float)
    bindings = {k: v for k, v in capture.bindings.items() if k != 'colorOutput'}
    inspect.dispatch(thread_count=[w,h,1], vars={**bindings, 'weightsAndEV': diagnostic})
    values = diagnostic.to_numpy()
    if not np.isfinite(values).all():
        raise ValueError('Non-finite diagnostic readback')
    weights, local_ev = values[...,:3], values[...,3]
    if np.max(abs(weights.sum(axis=-1)-1)) > 1e-5 or weights.min() < -.001:
        raise ValueError('Unexpected decoded weight range or normalization')
    exposures = []
    output = mapper.create_texture(w,h,spy.Format.rgba16_float)
    for offset in (-bracket, 0, bracket):
        baseline.dispatch(thread_count=[w,h,1], vars=dict(fullSource=source,
            colorOutput=output, globalEV=ev+offset))
        exposures.append(codes(output.to_numpy()))

    gray = [np.repeat(np.rint(np.clip(weights[...,i],0,1)*255).astype(np.uint8)[...,None],3,axis=-1)
            for i in range(3)]
    palette = np.array([[61,135,230], [28,32,39], [255,184,67]],float)
    stops = [-3,0,3]
    ev_rgb = np.stack([np.interp(local_ev,stops,palette[:,c]) for c in range(3)],axis=-1).astype(np.uint8)
    mixture = np.rint(np.clip(weights,0,1)*255).astype(np.uint8)
    panels = [
        (exposures[0], '01  Darker exposure', f'{-bracket:+g} EV relative to global exposure'),
        (exposures[1], '02  Middle exposure', f'Global exposure only: {ev:+g} EV'),
        (exposures[2], '03  Brighter exposure', f'{bracket:+g} EV relative to global exposure'),
        (gray[0], 'Weight: darker exposure', 'Bright pixels favor highlight protection'),
        (gray[1], 'Weight: middle exposure', 'Bright pixels favor the middle exposure'),
        (gray[2], 'Weight: brighter exposure', 'Bright pixels favor lifting shadows'),
        (mixture, 'Exposure preference', 'R: darker   G: middle   B: brighter'),
        (ev_rgb, 'Applied local exposure', 'Blue: -3 EV   Dark: 0 EV   Amber: +3 EV'),
        (codes(after), 'Final optimized result', 'HDR x local exposure, then real tone mapper'),
    ]
    tile_w, tile_h, gap, header = 480, 240, 16, 70
    width = 3*tile_w + 4*gap
    sheet = Image.new('RGB',(width,3*(tile_h+header+gap)+140),(16,20,27))
    draw = ImageDraw.Draw(sheet)
    def font(size):
        try: return ImageFont.truetype('DejaVuSans.ttf',size)
        except OSError:
            try: return ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',size)
            except OSError: return ImageFont.load_default(size=size)
    draw.text((gap,12),'Inside Fusion Local Exposure / Veranda',font=font(28),fill='white')
    draw.text((gap,52),f'Actual optimized buffers | {w} x {h} input | +/-{bracket:g} EV brackets | sigma 0.2',font=font(18),fill=(167,184,204))
    for i,(pixels,title,caption) in enumerate(panels):
        x=gap+(i%3)*(tile_w+gap); y=90+(i//3)*(tile_h+header+gap)
        draw.text((x,y),title,font=font(22),fill='white')
        draw.text((x,y+33),caption,font=font(17),fill=(167,184,204))
        sheet.paste(Image.fromarray(pixels).resize((tile_w,tile_h),Image.Resampling.LANCZOS),(x,y+header))
    draw.text((gap,sheet.height-38),'Weights: shared 0-1 scale, initialization mip 0 enlarged. EV colors clip at +/-3 stops; global EV is excluded.',
              font=font(18),fill=(167,184,204))
    out = ROOT/'docs/images/veranda-fusion-walkthrough.png'
    sheet.save(out)
    record = dict(variant=DEFAULT_VARIANT,global_ev=ev,bracket_ev=bracket,sigma=.2,
        size=[w,h],weight_source=f'Actual packed initialization mip 0 ({(w+3)//4}x{(h+3)//4}), decoded and bilinearly enlarged; no per-map contrast normalization',
        weight_min=float(weights.min()),weight_max=float(weights.max()),
        weight_sum_max_error=float(abs(weights.sum(axis=-1)-1).max()),
        ev_source='Production exposureMultiplier(), including half rounding; excludes global EV',
        ev_min=float(local_ev.min()),ev_max=float(local_ev.max()),display_ev_range=stops,
        ev_display_clipped_fraction=float(np.mean(abs(local_ev)>3)),
        final_matches='veranda-after.png',shader_sha256=hashlib.sha256(shader.read_bytes()).hexdigest(),
        image_sha256=hashlib.sha256(out.read_bytes()).hexdigest())
    out.with_suffix('.json').write_text(json.dumps(record,indent=2)+'\n')
    print(f'Saved {out}')
