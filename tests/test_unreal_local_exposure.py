"""UE ports versus independent equations, including odd edges and native storage."""
from dataclasses import replace
import unittest

import numpy as np
import slangpy as spy

from main import parse_args
from tone_mapper import create_hdr_texture
from ue_local_exposure import UEParameters, UnrealLocalExposure, gaussian_taps
from tests import ue_reference as reference


class UnrealLocalExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = spy.Device(enable_hot_reload=False)
        cls.sampler_bits = reference.detect_sampler_bits(cls.device)

    def render(self, rgb, method, parameters, ev=0, highlight=.8, shadow=.8, production=False, mapper=None):
        rgba = np.concatenate([np.asarray(rgb, np.float32), np.ones((*rgb.shape[:2], 1), np.float32)], axis=-1)
        source = create_hdr_texture(self.device, rgba)
        mapper = mapper or UnrealLocalExposure(self.device, method, parameters=parameters)
        out = mapper.create_output(source.width, source.height)
        encoder = self.device.create_command_encoder()
        if production:
            mapper.record_processing(encoder, source, ev, highlight, shadow)
        else:
            mapper.execute(encoder, source, out, ev, highlight_ev=6 * (1 - highlight), shadow_ev=6 * (1 - shadow))
        self.device.submit_command_buffer(encoder.finish())
        mapper.final_color.to_numpy()  # Wait before inspecting stages.
        return mapper

    def test_fusion_fp32_pyramids_and_inverse(self):
        p = UEParameters(storage='fp32')
        rng = np.random.default_rng(46)
        for h, w in [(1, 1), (1, 9), (7, 13), (33, 65)]:
            rgb = np.exp2(rng.uniform(-12, 8, (h, w, 3))).astype(np.float32)
            for ev, highlight, shadow in [(-2, .9, .5), (0, 1, 1), (2, .5, .9)]:
                with self.subTest(size=(w, h), ev=ev):
                    expected = reference.fusion(rgb, p, ev, highlight, shadow, fraction_bits=self.sampler_bits)
                    m = self.render(rgb, 'ue-fusion', p, ev, highlight, shadow)
                    self.assertEqual([(t.height, t.width) for t in m.exposures], [t.shape[:2] for t in expected['exposures']])
                    for texture, value in zip(m.exposures, expected['exposures']):
                        np.testing.assert_allclose(texture.to_numpy()[..., :3], value, atol=2e-6)
                    np.testing.assert_allclose(m.results[0].to_numpy()[..., 0], expected['fused'], atol=3e-6)
                    np.testing.assert_allclose(m.local_exposure.to_numpy(), expected['exposure'], rtol=5e-4, atol=8e-6)

    def test_bilateral_grid_blur_and_threshold_equations(self):
        rng = np.random.default_rng(49)
        for profile in ['desktop', 'mobile']:
            for h, w in [(1, 1), (3, 9), (35, 67), (65, 129)]:
                rgb = np.exp2(rng.uniform(-9, 3, (h, w, 3))).astype(np.float32)
                p = UEParameters(profile=profile, storage='fp32', blur_percent=35,
                    highlight_threshold=1.2, shadow_threshold=.7, highlight_threshold_strength=.3,
                    shadow_threshold_strength=.8, detail_strength=1.3, middle_grey_bias=.5)
                with self.subTest(size=(w, h), profile=profile):
                    expected = reference.bilateral(rgb, p, ev=-1, highlight=.6, shadow=.9, fraction_bits=self.sampler_bits)
                    m = self.render(rgb, 'ue-bilateral', p, -1, .6, .9)
                    np.testing.assert_allclose(m.grid.to_numpy(), expected['grid'], atol=.06)
                    # The ramp probe measures interpolation precision, but CPU
                    # and GPU log/UV arithmetic can straddle a rounding tie.
                    # Allow <0.0001 stop in blur and 0.05% in exposure, while
                    # checking the packed integer grid independently above.
                    np.testing.assert_allclose(m.blurred_log.to_numpy(), expected['blur'], atol=1e-4)
                    np.testing.assert_allclose(m.local_exposure.to_numpy(), expected['exposure'], rtol=5e-4, atol=3e-5)

    def test_native_storage_and_production_match_diagnostics(self):
        y, x = np.mgrid[:65, :129]
        rgb = np.where((x < 63)[..., None], [.001, .003, .002], [1000., 300., 30.]).astype(np.float32)
        rgb[0, 0] = 0
        rgb[-1, -1] = [65535, 0, 0]
        for method in ['ue-fusion', 'ue-bilateral']:
            for profile in ['desktop', 'mobile']:
                p = UEParameters(profile=profile)
                with self.subTest(method=method, profile=profile):
                    m = self.render(rgb, method, p)
                    diagnostic = m.final_color.to_numpy()
                    self.assertTrue(np.isfinite(m.local_exposure.to_numpy()).all())
                    self.render(rgb, method, p, production=True, mapper=m)
                    np.testing.assert_array_equal(m.final_color.to_numpy(), diagnostic)

    def test_bilateral_identity_empty_grid_and_zero_blend(self):
        p = UEParameters(storage='fp32', profile='mobile', blurred_blend=0)
        rgb = np.array([[[0, 0, 0], [.18, .18, .18], [100, 1, 0]]], np.float32)
        m = self.render(rgb, 'ue-bilateral', p, highlight=1, shadow=1)
        np.testing.assert_allclose(m.local_exposure.to_numpy(), 1, atol=1e-6)
        np.testing.assert_array_equal(m.grid.to_numpy(), 0)
        expected = reference.bilateral(rgb, p, highlight=.5, shadow=.8)
        m = self.render(rgb, 'ue-bilateral', p, highlight=.5, shadow=.8)
        np.testing.assert_allclose(m.local_exposure.to_numpy(), expected['exposure'], rtol=2e-5)

    def test_parameter_changes_and_hdr_pre_exposure(self):
        rgb = np.full((9, 17, 3), .12, np.float32)
        for method in ['ue-fusion', 'ue-bilateral']:
            p = UEParameters(storage='fp32', profile='mobile')
            a = self.render(rgb, method, p)
            first = a.final_color.to_numpy()
            scaled = self.render(rgb * 8, method, replace(p, pre_exposure=8))
            np.testing.assert_array_equal(first, scaled.final_color.to_numpy())
            a.parameters = replace(p, middle_grey_bias=1, blurred_blend=.2)
            self.render(rgb, method, a.parameters, mapper=a)
            self.assertTrue(np.isfinite(a.final_color.to_numpy()).all())

    def test_film_parameter_variants_keep_fixed_inverse(self):
        rgb = np.geomspace(.0001, 1000, 63).reshape(3, 7, 3).astype(np.float32)
        for toe in [.55, .85]:
            p = UEParameters(storage='fp32', film_toe=toe, film_slope=.95, film_shoulder=.3)
            m = self.render(rgb, 'ue-fusion', p)
            expected = reference.fusion(rgb, p, fraction_bits=self.sampler_bits)
            np.testing.assert_allclose(m.local_exposure.to_numpy(), expected['exposure'], rtol=3e-4, atol=2e-6)

    def test_cli_parameters_and_gaussian_limit(self):
        args = parse_args(['--method', 'ue-bilateral', '--ue-profile', 'mobile', '--ue-detail-strength', '1.4'])
        self.assertEqual(args.ue_parameters.profile, 'mobile')
        self.assertEqual(args.ue_parameters.detail_strength, 1.4)
        for radius in [0, .1, 1, 7, 20, 1000]:
            taps = gaussian_taps(radius)
            self.assertTrue(np.isfinite(taps).all())
            self.assertAlmostEqual(float(taps[:, 1].sum()), 1, places=6)
        for change in [dict(histogram_max=-8), dict(pre_exposure=0), dict(film_slope=0), dict(detail_strength=-1),
                       dict(film_toe=.6, film_shoulder=.4)]:
            with self.assertRaises(ValueError):
                UEParameters(**change)


if __name__ == '__main__':
    unittest.main()
