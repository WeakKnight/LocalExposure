"""Validate fused reconstruction halos and the small-image fallback."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ToneMapper, create_hdr_texture
from tools.profiling.android.quality_sweep import Candidate, codes
from tools.profiling.android.quality import image_quality


class FusedReconstructionTests(unittest.TestCase):
    def test_halos_cover_clamped_bilinear_taps(self):
        # Check both axes independently, including non-power-of-two ratios.
        for size in list(range(8, 257)) + [270, 480, 513, 1023, 1920]:
            parent, grand = size >> 1, size >> 2
            for origin in range(0, size, 16):
                p0 = int(np.floor((origin + .5) * parent / size - .5))
                g0 = int(np.floor((p0 + .5) * grand / parent - .5))
                for pixel in range(origin, min(origin + 16, size)):
                    tap = int(np.floor((pixel + .5) * parent / size - .5)) - p0
                    self.assertTrue(0 <= tap and tap + 1 < 10)
                for index in range(10):
                    pixel = np.clip(p0 + index, 0, parent - 1)
                    tap = int(np.floor((pixel + .5) * grand / parent - .5)) - g0
                    self.assertTrue(0 <= tap and tap + 1 < 7)

    def test_reference_agreement_on_small_thin_and_odd_images(self):
        device = spy.Device(enable_hot_reload=False)
        mapper = ToneMapper(device)
        candidate = Candidate(device, mapper, 'guided-fused-reconstruction')
        for w, h in [(1, 1), (1, 65), (65, 1), (17, 9), (129, 73), (513, 289)]:
            with self.subTest(size=(w, h)):
                y, x = np.mgrid[:h, :w]
                light = np.exp2(-10 + 16 * x / max(w - 1, 1))
                rgb = light[..., None] * np.array([1., .6, .2])
                rgb[y >= h // 2] *= 4
                source = create_hdr_texture(device, np.concatenate(
                    [rgb.astype(np.float32), np.ones((h, w, 1), np.float32)], axis=-1))
                enc = device.create_command_encoder()
                mapper.prepare_weights(enc, source, 0, 1.2, 1.2, .2)
                mapper.prepare_result(enc, source, 0)
                device.submit_command_buffer(enc.finish())
                actual, coefficients = candidate.render(source, 0)
                self.assertTrue(np.isfinite(coefficients).all())
                self.assertTrue(np.isfinite(actual).all())
                quality = image_quality(codes(mapper.final_color.to_numpy()), codes(actual))
                self.assertTrue(quality['accepted'], quality)
