"""Run with .venv/Scripts/python.exe test_lut.py."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import slangpy as spy

from lut_proxy import ROOT, ToneLut
from tone_mapper import ToneMapper


class LutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = spy.Device(enable_hot_reload=False)
        cls.lut = ToneLut(cls.device)

    def test_black_endpoints_and_domain_clamp(self):
        rgb = np.array([[[0,0,0], [65535,0,0], [0,65535,0], [0,0,65535],
                         [65535,65535,65535]]], np.float32)
        actual, expected = self.lut.sample(rgb), self.lut.sample(rgb, False)
        np.testing.assert_allclose(actual, expected, atol=1e-7)
        outside = np.array([[[65536,.1,2], [1e8,4,.01]]], np.float32)
        np.testing.assert_array_equal(self.lut.sample(outside),
                                      self.lut.sample(np.clip(outside, 0, 65535)))
        self.assertEqual(self.lut.texture.depth, 16)
        self.assertEqual(self.lut.texture.format, spy.Format.rgb10a2_unorm)
        self.assertEqual(self.lut.texture.to_numpy().nbytes, 16**3*4)

    def test_independent_trilinear_reference_and_error(self):
        rng = np.random.default_rng(53)
        rgb = np.exp2(rng.uniform(-14, 15, (16, 64, 3)))
        gpu = self.lut.sample(rgb)
        cpu = self.lut.evaluate_cpu(rgb)
        # Hardware filtering quantizes fractions; CPU interpolation uses float64.
        np.testing.assert_allclose(gpu, cpu, atol=.002)
        self.assertLess(self.lut.report['max_rgb_error'], .03)
        self.assertEqual(self.lut.report['lut_downward_steps'], 0)

    def test_packed_node_quantization(self):
        n = self.lut.size
        values = self.lut.knee*(np.exp2(np.linspace(0, 1, n)*
                                  np.log2(1+self.lut.max_input/self.lut.knee))-1)
        b, g, r = np.meshgrid(values, values, values, indexing='ij')
        inputs = np.stack([r, g, b], axis=-1).reshape(n, n*n, 3)
        real = self.lut.sample(inputs, False).reshape(n, n, n, 3)
        # Allow one UNORM code step for device conversion and bake arithmetic.
        np.testing.assert_allclose(self.lut.nodes, real, atol=1/1023+2e-6)

    def custom_session(self, directory, operator):
        directory = Path(directory)
        for name in ['lut_bake.slang', 'lut_proxy.slang', 'calibrate.slang']:
            (directory/name).write_text((ROOT/'shaders'/name).read_text())
        (directory/'tone_operator.slang').write_text(operator)
        return self.device.create_slang_session(compiler_options={'include_paths': [directory]})

    def test_cross_channel_operator(self):
        # Deliberately asymmetric and coupled: detects swapped 3D axes and tests
        # behavior that three independent channel curves cannot reproduce.
        with tempfile.TemporaryDirectory() as directory:
            session = self.custom_session(directory, '''float3 toneOperator(float3 c) {
                float3 v = float3(c.r+0.4*c.g, 0.2*c.r+c.g+0.3*c.b, 0.5*c.r+c.b);
                return v/(1.0+v);
            }''')
            lut = ToneLut(self.device, session=session)
            rng = np.random.default_rng(9)
            rgb = np.exp2(rng.uniform(-9, 5, (8, 32, 3)))
            np.testing.assert_allclose(lut.sample(rgb), lut.sample(rgb, False), atol=.04)
            np.testing.assert_allclose(lut.sample(rgb), lut.evaluate_cpu(rgb), atol=.002)
            self.device.wait()

    def test_nonmonotone_operator_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.custom_session(directory, '''float3 toneOperator(float3 c) {
                return c/((1.0+c)*(1.0+c));
            }''')
            with self.assertRaisesRegex(ValueError, 'nonmonotone'):
                ToneLut(self.device, session=session)
            self.device.wait()

    def test_failed_reload_retains_previous_lut_and_kernels(self):
        mapper = ToneMapper(self.device)
        old = mapper.lut, mapper.kernel, mapper.convert_kernel
        with patch('tone_mapper.ToneLut', side_effect=ValueError('invalid new operator')):
            with self.assertRaises(ValueError):
                mapper.reload()
        self.assertEqual(old, (mapper.lut, mapper.kernel, mapper.convert_kernel))


if __name__ == '__main__':
    unittest.main()
