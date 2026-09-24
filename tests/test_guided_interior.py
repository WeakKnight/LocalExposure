"""Interior tile addressing must preserve the clamped Guided coefficients."""
import unittest

import numpy as np
import slangpy as spy
from tone_mapper import ROOT


class GuidedInteriorTests(unittest.TestCase):
    def test_interior_and_border_coefficients(self):
        device = spy.Device(enable_hot_reload=False)
        sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
            mag_filter=spy.TextureFilteringMode.linear,
            address_u=spy.TextureAddressingMode.clamp_to_edge,
            address_v=spy.TextureAddressingMode.clamp_to_edge)
        kernels = []
        for packed, interior in ((False, False), (False, True), (True, False), (True, True)):
            defines = {key: '1' for key in ('SEPARABLE_GUIDED', 'PRECOMPUTED_EV',
                'GUIDED_DIRECT_MOMENTS', 'GUIDED_STATIC_WINDOWS', 'GUIDED_GATHER_ROWS',
                'HALF_ROW_COEFFICIENTS', 'REUSE_MOMENT_STORAGE')}
            defines.update(GUIDED_VERTICAL='2', GUIDED_BATCH='2', DIRECT_BATCH='1',
                GUIDED_THREADS_Y='16', TILE_X='16', TILE_Y='16',
                GUIDED_INTERIOR_FIT=str(int(interior)),
                PACKED_HALF_COEFFICIENTS=str(int(packed)), COEFF_PAD='4' if packed else '0')
            session = device.create_slang_session(compiler_options={
                'include_paths': [ROOT / 'shaders'], 'defines': defines})
            kernels.append(device.create_compute_kernel(session.load_program(
                'fusion_compact.slang', ['reconstruct_guided'])))
        rng = np.random.default_rng(1202)
        for width, height in ((1, 1), (65, 1), (1, 65), (17, 9), (65, 33),
                              (480, 270), (129, 73)):
            for smooth in (False, True):
                with self.subTest(size=(width, height), smooth=smooth):
                    guide = (8 + rng.uniform(-.05, .05, (height, width)) if smooth
                             else rng.uniform(-20, 16, (height, width)))
                    data = np.stack([rng.uniform(-12, 12, (height, width)), guide],
                                    axis=-1).astype(np.float16)
                    source = device.create_texture(width=width, height=height,
                        format=spy.Format.rg16_float,
                        usage=spy.TextureUsage.shader_resource, data=data)
                    results = []
                    for kernel in kernels:
                        output = device.create_texture(width=width, height=height,
                            format=spy.Format.rg32_float,
                            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
                        kernel.dispatch(thread_count=[((width+15)//16)*16,
                            ((height+15)//16)*16, 1], vars=dict(compactSource=source,
                            averagedOutput=output, linearSampler=sampler))
                        results.append(output.to_numpy())
                    for i in (0, 2):
                        self.assertTrue(np.isfinite(results[i+1]).all())
                        np.testing.assert_array_equal(results[i], results[i+1])


if __name__ == '__main__':
    unittest.main()
