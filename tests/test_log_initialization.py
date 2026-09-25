"""Check log-domain initialization at black, HDR limits and clamped brackets."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ROOT, create_hdr_texture


class LogInitializationTests(unittest.TestCase):
    def test_reduction_and_curve_match_scalar_control(self):
        device = spy.Device(enable_hot_reload=False)
        sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
            mag_filter=spy.TextureFilteringMode.linear,
            address_u=spy.TextureAddressingMode.clamp_to_edge,
            address_v=spy.TextureAddressingMode.clamp_to_edge)
        kernels = []
        for optimized, shared_log, unsigned in ((False, False, False), (True, False, False),
                                               (True, True, False), (True, True, True)):
            session = device.create_slang_session(compiler_options={
                'include_paths': [ROOT / 'shaders'], 'defines': {
                    'GATHER_QUAD_LOG': str(int(optimized)),
                    'CURVE_LOG': str(int(optimized)),
                    'SHARED_INPUT_LOG': str(int(shared_log)),
                    'GATHER_UNSIGNED_SOURCE': str(int(unsigned)),
                    'LOG_EXPOSURE': '1', 'RESIDUAL_PYRAMID': '1'}})
            kernels.append(device.create_compute_kernel(session.load_program(
                str(ROOT/'tests/fixtures/fusion_compact_reference.slang'), ['reduce_setup_gather'])))
        rng = np.random.default_rng(120)
        for width, height in ((64, 32), (65, 33), (1, 1)):
            rgba = np.exp2(rng.uniform(-35, 15.9, (height, width, 4))).astype(np.float32)
            rgba.reshape(-1, 4)[::3, :3] = 0
            rgba.reshape(-1, 4)[::7, :3] = [65024, 65024, 64512]
            source = create_hdr_texture(device, rgba)
            # The arithmetic domain matches finite game-format input; FP32
            # intermediates expose differences that half storage could conceal.
            w, h = (width + 3) // 4, (height + 3) // 4
            def texture(fmt):
                return device.create_texture(width=w, height=h, format=fmt,
                    usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
            for parameters in ([1.5258, .99945, 1.0061, .2102], [.5, 1, 1, .2], [4, 1, 1, .2]):
                a, shoulder, b, c = parameters
                z = 65535. ** a
                maximum = np.sqrt(z / (b * z ** shoulder + c))
                for ev, highlight, shadow in [(-4, 6, .6), (0, 1.2, 1.2), (4, .6, 6)]:
                    with self.subTest(size=(width, height), parameters=parameters, ev=ev):
                        results = []
                        for kernel in kernels:
                            outputs = dict(compactOutput=texture(spy.Format.rg32_float),
                                lightnessOutput=texture(spy.Format.rg32_float),
                                weightsOutput=texture(spy.Format.rg32_float),
                                baseLightnessOutput=texture(spy.Format.r32_float))
                            kernel.dispatch(thread_count=[w, h, 1], vars=dict(fullSource=source,
                                linearSampler=sampler, globalEV=ev, highlightEV=highlight,
                                shadowEV=shadow, sigma=.2, zParameters=parameters,
                                zMaxInput=65535., zMaxLightness=float(maximum), **outputs))
                            results.append({k: v.to_numpy() for k, v in outputs.items()})
                        for result in results[1:]:
                            for key in results[0]:
                                self.assertTrue(np.isfinite(result[key]).all(), key)
                                np.testing.assert_allclose(results[0][key], result[key],
                                    rtol=2e-5, atol=3e-6, err_msg=key)
                        for key in results[-1]:
                            np.testing.assert_array_equal(results[-2][key], results[-1][key],
                                                          err_msg=key)


if __name__ == '__main__':
    unittest.main()
