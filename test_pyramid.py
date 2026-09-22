"""GPU regression checks: run with .venv/Scripts/python.exe test_pyramid.py."""
import unittest

import numpy as np
import slangpy as spy

from tone_mapper import ToneMapper, create_hdr_texture, fusion_mip_count
from main import contrast_scale_to_ev, parse_args


def aces(x):
    return np.clip(x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)


def sample_bilinear(image, u, v):
    height, width = image.shape[:2]
    x = np.clip(u * width - 0.5, 0, width - 1)
    y = np.clip(v * height - 0.5, 0, height - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, width - 1), np.minimum(y0 + 1, height - 1)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    return (image[y0, x0] * (1-fx) + image[y0, x1] * fx) * (1-fy) + (image[y1, x0] * (1-fx) + image[y1, x1] * fx) * fy


def downsample_reference(image):
    height, width = image.shape[:2]
    yy, xx = np.mgrid[:max(1, height//2), :max(1, width//2)]
    u, v = (xx + .5) / max(1, width//2), (yy + .5) / max(1, height//2)
    return sum(sample_bilinear(image, u+dx/width, v+dy/height)
               for dx, dy in [(-1,-1), (1,-1), (-1,1), (1,1)]) * .25


class PyramidTests(unittest.TestCase):
    def test_contrast_scale_semantics_and_legacy_conversion(self):
        for scale, ev in [(1, 0), (.8, 1.2), (2/3, 2), (.5, 3), (0, 6)]:
            self.assertAlmostEqual(contrast_scale_to_ev(scale), ev)
        default = parse_args([])
        self.assertAlmostEqual(contrast_scale_to_ev(default.highlight_contrast), 1.2)
        self.assertAlmostEqual(contrast_scale_to_ev(default.shadow_contrast), 1.2)
        current = parse_args(['--highlight-contrast', '.8', '--shadow-contrast', '.5'])
        legacy = parse_args(['--highlights', '1.2', '--shadows', '3'])
        self.assertAlmostEqual(current.highlight_contrast, legacy.highlight_contrast)
        self.assertAlmostEqual(current.shadow_contrast, legacy.shadow_contrast)
        for value in [-.1, 1.1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                contrast_scale_to_ev(value)

    def test_ue_level_rule_and_single_level_reconstruction(self):
        self.assertEqual(fusion_mip_count(4096, 2048), 12)
        self.assertEqual(fusion_mip_count(1920, 1080), 11)
        self.assertEqual(fusion_mip_count(131072, 131072), 16)
        self.assertEqual(fusion_mip_count(4096, 2048, 6), 6)
        self.assertEqual(fusion_mip_count(1, 8), 1)
        mapper = ToneMapper(self.device, max_levels=1)
        rgba = np.ones((4, 8, 4), np.float32) * .18
        source = create_hdr_texture(self.device, rgba)
        output = mapper.create_output(8, 4)
        encoder = self.device.create_command_encoder()
        mapper.execute(encoder, source, output, 0, view_mode=0)
        self.device.submit_command_buffer(encoder.finish())
        self.assertEqual(mapper.reconstructed.mip_count, 1)
        y = mapper.luminance_pyramid.to_numpy()[...,:3]
        w = mapper.weight_pyramid.to_numpy()[...,:3]
        np.testing.assert_allclose(mapper.reconstructed.to_numpy(), (y*w).sum(axis=-1), atol=1e-6)

    @classmethod
    def setUpClass(cls):
        cls.device = spy.Device(enable_hot_reload=False)
        cls.mapper = ToneMapper(cls.device)

    def test_weights_normalization_preference_and_filter_order(self):
        rgba = np.ones((8, 8, 4), np.float32)
        rgba[:, :4, :3] = .01
        rgba[:, 4:, :3] = 1.0
        texture = create_hdr_texture(self.device, rgba)
        for sigma in [.2, .02, .8]:
            encoder = self.device.create_command_encoder()
            self.mapper.prepare_weights(encoder, texture, 0, 2, 2, sigma)
            self.device.submit_command_buffer(encoder.finish())
            y = np.stack([np.sqrt(np.sum(self.mapper.lut.sample(rgba[...,:3]*2.0**ev) * [0.2126,.7152,.0722],axis=-1)) for ev in [-2,0,2]],axis=-1)
            logw = -(y-.5)**2/(2*sigma*sigma)
            w = np.exp2(logw-logw.max(axis=-1,keepdims=True))
            w /= w.sum(axis=-1,keepdims=True)
            actual = self.mapper.weight_pyramid.to_numpy()[...,:3]
            self.assertEqual(int(actual[3,1].argmax()), 2)  # dark region prefers brighter
            self.assertEqual(int(actual[3,6].argmax()), 0)  # bright region prefers darker
            for mip in range(self.mapper.weight_pyramid.mip_count):
                actual = self.mapper.weight_pyramid.to_numpy(mip=mip)[...,:3]
                self.assertTrue(np.isfinite(actual).all())
                np.testing.assert_allclose(actual.sum(axis=-1), 1, atol=2e-6)
                np.testing.assert_allclose(actual, w, atol=3e-6)
                np.testing.assert_allclose(self.mapper.luminance_pyramid.to_numpy(mip=mip)[...,:3], y, atol=2e-6)
                w, y = downsample_reference(w), downsample_reference(y)
        encoder = self.device.create_command_encoder()
        self.mapper.prepare_weights(encoder, texture, 0, 0, 0, .02)
        self.device.submit_command_buffer(encoder.finish())
        np.testing.assert_allclose(self.mapper.weight_pyramid.to_numpy()[...,:3], 1/3, atol=1e-6)

    def test_reconstruction_and_rgb_exposure_inversion(self):
        rng = np.random.default_rng(91)
        for height, width in [(8, 8), (7, 13), (1, 1)]:
            rgba = rng.random((height, width, 4), dtype=np.float32) * 2
            texture = create_hdr_texture(self.device, rgba)
            output = self.mapper.create_output(width, height)
            encoder = self.device.create_command_encoder()
            self.mapper.execute(encoder, texture, output, 0, view_mode=0)
            self.device.submit_command_buffer(encoder.finish())
            expected = None
            for mip in reversed(range(self.mapper.reconstructed.mip_count)):
                fine = self.mapper.luminance_pyramid.to_numpy(mip=mip)[..., :3]
                w = self.mapper.weight_pyramid.to_numpy(mip=mip)[..., :3]
                w /= w.sum(axis=-1, keepdims=True)
                detail = fine.astype(float)
                if mip < self.mapper.reconstructed.mip_count - 1:
                    coarse = self.mapper.luminance_pyramid.to_numpy(mip=mip+1)[..., :3]
                    h, wi = fine.shape[:2]
                    yy, xx = np.mgrid[:h, :wi]
                    detail -= sample_bilinear(coarse, (xx+.5)/wi, (yy+.5)/h)
                band = (detail*w).sum(axis=-1)
                if expected is None:
                    expected = band.copy()
                else:
                    h, wi = band.shape
                    yy, xx = np.mgrid[:h, :wi]
                    expected = sample_bilinear(expected[...,None], (xx+.5)/wi, (yy+.5)/h)[...,0] + band
                actual = self.mapper.reconstructed.to_numpy(mip=mip)
                np.testing.assert_allclose(actual, expected, atol=.003 if width%2 else 3e-6)
            multiplier = self.mapper.local_exposure.to_numpy()
            actual_rgb = self.mapper.final_color.to_numpy()[...,:3]
            self.assertTrue(np.isfinite(multiplier).all())
            np.testing.assert_allclose(actual_rgb, aces(rgba[...,:3]*multiplier[...,None]), atol=2e-6)
            actual_y = np.sum(actual_rgb * [.2126,.7152,.0722],axis=-1)
            target = np.clip(self.mapper.reconstructed.to_numpy(),0,1)**2
            reachable = (multiplier > 2**-11.99) & (multiplier < 2**11.99)
            proxy_rgb = self.mapper.lut.sample(rgba[..., :3]*multiplier[..., None])
            proxy_y = proxy_rgb @ np.array([.2126,.7152,.0722])
            # Hardware interpolation has quantized fractional weights; bisection
            # can land at a small lookup step rather than an exact target.
            # Separate dispatches may round a coordinate to adjacent filter
            # steps. Bound that discrepancy using the actual baked node slopes.
            node_y = self.mapper.lut.nodes @ np.array([.2126,.7152,.0722])
            filter_step = sum(np.max(np.abs(np.diff(node_y, axis=a))) for a in range(3))/256
            # Ten iterations return the midpoint of a 24/1024 EV interval.
            # Verify that the target lies within that interval's luminance range,
            # including the separate-dispatch filter rounding bound.
            half_interval = 12.0 / 1024
            lower = self.mapper.lut.sample(rgba[..., :3]*multiplier[..., None]*2**(-half_interval)) @ np.array([.2126,.7152,.0722])
            upper = self.mapper.lut.sample(rgba[..., :3]*multiplier[..., None]*2**half_interval) @ np.array([.2126,.7152,.0722])
            tolerance = 2*filter_step+2e-6
            self.assertTrue(np.all(target[reachable] >= lower[reachable]-tolerance))
            self.assertTrue(np.all(target[reachable] <= upper[reachable]+tolerance))
            np.testing.assert_allclose(actual_y[reachable],target[reachable],atol=.03)

    def test_zero_brackets_are_identity_including_black_and_white(self):
        rgba = np.ones((4, 4, 4),np.float32)
        rgba[...,:3] = np.array([[0,0,0], [.01,.2,1], [10,10,10], [1e-9,1e-9,1e-9]])
        texture = create_hdr_texture(self.device,rgba)
        output = self.mapper.create_output(4,4)
        for ev in [-2, 0, 2]:
            encoder = self.device.create_command_encoder()
            self.mapper.execute(encoder,texture,output,ev,view_mode=0,highlight_ev=0,shadow_ev=0)
            self.device.submit_command_buffer(encoder.finish())
            np.testing.assert_allclose(self.mapper.local_exposure.to_numpy(),1,atol=1e-6)
            np.testing.assert_allclose(self.mapper.final_color.to_numpy()[...,:3],aces(rgba[...,:3]*2.0**ev),atol=2e-6)

    def test_parameter_changes_resize_and_reload(self):
        rng = np.random.default_rng(17)
        for height, width in [(8, 8), (7, 13), (1, 9), (1, 1)]:
            rgba = rng.random((height, width, 4), dtype=np.float32) * 3
            texture = create_hdr_texture(self.device, rgba)
            output = self.mapper.create_output(width, height)
            for ev, highlight, shadow, sigma in [(0, 2, 2, .2), (1, 3, 1, .3), (0, 0, 0, .02)]:
                encoder = self.device.create_command_encoder()
                self.mapper.execute(encoder, texture, output, ev,
                                    highlight_ev=highlight, shadow_ev=shadow, sigma=sigma)
                self.device.submit_command_buffer(encoder.finish())
                expected = np.stack([np.sqrt(np.sum(self.mapper.lut.sample(rgba[..., :3]*2.0**e) * [.2126,.7152,.0722], axis=-1))
                                     for e in [ev-highlight, ev, ev+shadow]], axis=-1)
                np.testing.assert_allclose(self.mapper.base_color.to_numpy()[..., :3],
                                           aces(rgba[..., :3]*2.0**ev), atol=2e-6)
                for mip in range(self.mapper.luminance_pyramid.mip_count):
                    tolerance = .002 if (width % 2 or height % 2) and mip else 2e-6
                    np.testing.assert_allclose(self.mapper.luminance_pyramid.to_numpy(mip=mip)[..., :3],
                                               expected, atol=tolerance)
                    expected = downsample_reference(expected)
            before = self.mapper.final_color.to_numpy().copy()
            self.mapper.reload()
            self.assertIsNone(self.mapper._weight_key)
            encoder = self.device.create_command_encoder()
            self.mapper.execute(encoder, texture, output, 0, highlight_ev=0, shadow_ev=0, sigma=.02)
            self.device.submit_command_buffer(encoder.finish())
            np.testing.assert_array_equal(self.mapper.final_color.to_numpy(), before)

    def test_display_modes_do_not_change_fusion(self):
        rgba = np.full((8, 8, 4), .18, np.float32)
        texture = create_hdr_texture(self.device, rgba)
        output = self.mapper.create_output(8, 8)
        images = []
        reference = None
        for mode in range(3):
            encoder = self.device.create_command_encoder()
            self.mapper.execute(encoder, texture, output, 0, view_mode=mode)
            self.device.submit_command_buffer(encoder.finish())
            images.append(output.to_numpy().copy())
            result = self.mapper.final_color.to_numpy()
            if reference is None:
                reference = result.copy()
            np.testing.assert_array_equal(result, reference)
        np.testing.assert_array_equal(images[0][:, 4:], images[1][:, 4:])
        self.assertTrue(np.any(images[0][:, :4] != images[1][:, :4]))
        np.testing.assert_array_equal(images[2][..., 0], images[2][..., 1])


if __name__ == "__main__":
    unittest.main()
