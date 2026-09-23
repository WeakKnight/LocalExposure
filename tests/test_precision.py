"""GPU precision regressions for the fixed mixed-precision implementation."""
import unittest

import numpy as np
import slangpy as spy

from tone_mapper import ToneMapper, create_hdr_texture
from tests.test_pyramid import aces
from tests.test_guided import box5


class PrecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = spy.Device(enable_hot_reload=False)
        cls.mixed = ToneMapper(cls.device)

    def render(self, rgba, scale=4, ev=0, bracket=1.2, sigma=.2):
        source = create_hdr_texture(self.device, rgba)
        mapper = self.mixed
        mapper.fusion_scale = scale
        output = mapper.create_output(source.width, source.height)
        encoder = self.device.create_command_encoder()
        mapper.execute(encoder, source, output, ev, highlight_ev=bracket,
                       shadow_ev=bracket, sigma=sigma)
        self.device.submit_command_buffer(encoder.finish())
        rgb = mapper.final_color.to_numpy()[..., :3].astype(np.float32)
        exposure = mapper.local_exposure.to_numpy()
        self.assertTrue(np.isfinite(rgb).all())
        self.assertTrue(np.isfinite(exposure).all())
        self.assertEqual(mapper.weight_pyramid.format, spy.Format.rgba32_float)
        self.assertEqual(mapper.final_color.format, spy.Format.rgba16_float)
        self.assertEqual(mapper.low_exposure.format, spy.Format.r16_float)
        self.assertEqual(mapper.local_exposure.format, spy.Format.r16_float)
        return rgb, exposure

    def test_identity_extremes_and_odd_sizes(self):
        rng = np.random.default_rng(501)
        for shape in [(1, 1), (1, 9), (33, 65)]:
            rgba = np.exp2(rng.uniform(-30, 16, (*shape, 4))).astype(np.float32)
            rgba[0, 0, :3] = [0, 65535, 1e-12]
            for scale in (1, 4):
                for ev in (-16, 0, 16):
                    mixed = self.render(rgba, scale, ev, bracket=0)
                    np.testing.assert_allclose(mixed[1], 1, atol=2e-6)
                    # FP16 UAV writes may truncate, hence one ULP, not half ULP.
                    np.testing.assert_allclose(mixed[0], aces(rgba[..., :3] * 2.0**ev), atol=2**-11+2e-6)

    def test_fusion_extremes_and_color_storage(self):
        h, w = 64, 128
        rng = np.random.default_rng(219)
        rgba = np.ones((h, w, 4), np.float32)
        rgba[..., :3] = np.exp2(np.linspace(-20, 16, w))[None, :, None]
        rgba[..., :3] *= rng.uniform(.02, 1, (h, w, 3)).astype(np.float32)
        rgba[:, :4, :3] = 0
        for scale in (1, 4):
            for sigma in (.02, .2, .8):
                mixed = self.render(rgba, scale, bracket=6, sigma=sigma)
                reference_rgb = aces(rgba[..., :3] * mixed[1][..., None])
                error = np.abs(mixed[0] - reference_rgb)
                self.assertLess(float(error.max()), 2**-11 + 2e-6)
                for mip in range(self.mixed.weight_pyramid.mip_count):
                    weights = self.mixed.weight_pyramid.to_numpy(mip=mip)[..., :3].astype(np.float32)
                    self.assertTrue(np.isfinite(weights).all())
                    self.assertTrue((weights >= 0).all())
                    np.testing.assert_allclose(weights.sum(-1), 1, atol=3e-6)

    def test_display_dense_sdr_ramps(self):
        # Include dark/subnormal inputs, the sRGB junction, and every binary16
        # value in [0,1], plus dense float samples between representable values.
        values = np.concatenate((np.linspace(0, 1, 65536),
                                 np.geomspace(1e-12, .01, 32768),
                                 np.linspace(.00312, .00314, 16384),
                                 np.arange(0x3c01, dtype=np.uint16).view(np.float16)))
        values = np.sort(np.pad(values, (0, (-len(values)) % 512), constant_values=1))
        gray = values.reshape(-1, 512).astype(np.float32)
        rgba = np.ones((*gray.shape, 4), np.float32)
        rgba[..., :3] = gray[..., None]
        source = create_hdr_texture(self.device, rgba)
        output = self.mixed.create_output(source.width, source.height)
        exposure = self.mixed.create_texture(source.width, source.height, spy.Format.r32_float)
        self.mixed.kernel.dispatch(thread_count=[source.width, source.height, 1],
            vars={'source': source, 'finalColor': source, 'localExposure': exposure,
                  'output': output, 'linearSampler': self.mixed.sampler, 'viewMode': 0})
        actual = output.to_numpy()[..., 0].astype(int)
        expected = np.rint(np.where(gray <= .0031308, 12.92*gray,
                                    1.055*np.power(gray.astype(float), 1/2.4)-.055)*255)
        self.assertLessEqual(float(np.abs(actual-expected).max()), 1)
        self.assertTrue((np.diff(actual.ravel()) >= 0).all())
        self.assertEqual(actual.flat[0], 0)
        self.assertEqual(actual.flat[-1], 255)

    def test_guided_products_extreme_windows(self):
        # Prescribed low-res guidance and local EV isolate regression error
        # from Fusion. CPU uses double precision and no half quantization.
        rng = np.random.default_rng(1701)
        h, w = 32, 64
        mapper = self.mixed
        coefficients = mapper.create_texture(w, h, spy.Format.rg32_float)
        averaged = mapper.create_texture(w, h, spy.Format.rg32_float)
        for case in range(12):
            g = rng.uniform(-19.9, 16, (h, w)).astype(np.float32)
            if case % 4 == 0:
                g = np.where(g > 0, 16., -19.9).astype(np.float32)
            elif case % 4 == 1:
                g[:] = rng.uniform(-19, 15)
                g += rng.uniform(-.002, .002, (h, w)).astype(np.float32)
                g[h//2, w//2] = 16
            e = (rng.integers(0, 1024, (h, w))*24/1024-12+12/1024).astype(np.float32)
            if case % 3 == 0:
                e[:] = 11.98828125
            rgba = np.ones((h, w, 4), np.float32)
            rgba[..., 3] = g
            guide = create_hdr_texture(self.device, rgba)
            exposure = self.device.create_texture(width=w, height=h, format=spy.Format.r32_float,
                usage=spy.TextureUsage.shader_resource, data=np.exp2(e))
            encoder = self.device.create_command_encoder()
            mapper.guided_kernels['fit_coefficients'].dispatch(thread_count=[w, h, 1],
                vars={'reducedSource': guide, 'lowExposure': exposure, 'coefficientOutput': coefficients},
                command_encoder=encoder)
            mapper.guided_kernels['average_coefficients'].dispatch(thread_count=[w, h, 1],
                vars={'coefficients': coefficients, 'averagedOutput': averaged}, command_encoder=encoder)
            self.device.submit_command_buffer(encoder.finish())
            ab = averaged.to_numpy()
            gf, ef = g.astype(float), e.astype(float)
            mean_g, mean_e = box5(gf), box5(ef)
            a = (box5(gf*ef)-mean_g*mean_e)/(np.maximum(box5(gf*gf)-mean_g**2, 0)+.04)
            a, b = box5(a), box5(mean_e-a*mean_g)
            for offset in (-8, 0, 8):
                full_g = np.clip(gf+offset, -19.9, 16)
                expected_ev = np.clip(a*full_g+b, -12, 12)
                actual_ev = np.clip(ab[..., 0]*full_g+ab[..., 1], -12, 12)
                # Explicit guided-regression error budget, in EV.
                np.testing.assert_allclose(actual_ev, expected_ev, atol=.012)
                actual_rgb = aces(np.exp2(full_g+actual_ev))
                expected_rgb = aces(np.exp2(full_g+expected_ev))
                np.testing.assert_allclose(actual_rgb, expected_rgb, atol=.002)


if __name__ == '__main__':
    unittest.main()
