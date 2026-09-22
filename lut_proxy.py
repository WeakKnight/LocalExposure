"""GPU-baked log-input / linear-output 3D LUT for the tone operator."""
import argparse
import colorsys
import json
from pathlib import Path

import numpy as np
import slangpy as spy

ROOT = Path(__file__).resolve().parent
LUMA = np.array([.2126, .7152, .0722])


class ToneLut:
    def __init__(self, device, session=None, size=16, max_input=65535.0, knee=1/64):
        if size < 2 or not np.isfinite([max_input, knee]).all() or min(max_input, knee) <= 0:
            raise ValueError('Invalid LUT dimensions or encoding range')
        self.device, self.size, self.max_input, self.knee = device, size, max_input, knee
        self.session = session or device.create_slang_session(compiler_options={'include_paths': [ROOT / 'shaders']})
        self.texture = device.create_texture(type=spy.TextureType.texture_3d,
            width=size, height=size, depth=size, format=spy.Format.rgb10a2_unorm,
            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
        self.sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
            mag_filter=spy.TextureFilteringMode.linear,
            address_u=spy.TextureAddressingMode.clamp_to_edge,
            address_v=spy.TextureAddressingMode.clamp_to_edge,
            address_w=spy.TextureAddressingMode.clamp_to_edge)
        bake = device.create_compute_kernel(self.session.load_program('lut_bake.slang', ['bake_lut']))
        self.real_kernel = device.create_compute_kernel(self.session.load_program('calibrate.slang', ['sample_operator']))
        self.proxy_kernel = device.create_compute_kernel(self.session.load_program('calibrate.slang', ['sample_proxy']))
        encoder = device.create_command_encoder()
        bake.dispatch(thread_count=[size, size, size], vars={'bakedLut': self.texture,
            'maxInput': max_input, 'knee': knee, 'size': size}, command_encoder=encoder)
        device.submit_command_buffer(encoder.finish())
        # Read once at bake/reload time, not on every frame.
        # Packed UNORM readback is raw bytes, not four float channels.
        packed = self.texture.to_numpy().view('<u4').reshape(size, size, size)
        self.nodes = np.stack([(packed >> shift) & 1023 for shift in (0, 10, 20)], axis=-1).astype(np.float32)/1023.0
        if not np.isfinite(self.nodes).all() or np.any(self.nodes < 0) or np.any(self.nodes > 1.00001):
            raise ValueError('Fusion currently requires finite display-linear SDR RGB in [0, 1]')
        self.report, self.samples = self.validate()
        if self.report['real_downward_steps'] or self.report['lut_downward_steps']:
            raise ValueError('Sampled exposure response is nonmonotone; scalar bisection is not valid')

    def bindings(self):
        return {'toneLut': self.texture, 'lutSampler': self.sampler,
                'lutMaxInput': self.max_input, 'lutKnee': self.knee, 'lutSize': self.size}

    def sample(self, rgb, proxy=True):
        rgb = np.asarray(rgb, dtype=np.float32)
        if rgb.ndim != 3 or rgb.shape[-1] != 3 or not np.isfinite(rgb).all() or np.any(rgb < 0):
            raise ValueError('Expected finite nonnegative RGB array [height, width, 3]')
        height, width = rgb.shape[:2]
        rgba = np.concatenate([rgb, np.ones((height, width, 1), np.float32)], axis=-1)
        usage = spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access
        source = self.device.create_texture(width=width, height=height, format=spy.Format.rgba32_float,
                                            usage=usage, data=rgba)
        output = self.device.create_texture(width=width, height=height, format=spy.Format.rgba32_float, usage=usage)
        encoder = self.device.create_command_encoder()
        bindings = {'calibrationInput': source, 'calibrationOutput': output}
        if proxy:
            bindings.update(self.bindings())
        (self.proxy_kernel if proxy else self.real_kernel).dispatch(thread_count=[width, height, 1],
            vars=bindings, command_encoder=encoder)
        self.device.submit_command_buffer(encoder.finish())
        return output.to_numpy()[..., :3]

    def evaluate_cpu(self, rgb):
        """Independent trilinear reference, in-domain only; nodes use [B,G,R] order."""
        rgb = np.asarray(rgb, dtype=float)
        if np.any(rgb < 0) or np.any(rgb > self.max_input):
            raise ValueError('CPU reference is restricted to the baked domain')
        coord = np.log2(1+rgb/self.knee)/np.log2(1+self.max_input/self.knee)*(self.size-1)
        lo = np.floor(coord).astype(int)
        hi = np.minimum(lo+1, self.size-1)
        f = coord-lo
        result = np.zeros_like(rgb)
        for b in range(2):
            for g in range(2):
                for r in range(2):
                    choices = np.array([r, g, b], dtype=bool)
                    index = np.where(choices, hi, lo)
                    weight = np.prod(np.where(choices, f, 1-f), axis=-1)
                    result += self.nodes[index[..., 2], index[..., 1], index[..., 0]]*weight[..., None]
        return result

    def validate(self):
        rays, names = [[1, 1, 1]], ['Neutral']
        for saturation in (.5, 1):
            for hue in range(0, 360, 30):
                rays.append(colorsys.hsv_to_rgb(hue/360, saturation, 1))
                names.append(f'H{hue} S{saturation:g}')
        rays = np.asarray(rays)
        rays /= (rays @ LUMA)[:, None]
        # Independent exposure samples; not LUT grid points.
        ev = np.linspace(-11.97, 11.97, 257)
        inputs = rays[:, None, :]*np.exp2(ev)[None, :, None]
        real, proxy = self.sample(inputs, False), self.sample(inputs)
        if not np.isfinite(real).all() or not np.isfinite(proxy).all():
            raise ValueError('Nonfinite validation output')
        if np.any(real < 0) or np.any(real > 1.00001):
            raise ValueError('Fusion requires display-linear SDR RGB in [0, 1]')
        error = proxy.astype(float)-real
        real_y, proxy_y = real @ LUMA, proxy @ LUMA
        reference_y = self.evaluate_cpu(inputs) @ LUMA
        rows = {name: {'rgb_rmse': float(np.sqrt(np.mean(e**2))),
                       'max_rgb_error': float(np.max(np.abs(e))),
                       'max_luminance_error': float(np.max(np.abs(e @ LUMA)))}
                for name, e in zip(names, error)}
        report = {'size': self.size, 'format': 'rgb10a2_unorm', 'max_input': self.max_input,
            'knee': self.knee, 'input_encoding': 'log2(1+x/knee)/log2(1+max_input/knee)',
            'output_encoding': 'linear Rec.709 RGB (no decode)', 'validation': rows,
            'rgb_rmse': float(np.sqrt(np.mean(error**2))),
            'max_rgb_error': float(np.max(np.abs(error))),
            'max_luminance_error': float(np.max(np.abs(proxy_y-real_y))),
            'real_downward_steps': int(np.count_nonzero(np.diff(real_y, axis=1) < -2e-5)),
            'lut_downward_steps': int(np.count_nonzero(np.diff(reference_y, axis=1) < -2e-5)),
            'hardware_downward_steps': int(np.count_nonzero(np.diff(proxy_y, axis=1) < -2e-5)),
            'hardware_max_luminance_drop': float(max(0, -np.diff(proxy_y, axis=1).min())),
            'monotonicity_scope': '25 sampled color rays; not a proof for arbitrary operators',
            'out_of_domain': 'clamp to LUT boundary', 'fusion_integrated': True}
        return report, {'ev': ev, 'real_rgb': real, 'lut_rgb': proxy, 'names': np.array(names)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, choices=[16, 33, 65, 129], default=16)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs' / 'lut')
    args = parser.parse_args()
    device = spy.Device(enable_hot_reload=False)
    lut = ToneLut(device, size=args.size)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'validation.json').write_text(json.dumps(lut.report, indent=2), encoding='utf-8')
    np.savez(args.output / 'samples.npz', **lut.samples)
    rows = ''.join(f'<tr><td>{name}</td><td>{r["rgb_rmse"]:.6f}</td><td>{r["max_rgb_error"]:.6f}</td><td>{r["max_luminance_error"]:.6f}</td></tr>'
                   for name, r in lut.report['validation'].items())
    (args.output / 'report.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><title>3D LUT validation</title>
<style>body{font:16px/1.5 system-ui;max-width:900px;margin:40px auto;padding:0 20px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px;border-bottom:1px solid #ccc}</style>
<h1>Log-input 3D LUT</h1><p>LUT_GRID node grid, GPU-baked from the real tone operator. Trilinear interpolation in log RGB coordinates; linear RGB output. Out-of-domain channels clamp to the LUT boundary.</p>'''.replace('LUT_GRID', str(args.size)+'³')
        + f'<p>RGB RMSE: {lut.report["rgb_rmse"]:.6f} · Max RGB error: {lut.report["max_rgb_error"]:.6f} · Max luminance error: {lut.report["max_luminance_error"]:.6f}</p>'
        + '<p>Real operator and ideal trilinear LUT: no downward luminance steps on 25 sampled exposure rays. Hardware filter rounding may introduce small steps; see validation.json. This is a sampled check, not a guarantee for arbitrary operators.</p>'
        + '<table><tr><th>Color ray</th><th>RGB RMSE</th><th>Max RGB error</th><th>Max luminance error</th></tr>'+rows+'</table></html>', encoding='utf-8')
    print(json.dumps({k:v for k,v in lut.report.items() if k != 'validation'}, indent=2))
    print(f'Report: {(args.output / "report.html").resolve()}')
    device.wait()


if __name__ == '__main__':
    main()
