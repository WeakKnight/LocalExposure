"""Cached forward tables for fine-residual Fusion; inverse remains in ZCurve."""
import numpy as np
import slangpy as spy
from zcurve import evaluate_curve

SIZE = 2048
LOG_MIN, LOG_MAX = -40.0, 40.0


def bake_tables(curve, highlight, shadow, sigma):
    if not np.isfinite([highlight, shadow, sigma]).all() or sigma <= 0:
        raise ValueError('Finite exposure brackets and positive sigma required')
    luminance = np.exp2(np.linspace(LOG_MIN, LOG_MAX, SIZE))
    inputs = np.minimum(luminance[:, None] * np.exp2([-highlight, 0, shadow]),
                        curve.bindings()['zMaxInput'])
    y = np.minimum(np.sqrt(evaluate_curve(inputs, curve.parameters.astype(float))),
                   curve.max_lightness)
    log_weights = -(y - .5) ** 2 / (2 * sigma * sigma)
    weights = np.exp2(log_weights - log_weights.max(axis=1, keepdims=True))
    weights /= weights.sum(axis=1, keepdims=True)
    forward = np.zeros((SIZE, 4), np.float32)
    forward[:, 0] = (y * weights).sum(axis=1)
    forward[:, 1:3] = weights[:, [0, 2]]
    reduced = np.zeros_like(forward)
    reduced[:, :2] = y[:, [0, 2]] - y[:, 1:2]
    reduced[:, 2] = y[:, 1]
    if not np.isfinite(forward).all() or not np.isfinite(reduced).all():
        raise ValueError('Non-finite Fusion table')
    return forward, reduced


class FusionLookup:
    def __init__(self, device):
        self.device, self.key = device, None

    def prepare(self, curve, highlight, shadow, sigma):
        key = (tuple(curve.parameters), curve.bindings()['zMaxInput'],
               curve.max_lightness, highlight, shadow, sigma)
        if key != self.key:
            arrays = bake_tables(curve, highlight, shadow, sigma)
            textures = [self.device.create_texture(
                type=spy.TextureType.texture_1d, width=SIZE,
                format=spy.Format.rgba32_float,
                usage=spy.TextureUsage.shader_resource, data=a) for a in arrays]
            self.arrays, self.textures, self.key = arrays, textures, key
        return dict(zip(('fineLookup', 'lowLookup'), self.textures))
