"""Fit quality, monotonicity, GPU inversion and atomic reload regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import slangpy as spy

from zcurve import ROOT, ZCurve, evaluate_curve, fit_curve
from tone_mapper import ToneMapper, create_hdr_texture


class ZCurveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = spy.Device(enable_hot_reload=False)
        cls.curve = ZCurve(cls.device)

    def test_all_four_parameters_fit_and_monotonic_constraint(self):
        x = np.geomspace(1e-8, 65535, 2048)
        known = np.array([1.1, .8, 20., .08])
        fitted = fit_curve(x, evaluate_curve(x, known))
        np.testing.assert_allclose(fitted, known, rtol=2e-5)
        a, d, b, c = fitted
        self.assertTrue(a > 0 and b > 0 and c > 0 and 0 < d <= 1)
        self.assertTrue((np.diff(evaluate_curve(x, fitted.astype(float))) > 0).all())

    def test_aces_fit_and_gpu_roundtrip(self):
        self.assertLess(self.curve.report['max_luminance_error'], .025)
        self.assertLess(self.curve.report['max_lightness_error'], .015)
        x = np.geomspace(1e-8, 65535, 32768).reshape(128, 256)
        gpu = self.curve.sample(x)
        expected = np.sqrt(evaluate_curve(x, self.curve.parameters.astype(float)))
        np.testing.assert_allclose(gpu[..., 0], expected, atol=1e-6)
        ev_error = np.abs(np.log2(gpu[..., 1]/x))
        # Budget includes FP16 log-luminance storage and hardware filtering.
        self.assertLess(float(ev_error.max()), .02)
        self.assertEqual(self.curve.texture.type, spy.TextureType.texture_1d)
        self.assertEqual(self.curve.texture.format, spy.Format.r16_float)
        self.assertEqual(self.curve.texture.width, 1024)
        self.assertEqual(self.curve.texture.to_numpy().nbytes, 1024*2)

    def test_black_endpoints_clamping_and_inverse_monotonicity(self):
        values = np.array([[0., 65535., 65536., 1e10]], np.float32)
        gpu = self.curve.sample(values)
        np.testing.assert_array_equal(gpu[0, 0, :2], 0)
        np.testing.assert_allclose(gpu[0, 1:, 1], 65535., rtol=2e-6)
        np.testing.assert_array_equal(gpu[0, 1:, 0], gpu[0, 1, 0])
        targets = np.linspace(0, self.curve.max_lightness, 8192)[None, :]
        inverse = self.curve.sample(targets)[..., 2]
        self.assertTrue(np.isfinite(inverse).all())
        self.assertTrue((np.diff(inverse) >= 0).all())
        near_white = np.linspace(self.curve.max_lightness*(1-1e-5),
                                 self.curve.max_lightness, 2048, dtype=np.float32)[None, :]
        decoded = self.curve.sample(near_white)[..., 2]
        self.assertTrue((decoded <= self.curve.max_input).all())
        self.assertTrue((np.diff(decoded) >= 0).all())

    def custom_curve(self, directory, function):
        path = Path(directory)
        (path / 'tone_operator.slang').write_text(function)
        for name in ['zcurve.slang', 'zcurve_calibrate.slang']:
            (path / name).write_text((ROOT / 'shaders' / name).read_text())
        session = self.device.create_slang_session(compiler_options={'include_paths': [path]})
        return ZCurve(self.device, session=session)

    def test_custom_operator_is_sampled_on_neutral_axis(self):
        with tempfile.TemporaryDirectory() as directory:
            curve = self.custom_curve(directory, '''float3 toneOperator(float3 c) {
                float3 z = pow(max(c, 0.0), 1.1);
                return z / (20.0 * pow(z, 0.8) + 0.08);
            }''')
            np.testing.assert_allclose(curve.parameters, [1.1, .8, 20., .08], rtol=2e-4)
            x = np.geomspace(1e-8, 65535, 2048)[None, :]
            self.assertLess(float(np.abs(np.log2(curve.sample(x)[..., 1]/x)).max()), .02)
            self.device.wait()

    def test_invalid_operator_and_atomic_reload(self):
        for function, message in [
            ('return c/((1+c)*(1+c));', 'nonmonotone'),
            ('return 0.1+c/(1+c)*0.8;', 'black-preserving'),
            ('return c*2;', 'SDR')]:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, message):
                    self.custom_curve(directory, 'float3 toneOperator(float3 c) {'+function+'}')
                self.device.wait()
        mapper = ToneMapper(self.device)
        previous = mapper.curve, mapper.kernel, mapper.convert_kernel
        with patch('tone_mapper.ZCurve', side_effect=ValueError('fit failed')):
            with self.assertRaises(ValueError):
                mapper.reload()
        self.assertEqual(previous, (mapper.curve, mapper.kernel, mapper.convert_kernel))

    def test_equal_luminance_colors_share_fusion_proxy(self):
        mapper = ToneMapper(self.device, fusion_scale=1)
        rgba = np.ones((1, 3, 4), np.float32)
        # Gray, red and green with identical linear luminance.
        rgba[0, :, :3] = [[.18, .18, .18], [.18/.2126, 0, 0], [0, .18/.7152, 0]]
        source = create_hdr_texture(self.device, rgba)
        encoder = self.device.create_command_encoder()
        mapper.prepare_weights(encoder, source, 0, 1.2, 1.2)
        self.device.submit_command_buffer(encoder.finish())
        lightness = mapper.luminance_pyramid.to_numpy()[0, :, :3]
        weights = mapper.weight_pyramid.to_numpy()[0, :, :3]
        np.testing.assert_allclose(lightness, np.broadcast_to(lightness[0], lightness.shape), atol=1e-6)
        np.testing.assert_allclose(weights, np.broadcast_to(weights[0], weights.shape), atol=1e-6)


if __name__ == '__main__':
    unittest.main()
