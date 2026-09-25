"""Signed source textures must retain the original per-sample clamping."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ToneMapper, create_hdr_texture
from tests.compact_reference import ReferenceCandidate as Candidate


class UnsignedGatherTests(unittest.TestCase):
    def test_signed_float_source_uses_clamped_fallback(self):
        device = spy.Device(enable_hot_reload=False)
        mapper = ToneMapper(device)
        rng = np.random.default_rng(12013)
        # Divisible dimensions exercise Gather, not the odd-size sampled fallback.
        rgba = rng.uniform(-50, 50, (32, 64, 4)).astype(np.float32)
        rgba[::3, ::3, :3] = -10
        rgba[..., 3] = 1
        source = create_hdr_texture(device, rgba)
        encoder = device.create_command_encoder()
        mapper.prepare_weights(encoder, source, 0, 3, 3, .2)
        device.submit_command_buffer(encoder.finish())
        control = Candidate(device, mapper, 'guided-pyramid-layout')
        candidate = Candidate(device, mapper, 'guided-unsigned-gather')
        expected = control.render(source, 0, bracket=3)
        actual = candidate.render(source, 0, bracket=3)
        for a, b in zip(actual, expected):
            self.assertTrue(np.isfinite(a).all())
            np.testing.assert_array_equal(a, b)


if __name__ == '__main__':
    unittest.main()
