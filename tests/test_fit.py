"""Bitwise regression for the guided-fit shared input tile."""
from pathlib import Path
import unittest
import numpy as np
import slangpy as spy

ROOT = Path(__file__).resolve().parents[1]


class FitTests(unittest.TestCase):
    def test_shared_inputs_match_original(self):
        device = spy.Device(enable_hot_reload=False)
        session = device.create_slang_session(compiler_options={
            'include_paths':[ROOT/'shaders',ROOT/'tests/fixtures']})
        kernels = [device.create_compute_kernel(session.load_program(name,['fit_coefficients']))
                   for name in ['fit_coefficients_original.slang','guided.slang']]
        usage = spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access
        rng = np.random.default_rng(731)
        for h,w in [(1,1),(1,9),(9,1),(7,7),(8,8),(9,17),(270,480),(271,481)]:
            for flat in [False,True]:
                with self.subTest(size=(h,w),flat=flat):
                    guide = np.zeros((h,w,4),np.float32)
                    guide[...,3] = (8 + rng.uniform(-1e-5,1e-5,(h,w)) if flat
                                    else rng.uniform(-20,16,(h,w)))
                    exposure = np.exp2(rng.uniform(-12,12,(h,w))).astype(np.float16)
                    exposure.flat[::13] = 1
                    source = device.create_texture(width=w,height=h,format=spy.Format.rgba32_float,
                                                   usage=usage,data=guide)
                    low = device.create_texture(width=w,height=h,format=spy.Format.r16_float,
                                                usage=usage,data=exposure)
                    outputs = [device.create_texture(width=w,height=h,format=spy.Format.rg32_float,
                                                      usage=usage) for _ in kernels]
                    encoder = device.create_command_encoder()
                    for kernel,out in zip(kernels,outputs):
                        kernel.dispatch(thread_count=[w,h,1],vars={'reducedSource':source,
                            'lowExposure':low,'coefficientOutput':out},command_encoder=encoder)
                    device.submit_command_buffer(encoder.finish())
                    a,b = [o.to_numpy() for o in outputs]
                    self.assertTrue(np.isfinite(b).all())
                    np.testing.assert_array_equal(a.view(np.uint32),b.view(np.uint32))


if __name__ == '__main__':
    unittest.main()
