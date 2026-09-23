"""Require bitwise FP32 equivalence for the shared coefficient tile."""
from pathlib import Path
import unittest
import numpy as np
import slangpy as spy

ROOT = Path(__file__).resolve().parents[1]


class AverageTests(unittest.TestCase):
    def test_original_and_tile_match(self):
        device = spy.Device(enable_hot_reload=False)
        session = device.create_slang_session(compiler_options={
            'include_paths': [ROOT/'shaders', ROOT/'tests/fixtures']})
        kernels = [device.create_compute_kernel(session.load_program(name,['average_coefficients']))
                   for name in ['average_coefficients_original.slang','guided.slang']]
        rng = np.random.default_rng(730)
        usage = spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access
        for h,w in [(1,1),(1,9),(9,1),(7,7),(8,8),(9,17),(270,480),(271,481)]:
            with self.subTest(size=(h,w)):
                values = (rng.uniform(-1,1,(h,w,2))*np.exp2(rng.uniform(-20,16,(h,w,2)))).astype(np.float32)
                values.reshape(-1,2)[::13] = 0
                source = device.create_texture(width=w,height=h,format=spy.Format.rg32_float,
                                               usage=usage,data=values)
                outputs = [device.create_texture(width=w,height=h,format=spy.Format.rg32_float,
                                                  usage=usage) for _ in kernels]
                encoder = device.create_command_encoder()
                for kernel,output in zip(kernels,outputs):
                    kernel.dispatch(thread_count=[w,h,1],vars={'coefficients':source,'averagedOutput':output},
                                    command_encoder=encoder)
                device.submit_command_buffer(encoder.finish())
                a,b = [o.to_numpy() for o in outputs]
                self.assertTrue(np.isfinite(b).all())
                np.testing.assert_array_equal(a.view(np.uint32), b.view(np.uint32))


if __name__ == '__main__':
    unittest.main()
