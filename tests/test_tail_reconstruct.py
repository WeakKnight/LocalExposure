"""A constant weight field must telescope through every complete pyramid tail."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ROOT


class TailReconstructTests(unittest.TestCase):
    def test_constant_weights_preserve_finest_residual_on_thin_and_odd_tails(self):
        device = spy.Device(enable_hot_reload=False)
        session = device.create_slang_session(compiler_options={
            'include_paths': [ROOT / 'shaders'],
            'defines': {'RESIDUAL_PYRAMID': '1', 'TAIL_X': '16'},
        })
        kernel = device.create_compute_kernel(session.load_program(
            'fusion_compact.slang', ['tail_reconstruct']))
        rng = np.random.default_rng(92)
        for w, h in [(1, 1), (1, 16), (16, 1), (15, 8), (16, 8)]:
            data = rng.uniform(-.5, .5, (h, w, 2)).astype(np.float16)
            source = device.create_texture(width=w, height=h, format=spy.Format.rg16_float,
                usage=spy.TextureUsage.shader_resource, data=data)
            for pair in [(65535, 0), (0, 65535), (0, 0), (16384, 32768)]:
                with self.subTest(size=(w, h), weights=pair):
                    weights = np.broadcast_to(np.array(pair, np.uint16), (h, w, 2)).copy()
                    wt = device.create_texture(width=w, height=h, format=spy.Format.rg16_unorm,
                        usage=spy.TextureUsage.shader_resource, data=weights)
                    output = device.create_texture(width=w, height=h, format=spy.Format.r32_float,
                        usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
                    kernel.dispatch(thread_count=[16, 8, 1], vars={
                        'fineLuminance': source, 'layerWeights': wt,
                        'reconstructionOutput': output, 'tailLevels': max(w, h).bit_length(),
                    })
                    expected = (data.astype(np.float32) * (np.array(pair, np.float32) / 65535)).sum(axis=-1)
                    actual = output.to_numpy().reshape(h, w)
                    self.assertTrue(np.isfinite(actual).all())
                    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-6)
