"""Bitwise GPU comparison against the frozen pre-optimization reduction."""
from pathlib import Path
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import create_hdr_texture

ROOT = Path(__file__).resolve().parents[1]


class ReductionTests(unittest.TestCase):
    def test_bitwise_unchanged(self):
        device = spy.Device(enable_hot_reload=False)
        session = device.create_slang_session(compiler_options={
            'include_paths': [ROOT/'shaders', ROOT/'tests/fixtures']})
        old = device.create_compute_kernel(session.load_program('reduce_source_original.slang', ['reduce_source']))
        new = device.create_compute_kernel(session.load_program('guided.slang', ['reduce_source']))
        sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
            mag_filter=spy.TextureFilteringMode.linear,
            address_u=spy.TextureAddressingMode.clamp_to_edge,
            address_v=spy.TextureAddressingMode.clamp_to_edge)
        rng = np.random.default_rng(9281)
        for h,w in [(1,1),(1,9),(9,1),(17,31),(64,128),(271,481),(1080,1920)]:
            with self.subTest(size=(h,w)):
                rgba = np.exp2(rng.uniform(-35,16,(h,w,4))).astype(np.float32)
                rgba[...,:3] = np.minimum(rgba[...,:3],65535)
                rgba.reshape(-1,4)[::7,:3] = 0
                rgba.reshape(-1,4)[::13,:3] = [-1,65535,1e-6]
                source = create_hdr_texture(device,rgba)
                outputs = [device.create_texture(width=(w+3)//4,height=(h+3)//4,
                    format=spy.Format.rgba32_float,
                    usage=spy.TextureUsage.shader_resource|spy.TextureUsage.unordered_access) for _ in range(2)]
                encoder = device.create_command_encoder()
                for kernel, output, extra in [(old,outputs[0],{}),(new,outputs[1],{'reductionRows':4})]:
                    kernel.dispatch(thread_count=[output.width,output.height,1],
                        vars=dict(fullSource=source,reducedOutput=output,linearSampler=sampler,**extra),
                        command_encoder=encoder)
                device.submit_command_buffer(encoder.finish())
                a,b = [o.to_numpy() for o in outputs]
                self.assertTrue(np.isfinite(b).all())
                np.testing.assert_array_equal(a.view(np.uint32),b.view(np.uint32))


if __name__ == '__main__':
    unittest.main()
