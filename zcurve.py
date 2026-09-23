"""Neutral-axis Z-curve calibration and an inverse lightness 1D LUT."""
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
import slangpy as spy

ROOT = Path(__file__).resolve().parent
LUMA = np.array([.2126, .7152, .0722])


def evaluate_curve(luminance, parameters):
    a, d, b, c = parameters
    z = np.maximum(luminance, 0.) ** a
    return z / (b * z**d + c)


def fit_curve(luminance, response):
    """All four parameters vary; a,b,c>0 and 0<d<=1 ensure global monotonicity."""
    x, y = np.asarray(luminance), np.asarray(response)
    def decode(p):
        return np.array([np.exp(p[0]), p[1], np.exp(p[2]), np.exp(p[3])])
    def residual(p):
        return np.sqrt(evaluate_curve(x, decode(p))) - np.sqrt(y)
    bounds = ([np.log(.1), .1, np.log(.001), np.log(1e-6)],
              [np.log(4.), 1., np.log(100.), np.log(1000.)])
    candidates = [least_squares(residual, [np.log(a), d, 0., np.log(.2)],
                    bounds=bounds, max_nfev=1500, ftol=1e-11, xtol=1e-11, gtol=1e-11)
                  for a, d in [(1., .8), (2., .95), (.5, .5)]]
    best = min(candidates, key=lambda r: np.sum(r.fun**2))
    if not best.success or not np.isfinite(best.x).all():
        raise ValueError('Z-curve fit did not converge')
    return decode(best.x).astype(np.float32)


class ZCurve:
    def __init__(self, device, session=None, size=1024, max_input=65535.):
        if size < 2 or not np.isfinite(max_input) or max_input <= 0:
            raise ValueError('Invalid inverse LUT size or HDR domain')
        self.device, self.size, self.max_input = device, size, max_input
        self.session = session or device.create_slang_session(compiler_options={
            'include_paths': [ROOT / 'shaders']})
        self.real_kernel = device.create_compute_kernel(self.session.load_program('zcurve_calibrate.slang', ['sample_operator']))
        self.proxy_kernel = device.create_compute_kernel(self.session.load_program('zcurve_calibrate.slang', ['sample_curve']))
        x = np.r_[0., np.geomspace(1e-8, max_input, 1024)]
        rgb = self.sample_operator(np.broadcast_to(x[None, :, None], (1, len(x), 3)))
        if not np.isfinite(rgb).all() or np.any(rgb < 0) or np.any(rgb > 1.00001):
            raise ValueError('Tone operator must return finite linear SDR RGB in [0,1]')
        y = (rgb @ LUMA).ravel()
        if y[0] > 1e-5:
            raise ValueError('Z curve requires a black-preserving neutral response')
        if np.any(np.diff(y) < -2e-5):
            raise ValueError('Neutral tone response is nonmonotone')
        if y.max() < .01:
            raise ValueError('Neutral tone response has insufficient dynamic range')
        self.parameters = fit_curve(x, y)
        # Use the actual float32 parameter values when baking the inverse.
        self.max_lightness = float(np.float32(np.sqrt(evaluate_curve(max_input, self.parameters.astype(float)))))
        self.warp_epsilon = 1e-5
        self.warp_span = float(np.log2((1+self.warp_epsilon)/self.warp_epsilon))
        u = np.linspace(0., 1., size)
        q = np.exp2((2*u-1)*self.warp_span)
        t = np.clip((q*(1+self.warp_epsilon)-self.warp_epsilon)/(1+q), 0, 1)
        target = (t*self.max_lightness)**2
        lo, hi = np.full(size, -40.), np.full(size, np.log2(max_input))
        # Calibration-time inversion only. No per-frame or per-pixel search.
        for _ in range(72):
            mid = (lo+hi)*.5
            below = evaluate_curve(np.exp2(mid), self.parameters.astype(float)) < target
            lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
        self.inverse_nodes = ((lo+hi)*.5).astype(np.float32)
        self.inverse_nodes[0], self.inverse_nodes[-1] = -40., np.log2(max_input)
        # Store log luminance in half; lookup coordinates and exp2 remain float.
        self.inverse_nodes = self.inverse_nodes.astype(np.float16)
        self.texture = device.create_texture(type=spy.TextureType.texture_1d, width=size,
            format=spy.Format.r16_float, usage=spy.TextureUsage.shader_resource, data=self.inverse_nodes)
        self.sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
            mag_filter=spy.TextureFilteringMode.linear, address_u=spy.TextureAddressingMode.clamp_to_edge)
        # Interleaved samples, independent of the fit sample positions.
        check = np.r_[0., np.geomspace(1.013e-8, max_input, 2047)]
        actual = self.sample_operator(np.broadcast_to(check[None, :, None], (1, len(check), 3))) @ LUMA
        predicted = evaluate_curve(check, self.parameters.astype(float))
        error = predicted-actual.ravel()
        light_error = np.sqrt(predicted)-np.sqrt(actual.ravel())
        self.report = dict(parameters=dict(zip(('contrast', 'shoulder', 'b', 'c'), map(float, self.parameters))),
            max_input=max_input, inverse_size=size, inverse_format='r16_float',
            luminance_rmse=float(np.sqrt(np.mean(error**2))), max_luminance_error=float(abs(error).max()),
            max_lightness_error=float(abs(light_error).max()),
            monotonicity='a,b,c>0; 0<shoulder<=1; globally monotone before domain clamping',
            calibration='neutral RGB only; not a model of chromatic response')
        if self.report['max_lightness_error'] > .1:
            raise ValueError(f'Z curve is a poor fit: maximum lightness error {abs(light_error).max():.4f}')
        probes = np.geomspace(1e-8, max_input, 8192)[None, :]
        inverse = self.sample(probes)[..., 1]
        if not np.isfinite(inverse).all() or np.any(inverse <= 0):
            raise ValueError('Invalid inverse LUT response')
        self.report['gpu_roundtrip_max_ev'] = float(np.max(np.abs(np.log2(inverse/probes))))

    def bindings(self):
        return dict(zParameters=self.parameters, zMaxInput=self.max_input,
                    zMaxLightness=self.max_lightness, inverseLut=self.texture,
                    inverseSampler=self.sampler, inverseSize=self.size,
                    inverseWarpEpsilon=self.warp_epsilon, inverseWarpSpan=self.warp_span)

    def _dispatch(self, rgb, kernel, bindings):
        rgb = np.asarray(rgb, dtype=np.float32)
        h, w = rgb.shape[:2]
        rgba = np.concatenate((rgb, np.ones((h, w, 1), np.float32)), axis=-1)
        usage = spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access
        source = self.device.create_texture(width=w, height=h, format=spy.Format.rgba32_float, usage=usage, data=rgba)
        output = self.device.create_texture(width=w, height=h, format=spy.Format.rgba32_float, usage=usage)
        kernel.dispatch(thread_count=[w, h, 1], vars={**bindings, 'calibrationInput': source, 'calibrationOutput': output})
        return output.to_numpy()[..., :3]

    def sample_operator(self, rgb):
        return self._dispatch(rgb, self.real_kernel, {})

    def sample(self, luminance):
        """GPU columns: forward lightness, inverse(forward), inverse(input target)."""
        values = np.asarray(luminance, dtype=np.float32)
        return self._dispatch(np.repeat(values[..., None], 3, axis=-1), self.proxy_kernel, self.bindings())


if __name__ == '__main__':
    device = spy.Device(enable_hot_reload=False)
    curve = ZCurve(device)
    directory = ROOT / 'outputs/zcurve'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'report.json').write_text(json.dumps(curve.report, indent=2) + '\n')
    print(json.dumps(curve.report, indent=2))
