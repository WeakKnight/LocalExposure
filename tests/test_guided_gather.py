"""Gather indexing and clamped halos must preserve Guided coefficient accuracy."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ROOT


class GuidedGatherTests(unittest.TestCase):
    def test_gather_matches_point_read_control(self):
        device = spy.Device(enable_hot_reload=False)
        sampler=device.create_sampler(min_filter=spy.TextureFilteringMode.linear,mag_filter=spy.TextureFilteringMode.linear,address_u=spy.TextureAddressingMode.clamp_to_edge,address_v=spy.TextureAddressingMode.clamp_to_edge)
        kernels = []
        for rows, reuse in [(20, 1), (16, 1)]:
            session = device.create_slang_session(compiler_options={
                'include_paths': [ROOT / 'shaders'],
                'defines': {'SEPARABLE_GUIDED': '1', 'PRECOMPUTED_EV': '1',
                            'GUIDED_DIRECT_MOMENTS': '1', 'DIRECT_BATCH': '1',
                            'GUIDED_STATIC_WINDOWS': '1', 'GUIDED_VERTICAL': '2',
                            'HALF_ROW_COEFFICIENTS': '1',
                            'GUIDED_THREADS_Y': str(rows),
                            'REUSE_MOMENT_STORAGE': str(reuse), 'GUIDED_GATHER_ROWS': str(int(rows==16))},
            })
            kernels.append((rows, device.create_compute_kernel(
                session.load_program('fusion_compact.slang', ['reconstruct_guided']))))
        rng = np.random.default_rng(148)
        for width, height in [(1, 1), (1, 33), (65, 1), (17, 9), (65, 33), (480,270)]:
            for smooth in (False, True):
                with self.subTest(size=(width, height), smooth=smooth):
                    guide = (8 + rng.uniform(-.05, .05, (height, width)) if smooth
                             else rng.uniform(-20, 16, (height, width)))
                    data = np.stack([rng.uniform(-12, 12, (height, width)), guide],
                                    axis=-1).astype(np.float16)
                    source = device.create_texture(
                        width=width, height=height, format=spy.Format.rg16_float,
                        usage=spy.TextureUsage.shader_resource, data=data)
                    results = []
                    for rows, kernel in kernels:
                        output = device.create_texture(
                            width=width, height=height, format=spy.Format.rg32_float,
                            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
                        kernel.dispatch(thread_count=[((width+15)//16)*16,
                            ((height+15)//16)*rows, 1], vars={
                            'compactSource': source, 'averagedOutput': output, **({'linearSampler':sampler} if rows==16 else {})})
                        results.append(output.to_numpy())
                    self.assertTrue(np.isfinite(results[1]).all())
                    # Different instruction grouping can cross a half rounding boundary.
                    # This coefficient check catches indexing/halo regressions;
                    # the independent display-image gates remain unchanged.
                    np.testing.assert_allclose(results[0], results[1], rtol=0, atol=1e-4)

if __name__=="__main__":unittest.main()
