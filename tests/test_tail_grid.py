"""Changing tail work assignment must not change reconstruction or omit pixels."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ROOT


class TailGridTests(unittest.TestCase):
    def test_grid_matches_linear_walk_for_full_odd_and_thin_tails(self):
        device = spy.Device(enable_hot_reload=False)
        rng = np.random.default_rng(240925)
        for residual_float, weights_float, direct in [(r, w, d) for r, w in [(0, 0), (1, 0), (1, 1)] for d in (0, 1)]:
            kernels = []
            for grid, compact, threads_x, skip_clear, fuse_base in [(0, 0, 16, 0, 0), (1, 1, 16, 0, 0), (1, 1, 8, 0, 0), (1, 1, 16, 1, 0), (1, 1, 8, 1, 0), (1, 1, 16, 1, 1), (1, 1, 8, 1, 1)]:
                session = device.create_slang_session(compiler_options={
                    'include_paths': [ROOT / 'shaders'], 'defines': {
                        'DIRECT_RESIDUAL_WEIGHTS': str(direct), 'FUSE_TAIL_BASE': str(fuse_base), 'SKIP_TAIL_CLEAR': str(skip_clear), 'RESIDUAL_PYRAMID': '1', 'TAIL_X': str(threads_x), 'TAIL_GRID_WALK': str(grid),
                        'COMPACT_TAIL_STORAGE': str(compact), 'FLOAT_TAIL_RESIDUAL': str(residual_float), 'FLOAT_TAIL_WEIGHTS': str(weights_float)}})
                kernels.append((device.create_compute_kernel(session.load_program('fusion_compact.slang', ['tail_reconstruct'])), threads_x))
            for w, h in [(32, 16), (30, 16), (15, 8), (1, 16), (16, 1), (1, 1)]:
                with self.subTest(size=(w, h), precision=(residual_float, weights_float), direct=direct):
                    residual = rng.uniform(-.5, .5, (h, w, 2)).astype(np.float16)
                    weights = np.rint(rng.dirichlet([1, 1, 1], (h, w))[..., :2] * 65535).astype(np.uint16)
                    source = device.create_texture(width=w, height=h, format=spy.Format.rg16_float,
                                                   usage=spy.TextureUsage.shader_resource, data=residual)
                    wt = device.create_texture(width=w, height=h, format=spy.Format.rg16_unorm,
                                               usage=spy.TextureUsage.shader_resource, data=weights)
                    results = []
                    for kernel, threads_x in kernels:
                        output = device.create_texture(width=w, height=h, format=spy.Format.r32_float,
                            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
                        kernel.dispatch(thread_count=[threads_x, 8, 1], vars=dict(fineLuminance=source,
                            layerWeights=wt, reconstructionOutput=output, tailLevels=max(w, h).bit_length()))
                        results.append(output.to_numpy())
                    self.assertTrue(np.isfinite(results[1]).all())
                    for result in results[1:]:
                        np.testing.assert_array_equal(results[0], result)


if __name__ == '__main__':
    unittest.main()

