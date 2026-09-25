"""Guided precision: exact FP32 control and final-image gates for raw moments."""
import unittest

import numpy as np
import slangpy as spy
from tone_mapper import ROOT
from tools.profiling.android.quality import image_quality
from tools.profiling.android.quality_sweep import codes


class GuidedInteriorTests(unittest.TestCase):
    def test_interior_and_border_coefficients(self):
        device = spy.Device(enable_hot_reload=False)
        sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
            mag_filter=spy.TextureFilteringMode.linear,
            address_u=spy.TextureAddressingMode.clamp_to_edge,
            address_v=spy.TextureAddressingMode.clamp_to_edge)
        apply_session = device.create_slang_session(compiler_options={'include_paths': [ROOT/'shaders']})
        apply = device.create_compute_kernel(apply_session.load_program('guided.slang', ['apply_exposure_production']))
        usage = spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access
        dummy = device.create_texture(width=1, height=1, format=spy.Format.r16_float, usage=usage)
        kernels = []
        for packed, candidate in ((False,False),(False,True),(True,False),(True,True)):
            session=device.create_slang_session(compiler_options={'defines':{'PACKED_HALF_COEFFICIENTS':str(int(packed))}})
            path=ROOT/'shaders/compact/guided.slang' if candidate else ROOT/'tests/fixtures/compact_guided_direct_reference.slang'
            kernel = device.create_compute_kernel(session.load_program(str(path),['reconstruct_guided']))
            kernels.append((kernel, (64, 1) if candidate else (8, 8)))
        rng = np.random.default_rng(1202)
        for width, height in ((1, 1), (65, 1), (1, 65), (17, 9), (65, 33),
                              (480, 270), (129, 73)):
            for smooth in (None, 8, 16, -19):
                with self.subTest(size=(width, height), smooth=smooth):
                    guide = (smooth + rng.uniform(-.01, .01, (height, width)) if smooth is not None
                             else rng.uniform(-20, 16, (height, width)))
                    data = np.stack([rng.uniform(-12, 12, (height, width)), guide],
                                    axis=-1).astype(np.float16)
                    source = device.create_texture(width=width, height=height,
                        format=spy.Format.rg16_float,
                        usage=spy.TextureUsage.shader_resource, data=data)
                    results = []
                    textures = []
                    for kernel, geometry in kernels:
                        output = device.create_texture(width=width, height=height,
                            format=spy.Format.rg32_float,
                            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
                        kernel.dispatch(thread_count=[((width+15)//16)*geometry[0],
                            ((height+15)//16)*geometry[1], 1], vars=dict(compactSource=source,
                            averagedOutput=output))
                        results.append(output.to_numpy())
                        textures.append(output)
                    self.assertTrue(all(np.isfinite(result).all() for result in results))
                    np.testing.assert_array_equal(results[0], results[1])
                    # Evaluate actual display error, not an arbitrary internal-EV
                    # cutoff. Extreme global EV reveals errors hidden by clipping.
                    hdr = np.repeat(np.repeat(np.exp2(data[..., 1].astype(np.float32)), 4, axis=0), 4, axis=1)
                    full = device.create_texture(width=width*4, height=height*4,
                        format=spy.Format.rgba32_float, usage=usage,
                        data=np.stack([hdr, hdr, hdr, np.ones_like(hdr)], axis=-1))
                    for ev in (-16, -8, 0, 8, 16):
                        images = []
                        for coefficient in textures[2:]:
                            out = device.create_texture(width=width*4, height=height*4,
                                format=spy.Format.rgba16_float, usage=usage)
                            apply.dispatch(thread_count=[width*4, height*4, 1], vars=dict(
                                fullSource=full, averagedCoefficients=coefficient, lowExposure=dummy,
                                colorOutput=out, linearSampler=sampler, globalEV=float(ev), guided=True))
                            images.append(codes(out.to_numpy()))
                        quality = image_quality(*images)
                        self.assertTrue(quality['accepted'], (width, height, smooth, ev, quality))



if __name__ == '__main__':
    unittest.main()
