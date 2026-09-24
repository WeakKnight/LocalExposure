"""Half residual storage must preserve fine-level weighted lightness after correction."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ROOT, ToneMapper, create_hdr_texture


class ResidualCompensationTests(unittest.TestCase):
    def test_weighted_lightness_survives_half_storage(self):
        device = spy.Device(enable_hot_reload=False)
        mapper = ToneMapper(device)
        rng = np.random.default_rng(2409)
        rgb = np.exp2(rng.uniform(-16, 15, (8, 64, 3))).astype(np.float32)
        source = create_hdr_texture(device, np.concatenate([rgb, np.ones((8, 64, 1), np.float32)], -1))
        results = []
        for compensate, fmt in [(0, spy.Format.rg32_float), (0, spy.Format.rg16_float), (1, spy.Format.rg16_float)]:
            session = device.create_slang_session(compiler_options={
                'include_paths': [ROOT / 'shaders'],
                'defines': {'RESIDUAL_PYRAMID': '1', 'COMPENSATE_RESIDUAL': str(compensate)}})
            kernel = device.create_compute_kernel(session.load_program('fusion_compact.slang', ['reduce_setup']))
            compact = mapper.create_texture(16, 2, spy.Format.rg32_float)
            residual = mapper.create_texture(16, 2, fmt)
            weights = mapper.create_texture(16, 2, spy.Format.rg32_float)
            base = mapper.create_texture(16, 2, spy.Format.r32_float)
            kernel.dispatch(thread_count=[16, 2, 1], vars=dict(
                fullSource=source, compactOutput=compact, lightnessOutput=residual,
                weightsOutput=weights, baseLightnessOutput=base, linearSampler=mapper.sampler,
                reductionRows=4, globalEV=-2., highlightEV=3., shadowEV=1.2, sigma=.2,
                **mapper.curve.bindings()))
            value = base.to_numpy().reshape(2, 16).astype(np.float64)
            value += (residual.to_numpy().astype(np.float64) * weights.to_numpy()).sum(-1)
            results.append(value)
        raw_error = np.max(abs(results[1] - results[0]))
        corrected_error = np.max(abs(results[2] - results[0]))
        self.assertGreater(raw_error, 1e-6)  # Ensure the input actually exercises quantization.
        self.assertLess(corrected_error, 2e-7)
        self.assertLess(corrected_error, raw_error / 10)


if __name__ == '__main__':
    unittest.main()
