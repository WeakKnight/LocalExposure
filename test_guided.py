"""Quarter-resolution Fusion and fast guided upsampling regression tests."""
import unittest
import numpy as np
import slangpy as spy

from tone_mapper import ToneMapper, create_hdr_texture
from test_pyramid import sample_bilinear, aces

LUMA = np.array([.2126, .7152, .0722])


def box5(image):
    padded = np.pad(image, ((2,2), (2,2)), mode='edge')
    h,w = image.shape
    return sum(padded[y:y+h,x:x+w] for y in range(5) for x in range(5))/25


class GuidedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = spy.Device(enable_hot_reload=False)
        cls.mapper = ToneMapper(cls.device)

    def render(self, rgba, **kwargs):
        source = create_hdr_texture(self.device, rgba)
        output = self.mapper.create_output(source.width, source.height)
        encoder = self.device.create_command_encoder()
        self.mapper.execute(encoder, source, output, 0, **kwargs)
        self.device.submit_command_buffer(encoder.finish())
        return source

    def test_odd_tiny_sizes_zero_adjustment_and_switching(self):
        rng = np.random.default_rng(23)
        self.assertEqual(self.mapper.fusion_scale, 4)
        for h,w in [(17,31), (1,9), (1,1)]:
            rgba = rng.random((h,w,4), dtype=np.float32)*2
            rgba[0,0,:3] = 0
            self.render(rgba, highlight_ev=0, shadow_ev=0)
            self.assertEqual((self.mapper.work_source.width, self.mapper.work_source.height), ((w+3)//4,(h+3)//4))
            self.assertEqual(self.mapper.local_exposure.to_numpy().shape, (h,w))
            np.testing.assert_allclose(self.mapper.local_exposure.to_numpy(), 1, atol=2e-6)
            # Typed FP16 UAV storage may truncate: allow one ULP below 1.
            np.testing.assert_allclose(self.mapper.final_color.to_numpy()[...,:3], aces(rgba[...,:3]), atol=2**-11 + 2e-6)
        rgba = rng.random((16,32,4), dtype=np.float32)
        for scale in [1,4,1,4]:
            self.mapper.fusion_scale = scale
            self.render(rgba, highlight_ev=0, shadow_ev=0)
            self.assertEqual(self.mapper.work_source.width, 32//scale)
            np.testing.assert_allclose(self.mapper.local_exposure.to_numpy(), 1, atol=2e-6)

    def test_reduction_and_guided_coefficients_match_cpu(self):
        rng = np.random.default_rng(19)
        rgba = np.exp2(rng.uniform(-6,2,(32,48,4))).astype(np.float32)
        self.render(rgba)
        low = self.mapper.work_source.to_numpy()
        expected_rgb = rgba[...,:3].reshape(8,4,12,4,3).mean(axis=(1,3))
        full_guide = np.log2(np.maximum(rgba[...,:3]@LUMA,1e-6))
        expected_guide = full_guide.reshape(8,4,12,4).mean(axis=(1,3))
        np.testing.assert_allclose(low[...,:3], expected_rgb, atol=2e-6)
        np.testing.assert_allclose(low[...,3], expected_guide, atol=2e-6)
        g = low[...,3].astype(float)
        e = np.log2(self.mapper.low_exposure.to_numpy().astype(float))
        mean_g, mean_e = box5(g), box5(e)
        a = (box5(g*e)-mean_g*mean_e)/(np.maximum(box5(g*g)-mean_g**2,0)+.04)
        b = mean_e-a*mean_g
        np.testing.assert_allclose(self.mapper.coefficients.to_numpy(), np.stack([a,b],axis=-1), atol=1e-5)
        expected_ab = np.stack([box5(a),box5(b)],axis=-1)
        np.testing.assert_allclose(self.mapper.averaged_coefficients.to_numpy(), expected_ab, atol=1e-5)
        yy,xx = np.mgrid[:32,:48]
        ab = sample_bilinear(expected_ab,(xx+.5)/48,(yy+.5)/32)
        expected_ev = np.clip(ab[...,0]*full_guide+ab[...,1],-12,12)
        actual_multiplier = self.mapper.local_exposure.to_numpy()
        np.testing.assert_allclose(np.log2(actual_multiplier), expected_ev, atol=.003)
        np.testing.assert_allclose(self.mapper.final_color.to_numpy()[...,:3],
                                   aces(rgba[...,:3]*actual_multiplier[...,None]), atol=2**-11 + 2e-6)

    def test_guidance_reduces_exposure_bleed_across_step(self):
        # Prescribe an exposure field to isolate upsampling from Fusion itself.
        m = self.mapper
        h,w = 32,64
        rgba = np.ones((h,w,4),np.float32)
        rgba[:,:w//2,:3] = 2**-4
        rgba[:,w//2:,:3] = 2**4
        source = self.render(rgba)
        ev = np.ones((h//4,w//4),np.float32)
        ev[:,w//8:] = -1
        low_exp = self.device.create_texture(width=w//4,height=h//4,format=spy.Format.r32_float,
            usage=spy.TextureUsage.shader_resource, data=np.exp2(ev))
        encoder = self.device.create_command_encoder()
        m.guided_kernels['fit_coefficients'].dispatch(thread_count=[w//4,h//4,1],
            vars={'reducedSource':m.work_source,'lowExposure':low_exp,'coefficientOutput':m.coefficients},command_encoder=encoder)
        m.guided_kernels['average_coefficients'].dispatch(thread_count=[w//4,h//4,1],
            vars={'coefficients':m.coefficients,'averagedOutput':m.averaged_coefficients},command_encoder=encoder)
        m.guided_kernels['apply_exposure'].dispatch(thread_count=[w,h,1],
            vars={'fullSource':source,'lowExposure':low_exp,'averagedCoefficients':m.averaged_coefficients,
                  'linearSampler':m.sampler,'globalEV':0.,'guided':True,
                  'fullExposureOutput':m.local_exposure,'baseOutput':m.base_color,'colorOutput':m.final_color},command_encoder=encoder)
        self.device.submit_command_buffer(encoder.finish())
        actual = np.log2(m.local_exposure.to_numpy())
        yy,xx = np.mgrid[:h,:w]
        plain = sample_bilinear(ev[...,None],(xx+.5)/w,(yy+.5)/h)[...,0]
        target = np.ones((h,w));target[:,w//2:] = -1
        band = np.s_[:,w//2-2:w//2+2]
        guided_error = np.abs(actual-target)[band].mean()
        plain_error = np.abs(plain-target)[band].mean()
        self.assertLess(guided_error,.15)
        self.assertLess(guided_error,plain_error*.3)


if __name__ == '__main__':
    unittest.main()
