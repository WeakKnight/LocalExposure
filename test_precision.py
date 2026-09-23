"""GPU precision regressions for the fixed mixed-precision implementation."""
import unittest

import numpy as np
import slangpy as spy

from tone_mapper import ToneMapper, create_hdr_texture
from test_pyramid import aces


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

    def test_ten_step_half_search_is_exact(self):
        # Exhaust every possible branch sequence, independent of the LUT.
        intervals = [(-12., 12.)]
        for _ in range(10):
            children = []
            for lo, hi in intervals:
                mid = (lo + hi) * .5
                half_mid = (np.float16(lo) + np.float16(hi)) * np.float16(.5)
                self.assertEqual(float(half_mid), mid)
                children.extend([(lo, mid), (mid, hi)])
            intervals = children


if __name__ == '__main__':
    unittest.main()
