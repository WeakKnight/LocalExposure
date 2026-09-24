"""Multi-output Guided kernels against the unchanged FP32 coefficient path."""
import unittest

import numpy as np
import slangpy as spy

from tone_mapper import ROOT


class GuidedBatchTests(unittest.TestCase):
    def test_window_reuse_preserves_guided_exposure(self):
        device = spy.Device(enable_hot_reload=False)
        kernels = {}
        for name, batch, sliding in [('control', 1, 0), ('batch2', 2, 0),
                                     ('batch4', 4, 0), ('sliding4', 4, 1)]:
            session = device.create_slang_session(compiler_options={
                'include_paths': [ROOT / 'shaders'],
                'defines': {'SEPARABLE_GUIDED': '1', 'PRECOMPUTED_EV': '1',
                            'GUIDED_BATCH': str(batch), 'GUIDED_SLIDING': str(sliding)},
            })
            kernels[name] = device.create_compute_kernel(
                session.load_program('fusion_compact.slang', ['reconstruct_guided']))

        rng = np.random.default_rng(48)
        for width, height in [(1, 1), (17, 9), (65, 33)]:
            for smooth in (False, True):
                with self.subTest(size=(width, height), smooth=smooth):
                    guide = (8 + rng.uniform(-.001, .001, (height, width)) if smooth
                             else rng.uniform(-20, 16, (height, width)))
                    data = np.stack([rng.uniform(-12, 12, (height, width)), guide],
                                    axis=-1).astype(np.float32)
                    source = device.create_texture(
                        width=width, height=height, format=spy.Format.rg32_float,
                        usage=spy.TextureUsage.shader_resource, data=data)
                    results = {}
                    for name, kernel in kernels.items():
                        # FP32 readback prevents half storage from hiding arithmetic drift.
                        output = device.create_texture(
                            width=width, height=height, format=spy.Format.rg32_float,
                            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
                        kernel.dispatch(thread_count=[width, height, 1], vars={
                            'compactSource': source, 'averagedOutput': output})
                        coefficients = output.to_numpy()
                        self.assertTrue(np.isfinite(coefficients).all(), name)
                        results[name] = coefficients[..., 0] * data[..., 1] + coefficients[..., 1]
                    for name in ('batch2', 'batch4', 'sliding4'):
                        # Under 0.001 EV is about 0.07% exposure; this checks only
                        # the scheduling change, independently of the Fusion proxy.
                        np.testing.assert_allclose(results[name], results['control'],
                                                   rtol=0, atol=.001, err_msg=name)
